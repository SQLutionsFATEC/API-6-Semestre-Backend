import psycopg2
import numpy as np
import random
import joblib
import torch
import gc

from bertopic import BERTopic
from umap import UMAP
from hdbscan import HDBSCAN
from sentence_transformers import SentenceTransformer
from sklearn.feature_extraction.text import CountVectorizer
from bertopic.representation import KeyBERTInspired

SEMENTE = 42
random.seed(SEMENTE)
np.random.seed(SEMENTE)
torch.manual_seed(SEMENTE)
torch.cuda.manual_seed_all(SEMENTE)
torch.backends.cudnn.deterministic = True
torch.backends.cudnn.benchmark = False

DB_PARAMS = {"dbname": "db", "user": "postgres", "password": "senha", "host": "localhost"}

def treinar():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Hardware: {device.upper()}")

    print("Carregando modelo de embeddings (Inglês)...")
    embedding_model = SentenceTransformer("all-MiniLM-L6-v2", device=device)

    # O texto já vem 100% limpo da extração, então o vetorizador só precisa 
    # focar em separar as palavras (mantendo a regra de segurança de 3 letras)
    vectorizer_model = CountVectorizer(
        token_pattern=r'(?u)\b[A-Za-z]{3,}\b',
        # max_features=10000
    )

    # Mantemos apenas o KeyBERT para destacar as palavras mais relevantes usando a GPU
    representacao = KeyBERTInspired()

    umap_model = UMAP(random_state=42, low_memory=True)

    hdbscan_model = HDBSCAN(
            min_cluster_size=15,
            metric='euclidean',
            cluster_selection_method='eom',
            prediction_data=True,
            cluster_selection_epsilon=0.1
            )
    
    topic_model = BERTopic(
        embedding_model=embedding_model, 
        language="english", 
        calculate_probabilities=False,
        vectorizer_model=vectorizer_model,
        umap_model=umap_model,
        hdbscan_model=hdbscan_model,
        representation_model=representacao,
        # Parâmetros de tuning ativados para evitar micro-tópicos
        # min_topic_size=75,
        # nr_topics="auto",
        # low_memory=True
    )    

    with psycopg2.connect(**DB_PARAMS) as conn:
        print("Buscando amostra de 75% para treinamento...")
        with conn.cursor() as cur:
            cur.execute("""
                SELECT conteudo FROM documentos_raw 
                WHERE status = 'SUCESSO' AND conteudo IS NOT NULL AND conteudo != '' 
                ORDER BY md5(file_path) 
                LIMIT (SELECT GREATEST(count(*)*0.75, 10) FROM documentos_raw);
            """)
            amostra = cur.fetchall()
            
        print("Preparando dados na memória...")
        textos_treino = [row[0] for row in amostra]
        del amostra
        gc.collect()
        
        print(f"Treinando BERTopic com {len(textos_treino)} documentos já pré-processados...")
        topic_model.fit(textos_treino)
        
        print("Salvando o modelo de GPU...")
        joblib.dump(topic_model, 'modelo_categorias_gpu.joblib')

        print("Salvando o modelo de CPU...")
        embedding_model.to('cpu')
        joblib.dump(topic_model, 'modelo_categorias_cpu.joblib')
        
        print("Gerando visualizações interativas em HTML...")
        fig_mapa = topic_model.visualize_topics()
        fig_mapa.write_html("mapa_topicos.html")
        
        fig_barras = topic_model.visualize_barchart() # top_n_topics=30, n_words=5)
        fig_barras.write_html("barras_topicos.html")
        
        print("Treinamento concluído. Gráficos salvos!")

if __name__ == "__main__":
    treinar()
