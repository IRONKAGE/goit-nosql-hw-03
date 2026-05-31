FROM python:3.12-slim

WORKDIR /app

# 1. Системні залежності
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# 2. Кешування шару залежностей (Best Practice)
COPY requirements.txt .

# 3. Встановлення пакетів з єдиного джерела істини
RUN pip install --no-cache-dir -r requirements.txt

# 4. Налаштування кешу для моделей
ENV HF_HOME=/app/.cache/huggingface

# 5. Запуск
CMD ["python", "-u", "scripts/generate_embeddings.py"]
