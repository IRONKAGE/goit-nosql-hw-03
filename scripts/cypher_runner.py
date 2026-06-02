import os
import sys
import argparse
import re
import time
import threading
import itertools
import logging
from pathlib import Path
from db_connector import Neo4jConnectionFactory # Імпортуємо Фабрику

# =========================================================================
# Вимикаємо інформаційне сміття від драйвера Neo4j
# Залишаємо тільки критичні помилки та ворнінги, щоб зберегти CLI чистим
# =========================================================================
logging.getLogger("neo4j").setLevel(logging.WARNING)

class QuerySpinner:
    """Асинхронний CLI-індикатор для відображення життєдіяльності довготривалих запитів."""
    def __init__(self, message="Обробка в Neo4j..."):
        self.message = message
        self.is_running = False
        self.spinner_thread = None
        self._lock = threading.Lock() # Lock для безпечного доступу до sys.stdout

    def spin(self):
        spinner = itertools.cycle(['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'])
        start_time = time.time()
        while self.is_running:
            elapsed = time.time() - start_time
            with self._lock:
                # \r повертає каретку на початок рядка, перезаписуючи його
                sys.stdout.write(f"\r      {next(spinner)} {self.message} [{elapsed:.1f}s]")
                sys.stdout.flush()
            time.sleep(0.1)

    def __enter__(self):
        self.is_running = True
        # daemon=True. Якщо головний потік падає, цей потік помре автоматично
        self.spinner_thread = threading.Thread(target=self.spin, daemon=True)
        self.spinner_thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.is_running = False
        if self.spinner_thread:
            self.spinner_thread.join()

        with self._lock: # 🛡️ FIX
            # Очищення рядка після завершення
            sys.stdout.write('\r' + ' ' * 60 + '\r')
            sys.stdout.flush()

class CypherRunner:
    def __init__(self, env="local"):
        self.env = env  # Зберігаємо середовище для механізму ретраїв

        # Фабрика сама розбереться з протоколами, паролями та стейтами!
        self.driver = Neo4jConnectionFactory.get_driver(env=self.env)

    def close(self):
        Neo4jConnectionFactory.close_driver()

    def parse_cypher_script(self, raw_text):
        """
        🥭 FAANG-grade Cypher Lexer (State Machine).
        Посимвольно аналізує текст, гарантуючи, що коментарі '//' та розділювачі ';'
        ВСЕРЕДИНІ рядкових літералів ('...' або "...") будуть проігноровані.
        """
        queries = []
        current_query = []
        in_string = False
        string_char = None
        in_comment = False

        i = 0
        length = len(raw_text)

        while i < length:
            char = raw_text[i]

            # Стан 1: Ми всередині коментаря (ігноруємо все до кінця рядка)
            if in_comment:
                if char == '\n':
                    in_comment = False
                    current_query.append(char)
                i += 1
                continue

            # Стан 2: Ми всередині рядка (ігноруємо ; та // всередині)
            if in_string:
                current_query.append(char)
                if char == '\\': # Обробка екранованих символів (напр. \')
                    i += 1
                    if i < length:
                        current_query.append(raw_text[i])
                elif char == string_char:
                    in_string = False # Закрили рядок
                i += 1
                continue

            # Стан 3: Звичайний парсинг коду
            if char in ("'", '"'):
                in_string = True
                string_char = char
                current_query.append(char)
            elif char == '/' and i + 1 < length and raw_text[i+1] == '/':
                in_comment = True
                i += 1 # Пропускаємо другий '/'
            elif char == ';':
                # Знайшли кінець запиту ПОЗА рядком чи коментарем!
                query = "".join(current_query).strip()
                if query:
                    queries.append(query)
                current_query = []
            else:
                current_query.append(char)

            i += 1

        # Зберігаємо останній запит (якщо в кінці файлу не було ';')
        final_query = "".join(current_query).strip()
        if final_query:
            queries.append(final_query)

        return queries

    def run_script(self, file_path):
        """Читає .cypher файл і послідовно виконує запити з профілюванням часу."""
        path = Path(file_path)
        if not path.exists():
            print(f"⚠️ Файл {file_path} не знайдено. Пропускаємо...")
            return

        print(f"\n▶️ Читання та виконання запитів з {file_path}...")
        with open(path, 'r', encoding='utf-8') as f:
            raw_text = f.read()

        # Розбиваємо скрипт за допомогою State Machine Lexer
        queries = self.parse_cypher_script(raw_text)

        if not queries:
            print("  ℹ️ Скрипт порожній або містить лише коментарі.")
            return

        total_script_time = 0

        for i, query in enumerate(queries, 1):
            try:
                preview = query.replace('\n', ' ')[:60] + "..."
                print(f"  ⏳ [{i}/{len(queries)}] Виконання: {preview}")

                start_time = time.time()

                # =================================================================
                # 🛡️ АРХІТЕКТУРА ТРАНЗАКЦІЙ (Auto-commit vs Managed)
                # =================================================================
                upper_query = query.upper()
                is_ddl = any(kw in upper_query for kw in ["IN TRANSACTIONS", "CREATE INDEX", "DROP INDEX", "CREATE CONSTRAINT"])

                # 🔄 SRE Pattern: Ультимативний захист від кешування та вичерпання пулу
                max_retries = 15 # 150 секунд - надійний запас для важкого Docker-кластера
                for attempt in range(max_retries):
                    try:
                        # Запускаємо фоновий індикатор навколо бази даних
                        with QuerySpinner(message="Виконання запиту..."):
                            with self.driver.session() as session:
                                # Автоматично інжектуємо базовий URL з .env у кожен запит
                                params = {"base_url": os.getenv("NEO4J_DATA_BASE_URL", "file:///")}

                                if is_ddl:
                                    session.run(query, params).consume()
                                else:
                                    session.execute_write(lambda tx: tx.run(query, params))

                        break  # Успіх - виходимо

                    except Exception as e:
                        error_msg = str(e)
                        # Додано "NoThreadsAvailable" та "resource exhaustion"
                        if any(err in error_msg for err in ["WRITE server", "TransientError", "routing", "NoThreadsAvailable", "resource exhaustion"]):
                            if attempt < max_retries - 1:
                                print(f"      ⏳ [Raft / I/O Bottleneck] Кластер стабілізується. Скидаємо пули... (Спроба {attempt+1}/{max_retries})")
                                Neo4jConnectionFactory.close_driver()
                                time.sleep(10)
                                self.driver = Neo4jConnectionFactory.get_driver(env=self.env)
                            else:
                                raise e
                        else:
                            raise e # Синтаксична помилка - падаємо

                exec_time = time.time() - start_time
                total_script_time += exec_time
                print(f"      ✅ Завершено за {exec_time:.2f} сек.")

            except Exception as e:
                print(f"\n❌ КРИТИЧНА ПОМИЛКА: Файл '{file_path}' (Запит №{i})")
                print(f"{'-'*85}\n{query}\n{'-'*85}")
                print(f"Текст помилки: {e}")
                print("🛑 Пайплайн зупинено для збереження цілісності графа.")
                sys.exit(1)

        print(f"🏁 Скрипт {file_path} виконано за {total_script_time:.2f} сек сумарно.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enterprise Cypher Execution Engine")
    parser.add_argument("--env", choices=["local", "cloud"], default="local", help="Середовище виконання")
    parser.add_argument("--file", type=str, help="Шлях до конкретного .cypher файлу (якщо не вказано, запускається Batch-режим)")
    args = parser.parse_args()

    runner = CypherRunner(env=args.env)

    # Гарантоване закриття з'єднань
    try:
        if args.file:
            # 🎯 Режим одиничного запуску (для конкретного make-таргету)
            runner.run_script(args.file)
        else:
            # 🔄 Режим Batch (Explicit DAG / Жорсткий порядок)
            # 🗺️ Декларативний маніфест пайплайну
            pipeline_manifest = [
                {"path": "queries/part2_load.cypher",       "envs": ["local", "cloud"], "desc": "Імпорт даних (ETL)"},
                {"path": "queries/part3_queries.cypher",    "envs": ["local", "cloud"], "desc": "Базова аналітика"},
                {"path": "queries/part4_supernodes.cypher", "envs": ["local", "cloud"], "desc": "Ізоляція супервузлів"},
                {"path": "queries/part5_gds.cypher",        "envs": ["local", "cloud"], "desc": "Graph Data Science (Louvain, PageRank)"},
                {"path": "queries/part6_graphrag.cypher",   "envs": ["local", "cloud"], "desc": "GraphRAG Векторизація"}
            ]

            scripts_to_run = []
            aura_tier = os.getenv("AURA_TIER", "free").strip().lower()

            print(f"\n🗺️  Аналіз маніфесту пайплайну для середовища: [{args.env.upper()}] (Tier: {aura_tier.upper()})")

            # Універсальний фільтр маршрутизації (Dynamic Pruning)
            for step in pipeline_manifest:
                # 1. Перевірка базового середовища
                if args.env not in step["envs"]:
                    print(f"  ⚠️  [ПРОПУСК] {step['path']} — Вимкнено для {args.env.upper()} ({step['desc']})")
                    continue

                # 2. 🛡️ VIP-захист для алгоритмів GDS у хмарі
                if args.env == "cloud" and "part5_gds" in step["path"] and aura_tier != "ds":
                    print(f"  ⚠️  [ПРОПУСК] {step['path']} — Вимкнено для Aura {aura_tier.upper()}. Потрібен тариф AuraDS.")
                    continue

                scripts_to_run.append(step["path"])

            print(f"\n📋 Запуск {len(scripts_to_run)} скриптів за узгодженим сценарієм...")
            for script in scripts_to_run:
                runner.run_script(script)

        print("\n🎉 Усі графові операції успішно завершено!")

    finally:
        # Гарантоване закриття пулу з'єднань, навіть при помилках чи перериваннях
        runner.close()
