import os
import logging
from pathlib import Path
from neo4j import GraphDatabase, Driver
from dotenv import load_dotenv

# 1. Observability (MAAMA Standard)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

class Neo4jConnectionFactory:
    """
    Справжня Singleton-фабрика
    Гарантує створення лише одного пулу з'єднань (Driver) для всього життєвого циклу програми
    Для створення з'єднань з Neo4j залежно від поточного стейту (локальний чи хмарний)
    """
    # Класова змінна для кешування інстансу (FAANG Singleton Pattern)
    _driver_instance: Driver | None = None

    @classmethod
    def get_driver(cls, env: str = "local", timeout: float = 30.0) -> Driver:
        """Повертає єдиний екземпляр драйвера Neo4j."""

        # Якщо драйвер уже створено — просто віддаємо його (захист від витоку пулів)
        if cls._driver_instance is not None:
            return cls._driver_instance

        # 2. Security (Без хардкоду паролів)
        if env == "cloud":
            uri = os.getenv("NEO4J_CLOUD_URI")
            user = os.getenv("NEO4J_CLOUD_USER")
            password = os.getenv("NEO4J_CLOUD_PASS")
            # 💡 Показуємо фактичну адресу хмари
            logger.info(f"☁️  Підключення до хмарної Neo4j AuraDB (URI: {uri})...")
        else:
            user = os.getenv("NEO4J_LOCAL_USER")
            password = os.getenv("NEO4J_LOCAL_PASS")

            # Smart Detection стейту: Визначаємо фактичний стан локальної інфраструктури
            dynamic_profile_path = Path(".dynamic_profile")

            if dynamic_profile_path.exists():
                # Якщо Makefile залишив State File, віримо йому (на випадок авто-даунгрейду)
                active_profile = dynamic_profile_path.read_text().strip()
            else:
                # Якщо запускають без Makefile, беремо заявлений профіль з .env
                active_profile = os.getenv("COMPOSE_PROFILES", "standalone")

            if active_profile == "cluster":
                # Кластер вимагає розумної маршрутизації
                uri = os.getenv("NEO4J_LOCAL_URI", "neo4j://127.0.0.1:7687")
                # 💡 Показуємо фактичну адресу маршрутизатора
                logger.info(f"🐳 Підключення до локального Кластера (Routing: {uri})...")
            else:
                # Standalone працює швидше і надійніше через прямий сокет
                uri = "bolt://127.0.0.1:7687"
                logger.info(f"🐳 Підключення до локальної Standalone ноди (Direct: {uri})...")

        # 3. Smart Validation (DX покращення)
        missing_vars = []
        if not uri: missing_vars.append("URI")
        if not user: missing_vars.append("USER")
        if not password: missing_vars.append("PASS")

        if missing_vars:
            # Factory не вбиває процес, а делегує це нагору через Exception
            raise ValueError(f"КРИТИЧНО: Відсутні обов'язкові змінні оточення: {', '.join(missing_vars)}!")

        try:
            # 4. MANGO Optimization: створення пулу з'єднань
            pool_size = 50 # Ліміт пулу для захисту бази від OOM
            driver = GraphDatabase.driver(
                uri,
                auth=(user, password),
                connection_timeout=timeout,
                max_connection_lifetime=3600,
                max_connection_pool_size=pool_size
            )
            driver.verify_connectivity()

            # 💡 Централізоване повідомлення про успіх із конфігурацією пулу
            logger.info(f"✅ З'єднання верифіковано! (Pool Size: {pool_size})")

            # Кешуємо драйвер для наступних викликів
            cls._driver_instance = driver
            return cls._driver_instance

        except Exception as e:
            logger.error(f"❌ Помилка підключення до бази даних Neo4j: {e}")
            raise ConnectionError(f"Failed to connect to Neo4j at {uri}") from e

    @classmethod
    def close_driver(cls) -> None:
        """Коректне закриття пулу з'єднань при завершенні програми."""
        if cls._driver_instance is not None:
            cls._driver_instance.close()
            cls._driver_instance = None
            logger.info("🔌 Пул з'єднань Neo4j коректно відключено.")
