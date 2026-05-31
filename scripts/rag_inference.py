import os
# ===============================================================================
# 🛡️ БРОНЯ ДЛЯ APPLE MPS ТА АПАРАТНОГО ПРИСКОРЕННЯ
# ===============================================================================
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

import sys
import argparse
import torch
from sentence_transformers import SentenceTransformer
import warnings
import time
from db_connector import Neo4jConnectionFactory

# Вимикаємо попередження від transformers
warnings.filterwarnings("ignore")

class GraphRAGClient:
    def __init__(self, env="local"):
        self.model_name = "BAAI/bge-base-en-v1.5"
        self.device = self._get_hardware_config()
        print(f"🧠 Ініціалізація AI-моделі {self.model_name} на пристрої: [{self.device.upper()}]...")
        self.model = SentenceTransformer(self.model_name, device=self.device)

        # Фабрика робить усю магію підключення
        self.driver = Neo4jConnectionFactory.get_driver(env=env)

    def _get_hardware_config(self):
        """Повертає найкращий доступний бекенд для інференсу."""
        if torch.cuda.is_available(): return "cuda"
        elif hasattr(torch, "xpu") and torch.xpu.is_available(): return "xpu"
        elif torch.backends.mps.is_available(): return "mps"
        else: return "cpu"

    def search(self, query, top_k=5):
        """Перетворює текст на вектор і виконує гібридний пошук у графі."""
        start_time = time.time()

        # 1. Векторизація (Швидка, бо працює на GPU/MPS)
        query_vector = self.model.encode(query, normalize_embeddings=True).tolist()

        # 2. Гібридний Cypher-запит (Справжнє гібридне ранжування + Захист від аномалій)
        cypher_query = """
        // Беремо більший запас векторів (50) для подальшої фільтрації
        CALL db.index.vector.queryNodes('movie_embeddings', 50, $vector)
        YIELD node AS movie, score AS semantic_score

        // Витягуємо жанри як масив (без форматування на рівні БД)
        OPTIONAL MATCH (movie)-[:HAS_GENRE]->(g:Genre)
        WITH movie, semantic_score, collect(g.name) AS genre_list

        // Використовуємо MATCH замість OPTIONAL, щоб брати лише оцінені фільми
        MATCH (movie)<-[r:RATED]-()
        WITH movie,
             semantic_score,
             genre_list,
             count(r) AS total_ratings,
             avg(r.rating) AS avg_rating

        // Захист від аномалій: відкидаємо фільми, які мають менше 10 оцінок
        WHERE total_ratings >= 10

        // Математика гібридного скорингу (60% Сенс + 40% Якість)
        WITH movie,
             semantic_score,
             genre_list,
             total_ratings,
             avg_rating,
             (semantic_score * 0.6) + ((avg_rating / 5.0) * 0.4) AS hybrid_score

        RETURN movie.title AS title,
               genre_list AS genres,
               round(semantic_score * 100) / 100.0 AS score,
               total_ratings,
               round(avg_rating * 10) / 10.0 AS avg_rating,
               round(hybrid_score * 100) / 100.0 AS final_score
        ORDER BY final_score DESC
        LIMIT $top_k
        """

        with self.driver.session() as session:
            result = session.run(cypher_query, vector=query_vector, top_k=top_k)
            records = list(result)

        exec_time = time.time() - start_time
        return records, exec_time

    def close(self):
        self.driver.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MovieLens GraphRAG CLI")
    parser.add_argument("--env", choices=["local", "cloud"], default="local")
    args = parser.parse_args()

    print("\n" + "="*111)
    print("🎬 MOVIELENS GRAPHRAG AI-ENGINE")
    print("="*111)

    client = GraphRAGClient(env=args.env)

    print("\n" + "-"*111)
    print("💡 Підказка: Введіть опис фільму, настрій або прихований сенс.")
    print("Приклади: 'dark sci-fi with hackers', 'feel good family movie', 'existential crisis in space'")
    print("Для виходу введіть 'exit'.")
    print("-"*111)

    try:
        while True:
            user_input = input("\n🔍 Ваш запит: ").strip()
            if user_input.lower() in ['exit', 'quit']:
                break
            if not user_input:
                continue

            results, exec_time = client.search(user_input)

            if not results:
                print("🤷 Фільмів не знайдено. Перевірте, чи побудовано векторний індекс у базі.")
            else:
                print(f"\n⚡ Знайдено за {exec_time:.3f} сек:")
                for i, r in enumerate(results, 1):
                    genres_str = ", ".join(r['genres']) if r['genres'] else "Unknown"

                    print(f"  {i}. {r['title']} ({genres_str})")
                    print(f"     [🏆 Гібридний бал: {r['final_score']:.3f} | Семантика: {r['score']:.3f} | Граф: ⭐ {r['avg_rating']:.1f} ({r['total_ratings']} оцінок)]")

    except KeyboardInterrupt:
        print("\n🛑 Зупинка сесії...")
    finally:
        client.close()
        print("👋 До побачення! База даних відключена.")
