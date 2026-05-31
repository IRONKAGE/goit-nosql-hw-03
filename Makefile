# ==============================================================================
# MLOps & Data Engineering Orchestrator (Task 3: Neo4j) by IRONKAGE
# ==============================================================================

# 1. Експорт змінних середовища
ifneq (,$(wildcard ./.env))
	include .env
	export $(shell awk -F= '/^[a-zA-Z_]/ {print $$1}' .env)
endif

# --- Детектор рушія контейнерів (Docker або Podman) ---
ifneq (,$(shell command -v docker 2>/dev/null))
	DOCKER_CMD := docker
	COMPOSE_CMD := docker compose
else ifneq (,$(shell command -v podman 2>/dev/null))
	DOCKER_CMD := podman
	COMPOSE_CMD := podman compose
else
	DOCKER_CMD := none
endif

# 2. Кросплатформна підтримка ОС (Windows / Linux / MacOS) та Container Engine
ifeq ($(OS),Windows_NT)
	OPEN_CMD := start ""
	DOCKER_START_CMD := start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
	WAIT_DOCKER := powershell -Command "do { Write-Host '⏳ Чекаю на старт $(DOCKER_CMD)...'; Start-Sleep -Seconds 3 } while (!($(DOCKER_CMD) info 2>$$null))"
else
	UNAME_S := $(shell uname -s)
	UNAME_M := $(shell uname -m)
	ifeq ($(UNAME_S),Linux)
	    OPEN_CMD := xdg-open
	    DOCKER_START_CMD := systemctl --user start docker-desktop || sudo systemctl start docker
	    WAIT_DOCKER := until $(DOCKER_CMD) info >/dev/null 2>&1; do echo "⏳ Чекаю на старт $(DOCKER_CMD)..."; sleep 3; done
	endif
	ifeq ($(UNAME_S),Darwin)
	    OPEN_CMD := open
	    DOCKER_START_CMD := open -a Docker
	    WAIT_DOCKER := until $(DOCKER_CMD) info >/dev/null 2>&1; do echo "⏳ Чекаю на старт $(DOCKER_CMD)..."; sleep 3; done
	endif
endif

# ==============================================================================
# 🍎 ДЕТЕКТОР INTEL MAC (Для специфічних ML-залежностей)
# ==============================================================================
ifeq ($(UNAME_S),Darwin)
    ifeq ($(UNAME_M),x86_64)
        IS_MAC_INTEL := true
    endif
endif

# 3. Змінні середовища та DRY версіонування
PY_VER := 3.12
# Магія GNU Make: автоматично видаляємо крапку (3.12 -> 312) для AUR
PY_VER_FLAT := $(subst .,,$(PY_VER))
PYTHON_CMD := python$(PY_VER)

VENV := venv
# Прапорець -u вимикає буферизацію. Логи та прогрес-бари виводитимуться МИТТЄВО!
PYTHON := $(VENV)/bin/python -u
PIP := $(VENV)/bin/pip
STREAMLIT := $(VENV)/bin/streamlit

# Кольори
CYAN := \033[36m
GREEN := \033[32m
YELLOW := \033[33m
RED := \033[31m
RESET := \033[0m
GRAY := \033[90m

# ==============================================================================
# 🧠 POSITION ARGUMENT PARSER (Магія GNU Make для синтаксису без "=")
# ==============================================================================
# Визначаємо безпечний дефолтний розмір залежно від середовища (Захист хмари)
ifeq ($(strip $(ACTIVE_ENV)),cloud)
	DEFAULT_SIZE := 100K
else
	DEFAULT_SIZE := 1M
endif

# Перевіряємо, чи першою командою є db-up або db-load
SUPPORTED_ARGS_COMMANDS := db-up db-load

ifeq ($(filter $(word 1,$(MAKECMDGOALS)),$(SUPPORTED_ARGS_COMMANDS)),$(word 1,$(MAKECMDGOALS)))
	# Беремо другий за рахунком аргумент з термінала
	RAW_SIZE := $(word 2,$(MAKECMDGOALS))
	# Якщо другого аргументу немає, ставимо безпечний дефолт
	SIZE := $(if $(RAW_SIZE),$(RAW_SIZE),$(DEFAULT_SIZE))
	# Перетворюємо у верхній регістр (для 100k -> 100K)
	SIZE := $(shell echo $(SIZE) | tr '[:lower:]' '[:upper:]')

	# Магія: створюємо пусту ціль для аргументу, щоб Make не лаявся
	ifneq ($(RAW_SIZE),)
	    $(eval $(RAW_SIZE):;@:)
	endif
else
	SIZE := $(DEFAULT_SIZE)
endif

# ==============================================================================
# 🧠 SMART SIZING (Under the hood Resource Mapping)
# ==============================================================================
ifeq ($(SIZE),100K)
	DB_CLASS = db-s
	MEM_PER_NODE = 2
	NEO4J_MEM_LIMIT = 2G
	NEO4J_PAGECACHE = 512M
	NEO4J_HEAP_INIT = 256M
	NEO4J_HEAP_MAX = 1G
else ifeq ($(SIZE),1M)
	DB_CLASS = db-s
	MEM_PER_NODE = 4
	NEO4J_MEM_LIMIT = 4G
	NEO4J_PAGECACHE = 1G
	NEO4J_HEAP_INIT = 512M
	NEO4J_HEAP_MAX = 2G
else ifeq ($(SIZE),10M)
	DB_CLASS = db-m
	MEM_PER_NODE = 10
	NEO4J_MEM_LIMIT = 10G
	NEO4J_PAGECACHE = 3G
	NEO4J_HEAP_INIT = 2G
	NEO4J_HEAP_MAX = 4G
else ifeq ($(SIZE),25M)
	DB_CLASS = db-m
	MEM_PER_NODE = 16
	NEO4J_MEM_LIMIT = 16G
	NEO4J_PAGECACHE = 5G
	NEO4J_HEAP_INIT = 4G
	NEO4J_HEAP_MAX = 8G
else ifeq ($(SIZE),32M)
	DB_CLASS = db-l
	MEM_PER_NODE = 30
	NEO4J_MEM_LIMIT = 30G
	NEO4J_PAGECACHE = 8G
	NEO4J_HEAP_INIT = 8G
	NEO4J_HEAP_MAX = 16G
else
	$(error ❌ Невідомий розмір датасету: $(SIZE). Доступні валіди: 100K, 1M, 10M, 25M, 32M)
endif

# Розрахунок сумарної пам'яті залежно від профілю кластера
ifeq ($(strip $(COMPOSE_PROFILES)),cluster)
	REQ_MEM_TOTAL := $(shell expr $(MEM_PER_NODE) \* 3)
else
	REQ_MEM_TOTAL := $(MEM_PER_NODE)
endif

# ------------------------------------------------------------------------------
# 🧠 SMART ROUTING & DYNAMIC HELP: Динамічний вибір бази та тексту
# ------------------------------------------------------------------------------
ifeq ($(strip $(ACTIVE_ENV)),cloud)
	ENV_LABEL := ☁️  Хмара (Neo4j AuraDB)
	HELP_DB_UP      := $(GRAY)[Пропустити] Aura працює 24/7\n                         ⚠️  УВАГА: Дефолт змінено на 100K через ліміт ~200MB$(RESET)
	HELP_UI         := Відкрити хмарну веб-консоль (https://console.neo4j.io)
	HELP_DB_DOWN    := $(GRAY)[Пропустити] Не потрібно для хмари$(RESET)
	HELP_DB_CLEAN   := $(GRAY)[Пропустити] Очищення хмари робиться через консоль Aura (Reset to blank)$(RESET)
	HELP_DEEP_CLEAN := ПОВНЕ очищення (Лише Python кеші та імпорти, хмара не зачіпається)
else
	ifeq ($(strip $(COMPOSE_PROFILES)),cluster)
	    ENV_LABEL := 🖥️  Локально ($(DOCKER_CMD) 3-Node Enterprise Cluster)
	else
	    ENV_LABEL := 🖥️  Локально ($(DOCKER_CMD) Community Standalone)
	endif

	HELP_DB_UP      := Підняти інфраструктуру та автоматично підготувати датасет
	HELP_UI         := Відкрити Neo4j Browser (http://localhost:7474)
	HELP_DB_DOWN    := Зупинити контейнери (Дані ЗБЕРІГАЮТЬСЯ у volume)
	HELP_DB_CLEAN   := Очистити базу даних (Знищити Volumes, але залишити CSV)
	HELP_DEEP_CLEAN := ПОВНЕ очищення (Знищити БД, Volumes, Образи $(DOCKER_CMD) та CSV)
endif

# ==============================================================================
# ⚡ УНІВЕРСАЛЬНИЙ CYPHER ЗАПУСКАЧ (Пряме підключення через драйвер Python)
# Відмова від cypher-shell робить код кросплатформним та єдиним для Local/Cloud
# ==============================================================================
CYPHER_CMD := $(PYTHON) scripts/cypher_runner.py --env $(strip $(ACTIVE_ENV)) --file

.PHONY: help setup env ensure-python docker-ensure check-resources db-up db-down db-clean ui etl pipeline db-load embeddings part3 part4 part5 part6 run-queries dashboard rag clean ml-clean deep-clean setup-intel
help:
	@echo "$(CYAN)=======================================================================================================================$(RESET)"
	@echo "$(GREEN)🎥 MovieLens Graph Recommendation Platform - Data Engineering Makefile | $(YELLOW)$(ENV_LABEL)$(RESET)"
	@echo "$(CYAN)=======================================================================================================================$(RESET)"
	@echo "Послідовність виконання проекту:"
	@echo "  $(YELLOW)[КРОК 0] Підготовка середовища:$(RESET)"
	@echo "    $(GREEN)make env$(RESET)           - Створити базовий .env файл (додайте ваші ключі Kaggle/AuraDB)"
	@echo "    $(GREEN)make setup$(RESET)         - Створити віртуальне середовище та встановити залежності"
ifdef IS_MAC_INTEL
	@echo "    $(GREEN)make setup-intel$(RESET)   - 🍎 Встановити PyTorch 2.2.2 для GraphRAG (Оптимізовано для macOS з Intel)"
endif
	@echo "--------------------------------------------------------------------------------------------------"
	@echo "  $(YELLOW)[КРОК 1] Інфраструктура бази даних та Датасет:$(RESET)"
	@echo "    $(GREEN)make db-up$(RESET)         - $(HELP_DB_UP)"
	@echo "                         $(GRAY)Синтаксис: make db-up [100K | 1M | 10M | 25M | 32M]$(RESET)"
	@echo "--------------------------------------------------------------------------------------------------"
	@echo "  $(YELLOW)[КРОК 2] Покрокова Побудова, AI та Аналітика (Cypher):$(RESET)"
	@echo "    $(GREEN)make pipeline$(RESET)      - 🚀 АВТОПІЛОТ: Запустити весь пайплайн (Граф + Вектори + Запити)"
	@echo "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"
	@echo "    $(GREEN)make db-load$(RESET)       - (Частина 2) Завантажити граф знань та індекси (LOAD CSV)"
	@echo "                         $(GRAY)Приклад: 'make db-load 32M' (має збігатися з розміром бази)$(RESET)"
	@echo "    $(GREEN)make embeddings$(RESET)    - Згенерувати вектори для GraphRAG 🧬"
	@echo "    $(GREEN)make part3$(RESET)         - (Частина 3) Виконати базові та рекомендаційні запити"
	@echo "    $(GREEN)make part4$(RESET)         - (Частина 4) Знайти супервузли (Supernodes)"
	@echo "    $(GREEN)make part5$(RESET)         - (Частина 5) Запустити Graph Data Science (PageRank, Louvain, Dijkstra)"
	@echo "    $(GREEN)make part6$(RESET)         - (Частина 6) Завантажити вектори у граф та створити HNSW індекс (Бонус 📟)"
	@echo "                         $(GRAY)❗️ Увага: Запит потребує попереднього завантаження векторів GraphRAG$(RESET)"
	@echo "    $(GREEN)make run-queries$(RESET)   - Запустити всі запити батчем (через Python runner) 🦄"
	@echo "                         $(GRAY)❗️ Увага: Запит потребує попереднього завантаження векторів GraphRAG$(RESET)"
	@echo "--------------------------------------------------------------------------------------------------"
	@echo "  $(YELLOW)[КРОК 3] Інтерфейси та Візуалізація:$(RESET)"
	@echo "    $(GREEN)make ui$(RESET)            - $(HELP_UI)"
	@echo "    $(GREEN)make dashboard$(RESET)     - Запустити інтерактивний BI-дашборд на Streamlit"
	@echo "    $(GREEN)make rag$(RESET)           - Запустити GraphRAG AI Чат-бот 👾"
	@echo "--------------------------------------------------------------------------------------------------"
	@echo "  $(YELLOW)[КРОК 4] Керування та очищення:$(RESET)"
	@echo "    $(GREEN)make db-down$(RESET)       - $(HELP_DB_DOWN)"
	@echo "    $(GREEN)make db-clean$(RESET)      - $(HELP_DB_CLEAN)"
	@echo "    $(GREEN)make deep-clean$(RESET)    - $(HELP_DEEP_CLEAN)"
	@echo "    $(GREEN)make ml-clean$(RESET)      - Очистити глобальний кеш ML-моделей Hugging Face"
	@echo "$(CYAN)==================================================================================================$(RESET)"

env:
	@if [ ! -f .env ]; then \
	    echo "ACTIVE_ENV=local" > .env; \
	    echo "COMPOSE_PROFILES=cluster" >> .env; \
	    echo "NEO4J_LOCAL_USER=neo4j" >> .env; \
	    echo "NEO4J_LOCAL_PASS=secret12345" >> .env; \
	    echo "NEO4J_LOCAL_URI=neo4j://127.0.0.1:7687" >> .env; \
	    echo "NEO4J_CLOUD_URI=neo4j+s://<твій_інстанс>.databases.neo4j.io" >> .env; \
	    echo "NEO4J_CLOUD_USER=neo4j" >> .env; \
	    echo "NEO4J_CLOUD_PASS=your_cloud_password_here" >> .env; \
	    echo "KAGGLE_USERNAME=" >> .env; \
	    echo "KAGGLE_KEY=" >> .env; \
	    echo "$(GREEN)✅ Файл .env створено! (Згенеровано для Cluster Profile)$(RESET)"; \
	else \
	    echo "$(YELLOW)⚡ Файл .env вже існує. Пропускаємо.$(RESET)"; \
	fi

# ------------------------------------------------------------------------------
# АВТОМАТИЗАЦІЯ PYTHON (Авто-встановлення та VENV)
# ------------------------------------------------------------------------------
ensure-python:
	@echo "$(CYAN)🔍 Перевірка наявності $(PYTHON_CMD)...$(RESET)"
	@command -v $(PYTHON_CMD) >/dev/null 2>&1 || { \
	    echo "$(YELLOW)⚙️  $(PYTHON_CMD) не знайдено. Запускаю автоматичне встановлення...$(RESET)"; \
	    if [ "$(OS)" = "Windows_NT" ] || [ -n "$$WINDIR" ]; then \
	        echo "$(CYAN)🪟 Виявлено Windows. Встановлюю через PowerShell (winget)...$(RESET)"; \
	        powershell -NoProfile -Command "winget install --id Python.Python.$(PY_VER) -e --silent --accept-package-agreements --accept-source-agreements"; \
	    elif [ "$(UNAME_S)" = "Darwin" ]; then \
	        echo "$(CYAN)🍏 Виявлено macOS. Встановлюю через Homebrew...$(RESET)"; \
	        brew install python@$(PY_VER); \
	    elif [ "$(UNAME_S)" = "Linux" ]; then \
	        if command -v apt-get >/dev/null 2>&1; then \
	            echo "$(CYAN)🟠 Виявлено Debian/Ubuntu. Встановлюю через APT...$(RESET)"; \
	            sudo apt-get update && sudo apt-get install -y python$(PY_VER) python$(PY_VER)-venv; \
	        elif command -v pacman >/dev/null 2>&1; then \
	            echo "$(CYAN)👻 Виявлено Arch Linux. Шукаю специфічну версію Python $(PY_VER)...$(RESET)"; \
	            if command -v yay >/dev/null 2>&1; then \
	                echo "$(CYAN)📦 Знайдено AUR-хелпер 'yay'. Встановлюю python$(PY_VER_FLAT)...$(RESET)"; \
	                yay -S --noconfirm python$(PY_VER_FLAT); \
	            elif command -v paru >/dev/null 2>&1; then \
	                echo "$(CYAN)📦 Знайдено AUR-хелпер 'paru'. Встановлюю python$(PY_VER_FLAT)...$(RESET)"; \
	                paru -S --noconfirm python$(PY_VER_FLAT); \
	            else \
	                echo "$(YELLOW)❌ В офіційних репозиторіях Arch лише найновіший Python.$(RESET)"; \
	                echo "$(YELLOW)👉 Для встановлення $(PY_VER) потрібен AUR. Виконайте вручну: yay -S python$(PY_VER_FLAT)$(RESET)" && exit 1; \
	            fi; \
	        elif command -v dnf >/dev/null 2>&1; then \
	            echo "$(CYAN)🎩 Виявлено Fedora/RHEL. Встановлюю через DNF...$(RESET)"; \
	            sudo dnf install -y python$(PY_VER); \
	        else \
	            echo "$(YELLOW)❌ Невідомий пакетний менеджер Linux. Встановіть Python $(PY_VER) вручну.$(RESET)" && exit 1; \
	        fi; \
	    else \
	        echo "$(YELLOW)❌ Невідома ОС. Встановіть Python $(PY_VER) вручну з python.org$(RESET)" && exit 1; \
	    fi; \
	}
	@echo "$(GREEN)✅ $(PYTHON_CMD) присутній у системі!$(RESET)"

setup: env ensure-python
	@echo "$(CYAN)📦 Створення віртуального середовища ($(PYTHON_CMD))...$(RESET)"
	$(PYTHON_CMD) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo "$(GREEN)✅ Віртуальне оточення готове!$(RESET)"

# ------------------------------------------------------------------------------
# 🍎 СПЕЦІАЛЬНА ЦІЛЬ ДЛЯ INTEL MAC (Створення Sidecar Environment через uv)
# ------------------------------------------------------------------------------
setup-intel:
ifdef IS_MAC_INTEL
	@echo "$(CYAN)🍎 Виявлено macOS Intel. Розгортання ізольованого ML-середовища через 'uv'...$(RESET)"
	@$(PIP) install uv
	@echo "$(YELLOW)⏳ Створення мікро-середовища (venv-intel) на базі $(PYTHON_CMD)...$(RESET)"
	@# 🚀 Явно змушуємо uv використовувати Python 3.12 замість системного 3.13
	@$(VENV)/bin/uv venv --python $(PYTHON_CMD) venv-intel
	@echo "$(YELLOW)🐣 Блискавичне встановлення сумісного стеку (NumPy 1.x)...$(RESET)"
	@# Встановлюємо старий ML-стек + базові драйвери, які потрібні для RAG
	@$(VENV)/bin/uv pip install --python venv-intel \
		torch==2.2.2 \
		sentence-transformers==2.7.0 \
		transformers==4.41.2 \
		numpy==1.26.4 \
		neo4j==6.2.0 \
		python-dotenv==1.2.2
	@echo "$(GREEN)✅ Sidecar-середовище готове! Головний 'venv' залишився недоторканим.$(RESET)"
else
	@echo "$(RED)🛑 ПОМИЛКА: Ця команда призначена ВИКЛЮЧНО для macOS на базі процесорів Intel (x86_64).$(RESET)"
	@exit 1
endif

# ------------------------------------------------------------------------------
# АВТОМАТИЗАЦІЯ КОНТЕЙНЕРІВ (Перевірка, запуск та очікування)
# ------------------------------------------------------------------------------
docker-ensure:
	@echo "$(CYAN)[*] Перевірка наявності Container Engine (Docker/Podman)...$(RESET)"
	@if [ "$(DOCKER_CMD)" = "none" ]; then \
	    echo "$(YELLOW)❌ Критична помилка: Docker або Podman не знайдено!$(RESET)\n👉 Встановіть Docker Desktop або Podman." && exit 1; \
	fi
	@echo "$(CYAN)[*] Знайдено рушій: $(DOCKER_CMD). Перевірка стану...$(RESET)"
	@$(DOCKER_CMD) info >/dev/null 2>&1 || (echo "$(YELLOW)[!] $(DOCKER_CMD) вимкнено. Виконую автоматичний запуск...$(RESET)" && $(DOCKER_START_CMD) && $(WAIT_DOCKER))
	@echo "$(GREEN)[+] $(DOCKER_CMD) готовий до роботи!$(RESET)"

# --- ХАРДВЕРНИЙ ДЕТЕКТОР (PYTHON DYNAMIC SCRIPT) ТА АВТО-ПЕРЕМИКАННЯ ПРОФІЛІВ ---
check-resources:
	@echo "$(CYAN)🔍 Аналіз заліза (Авто-підбір конфігурації)...$(RESET)"
	@echo "import platform, subprocess" > .hw_check.py
	@echo "gb = 8" >> .hw_check.py
	@echo "try:" >> .hw_check.py
	@echo "    s = platform.system()" >> .hw_check.py
	@echo "    if s == 'Windows':" >> .hw_check.py
	@echo "        import ctypes" >> .hw_check.py
	@echo "        class M(ctypes.Structure): _fields_=[('l',ctypes.c_ulong),('m',ctypes.c_ulong),('t',ctypes.c_ulonglong)]" >> .hw_check.py
	@echo "        mem = M(); mem.l = ctypes.sizeof(M); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)); gb = mem.t / (1024**3)" >> .hw_check.py
	@echo "    elif s == 'Darwin':" >> .hw_check.py
	@echo "        gb = int(subprocess.check_output(['sysctl', '-n', 'hw.memsize'])) / (1024**3)" >> .hw_check.py
	@echo "    else:" >> .hw_check.py
	@echo "        gb = int([l.split()[1] for l in open('/proc/meminfo') if 'MemTotal' in l][0]) / (1024**2)" >> .hw_check.py
	@echo "except:" >> .hw_check.py
	@echo "    pass" >> .hw_check.py
	@echo "req = int('$(MEM_PER_NODE)'); prof = '$(strip $(COMPOSE_PROFILES))'" >> .hw_check.py
	@echo "if prof == 'cluster' and gb >= (req * 3): print('cluster')" >> .hw_check.py
	@echo "elif gb >= req: print('standalone')" >> .hw_check.py
	@echo "else: print('fail')" >> .hw_check.py
	@ACTUAL_PROFILE=$$($(PYTHON_CMD) .hw_check.py 2>/dev/null); \
	rm -f .hw_check.py; \
	if [ -z "$$ACTUAL_PROFILE" ]; then ACTUAL_PROFILE="standalone"; fi; \
	if [ "$$ACTUAL_PROFILE" = "fail" ]; then \
		echo "\n$(RED)❌ М'ЯКА ПОМИЛКА: Катастрофічно мало оперативної пам'яті!$(RESET)"; \
		echo "Для датасету $(CYAN)$(SIZE)$(RESET) потрібно мінімум $(RED)$(MEM_PER_NODE) ГБ$(RESET) ОЗП."; \
		echo "👉 Оберіть менший розмір, наприклад: $(YELLOW)make db-up 100K$(RESET)\n"; \
		exit 1; \
	elif [ "$(strip $(COMPOSE_PROFILES))" = "cluster" ] && [ "$$ACTUAL_PROFILE" = "standalone" ]; then \
		echo "$(YELLOW)⚠️  БРАКУЄ ОЗП ДЛЯ КЛАСТЕРА ($(REQ_MEM_TOTAL) ГБ). Система автоматично перемикається на $(GREEN)STANDALONE$(YELLOW) ($(MEM_PER_NODE) ГБ)!$(RESET)"; \
	else \
		echo "$(GREEN)✅ Залізо перевірено: ресурсів достатньо для профілю $$ACTUAL_PROFILE.$(RESET)"; \
	fi; \
	echo "$$ACTUAL_PROFILE" > .dynamic_profile

# --- SMART ETL (Авто-відключення якщо файли існують, з використанням маркерів стану та перевірки цілісності) ---
etl:
	@echo "$(CYAN)🔄 Перевірка стану датасету $(SIZE)...$(RESET)"
	@if [ -f "import/.dataset_$(SIZE)" ] && [ -f "import/movies.csv" ] && [ -f "import/ratings.csv" ] && [ -f "import/users.csv" ]; then \
	    echo "$(GREEN)✅ Актуальний датасет ($(SIZE)) та всі CSV-файли цілі! Пропускаємо конвертацію.$(RESET)"; \
	else \
	    echo "$(YELLOW)⏳ Датасет $(SIZE) відсутній, змінено розмір або файли пошкоджено. Запускаємо генерацію...$(RESET)"; \
	    rm -f import/.dataset_* import/*.csv; \
	    $(PYTHON) scripts/convert.py --size $(SIZE); \
	    touch import/.dataset_$(SIZE); \
	fi

db-up:
	@if [ "$(strip $(ACTIVE_ENV))" = "cloud" ]; then \
		echo "$(YELLOW)⚡ Активне середовище - хмара (AuraDB). Локальні ресурси та контейнери ігноруються.$(RESET)"; \
		if [ "$(SIZE)" != "100K" ]; then \
			echo "$(RED)⚠️ КРИТИЧНО: Ви готуєте датасет $(SIZE), але безкоштовна AuraDB витримає лише 100K (~200MB)!$(RESET)"; \
		else \
			echo "$(GREEN)✅ Розмір $(SIZE) є безпечним для безкоштовної хмари AuraDB.$(RESET)"; \
		fi; \
		$(MAKE) etl; \
	else \
		$(MAKE) docker-ensure; \
		$(MAKE) check-resources; \
		$(MAKE) etl; \
		ACTUAL_PROFILE=$$(cat .dynamic_profile 2>/dev/null | tr -d '[:space:]'); \
		if [ -z "$$ACTUAL_PROFILE" ]; then ACTUAL_PROFILE="standalone"; fi; \
		echo "$(CYAN)🐳 Підняття Neo4j (Клас: $(DB_CLASS) | Розмір: $(SIZE) | Профіль: $$ACTUAL_PROFILE)...$(RESET)"; \
		if [ "$$ACTUAL_PROFILE" = "cluster" ] && [ "$(MEM_PER_NODE)" -ge 10 ]; then \
			echo "$(YELLOW)⚠️  УВАГА: Виділяється залізо для КЛАСТЕРА (Сумарно $(REQ_MEM_TOTAL)GB RAM)!$(RESET)"; \
		fi; \
		NEO4J_MEM_LIMIT=$(NEO4J_MEM_LIMIT) NEO4J_PAGECACHE=$(NEO4J_PAGECACHE) NEO4J_HEAP_INIT=$(NEO4J_HEAP_INIT) NEO4J_HEAP_MAX=$(NEO4J_HEAP_MAX) COMPOSE_PROFILES="$$ACTUAL_PROFILE" $(COMPOSE_CMD) up -d --wait || { echo "$(RED)❌ Помилка: Docker не зміг підняти інфраструктуру! Дивіться логи вище.$(RESET)"; exit 1; }; \
		echo "$(GREEN)✅ Neo4j успішно піднято та готовий до роботи!$(RESET)"; \
	fi

# ------------------------------------------------------------------------------
# ⚠️ STATE MANAGEMENT ТА PID FILES
# ------------------------------------------------------------------------------
# Чому відсутня команда `rm -f .dynamic_profile;`?
#
# 1. SRE/Linux Парадигма (PID Files):
# У класичному адмініструванні Linux файли стану (наприклад, .pid файли демонів)
# є ефемерними. Вони існують виключно тоді, коли процес фізично працює.
# При зупинці сервісу PID-файл видаляється, щоб уникнути хибної маршрутизації
# трафіку на "мертвий" вузол (Stale State).
#
# 2. Наша парадигма (Docker Hibernation State):
# Команда `docker compose down` (без прапорця -v) виконує роль "гібернації".
# Інфраструктура зупиняється, звільняючи ОЗП, але томи (Volumes) з даними
# залишаються недоторканими.
#
# Якби ми видалили `.dynamic_profile` під час гібернації, Python-фабрика
# підключень втратила б контекст того, в якому саме стані (cluster чи standalone)
# система "заснула". Залишаючи цей State-файл, ми гарантуємо абсолютну
# архітектурну консистентність: при наступному `make db-up` система прокинеться
# з тими самими налаштуваннями протоколу (neo4j:// або bolt://).
#
# Повне знищення файлу стану логічно перенесено у таргети `db-clean` та `deep-clean`,
# де відбувається фізичне знищення графів (Volumes).
# ------------------------------------------------------------------------------
db-down:
	@if [ "$(strip $(ACTIVE_ENV))" = "cloud" ]; then \
		echo "$(YELLOW)⚡ Активне середовище - хмара (AuraDB). Інфраструктура не запущена локально.$(RESET)"; \
	else \
		$(MAKE) docker-ensure; \
		echo "$(YELLOW)🛑 Згортання інфраструктури Neo4j (знищення тимчасових контейнерів)...$(RESET)"; \
		$(COMPOSE_CMD) down; \
		echo "$(GREEN)✅ Контейнери та віртуальну мережу видалено (дані безпечно збережено у Volume).$(RESET)"; \
	fi

# Очищення бази даних - видалення томів (Volumes) та маркерів стану, але збереження CSV для швидкого повторного завантаження
db-clean:
	@if [ "$(strip $(ACTIVE_ENV))" = "cloud" ]; then \
		echo "$(YELLOW)⚡ Активне середовище - хмара (AuraDB). Очищення локальних томів не потрібне.$(RESET)"; \
	else \
		$(MAKE) docker-ensure; \
		echo "$(YELLOW)🧹 Видалення контейнерів Neo4j та очищення графа (Volumes)...$(RESET)"; \
		$(COMPOSE_CMD) down -v; \
		rm -f .dynamic_profile; \
		echo "$(GREEN)✅ Базу даних повністю очищено! Можна піднімати новий розмір (наприклад: make db-up 32M).$(RESET)"; \
	fi

ui:
	@if [ "$(strip $(ACTIVE_ENV))" = "cloud" ]; then \
		echo "$(CYAN)🌐 Відкриваємо хмарну консоль Neo4j Aura...$(RESET)"; \
		$(OPEN_CMD) https://console.neo4j.io/; \
	else \
		echo "$(CYAN)🌐 Відкриваємо локальний Neo4j Browser...$(RESET)"; \
		$(OPEN_CMD) http://127.0.0.1:7474; \
	fi

# ------------------------------------------------------------------------------
# ПАЙПЛАЙН ДАНИХ ТА АНАЛІТИКА (ПОКРОКОВИЙ ЗАПУСК АБО БАТЧ)
# ------------------------------------------------------------------------------
pipeline:
	@echo "$(CYAN)🚀 ЗАПУСК АВТОМАТИЧНОГО ПАЙПЛАЙНУ (END-TO-END)...$(RESET)"
	@if [ "$(strip $(ACTIVE_ENV))" = "cloud" ]; then \
		echo "$(RED)⛔ СТОП: Автоматичний End-to-End пайплайн призупинено для хмари!$(RESET)"; \
		echo "$(YELLOW)ℹ️  Причина: Після кроку 'embeddings' файл 'movies_embedded.csv' з'явиться локально.$(RESET)"; \
		echo "$(YELLOW)   Але хмарна AuraDB шукатиме його за вашим URL у S3-бакеті: $(NEO4J_DATA_BASE_URL)$(RESET)"; \
		echo "$(CYAN)👉 Правильний SRE Workflow для хмари:$(RESET)"; \
		echo "   1. Виконайте $(YELLOW)make embeddings$(RESET) (згенерує вектори локально)"; \
		echo "   2. Завантажте файли з папки import/ у свій S3-сховище"; \
		echo "   3. Виконайте $(YELLOW)make run-queries$(RESET) (база прочитає файли з S3)"; \
		exit 1; \
	fi
	$(MAKE) embeddings
	$(MAKE) run-queries
	@echo "$(GREEN)🎉 Пайплайн успішно завершено! Граф та вектори готові.$(RESET)"
	@echo "$(YELLOW)👉 Тепер ви можете запустити 'make dashboard' або 'make rag'.$(RESET)"

db-load:
	@echo "$(CYAN)🧠 (Частина 2) Завантаження графа знань у Neo4j ($(ENV_LABEL)) для розміру $(SIZE)...$(RESET)"
	@if [ "$(strip $(ACTIVE_ENV))" = "cloud" ] && [ "$(strip $(AURA_TIER))" = "free" ] && [ "$(SIZE)" != "100K" ]; then \
		echo "$(RED)⛔ КРИТИЧНЕ ПОПЕРЕДЖЕННЯ: Ви намагаєтесь завантажити $(SIZE) у БЕЗКОШТОВНУ хмару!$(RESET)"; \
		echo "$(RED)База гарантовано впаде (Out of Memory/Quota). Змініть AURA_TIER у .env, якщо у вас платний тариф!$(RESET)"; \
		echo "$(YELLOW)⏳ Очікування 5 секунд перед суїцидальним завантаженням...$(RESET)"; \
		sleep 5; \
	fi
	$(CYPHER_CMD) queries/part2_load.cypher
	@echo "$(GREEN)✅ Граф успішно завантажено! Переходьте до генерації векторів або аналітики.$(RESET)"

embeddings:
	@if [ "$(UNAME_S)" = "Darwin" ] && [ "$(UNAME_M)" = "x86_64" ]; then \
		echo "$(CYAN)⚡ Виявлено macOS x86_64 (Intel Mac). Запуск через ізольований контейнер...$(RESET)"; \
		echo "$(YELLOW)⚠️  Примітка: Віртуалізація macOS не підтримує прокидання GPU. Векторизація виконається на потужностях CPU.$(RESET)"; \
		if [ "$(DOCKER_CMD)" = "none" ]; then \
			echo "$(RED)❌ КРИТИЧНО: Не знайдено ні Docker, ні Podman!$(RESET)"; exit 1; \
		fi; \
		echo "$(YELLOW)📦 Збірка ML-образу через $(DOCKER_CMD)...$(RESET)"; \
		$(DOCKER_CMD) build -t movielens_ml -f Dockerfile.ml .; \
		echo "$(GREEN)🚀 Запуск векторизації...$(RESET)"; \
		$(DOCKER_CMD) run --rm -v "$$(pwd):/app" movielens_ml; \
	else \
		echo "$(CYAN)⚡ Виявлено нативне середовище. Запуск генерації...$(RESET)"; \
		$(PYTHON) scripts/generate_embeddings.py; \
	fi

part3:
	@echo "$(CYAN)📊 (Частина 3) Запуск базових та рекомендаційних запитів...$(RESET)"
	$(CYPHER_CMD) queries/part3_queries.cypher

part4:
	@echo "$(CYAN)🕸️  (Частина 4) Аналіз та виявлення супервузлів...$(RESET)"
	$(CYPHER_CMD) queries/part4_supernodes.cypher

part5:
	@echo "$(CYAN)🧬 (Частина 5) Запуск алгоритмів Graph Data Science (GDS)...$(RESET)"
	@if [ "$(strip $(ACTIVE_ENV))" = "cloud" ] && [ "$(strip $(AURA_TIER))" != "ds" ]; then \
		echo "$(RED)⛔ КРИТИЧНО: Ваш тариф хмари ($(AURA_TIER)) не підтримує плагін GDS!$(RESET)"; \
		echo "$(YELLOW)💡 GDS доступний лише локально (Docker) або у дорогому тарифі Neo4j AuraDS (AURA_TIER=ds).$(RESET)"; \
		echo "$(YELLOW)⏩ Зупинка таргету...$(RESET)"; \
		exit 1; \
	fi
	$(CYPHER_CMD) queries/part5_gds.cypher
	@echo "$(YELLOW)💡 Порада: Проекції GDS створюються в оперативній пам'яті. Переконайтесь, що у вас достатньо ОЗП.$(RESET)"

part6:
	@echo "$(CYAN)🧠 (Частина 6) Завантаження векторів у граф та побудова GraphRAG HNSW індексу...$(RESET)"
	$(CYPHER_CMD) queries/part6_graphrag.cypher
	@echo "$(GREEN)✅ Векторний індекс побудовано! GraphRAG готовий до запитів.$(RESET)"

run-queries:
	@echo "$(CYAN)⚡ АВТОМАТИЗАЦІЯ: Пакетний запуск усіх запитів...$(RESET)"
	@if [ "$(strip $(ACTIVE_ENV))" = "cloud" ]; then \
		if [ "$(strip $(AURA_TIER))" = "free" ] && [ "$(SIZE)" != "100K" ]; then \
			echo "$(RED)⛔ КРИТИЧНЕ ПОПЕРЕДЖЕННЯ: Виконувати повний батч на $(SIZE) у БЕЗКОШТОВНІЙ хмарі ЗАБОРОНЕНО!$(RESET)"; \
			exit 1; \
		fi; \
		echo "$(YELLOW)⚠️  УВАГА: Ви в хмарному режимі (AuraDB - Тариф: $(AURA_TIER)).$(RESET)"; \
		echo "$(YELLOW)Переконайтеся, що всі CSV-файли (включно з векторами) вже завантажено до: $(NEO4J_DATA_BASE_URL)$(RESET)"; \
		echo "$(CYAN)⏳ Запуск через 3 секунди... (Натисніть Ctrl+C для скасування)$(RESET)"; \
		sleep 3; \
	fi
	@echo "$(YELLOW)📍 Запускаю скрипт агрегації...$(RESET)"
	$(PYTHON) scripts/cypher_runner.py --env $(strip $(ACTIVE_ENV))

dashboard:
	@echo "$(CYAN)📈 Запуск Streamlit BI Dashboard...$(RESET)"
	$(STREAMLIT) run dashboard/app.py

rag:
	@echo "$(CYAN)🤖 Запуск GraphRAG AI Чат-бота...$(RESET)"
	@if [ "$(IS_MAC_INTEL)" = "true" ]; then \
		echo "$(YELLOW)⚡ Маршрутизація: Запуск через ізольоване середовище Intel (venv-intel)...$(RESET)"; \
		if [ ! -d "venv-intel" ]; then \
			echo "$(RED)❌ Середовище не знайдено. Спочатку виконайте: make setup-intel$(RESET)"; exit 1; \
		fi; \
		venv-intel/bin/python -u scripts/rag_inference.py --env $(strip $(ACTIVE_ENV)); \
	else \
		$(PYTHON) scripts/rag_inference.py --env $(strip $(ACTIVE_ENV)); \
	fi

clean:
	@echo "$(YELLOW)🧹 Очищення тимчасових файлів...$(RESET)"
	rm -rf __pycache__ .pytest_cache .cache
	find . -type d -name "__pycache__" -exec rm -r {} +
	find . -type f -name "*.pyc" -delete
	@echo "$(YELLOW)🧹 Очищення артефактів Streamlit/PyVis...$(RESET)"
	rm -rf dashboard/lib dashboard/*.html
	@echo "$(GREEN)✅ Проект очищено!$(RESET)"

# Хардкорне знищення всього
deep-clean: clean
	@echo "$(YELLOW)🧹 Видалення ізольованого середовища venv-intel (якщо існує)...$(RESET)"
	@rm -rf venv-intel
	@if [ "$(strip $(ACTIVE_ENV))" = "cloud" ]; then \
		echo "$(YELLOW)⚠️  ПОВНЕ ОЧИЩЕННЯ: Знищено локальні кеші. Хмарна БД не зачеплена.$(RESET)"; \
		rm -rf import/* import/.dataset_*; \
		echo "$(YELLOW)🐳 Видалення ML Docker-образу (якщо існує)...$(RESET)"; \
		docker rmi movielens_ml -f 2>/dev/null || true; \
	else \
		echo "$(YELLOW)⚠️  ПОВНЕ ОЧИЩЕННЯ: Видалення Томів (Графа), Імпортів та зупинка контейнерів...$(RESET)"; \
		$(COMPOSE_CMD) down -v || true; \
		rm -rf import/* import/.dataset_*; \
		rm -f .dynamic_profile; \
		echo "$(YELLOW)🐳 Видалення ізольованого ML Docker-образу (якщо існує)...$(RESET)"; \
		docker rmi movielens_ml -f 2>/dev/null || true; \
		echo "$(GREEN)✅ Локальну інфраструктуру повністю знищено. Пам'ять звільнено!$(RESET)"; \
	fi
	@echo "$(CYAN)💡 Підказка: Якщо ви хочете також звільнити місце на диску від глобальних нейромереж, запустіть 'make ml-clean'.$(RESET)"

ml-clean:
	@echo "$(YELLOW)🧠 Запуск менеджера кешу ML-моделей (Hugging Face)...$(RESET)"
	@echo "$(RED)Увага: Це глобальний кеш ОС. Видалення вплине на всі ваші локальні ML-проекти.$(RESET)"
	@huggingface-cli delete-cache || true
	@echo "$(GREEN)✅ Роботу з кешем моделей завершено!$(RESET)"

# Хак для ігнорування невідомих аргументів термінала
%:
	@:
