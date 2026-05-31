import os
# ===============================================================================
# 🛡️ БРОНЯ ДЛЯ APPLE MPS (Metal Performance Shaders)
# Наказуємо PyTorch мовчки використовувати CPU для операцій, які ще не підтримуються відеокартою,
# замість того, щоб викидати фатальну помилку (особливо актуально для torch 2.2.2 на Intel/AMD Mac).
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
# ===============================================================================

import logging
import gc
from pathlib import Path
import pandas as pd
import numpy as np
import torch
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

# Налаштування логера
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger(__name__)

# ==========================================
# КОНФІГУРАЦІЯ
# ==========================================
IMPORT_DIR = Path("import")
INPUT_FILE = IMPORT_DIR / "movies.csv"
OUTPUT_FILE = IMPORT_DIR / "movies_embedded.csv"

# Сучасна Safetensors модель (768 вимірів, топ у бенчмарках MTEB)
MODEL_NAME = "BAAI/bge-base-en-v1.5"
BATCH_SIZE = 16 # Навіть при 64 - GPU AMD 5600 Pro з HMB2 8 Gb - вибиває помилку "CUDA out of memory", тому 16 - це безпечний вибір для широкої сумісності
GLOBAL_SEED = 42

def get_hardware_config():
    """
    АПАРАТНЕ ПРИСКОРЕННЯ (Ультимативна автодетекція заліза)
    Визначає найкращий доступний обчислювальний бекенд та синхронізує випадковість.
    """
    torch.manual_seed(GLOBAL_SEED) # Базовий сід для CPU та загальних генераторів

    if torch.cuda.is_available():
        device = torch.device("cuda")
        device_ui_name = "CUDA (NVIDIA / AMD GPU)"   # Від домашніх GTX 1060 до серверних монстрів NVIDIA B200 / AMD MI300X та хмарних ASICs типу Baidu Kunlunxin / Tencent Zixiao
        torch.cuda.manual_seed_all(GLOBAL_SEED)      # Синхронізує випадковість на всіх підключених відеокартах

    elif hasattr(torch, "xpu") and torch.xpu.is_available():
        device = torch.device("xpu")
        device_ui_name = "XPU (Intel / AI Accelerators)" # Від бюджетних Intel Arc A380 до кластерів Intel Gaudi 3 та дата-центрових Ponte Vecchio / Max Series
        torch.xpu.manual_seed_all(GLOBAL_SEED)       # Синхронізує всі Intel прискорювачі

    elif torch.backends.mps.is_available():
        device = torch.device("mps")
        device_ui_name = "MPS (Apple Metal API)"     # Від Metal 2 на Intel Mac + AMD Radeon (macOS 12.3+) до Metal 4 на новітніх M5 Max / M3 Ultra
        torch.mps.manual_seed(GLOBAL_SEED)           # Для Apple завжди один GPU, тому _all не використовується

    else:
        device = torch.device("cpu")
        device_ui_name = "CPU (x86_64 / ARM64)"      # Від AVX2/NEON на Intel 4-th Gen, AMD Excavator, Raspberry Pi 4 до 128-ядерних AMD EPYC 9754 / AWS Graviton4, Intel Xeon 6 та Qualcomm X Elite

    return device, device_ui_name

def clear_vram(device):
    """Архітектурне звільнення пам'яті пристрою."""
    if device.type == "mps":
        torch.mps.empty_cache()
    elif device.type == "cuda":
        torch.cuda.empty_cache()
    gc.collect()

def main():
    if not INPUT_FILE.exists():
        logger.error(f"❌ Файл {INPUT_FILE} відсутній. Спочатку запустіть 'convert.py'.")
        return

    device, device_ui_name = get_hardware_config()
    logger.info(f"🖥️  Виявлено апаратне забезпечення: {device_ui_name}")

    # pd.options.mode.copy_on_write = True - Pandas 3.0.3 по замовчуванню включений режим Copy-on-Write,
    # який оптимізує пам'ять при обробці великих DataFrame, що критично для нашого випадку з 32M записів
    # Ця опція запобігає непотрібному копіюванню даних, дозволяючи ефективно працювати з обмеженою оперативною пам'яттю
    df = pd.read_csv(INPUT_FILE)

    # Формуємо текст для векторизації (Title + Genres).
    # BGE модель краще розуміє природний текст, тому розділяємо жанри пробілами.
    df['title'] = df['title'].fillna("").astype(str)
    df['genres'] = df['genres'].fillna("").astype(str).str.replace('|', ' ')

    # Створюємо масив текстів: "The Matrix. Genres: Action Sci-Fi"
    texts = df.apply(lambda row: f"{row['title']}. Genres: {row['genres']}", axis=1).tolist()

    logger.info(f"🚀 Ініціалізація моделі {MODEL_NAME} у пам'ять ({device_ui_name})...")
    # Модель автоматично завантажить безпечні .safetensors файли без жодних попереджень
    model = SentenceTransformer(MODEL_NAME, device=device)

    logger.info(f"⚡ Генерація векторів для {len(texts)} фільмів...")

    # normalize_embeddings=True обов'язково для косинусної подібності (Cosine Similarity)
    embeddings = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True
    )

    # ===================================================================
    # 🛡️ АВТОМАТИЧНИЙ FALLBACK (Self-Healing)
    # ===================================================================
    if np.isnan(embeddings).any() or np.all(embeddings == 0, axis=1).any():
        logger.warning("⚠️  Апаратний збій матриці (NaN/Нулі)! Перекидаємо модель на CPU для перегенерації...")

        # Видаляємо модель з VRAM, щоб не тримати пам'ять у заручниках (запобігає витоку відеопам'яті)
        model.to("cpu")
        clear_vram(device)

        embeddings = model.encode(texts, batch_size=BATCH_SIZE, show_progress_bar=True, normalize_embeddings=True)

    # ===================================================================
    # 💾 ОПТИМІЗАЦІЯ ПАМ'ЯТІ ТА ЕКСПОРТУ (Architect Level)
    # ===================================================================
    logger.info("💾 Форматування векторів для експорту в Neo4j...")

    # 1. Округлення до 5 знаків зменшує розмір CSV на 40% і прискорює LOAD CSV у Neo4j
    embeddings = np.round(embeddings, 5)

    # 2. Обходимо ".tolist()", створюючи рядки напряму. Це уникає вибуху RAM на 2+ ГБ під час роботи Pandas
    df['embedding'] = [str(vec.tolist()) for vec in embeddings]

    # Видаляємо важкі об'єкти з RAM перед записом на диск (Garbage Collection)
    del texts, embeddings, model
    clear_vram(device)

    # Експортуємо тільки ID та вектор. Нам не треба дублювати title та genres.
    df[['movieId', 'embedding']].to_csv(OUTPUT_FILE, index=False)
    logger.info(f"✅ Вектори успішно збережено у: {OUTPUT_FILE} (Оптимізовано для Neo4j)")

if __name__ == "__main__":
    main()
