import argparse
import os
import sys
from pathlib import Path
import pandas as pd
from tqdm import tqdm
import warnings

# Вимикаємо DtypeWarning та ParserWarning, щоб логіка Fallback працювала тихо і не лякала консоль
warnings.filterwarnings('ignore', category=pd.errors.ParserWarning)

# Імпортуємо наші суміжні інфраструктурні модулі
import dataset_config
from etl_core import SecureDownloader

# =========================================
# 1. ГЛОБАЛЬНІ НАЛАШТУВАННЯ ТА ОПТИМІЗАЦІЯ
# =========================================
# pd.options.mode.copy_on_write = True - Pandas 3.0.3 по замовчуванню включений режим Copy-on-Write,
# який оптимізує пам'ять при обробці великих DataFrame, що критично для нашого випадку з 32M записів
# Ця опція запобігає непотрібному копіюванню даних, дозволяючи ефективно працювати з обмеженою оперативною пам'яттю

DATA_DIR = Path("data")
IMPORT_DIR = Path("import")

def ensure_infrastructure():
    """Атомарно створює цільові директорії платформи."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)

# =========================================================================
# 🧬 SMART READER: ПАТЕРН GRACEFUL DEGRADATION (DRY)
# =========================================================================
def smart_read_csv(file_path, desc_name, **kwargs):
    """
    Універсальний DRY-рідер. Автоматично підбирає найшвидший доступний рушій
    Спроби:
      1. 'pyarrow' (Найшвидший, але боїться chunksize та екзотичних роздільників)
      2. 'c'       (Стабільний, підтримує chunksize, але не любить роздільники > 1 символу)
      3. 'python'  (Повільний, але "з'їсть" будь-який формат)
    """
    engines = ["pyarrow", "c", "python"]
    last_error = None

    for engine in engines:
        try:
            attempt_kwargs = kwargs.copy()
            attempt_kwargs["engine"] = engine

            # Якщо рушій не підтримує комбінацію аргументів (наприклад pyarrow + chunksize),
            # Pandas миттєво викине Exception саме на цьому етапі:
            reader = pd.read_csv(file_path, **attempt_kwargs)

            # Якщо код дійшов сюди - рушій сумісний з налаштуваннями!
            print(f"   ⚡ [{desc_name}] Оптимальний рушій: '{engine}'")
            return reader

        except Exception as e:
            last_error = e
            continue

    # Якщо всі 3 рушії впали (наприклад, файл битий фізично)
    raise RuntimeError(f"❌ Жоден рушій не зміг прочитати '{desc_name}'. Остання помилка: {last_error}")

# ===================================================
# 2. ШАР ПЕРЕТВОРЕННЯ ДАНИХ (PANDAS & PYARROW ENGINE)
# ===================================================
def convert_movies(config: dict):
    """
    Парсить сирий файл фільмів та приводить його до єдиного Enterprise-стандарту.
    """
    print("\n🎬 Запуск очищення та нормалізації компонентів 'movies'...")
    raw_file_path = DATA_DIR / config["movies_file"]
    clean_file_path = IMPORT_DIR / "movies.csv"

    if not raw_file_path.exists():
        raise FileNotFoundError(f"Сирий файл фільмів не знайдено за адресою: {raw_file_path}")

    # 👾 РЕТРО-АДАПТЕР: Складання жанрів з 19 колонок нулів і одиниць
    if config.get("is_retro"):
        retro_columns = [
            "movieId", "title", "release_date", "video_release_date", "imdb_url",
            "unknown", "Action", "Adventure", "Animation", "Children's", "Comedy", "Crime",
            "Documentary", "Drama", "Fantasy", "Film-Noir", "Horror", "Musical", "Mystery",
            "Romance", "Sci-Fi", "Thriller", "War", "Western"
        ]
        # Замість хардкоду - делегуємо роботу Smart Reader
        df = smart_read_csv(raw_file_path, "Movies (Retro)", sep=config["sep"], header=config["header"], names=retro_columns, encoding=config["encoding"])

        # Збираємо жанри в один рядок
        genre_cols = retro_columns[5:]
        # Для кожного рядка: беремо назви колонок, де стоїть 1, і з'єднуємо їх через |
        df["genres"] = df[genre_cols].apply(lambda row: "|".join([col for col in genre_cols if row[col] == 1]), axis=1)
        # Якщо фільм не має жанрів (все по нулях), ставимо заглушку
        df["genres"] = df["genres"].replace("", "(no genres listed)")

        # Відкидаємо зайві 22 колонки, залишаємо тільки потрібні три
        df = df[["movieId", "title", "genres"]]
    else:
        # Стандартна обробка для датасетів з уже готовою колонкою жанрів
        df = smart_read_csv(raw_file_path, "Movies", sep=config["sep"], header=config["header"], names=dataset_config.MOVIES_COLUMNS, encoding=config["encoding"])

    df["title"] = df["title"].astype("string[pyarrow]")
    df["genres"] = df["genres"].astype("string[pyarrow]")
    df.to_csv(clean_file_path, index=False, encoding="utf-8")
    print(f"✅ Успішно експортовано {len(df)} фільмів у: {clean_file_path}")


def convert_users(config: dict):
    if "users_file" not in config:
        print("\n👤 [Пропуск] Датасет не містить демографії. (Заглушка users.csv буде згенерована автоматично під час парсингу рейтингів).")
        return

    print("\n👤 Запуск очищення та нормалізації демографії 'users'...")
    raw_file_path = DATA_DIR / config["users_file"]
    clean_file_path = IMPORT_DIR / "users.csv"

    if not raw_file_path.exists():
        print(f"⚠️ Файл користувачів {raw_file_path} не знайдено. Пропускаємо.")
        return

    # 👾 РЕТРО-АДАПТЕР: Перестановка колонок місцями
    if config.get("is_retro"):
        # У 1998 вік і стать були переплутані місцями порівняно з 1M
        retro_user_cols = ["userId", "age", "gender", "occupation", "zipCode"]
        df = smart_read_csv(raw_file_path, "Users (Retro)", sep=config["sep"], header=config["header"], names=retro_user_cols, encoding=config["encoding"])
        # Переставляємо колонки в наш стандартний порядок для бази даних
        df = df[dataset_config.USERS_COLUMNS]
    else:
        df = smart_read_csv(raw_file_path, "Users", sep=config["sep"], header=config["header"], names=dataset_config.USERS_COLUMNS, encoding=config["encoding"])

    df["userId"] = pd.to_numeric(df["userId"], downcast="integer")
    df.to_csv(clean_file_path, index=False, encoding="utf-8")
    print(f"✅ Успішно експортовано {len(df)} користувачів у: {clean_file_path}")


def convert_ratings(config: dict):
    """
    Конвеєрна обробка рейтингів (Chunking Pipeline).
    Одночасно збирає унікальні userId для автогенерації users.csv (якщо потрібно).
    [ШЛЯХ PURISTS]: Парсить ВЕСЬ оригінальний датасет цілком, без відрізання рядків.
    """
    print(f"\n⭐ Запуск конвеєрного парсингу оригінального датасету 'ratings'...")

    raw_file_path = DATA_DIR / config["ratings_file"]
    clean_file_path = IMPORT_DIR / "ratings.csv"

    if not raw_file_path.exists():
        raise FileNotFoundError(f"Сирий файл рейтингів не знайдено за адресою: {raw_file_path}")

    # 👾 РЕТРО-АДАПТЕР: Окремий роздільник для рейтингів
    active_sep = config.get("ratings_sep", config["sep"])
    chunk_size = 1_000_000
    rows_processed = 0
    unique_users = set() # Ініціалізуємо множину для унікальних ID

    pd.DataFrame(columns=dataset_config.RATINGS_COLUMNS).to_csv(clean_file_path, index=False, encoding="utf-8")

    # Передаємо генерацію чанків нашому Smart Reader
    chunk_iter = smart_read_csv(
        raw_file_path,
        "Ratings (Chunked)",
        sep=active_sep,
        header=config["header"],
        names=dataset_config.RATINGS_COLUMNS,
        encoding=config["encoding"],
        chunksize=chunk_size
    )

    # Використовуємо target_rows лише для візуалізації прогресу (ETA)
    with tqdm(total=config["target_rows"], desc="⚙️  Парсинг масиву ratings", unit=" рядків", file=sys.stdout) as pbar:
        for chunk in chunk_iter:
            # Оптимізація пам'яті (Downcasting)
            chunk["userId"] = pd.to_numeric(chunk["userId"], downcast="integer")
            chunk["movieId"] = pd.to_numeric(chunk["movieId"], downcast="integer")
            chunk["rating"] = pd.to_numeric(chunk["rating"], downcast="float")
            chunk["timestamp"] = pd.to_numeric(chunk["timestamp"], downcast="integer")

            # Додаємо унікальні ID з цього чанка в загальну множину
            unique_users.update(chunk["userId"].unique())
            chunk.to_csv(clean_file_path, mode="a", header=False, index=False, encoding="utf-8")

            rows_processed += len(chunk)
            pbar.update(len(chunk))

    print(f"✅ Успішно згенеровано чистовий файл рейтингів ({rows_processed:,} рядків) у: {clean_file_path}")

    # =========================================================================
    # 🛡️ ARCHITECTURE FIX: АВТО-ГЕНЕРАЦІЯ USERS ДЛЯ НОВИХ ДАТАСЕТІВ (25M, 32M)
    # =========================================================================
    if "users_file" not in config:
        print(f"\n👤 [Авто-Генерація] Створення відсутнього файлу users.csv із {len(unique_users):,} унікальних ID...")

        # Створюємо DataFrame з єдиною заповненою колонкою (userId)
        # Додано sorted() для послідовного створення вузлів у Neo4j (швидша побудова B-Tree індексу)
        users_df = pd.DataFrame({"userId": sorted(list(unique_users))})

        # Додаємо порожні колонки, щоб відповідати стандарту Neo4j LOAD CSV
        for col in dataset_config.USERS_COLUMNS[1:]:
            users_df[col] = ""

        # Гарантуємо правильний порядок колонок
        users_df = users_df[dataset_config.USERS_COLUMNS]
        users_df.to_csv(IMPORT_DIR / "users.csv", index=False, encoding="utf-8")
        print(f"✅ Успішно згенеровано users.csv-заглушку для Neo4j!")

# ==============================
# 3. ТОЧКА ВХОДУ (CLI ИНТЕРФЕЙС)
# ==============================
if __name__ == "__main__":
    import logging
    # Вмикаємо логи для SecureDownloader, щоб нарешті бачити процес завантаження
    logging.basicConfig(level=logging.INFO, format='%(message)s')

    parser = argparse.ArgumentParser(description="MovieLens ETL Платформа (Purist Mode)")
    parser.add_argument(
        "--size",
        type=str,
        required=True,
        choices=list(dataset_config.DATASETS.keys()),
        help="Оригінальний масштаб датасету для завантаження та парсингу"
    )
    args = parser.parse_args()

    print("=" * 70)
    print(f"🚀 СТАРТ ЕТАПУ ETL ПАЙПЛАЙНУ [КОНВЕРТАЦІЯ ДАНИХ] | ОРИГІНАЛ: {args.size}")
    print("=" * 70)

    ensure_infrastructure()

    try:
        config = dataset_config.get_config(args.size)

        # =========================================================================
        # 🛡️ АБСОЛЮТНИЙ ЗАХИСТ ВІД CACHE POISONING (Розумне очищення)
        # =========================================================================
        # Оскільки Makefile чистить import/, ми трекаємо стан безпосередньо в data/
        state_marker = DATA_DIR / f".state_{args.size}"
        old_markers = list(DATA_DIR.glob(".state_*"))

        # Якщо ми перемикаємось на інший розмір датасету (маркер не збігається)
        if not state_marker.exists():
            old_name = old_markers[0].name.replace('.state_', '') if old_markers else "Відсутній"
            print(f"🧹 Виявлено зміну датасету ({old_name} ➔ {args.size}).")
            print("💣 Очищення розпакованих файлів (САМІ АРХІВИ .zip ЗБЕРІГАЮТЬСЯ!)...")

            # 1. Видаляємо старі маркери стану
            for marker in old_markers:
                marker.unlink(missing_ok=True)

            # 2. Видаляємо ЛИШЕ розпаковані файли в data/, ігноруючи .zip архіви
            for ext in ("*.csv", "*.dat", "*.item", "*.data", "*.user"):
                for f in DATA_DIR.glob(ext):
                    f.unlink(missing_ok=True)

            # 3. Знищуємо старі результати в папці import/, АЛЕ бережемо .gitkeep
            for f in IMPORT_DIR.iterdir():
                if f.is_file() and f.name != ".gitkeep":
                    f.unlink(missing_ok=True)

            # Фіксуємо новий стан
            state_marker.touch()

        # 🎯 Динамічне ім'я архіву
        dynamic_zip_name = f"archive_{args.size}.zip"

        downloader = SecureDownloader(
            dataset_path=config["kaggle_path"],
            dataset_url=config["url_fallback"],
            kaggle_direct_url=config["kaggle_direct_url"],
            data_dir=str(DATA_DIR),
            zip_name=dynamic_zip_name,
            expected_size=config.get("expected_zip_bytes") # Передаємо еталонний розмір для перевірки!
        )

        downloader.download(target_filename=config["movies_file"])

        downloader.extract_atomically(
            target_extensions=(".csv", ".dat", ".item", ".data", ".user"),
            expected_filename=config["movies_file"]
        )

        convert_movies(config)
        convert_users(config)
        convert_ratings(config)

        # Повертаємо маркер успішності для Makefile
        marker_path = IMPORT_DIR / f".dataset_{args.size}"
        marker_path.touch(exist_ok=True)

        print("\n🎉 [ETL СТАТУС]: Всі операції успішно завершено! Дані готові для завантаження в Neo4j.")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ КРИТИЧНИЙ ЗБІЙ ПІД ЧАС ВИКОНАННЯ ETL: {e}", file=sys.stderr)
        sys.exit(1)
