import os
import sys
import time
import streamlit as st
import pandas as pd
import torch
import streamlit.components.v1 as components
import plotly.express as px
from sentence_transformers import SentenceTransformer
from neo4j import GraphDatabase
from dotenv import load_dotenv
from pyvis.network import Network

# Броня для апаратного прискорення Apple Silicon / Intel Mac
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"

# Завантажуємо конфігураційне оточення
load_dotenv()

# pd.options.mode.copy_on_write = True - Pandas 3.0.3 по замовчуванню включений режим Copy-on-Write,
# який оптимізує пам'ять при обробці великих DataFrame, що критично для нашого випадку з 32M записів
# Ця опція запобігає непотрібному копіюванню даних, дозволяючи ефективно працювати з обмеженою оперативною пам'яттю

# ===============================================================================
# 🧠 1. РЕСУРСНЕ КЕШУВАННЯ (Драйвер БД та AI-Модель)
# ===============================================================================
@st.cache_resource
def get_neo4j_driver(env_type):
    """Створює та кешує безпечний пул з'єднань з ексклюзивними таймаутами."""
    if env_type == "Хмара (AuraDB)":
        uri = os.getenv("NEO4J_CLOUD_URI")
        user = os.getenv("NEO4J_CLOUD_USER")
        pwd = os.getenv("NEO4J_CLOUD_PASS")
    else:
        uri = os.getenv("NEO4J_LOCAL_URI", "neo4j://127.0.0.1:7687")
        user = os.getenv("NEO4J_LOCAL_USER", "neo4j")
        pwd = os.getenv("NEO4J_LOCAL_PASS", "secret12345")

    # FAANG-стандарт ініціалізації БД
    driver = GraphDatabase.driver(
        uri,
        auth=(user, pwd),
        connection_timeout=30.0,
        max_connection_lifetime=3600
    )

    # Повертаємо об'єкт напряму, уникаючи багів Streamlit з генераторами
    # Neo4j Driver є thread-safe і сам керує пулом з'єднань, ручний close() тут не критичний
    return driver

@st.cache_resource
def load_embedding_model():
    """Автоматично детектує залізо хоста та завантажує Safetensors модель у пам'ять."""
    model_name = "BAAI/bge-base-en-v1.5"

    if torch.cuda.is_available(): device = "cuda"
    elif hasattr(torch, "xpu") and torch.xpu.is_available(): device = "xpu"
    elif torch.backends.mps.is_available(): device = "mps"
    else: device = "cpu"

    model = SentenceTransformer(model_name, device=device)
    return model, device

# ===============================================================================
# ⚙️ 2. СИСТЕМНЕ НАЛАШТУВАННЯ ІНТЕРФЕЙСУ
# ===============================================================================
st.set_page_config(page_title="MovieLens Advanced Graph Explorer", layout="wide", page_icon="🕸️")

DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))

# Сайдбар: Керування інфраструктурою бази даних
st.sidebar.title("⚙️ Інфраструктура та Мережа")
env_choice = st.sidebar.radio("Активне середовище:", ["Локально (Docker)", "Хмара (AuraDB)"])

try:
    driver = get_neo4j_driver(env_choice)
    driver.verify_connectivity()
    st.sidebar.success(f"✅ З'єднано з Neo4j ({env_choice.split()[0]})")
except Exception as db_err:
    st.sidebar.error("❌ Збій підключення! Перевірте конфігурацію `.env` або статус контейнера.")
    st.sidebar.code(str(db_err))
    st.stop()

# Сайдбар: Ініціалізація та статус штучного інтелекту
try:
    ai_model, target_device = load_embedding_model()
    st.sidebar.success(f"🧠 AI-Двигун: {target_device.upper()} Активний")
except Exception as ai_err:
    st.sidebar.warning(f"⚠️ Помилка GPU інференсу, активовано CPU-фолбек: {ai_err}")
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    ai_model = SentenceTransformer("BAAI/bge-base-en-v1.5", device="cpu")
    st.sidebar.info("🧠 AI-Двигун: СРU Режим")

st.title("🎬 Кіновсесвіт: Платформа Інтелектуальної Графової Аналітики")
st.caption("Платформа Enterprise-рівня: об'єднання Collaborative Filtering, Graph Data Science та Векторного Пошуку (GraphRAG)")

# Організація модульної архітектури через вкладки
tab_rag, tab_cf, tab_nodes = st.tabs([
    "🔍 Гібридний Пошук (GraphRAG Engine)",
    "🎯 Колаборативна Фільтрація (OLTP CF)",
    "🕸️ Топологічний Аудит (Супервузли)"
])

# ===============================================================================
# 🔍 ВКЛАДКА 1: GRAPHRAG ENGINE (КРУТІННЯ ВЕКТОРІВ ТА ГРАФА)
# ===============================================================================
with tab_rag:
    st.subheader("🎛️ Налаштування Гібридного Ранжування (Semantic vs Topological)")
    st.write("Тут ви можете безпосередньо керувати архітектурними вагами математичного пошуку:")

    # Слайдери для динамічного балансування двох різних сутностей
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        v_weight = st.slider("Вага Векторного Простору (Семантика запиту/Сенс сюжету):", 0.0, 1.0, 0.6, 0.05)
    with col_s2:
        g_weight = st.slider("Вага Графового Простору (Популярність/Середній рейтинг бази):", 0.0, 1.0, 0.4, 0.05)

    # Автоматичний нормалізатор ваг (Захист від некоректного вводу)
    sum_w = v_weight + g_weight
    w_vec = v_weight / sum_w if sum_w > 0 else 0.5
    w_graph = g_weight / sum_w if sum_w > 0 else 0.5

    st.divider()

    col_input, col_view = st.columns([1, 2])

    with col_input:
        search_query = st.text_input(
            "Введіть сенсовий опис для нейромережі:",
            "dark cyberpunk with philosophical overtones or hackers"
        )
        top_k_select = st.slider("Кількість результатів (Top-K):", 3, 15, 5)
        run_rag_btn = st.button("Запустити Гібридний Пошук", type="primary")

    if run_rag_btn and search_query:
        with st.spinner("⚡ AI-інференс: векторизація запиту та обхід HNSW індексу..."):
            # 1. Векторизуємо локально з апаратним прискоренням
            raw_embedding = ai_model.encode(search_query, normalize_embeddings=True).tolist()

            # 2. Виконуємо чистий Push-Down запит у Neo4j. Математика зважування рахується в СУБД
            rag_cypher = """
            CALL db.index.vector.queryNodes('movie_embeddings', $limit_candidate, $vector)
            YIELD node AS movie, score AS semantic_score

            // Витягуємо жанри через зв'язок
            OPTIONAL MATCH (movie)-[:HAS_GENRE]->(g:Genre)
            WITH movie, semantic_score, collect(g.name) AS genre_list

            // Беремо тільки оцінені фільми
            MATCH (movie)<-[r:RATED]-()
            WITH movie, semantic_score, genre_list, count(r) AS total_ratings, avg(r.rating) AS avg_rating
            WHERE total_ratings >= 10  // Жорсткий фільтр аномалій

            WITH movie, semantic_score, genre_list, total_ratings, avg_rating,
                 (semantic_score * $w_vec) + ((avg_rating / 5.0) * $w_graph) AS hybrid_score

            RETURN movie.title AS title,
                   genre_list AS genres,
                   round(semantic_score * 100) / 100.0 AS v_score,
                   total_ratings AS ratings_cnt,
                   round(avg_rating * 10) / 10.0 AS graph_rtg,
                   round(hybrid_score * 100) / 100.0 as final_score
            ORDER BY final_score DESC
            LIMIT $top_k
            """

            try:
                with driver.session() as session:
                    records = session.run(
                        rag_cypher,
                        vector=raw_embedding,
                        limit_candidate=int(top_k_select * 2),
                        w_vec=float(w_vec),
                        w_graph=float(w_graph),
                        top_k=int(top_k_select)
                    )

                    rag_data = [{
                        "Назва фільму": r["title"],
                        # Красиво форматуємо жанри для таблиці: "Action, Sci-Fi"
                        "Жанри": ", ".join(r["genres"]) if r["genres"] else "Unknown",
                        "Векторний скор (Сенс)": r["v_score"],
                        "Рейтинг графа (⭐)": r["graph_rtg"],
                        "Кількість оцінок": r["ratings_cnt"],
                        "🔥 Гібридний Бал": r["final_score"],
                        "_raw_genres": r["genres"] # Схований масив жанрів для відмальовки графа
                    } for r in records]

            except Exception as e:
                st.error("❌ Помилка бази даних. Переконайтеся, що ви запустили створення векторних індексів (`part6_graphrag.cypher`).")
                rag_data = []

        with col_view:
            if rag_data:
                # Видаляємо схований стовпець _raw_genres перед виводом таблиці
                df_display = pd.DataFrame(rag_data).drop(columns=["_raw_genres"])
                st.dataframe(df_display, hide_index=True, use_container_width=True)
                st.info(f"💡 **Аналітичний звіт:** Ваги розподілені як {w_vec:.1f}:{w_graph:.1f}. "
                        f"Система відібрала семантично близькі фільми, але переранжувала їх "
                        f"на основі реальних оцінок користувачів графа.")

                # --- КОМБІНОВАНА ВІЗУАЛІЗАЦІЯ (GRAPHRAG) ---
                st.markdown("### 🕸️ Інтерактивна топологія: Вектори + Граф")
                with st.spinner("Відмальовка 3D-графа..."):
                    net = Network(height="500px", width="100%", bgcolor="#0e1117", font_color="white", cdn_resources='remote')
                    net.barnes_hut(gravity=-5000, central_gravity=0.3, spring_length=150)

                    # 1. ЦЕНТР ВЕКТОРНОГО ПРОСТОРУ (Запит користувача)
                    query_node_id = "QUERY_NODE"
                    net.add_node(query_node_id, label=f"🔍 Запит:\n{search_query[:15]}...", color="#e74c3c", size=30)

                    for r in rag_data:
                        movie_title = r["Назва фільму"]
                        v_score = r["Векторний скор (Сенс)"]

                        # 2. ФІЛЬМИ
                        net.add_node(movie_title, label=f"🎬 {movie_title[:20]}", color="#3498db", size=20)

                        # 3. ВЕКТОРНИЙ ЗВ'ЯЗОК (Пунктир: Семантика)
                        net.add_edge(query_node_id, movie_title,
                                     label=f"Сенс: {v_score}",
                                     color="#e74c3c",
                                     dashes=True,
                                     width=v_score * 3)

                        # 4. ГРАФОВА ТОПОЛОГІЯ (Жанри з БД)
                        # НІЯКОГО .split()! ми просто беремо готовий масив
                        genres = r["_raw_genres"] if r["_raw_genres"] else []
                        for g in genres[:3]: # Беремо макс 3 жанри
                            genre_id = f"GENRE_{g}"
                            net.add_node(genre_id, label=f"🎭 {g}", color="#2ecc71", size=15)
                            net.add_edge(movie_title, genre_id, color="#2ecc71")

                    try:
                        rag_html_path = os.path.join(DASHBOARD_DIR, 'graphrag_vis.html')

                        net.save_graph(rag_html_path)

                        with open(rag_html_path, 'r', encoding='utf-8') as HtmlFile:
                            components.html(HtmlFile.read(), height=510)
                    except Exception as e:
                        st.error(f"Помилка візуалізації: {e}")
            else:
                st.warning("Фільмів не знайдено або індекс відсутній.")

# ===============================================================================
# 🎯 ВКЛАДКА 2: COLLABORATIVE FILTERING & GHOST NODES DEGRADATION
# ===============================================================================
with tab_cf:
    st.subheader("🎯 Спільні смаки (User-Based Collaborative Filtering)")
    col_cf_in, col_cf_out = st.columns([1, 2])

    with col_cf_in:
        user_id_input = st.text_input("Введіть глобальний ID користувача:", "42")
        run_cf_btn = st.button("Згенерувати персональний топ")

    if run_cf_btn:
        try:
            target_uid = int(user_id_input)

            # Правильна агрегація скорингу + витягування жанрів через граф
            cf_cypher = """
            MATCH (target:User {userId: $uid})-[r1:RATED]->(m:Movie)<-[r2:RATED]-(similar:User)
            WHERE r1.rating >= 4.0 AND r2.rating >= 4.0
            WITH target, similar, count(m) AS simScore
            ORDER BY simScore DESC LIMIT 20

            MATCH (similar)-[r3:RATED]->(rec:Movie)
            WHERE r3.rating >= 4.0 AND NOT (target)-[:RATED]->(rec)

            // Спочатку агрегуємо математику
            WITH target, rec, sum(simScore) AS Score, count(similar) AS Users

            // А тепер дістаємо жанри за новою топологією
            OPTIONAL MATCH (rec)-[:HAS_GENRE]->(g:Genre)
            WITH target, rec, Score, Users, collect(g.name) AS genre_list

            RETURN rec.title AS Movie,
                   genre_list AS Genres,
                   Score,
                   Users,
                   coalesce(target.gender, "Приховано (GDPR)") AS user_gender,
                   coalesce(target.age, 0) AS user_age
            ORDER BY Score DESC LIMIT 5
            """

            with st.spinner("⚙️ Сканування суміжних шляхів та підрахунок ваг..."):
                with driver.session() as session:
                    cf_records = session.run(cf_cypher, uid=target_uid)
                    cf_data = []
                    gender_meta, age_meta = "Невідомо", 0

                    for r in cf_records:
                        gender_meta = r["user_gender"]
                        age_meta = r["user_age"]

                        # Форматуємо масив жанрів у Python для красивого виводу
                        genres_str = ", ".join(r["Genres"]) if r["Genres"] else "Unknown"

                        cf_data.append({
                            "Рекомендований фільм": r["Movie"],
                            "Категорія/Жанри": genres_str,
                            "Сила рекомендації (Скор)": r["Score"],
                            "Кількість однодумців": r["Users"]
                        })

            with col_cf_out:
                if cf_data:
                    st.markdown(f"**👤 Профіль клієнта:** Стать: `{gender_meta}` | Вік: `{age_meta if age_meta > 0 else 'Не вказано (Ghost Node)'}`")
                    st.dataframe(pd.DataFrame(cf_data), hide_index=True, use_container_width=True)

                    # --- ВІЗУАЛІЗАЦІЯ COLLABORATIVE FILTERING ---
                    st.markdown("### 🕸️ Топологія рекомендацій")
                    with st.spinner("Генерація візуального графа..."):
                        net_cf = Network(height="400px", width="100%", bgcolor="#222222", font_color="white", cdn_resources='remote')
                        net_cf.barnes_hut(gravity=-8000, central_gravity=0.3, spring_length=150)

                        # Додаємо цільового користувача (Центр)
                        net_cf.add_node(f"User {target_uid}", label=f"🧑 Юзер {target_uid}", color="#e74c3c", size=25)

                        for r in cf_data:
                            movie_title = r["Рекомендований фільм"]
                            net_cf.add_node(movie_title, label=f"🎬 {movie_title[:15]}...", color="#3498db", size=20)
                            net_cf.add_edge(f"User {target_uid}", movie_title, value=r["Сила рекомендації (Скор)"], title=f"Скор: {r['Сила рекомендації (Скор)']}")

                        try:
                            cf_html_path = os.path.join(DASHBOARD_DIR, 'pyvis_graph_cf.html')

                            net_cf.save_graph(cf_html_path)

                            with open(cf_html_path, 'r', encoding='utf-8') as HtmlFile:
                                components.html(HtmlFile.read(), height=410)
                        except Exception as e:
                            st.warning("Не вдалося відмалювати граф локально.")
                else:
                    st.warning("⚠️ Користувач є 'холодним' (немає оцінок ≥ 4.0) або відсутній у базі.")

        except ValueError:
            st.error("❌ ID користувача повинно бути цілим числом.")

# ===============================================================================
# 🕸️ ВКЛАДКА 3: ТОПОЛОГІЧНИЙ АУДИТ ТА СУПЕРВУЗЛИ ($O(1)$ DEGREE COUNT)
# ===============================================================================
with tab_nodes:
    st.subheader("🕸️ Моніторинг щільності графа та виявлення Супервузлів")
    st.write("Автоматичний аудит Dense Nodes за допомогою прямого зчитування метаданих з Degree Store:")

    if st.button("Запустити глобальний скан топології", type="secondary"):
        # Ми знаходимо топ-5 супервузлів ДЛЯ КОЖНОГО ТИПУ (User, Movie, Genre)
        nodes_cypher = """
        MATCH (n)
        WITH labels(n)[0] AS label, n
        // Підраховуємо ступінь (degree) за O(1)
        WITH label, n, COUNT { (n)--() } AS degree
        ORDER BY degree DESC
        // Групуємо по лейблу і беремо топ-5 для кожного
        WITH label, collect({
            identifier: coalesce(n.name, n.title, "User_" + toString(n.userId)),
            degree: degree
        })[0..4] AS top_nodes
        UNWIND top_nodes AS t
        RETURN label, t.identifier AS identifier, t.degree AS degree
        ORDER BY label, degree DESC
        """

        with st.spinner("🔍 Зчитування системних дескрипторів Neo4j..."):
            with driver.session() as session:
                node_records = session.run(nodes_cypher)
                df_topology = pd.DataFrame([{
                    "Тип вузла": r["label"],
                    "Ідентифікатор сутності": r["identifier"],
                    "Ступінь (Кількість ребер)": r["degree"]
                } for r in node_records])

        if not df_topology.empty:
            col_graph_a, col_graph_b = st.columns(2)
            with col_graph_a:
                st.dataframe(df_topology, hide_index=True, use_container_width=True)
            with col_graph_b:
                fig = px.bar(
                    df_topology,
                    x="Ідентифікатор сутності",
                    y="Ступінь (Кількість ребер)",
                    color="Тип вузла",
                    title="Розподіл Супервузлів за Типом",
                    template="plotly_dark"
                )
                st.plotly_chart(fig, use_container_width=True)

            st.warning("🚨 **Tech Lead Alert:** Вузли з графіку вище є критичними точками відмови продуктивності. "
                       "Будь-який неізольований обхід типу `-[*]-` через ці сутності призведе до "
                       "**комбінаторного вибуху пам'яті** Heap Java-машини. Використовуйте жорсткий Pruning!")
        else:
            st.info("База даних порожня. Виконайте імпорт.")
