import psycopg2
from psycopg2.extras import execute_values
import numpy as np
import joblib
import torch
import gc

DB_PARAMS = {"dbname": "db", "user": "postgres", "password": "senha", "host": "localhost"}

def categorizar_base():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Hardware ativo: {device.upper()}")

    print("Carregando o modelo pré-treinado do disco (isso pode levar alguns segundos)...")
    # Carrega o modelo com toda a configuração matemática e de embeddings já travada
    topic_model = joblib.load('modelo_categorias_cpu_named.joblib')
    print("Modelo carregado com sucesso!")

    with psycopg2.connect(**DB_PARAMS) as conn:
        print("Iniciando etiquetagem em lote do banco completo (Server-side Cursor)...")
        
        with conn.cursor(name="fetch_cursor", withhold=True) as cur_fetch:
            # Puxa os documentos para classificar
            cur_fetch.execute("SELECT id, conteudo FROM documentos_raw WHERE status = 'SUCESSO' AND conteudo IS NOT NULL;")
            
            lote_atual = 1
            while True:
                lote_db = cur_fetch.fetchmany(1000)
                if not lote_db:
                    break
                    
                ids_lote = [row[0] for row in lote_db]
                textos_lote = [row[1] for row in lote_db]
                
                print(f"Lote {lote_atual} - Calculando distribuição múltipla para {len(textos_lote)} PDFs...")
                
                # window=8 e stride=4 controlam o tamanho das "fatias"
                distribuicoes, _ = topic_model.approximate_distribution(
                    textos_lote, 
                    window=50, 
                    stride=15
                )
                
                registros_etiquetas = []
                
                for doc_id, notas_topicos in zip(ids_lote, distribuicoes):
                    # Pega os IDs dos tópicos que atingiram 15% de confiança
                    topicos_aprovados = np.where(notas_topicos >= 0.05)[0]

                    for num_topico in topicos_aprovados:
                        # Ignora a lixeira matemática (Tópico -1) caso ele apareça
                        if num_topico == -1:
                            continue
                            
                        # Busca as informações desse tópico específico
                        info_topico = topic_model.get_topic_info(num_topico)
                        
                        # Extrai o nome gerado pelo Gemma (CustomName) 
                        if 'CustomName' in info_topico.columns:
                            nome_oficial = info_topico['CustomName'].values[0]
                        else:
                            # Fallback de segurança caso o tópico não tenha nome customizado
                            nome_oficial = info_topico['Name'].values[0]
                            
                        # Salva direto: ID do Doc, ID do Tópico, e o Nome Bonito
                        registros_etiquetas.append((doc_id, int(num_topico), nome_oficial))

                # categorização antiga que colocava cada nome individualmente
                # for doc_id, notas_topicos in zip(ids_lote, distribuicoes):
                #     topicos_aprovados = np.where(notas_topicos >= 0.15)[0]
                #     palavras_vistas = set()
                #
                #     for num_topico in topicos_aprovados:
                #         detalhes_topico = topic_model.get_topic(num_topico)
                #         if detalhes_topico:
                #             palavras_fortes = [palavra for palavra, peso in detalhes_topico if peso >= 0.01]
                #             for palavra in palavras_fortes:
                #                 if palavra not in palavras_vistas:
                #                     palavras_vistas.add(palavra)
                #                     registros_etiquetas.append((doc_id, int(num_topico), palavra))
                
                if registros_etiquetas:
                    with conn.cursor() as cur_insert:
                        execute_values(cur_insert, '''
                            INSERT INTO documento_etiqueta (documento_id, topico_id, nome_etiqueta)
                            VALUES %s
                        ''', registros_etiquetas)
                    conn.commit()

                # Limpeza severa de memória para proteger a RX 7600
                del lote_db, ids_lote, textos_lote, distribuicoes, registros_etiquetas
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                
                lote_atual += 1
                
        print("Etiquetagem finalizada com sucesso.")

if __name__ == "__main__":
    categorizar_base()
