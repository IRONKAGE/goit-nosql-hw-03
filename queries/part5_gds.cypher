// ============================================================================
// ЧАСТИНА 5: GRAPH DATA SCIENCE (GDS)
// Аналітика топології графа: PageRank, Louvain (Спільноти), Dijkstra
// ============================================================================
// ----------------------------------------------------------------------------
// КРОК 0: SRE IDEMPOTENCY (САМОЛІКУВАННЯ КЛАСТЕРА)
// Гарантує, що пам'ять бази чиста від попередніх перерваних запусків (Ctrl+C)
// Це запобігає фатальній помилці "Graph already exists"
// ----------------------------------------------------------------------------
CALL gds.graph.exists('movieGraph') YIELD exists
WITH exists
WHERE exists
CALL gds.graph.drop('movieGraph') YIELD graphName
RETURN graphName;

CALL gds.graph.exists('userMovieBipartite') YIELD exists
WITH exists
WHERE exists
CALL gds.graph.drop('userMovieBipartite') YIELD graphName
RETURN graphName;

CALL gds.graph.exists('userSimilarity') YIELD exists
WITH exists
WHERE exists
CALL gds.graph.drop('userSimilarity') YIELD graphName
RETURN graphName;

// ----------------------------------------------------------------------------
// 5.1. PAGERANK НА ГРАФІ ФІЛЬМІВ (Структурний авторитет)
// Мета: Знайти "фільми-модулятори", які об'єднують різні групи користувачів
//
// Архітектурне рішення: Використання m1.movieId < m2.movieId замість застарілого
// id(m1) < id(m2) для уникнення дублікатів пар без звернення до internal IDs
// ----------------------------------------------------------------------------
// Крок 1.1: Матеріалізація тимчасових ребер між фільмами
// SRE OPTIMIZATION: Відсікаємо нішові фільми ДО пошуку зв'язків
// Це гарантує мінімальне навантаження на Heap і відсутність OOM ретраїв
MATCH (m1:Movie)
WHERE COUNT { (m1)<-[:RATED]-() } > 20
MATCH (m2:Movie)
WHERE COUNT { (m2)<-[:RATED]-() } > 20 AND m1.movieId < m2.movieId
MATCH (m1)<-[r1:RATED]-(u:User)-[r2:RATED]->(m2)
WHERE r1.rating >= 4.0 AND r2.rating >= 4.0
WITH m1, m2, count(u) AS weight
ORDER BY weight DESC
LIMIT 50000
// 🚀 Neo4j 2026.04 Standard: Явний scope CALL (m1, m2, weight)
CALL (m1, m2, weight) {
  MERGE (m1)-[co:CO_RATED]->(m2)
  SET co.weight = weight
} IN TRANSACTIONS OF 10000 ROWS;

// Крок 1.2: Створення In-Memory проекції
CALL
  gds.graph.project(
    'movieGraph',
    'Movie',
    {CO_RATED: {orientation: 'UNDIRECTED', properties: 'weight'}}
  )
  YIELD graphName, nodeCount, relationshipCount
RETURN graphName, nodeCount, relationshipCount;

// Крок 1.3: Запуск алгоритму PageRank (ЗВАЖЕНИЙ)
CALL
  gds.pageRank.stream(
    'movieGraph',
    {relationshipWeightProperty: 'weight'}
  )
  YIELD nodeId, score
RETURN gds.util.asNode(nodeId).title AS movie_title, score AS pagerank_score
ORDER BY pagerank_score DESC
LIMIT 10;

// Крок 1.4: Очищення (Garbage Collection)
CALL gds.graph.drop('movieGraph') YIELD graphName
RETURN graphName;
MATCH ()-[co:CO_RATED]->()
CALL (co) {
  DELETE co
} IN TRANSACTIONS OF 10000 ROWS;

// ----------------------------------------------------------------------------
// 5.2. ВИЯВЛЕННЯ СПІЛЬНОТ (LOUVAIN ALGORITHM) + TOP GENRES
// Мета: Розбити користувачів на "смакові бульбашки" (кластери) та визначити
// їхні інтереси на основі K-Nearest Neighbors (KNN) графа схожості
//
// [ADR - ARCHITECTURE DECISION RECORD]:
// 1. C++ Kernel Delegation: Замість пошуку перетинів користувачів через Cypher
//    MATCH (що створює Декартовий добуток у RAM та вбиває дискову підсистему I/O),
//    ми делегуємо розрахунок матриці багатопотоковому ядру GDS
// 2. Smart Pruning (Без кастрації даних): Замість жорсткого видалення блокбастерів,
//    використовується алгоритм Node Similarity (індекс Жаккара). Його формула
//    автоматично зменшує вагу (пеналізує) популярні фільми через знаменник,
//    математично нівелюючи "шум" супервузлів
// 3. License Hack (Stream to Transaction): У 3-Node Raft кластерах функція
//    gds.nodeSimilarity.write() заблокована без Enterprise-ліцензії. Рішення:
//    використовуємо .stream() у комбінації з CALL {} IN TRANSACTIONS, що дозволяє
//    зробити безкоштовний паралельний запис графа на швидкості O(1) (через CREATE)
// 4. Neo4j 2026.04 Standard: Використання gds.graph.project як агрегатної
//    функції Cypher скасовує необхідність у застарілому gds.graph.project.cypher
// ----------------------------------------------------------------------------

// Крок 2.1: Матеріалізація K-Nearest Neighbors (ENTERPRISE GDS C++ KERNEL)
// Делегуємо всю математику на рівень ядра GDS

// 2.1.1: Створюємо тимчасову дводольну (bipartite) проекцію у RAM
// Neo4j 2026.04 Standard: Використовуємо Cypher Projection як функцію агрегації
MATCH (u:User)-[r:RATED]->(m:Movie)
WHERE r.rating >= 4.0
WITH gds.graph.project('userMovieBipartite', u, m) AS g
RETURN
  g.graphName AS graphName,
  g.nodeCount AS nodeCount,
  g.relationshipCount AS relationshipCount;

// 2.1.2: Запускаємо алгоритм Node Similarity (Jaccard Index)
// CLUSTER LICENSE HACK: У 3-Node Raft кластерах функція .write() вимагає платної ліцензії
// Ми використовуємо .stream() і делегуємо запис стандартному Cypher
CALL
  gds.nodeSimilarity.stream(
    'userMovieBipartite',
    {topK: 20}
  )
  YIELD node1, node2, similarity
WITH gds.util.asNode(node1) AS u1, gds.util.asNode(node2) AS u2, similarity
// Оптимізація: оскільки індекс Жаккара симетричний, відсікаємо дублікати і використовуємо швидкий CREATE
WHERE u1.userId < u2.userId
CALL (u1, u2, similarity) {
  CREATE (u1)-[sim:SIMILAR]->(u2)
  SET sim.weight = similarity
} IN TRANSACTIONS OF 10000 ROWS;

// 2.1.3: Видаляємо тимчасову проекцію
CALL gds.graph.drop('userMovieBipartite') YIELD graphName
RETURN graphName;

// Крок 2.2: Створення In-Memory проекції для Louvain
CALL
  gds.graph.project(
    'userSimilarity',
    'User',
    {SIMILAR: {orientation: 'UNDIRECTED', properties: 'weight'}}
  )
  YIELD graphName, nodeCount, relationshipCount
RETURN graphName, nodeCount, relationshipCount;

// Крок 2.3: Запуск алгоритму Louvain та визначення Топ-3 жанрів для кожної групи
CALL gds.louvain.stream('userSimilarity') YIELD nodeId, communityId
WITH
  communityId,
  count(nodeId) AS community_size,
  collect(gds.util.asNode(nodeId)) AS users
ORDER BY community_size DESC
LIMIT 5
// Розгортаємо безпосередньо об'єкти користувачів кластера, уникаючи застарілих id(u)
UNWIND users AS u
// Прямий матчинг від вузла `u` замість використання застарілої функції id(u)
MATCH (u)-[r:RATED]->(m:Movie)-[:HAS_GENRE]->(g:Genre)
WHERE r.rating >= 4.0
WITH communityId, community_size, g.name AS genre, count(m) AS genre_count
ORDER BY communityId, genre_count DESC
WITH communityId, community_size, collect(genre)[0..3] AS top_genres
RETURN communityId, community_size, top_genres;

// ----------------------------------------------------------------------------
// 5.3. НАЙКОРОТШИЙ ШЛЯХ (DIJKSTRA)
// Мета: Знайти шлях між користувачами з урахуванням ваги (Weight) ребер
//
// Архітектурне рішення: Замість створення нової проекції 'userGraphDijkstra',
// ми перевикористовуємо 'userSimilarity', що економить оперативну пам'ять бази
// ----------------------------------------------------------------------------

// Крок 3.1: Запуск алгоритму Дейкстри
MATCH (source:User {userId: 1}), (target:User {userId: 15})
CALL
  gds.shortestPath.dijkstra.stream(
    'userSimilarity',
    {
      sourceNode: source,
      targetNode: target,
      relationshipWeightProperty: 'weight'
    }
  )
  YIELD index, sourceNode, targetNode, totalCost, nodeIds, costs
RETURN
  gds.util.asNode(sourceNode).userId AS source_user,
  gds.util.asNode(targetNode).userId AS target_user,
  totalCost AS total_weight,
  [nodeId IN nodeIds | gds.util.asNode(nodeId).userId] AS user_path;

// Крок 3.2: Фінальне очищення (Звільнення RAM та очищення транзакційної БД)
CALL gds.graph.drop('userSimilarity') YIELD graphName
RETURN graphName;
MATCH ()-[sim:SIMILAR]->()
CALL (sim) {
  DELETE sim
} IN TRANSACTIONS OF 10000 ROWS;