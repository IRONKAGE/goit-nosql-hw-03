"""
⚠️ Єдиний реєстр конфігурацій датасетів MovieLens
Містить параметри для Kaggle API, прямих безключових завантажень з Kaggle,
резервних лінків GroupLens, а також індивідуальні налаштування парсингу для кожного розміру
Цей файл вирішує проблему "зоопарку форматів":
- Ретро датасети (100K-RETRO) мають унікальні роздільники та кодування, які відрізняються від сучасних
- Старі датасети (1M, 10M) використовують .dat файли, роздільник '::', відсутність заголовків і кодування latin-1
- Нові датасети (100K-latest, 25M, 32M) використовують .csv файли, роздільник ',', наявність заголовків і кодування utf-8
"""

# ==========================================
# КОНСТАНТИ КОЛОНОК (ЄДИНІ ДЛЯ NEO4J)
# ==========================================
# Незалежно від того, які імена колонок в оригіналі,
# ми примусово перейменовуємо їх у цей стандарт для Cypher LOAD CSV
MOVIES_COLUMNS = ["movieId", "title", "genres"]
RATINGS_COLUMNS = ["userId", "movieId", "rating", "timestamp"]
USERS_COLUMNS = ["userId", "gender", "age", "occupation", "zipCode"]

# ==========================================
# РЕЄСТР ДАТАСЕТІВ ТА ПОРЯДОК МАРШРУТИЗАЦІЇ
# ==========================================
DATASETS = {
    "100K-RETRO": {
        # Оригінальний датасет 1998 року (з u.data, u.item, u.user)
        "kaggle_path": "prajitdatta/movielens-100k-dataset",
        "kaggle_direct_url": "https://www.kaggle.com/api/v1/datasets/download/prajitdatta/movielens-100k-dataset",
        "url_fallback": "https://files.grouplens.org/datasets/movielens/ml-100k.zip",
        "target_rows": 100_000,

        # Специфічні назви файлів з 90-х
        "movies_file": "u.item",
        "ratings_file": "u.data",
        "users_file": "u.user",

        # Зоопарк роздільників
        "sep": "|",               # Для movies та users
        "ratings_sep": "\t",      # РЕЙТИНГИ використовують табуляцію!
        "header": None,           # Немає заголовків, pandas має генерувати колонки сам
        "encoding": "latin-1",
        "is_retro": True          # Адаптер конфігураційного прапора для парсера
    },

    "100K": {
        # Використовуємо ml-latest-small (~100 000 рейтингів), оскільки старий ml-100k має жахливу структуру (u.data, u.item)
        "kaggle_path": "shubhammehta21/movie-lens-small-latest-dataset",
        "kaggle_direct_url": "https://www.kaggle.com/api/v1/datasets/download/shubhammehta21/movie-lens-small-latest-dataset",
        "url_fallback": "https://files.grouplens.org/datasets/movielens/ml-latest-small.zip",
        "target_rows": 100_000,

        # Налаштування парсингу
        "movies_file": "movies.csv",
        "ratings_file": "ratings.csv",
        # "users_file" ВІДСУТНІЙ
        "sep": ",",
        "header": 0,              # 0 означає, що перший рядок - це заголовок
        "encoding": "utf-8"
    },

    "1M": {
        # Легасі формат (2003 рік)
        "kaggle_path": "odedgolden/movielens-1m-dataset",
        "kaggle_direct_url": "https://www.kaggle.com/api/v1/datasets/download/odedgolden/movielens-1m-dataset",
        "url_fallback": "https://files.grouplens.org/datasets/movielens/ml-1m.zip",
        "target_rows": 1_000_000,

        # Налаштування парсингу
        "movies_file": "movies.dat",
        "ratings_file": "ratings.dat",
        "users_file": "users.dat",
        "sep": "::",
        "header": None,           # Немає заголовків, pandas має генерувати колонки сам
        "encoding": "latin-1"     # Важливо: старий формат часто "ламається" на utf-8
    },

    "10M": {
        # Перехідний формат (2009 рік)
        "kaggle_path": "amirmotefaker/movielens-10m-dataset-latest-version",
        "kaggle_direct_url": "https://www.kaggle.com/api/v1/datasets/download/amirmotefaker/movielens-10m-dataset-latest-version",
        "url_fallback": "https://files.grouplens.org/datasets/movielens/ml-10m.zip",
        "target_rows": 10_000_000,

        # Налаштування парсингу
        "movies_file": "movies.dat",
        "ratings_file": "ratings.dat",
        # "users_file" ВІДСУТНІЙ
        "sep": "::",
        "header": None,           # Немає заголовків, pandas має генерувати колонки сам
        "encoding": "utf-8"
    },

    "25M": {
        # Сучасний формат (2019 рік)
        "kaggle_path": "veeralakrishna/movielens-25m-dataset",
        "kaggle_direct_url": "https://www.kaggle.com/api/v1/datasets/download/veeralakrishna/movielens-25m-dataset",
        "url_fallback": "https://files.grouplens.org/datasets/movielens/ml-25m.zip",
        "target_rows": 25_000_000,

        # Налаштування парсингу
        "movies_file": "movies.csv",
        "ratings_file": "ratings.csv",
        # "users_file" ВІДСУТНІЙ
        "sep": ",",
        "header": 0,              # 0 означає, що перший рядок - це заголовок
        "encoding": "utf-8"
    },

    "32M": {
        # Найсвіжіший формат на травень 2026, цей архів був релізнутий у травні 2024 (Latest Full - оновлюється періодично)
        "kaggle_path": "justsahil/movielens-32m",
        "kaggle_direct_url": "https://www.kaggle.com/api/v1/datasets/download/justsahil/movielens-32m",
        "url_fallback": "https://files.grouplens.org/datasets/movielens/ml-latest.zip",
        "target_rows": 32_000_000,  # Округляємо для нашого таргетування

        # Налаштування парсингу
        "movies_file": "movies.csv",
        "ratings_file": "ratings.csv",
        # "users_file" ВІДСУТНІЙ
        "sep": ",",
        "header": 0,              # 0 означає, що перший рядок - це заголовок
        "encoding": "utf-8"
    }
}

def get_config(size: str) -> dict:
    """
    Безпечно повертає конфігурацію для вказаного розміру датасету
    """
    size = size.upper()
    if size not in DATASETS:
        raise ValueError(f"❌ Розмір '{size}' не підтримується! Доступні варіанти: {list(DATASETS.keys())}")
    return DATASETS[size]
