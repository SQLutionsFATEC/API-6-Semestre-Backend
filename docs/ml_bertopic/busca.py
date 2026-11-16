import psycopg2
import spacy
import os

DB_PARAMS = {"dbname": "db", "user": "postgres", "password": "senha", "host": "localhost"}

def motor_busca():
    # Carrega o spaCy bem leve, só para lematizar a pesquisa do usuário
    print("Iniciando motor NLP de busca...")
    nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])

    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()

        print("\n" + "="*60)
        print("🔍 MOTOR DE BUSCA: MANUAIS TÉCNICOS EVERYSPEC")
        print("="*60)

        while True:
            termo = input("\nDigite os termos de busca (ou 'sair' para fechar): ").strip().lower()

            if termo in ['sair', 'exit', 'quit', 'q']:
                print("Encerrando motor de busca.")
                break
            if not termo:
                continue

            # Lematiza a busca (converte plurais e verbos para a raiz)
            doc = nlp(termo)
            palavras_busca = [token.lemma_ for token in doc if token.is_alpha]

            if not palavras_busca:
                print("Por favor, digite palavras válidas.")
                continue

            print(f"\nBuscando por termos relacionados a: {palavras_busca}...")

            # O Segredo: Prepara as palavras para busca parcial (LIKE) 
            # Ex: "gear" vira "%gear%" para encontrar "Landing Gear Assembly"
            # Também incluímos a frase exata do usuário como um termo bônus
            termos_sql = [f"%{word}%" for word in palavras_busca] + [f"%{termo}%"]

            # ILIKE garante que a busca ignora Maiúsculas/Minúsculas do banco
            query = """
                SELECT 
                    d.file_path,
                    COUNT(DISTINCT e.nome_etiqueta) as matches,
                    STRING_AGG(DISTINCT e.nome_etiqueta, ', ') as tags_encontradas
                FROM documentos_raw d
                JOIN documento_etiqueta e ON d.id = e.documento_id
                WHERE e.nome_etiqueta ILIKE ANY(%s)
                GROUP BY d.id, d.file_path
                ORDER BY matches DESC, d.id
                LIMIT 10;
            """

            cur.execute(query, (termos_sql,))
            resultados = cur.fetchall()

            if not resultados:
                print("Nenhum documento encontrado com essas etiquetas.")
            else:
                print(f"Encontrados {len(resultados)} resultados principais:\n")
                for i, (path, matches, tags) in enumerate(resultados, 1):
                    # Pega só o nome do arquivo no final do caminho
                    nome_arquivo = os.path.basename(path)
                    
                    print(f"{i}. 📄 {nome_arquivo}")
                    print(f"   Qtd de Tags Correspondentes: {matches} -> [{tags}]")
                    print(f"   Caminho: {path}\n")

    except Exception as e:
        print(f"Erro fatal: {e}")
    finally:
        if 'conn' in locals() and conn:
            cur.close()
            conn.close()

if __name__ == "__main__":
    motor_busca()
