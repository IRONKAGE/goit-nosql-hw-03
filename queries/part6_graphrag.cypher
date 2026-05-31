// ============================================================================
// ЧАСТИНА 6: GRAPHRAG ТА ГІБРИДНИЙ ПОШУК (HYBRID SEARCH ENGINE)
// Завантаження векторів, створення індексів та семантичний пошук
// ============================================================================
// ----------------------------------------------------------------------------
// 6.1. ЗАВАНТАЖЕННЯ ВЕКТОРІВ У ГРАФ (Vector Ingestion - Neo4j 2026.04 Standard)
// Мета: Збагатити існуючі вузли фільмів (Movie) ML-векторами (Embeddings)
// для забезпечення можливості семантичного пошуку, зберігаючи жорсткий
// контроль над споживанням пам'яті (Heap)
//
// [ADR - ARCHITECTURE DECISION RECORD]:
// 1. Native Engine: Замінили застарілий apoc.periodic.iterate на нативний
//    CALL (row) {} IN TRANSACTIONS для запобігання OOM та Deprecation Warnings
// 2. Vector Casting: Прямий SET із жорстким кастуванням toFloat(val) — це сучасний
//    стандарт Neo4j 2026.04 замість застарілої процедури db.create.setNodeVectorProperty
// 3. APOC Core: Використовуємо apoc.convert.fromJsonList для швидкого та надійного
//    парсингу JSON-масивів з CSV-файлу
// 4. SRE Tuning: Розмір батчу для векторів зменшено до 5000 ROWS, оскільки
//    Float-масиви на 768 вимірів займають значно більше місця в Heap Memory
// ----------------------------------------------------------------------------
LOAD CSV WITH HEADERS FROM $base_url + 'movies_embedded.csv' AS row
CALL (row) {
  MATCH (m:Movie {movieId: toInteger(row.movieId)})
  // Конвертуємо JSON-рядок у список і примусово кастуємо кожен елемент до Float
  SET
    m.embedding =
      [val IN apoc.convert.fromJsonList(row.embedding) | toFloat(val)]
} IN TRANSACTIONS OF 5000 ROWS;

// ----------------------------------------------------------------------------
// 6.2. СТВОРЕННЯ ВЕКТОРНОГО ІНДЕКСУ (HNSW)
// Мета: Створити векторний індекс HNSW (Hierarchical Navigable Small World)
// для забезпечення логарифмічної швидкості O(log N) під час пошуку за
// косинусною відстанню (Cosine Similarity)
//
// [ADR - ARCHITECTURE DECISION RECORD]:
// 1. HNSW vs Exact k-NN: Використовується алгоритм HNSW (Approximate Nearest
//    Neighbor) замість точного пошуку. Це знижує точність на мікроскопічні 1-2%,
//    але забезпечує миттєвий пошук O(log N) навіть при мільйонах векторів
// 2. Hardware-Model Sync (768 вимірів): Розмірність жорстко зафіксовано на 768,
//    що гарантує 100% сумісність із векторами, згенерованими ML-моделлю
//    BAAI/bge-base-en-v1.5 у Python-скрипті
// 3. Math Optimization (Cosine): Використання косинусної відстані ідеально
//    працює в парі з параметром normalize_embeddings=True на етапі інгекції
//    Базі даних більше не потрібно вираховувати довжину векторів — вона
//    одразу шукає семантичний кут між ними, що кардинально прискорює пошук
// 4. SRE Idempotency: Патерн DROP INDEX IF EXISTS гарантує, що інфраструктурний
//    скрипт можна безпечно запускати багато разів поспіль у CI/CD пайплайні
//    без отримання помилки "Index already exists"
// ----------------------------------------------------------------------------
DROP INDEX movie_embeddings IF EXISTS;

CREATE VECTOR INDEX movie_embeddings FOR (m:Movie) ON (m.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 768,
    `vector.similarity_function`: 'cosine'
  }
};

// ----------------------------------------------------------------------------
// 6.3. ТЕСТОВИЙ ГІБРИДНИЙ ЗАПИТ (GraphRAG E2E Test)
// Мета: Довести працездатність гібридного пошуку під час розгортання інфраструктури
//
// Архітектурне рішення: Замість очікування зовнішнього $vector, ми динамічно
// витягуємо вектор фільму "Toy Story" (movieId: 1) і шукаємо схожі на нього
// ----------------------------------------------------------------------------
MATCH (test_movie:Movie {movieId: 1})
WITH test_movie.embedding AS query_vector
// ⚠️ Попередження "deprecated" ігноруємо, оскільки новий синтаксис SEARCH ще не стабілізовано у 2026.04
CALL
  db.index.vector.queryNodes(
    'movie_embeddings',
    50,
    query_vector
  )
  YIELD node AS movie, score AS semantic_score
// Знаходимо топологічну вагу (рейтинги)
MATCH (movie)<-[r:RATED]-()
WITH
  movie,
  semantic_score,
  count(r) AS total_ratings,
  avg(r.rating) AS avg_rating
// Pruning: Відсікаємо релевантні за сенсом, але непопулярні/низькооцінені фільми
WHERE total_ratings > 50

// Математика гібридного скорингу:
// Ваги: 60% за сенс (Vector), 40% за соціальну якість (Graph)
WITH
  movie,
  semantic_score,
  avg_rating,
  total_ratings,
  (semantic_score * 0.6) + ((avg_rating / 5.0) * 0.4) AS hybrid_score
RETURN
  movie.title AS movie_title,
  round(semantic_score * 100) / 100.0 AS vector_score,
  round(avg_rating * 10) / 10.0 AS graph_rating,
  round(hybrid_score * 100) / 100.0 AS final_hybrid_score
ORDER BY final_hybrid_score DESC
LIMIT 10;

// ----------------------------------------------------------------------------
// 6.4. ВИДОБУТОК КОНТЕКСТУ ДЛЯ RAG (Context Assembly E2E Test)
// Мета: Довести працездатність генерації контексту для LLM
//
// Архітектурне рішення: Використовуємо жорстко заданий movieId: 1 ("Toy Story")
// замість параметра $targetMovieId для успішного виконання в CI/CD пайплайні
// ----------------------------------------------------------------------------
MATCH (target:Movie {movieId: 1})
// 1. Витягуємо Жанри (O(1) доступ)
MATCH (target)-[:HAS_GENRE]->(g:Genre)
WITH target, collect(g.name) AS genres

// 2. Знаходимо, що ще дивилися фанати цього фільму (Graph CF Constraint):
// - Беремо лише позитивні оцінки (rating >= 4.0)
// - Відсікаємо супервузли (COUNT < 1000) для високої релевантності та захисту RAM
MATCH (target)<-[r1:RATED]-(u:User)-[r2:RATED]->(similar:Movie)
WHERE
  r1.rating >= 4.0 AND
  r2.rating >= 4.0 AND
  COUNT { (similar)<-[:RATED]-() } < 1000
WITH target, genres, similar, COUNT(u) AS common_fans
ORDER BY common_fans DESC
LIMIT 5

// 3. Формуємо JSON-подібний контекст для промпта нейромережі
RETURN
  target.title AS requested_movie,
  genres AS movie_genres,
  collect(similar.title) AS community_also_liked;