import psycopg2
import pandas as pd

DB_PARAMS = {
    "dbname": "db", 
    "user": "postgres", 
    "password": "senha", 
    "host": "localhost"
}

def exportar_relatorio_agrupado(nome_arquivo="relatorio_etiquetas_agrupado.csv"):
    print("Conectando ao banco de dados...")
    
    with psycopg2.connect(**DB_PARAMS) as conn:
        # A query agrupa por etiqueta, conta os PDFs e concatena os caminhos separados por ' | '
        query = """
            SELECT 
                e.nome_etiqueta AS etiqueta,
                COUNT(d.id) AS quantidade_pdfs,
                STRING_AGG(d.file_path, ' | ') AS lista_arquivos
            FROM 
                documento_etiqueta e
            JOIN 
                documentos_raw d ON e.documento_id = d.id
            GROUP BY 
                e.nome_etiqueta
            ORDER BY 
                quantidade_pdfs DESC;
        """
        
        print("Agrupando dados e gerando o relatório...")
        df = pd.read_sql_query(query, conn)
        
        print(f"Foram encontrados {len(df)} tópicos (etiquetas) distintos.")
        
        # Salva o DataFrame no formato CSV
        df.to_csv(nome_arquivo, index=False, encoding='utf-8')
        
    print(f"Exportação concluída! Arquivo salvo como: {nome_arquivo}")

if __name__ == "__main__":
    exportar_relatorio_agrupado()
