// ============================================================================
// ЧАСТИНА 2: СТВОРЕННЯ СХЕМИ ТА ІМПОРТ ДАНИХ (ETL)
// ============================================================================
// ----------------------------------------------------------------------------
// 1. СТВОРЕННЯ ІНДЕКСІВ ТА ОБМЕЖЕНЬ (Schema-First Optimization)
// Мета: Підготувати схему бази даних, гарантувати унікальність ідентифікаторів
// та забезпечити алгоритмічну швидкість O(1) для всіх наступних операцій MERGE
//
// Архітектурне рішення: Виконується строго до імпорту даних для забезпечення O(1) складності при MERGE
// Сучасний синтаксис Neo4j 2026.04 вимагає обов'язкового іменування констрейнтів
// ----------------------------------------------------------------------------
CREATE CONSTRAINT user_id_unique IF NOT EXISTS
FOR (u:User)
REQUIRE u.userId IS UNIQUE;

CREATE CONSTRAINT movie_id_unique IF NOT EXISTS
FOR (m:Movie)
REQUIRE m.movieId IS UNIQUE;

CREATE CONSTRAINT genre_name_unique IF NOT EXISTS
FOR (g:Genre)
REQUIRE g.name IS UNIQUE;

// ----------------------------------------------------------------------------
// 2. ЗАВАНТАЖЕННЯ КОРИСТУВАЧІВ
// Мета: Ідемпотентно завантажити демографічні дані користувачів у вузли :User
//
// Best Practice: Використовуємо ON CREATE SET замість звичайного SET
// Це гарантує 100% ідемпотентність і нульове навантаження на диск (Zero I/O)
// при випадковому повторному виконанні скрипта
// ----------------------------------------------------------------------------
LOAD CSV WITH HEADERS FROM $base_url + 'users.csv' AS row
MERGE (u:User {userId: toInteger(row.userId)})
  ON CREATE SET
    u.gender = row.gender,
    u.age = toInteger(row.age),
    u.occupation = toInteger(row.occupation);

// ----------------------------------------------------------------------------
// 3. ЗАВАНТАЖЕННЯ ФІЛЬМІВ ТА ЖАНРІВ
// Мета: Завантажити вузли фільмів, динамічно розпарсити рядки з жанрами
// та створити структурні зв'язки [:HAS_GENRE] між фільмами та жанрами
//
// Best Practice: Перевірка IS NOT NULL захищає від падіння транзакції
// на "битих" рядках під час виконання функції split() та UNWIND.
// ----------------------------------------------------------------------------
LOAD CSV WITH HEADERS FROM $base_url + 'movies.csv' AS row
MERGE (m:Movie {movieId: toInteger(row.movieId)})
  ON CREATE SET m.title = row.title
WITH m, row
WHERE row.genres IS NOT NULL
UNWIND split(row.genres, '|') AS genreName
MERGE (g:Genre {name: genreName})
MERGE (m)-[:HAS_GENRE]->(g);

// ----------------------------------------------------------------------------
// 4. ЗАВАНТАЖЕННЯ ОЦІНОК (Native Batched Transactions - Neo4j 2026.04 Standard)
// Мета: Побудувати основний масив графа — мільйони зв'язків [:RATED] між
// користувачами та фільмами, уникаючи переповнення пам'яті (OOM)
//
// [ADR - ARCHITECTURE DECISION RECORD]:
// 1. Native Engine: Використовуємо нативний CALL () {} IN TRANSACTIONS замість
//    застарілого apoc.periodic.iterate. Це працює на рівні ядра (Core Engine),
//    що мінімізує споживання ОЗП та повністю уникає оверхеду плагінів
// 2. Explicit Scope: Синтаксис CALL (row) явно визначає область видимості
//    змінної для підзапиту (усуває Deprecation Warning 01N00)
// 3. SRE Tuning: Розмір батчу жорстко встановлено на 10 000 ROWS. Це захищає
//    віртуалізований Docker-кластер від жорстких пауз JVM (Garbage Collection),
//    які призводять до втрати лідера (I/O Starvation та Deadlocks)
// 4. Idempotency: ON CREATE SET для ребер гарантує 100% захист від дублювання
//    зв'язків та забезпечує Zero I/O при повторному виконанні пайплайну
// ----------------------------------------------------------------------------
LOAD CSV WITH HEADERS FROM $base_url + 'ratings.csv' AS row
CALL (row) {
  MATCH (u:User {userId: toInteger(row.userId)})
  MATCH (m:Movie {movieId: toInteger(row.movieId)})
  MERGE (u)-[r:RATED]->(m)
    ON CREATE SET
      r.rating = toFloat(row.rating),
      r.timestamp = toInteger(row.timestamp)
} IN TRANSACTIONS OF 10000 ROWS;