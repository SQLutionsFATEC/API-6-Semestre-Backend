import joblib
import pandas as pd

def gerar_relatorios():
    print("1. Carregando o modelo atualizado...")
    topic_model = joblib.load('modelo_categorias_gpu_named.joblib')

    # Exibe um resumo tabular direto no terminal para checagem rápida
    info_topicos = topic_model.get_topic_info()
    
    print("\n" + "="*60)
    print("📊 TOP 15 MAIORES CATEGORIAS DO BANCO")
    print("="*60)
    
    # O BERTopic salva os nomes gerados pela LLM na coluna 'CustomName'
    for _, linha in info_topicos.head(16).iterrows():
        if linha['Topic'] == -1:
            continue
        print(f"Tópico {linha['Topic']:03d} | PDFs: {linha['Count']:<5} | Nome: 🟢 {linha['CustomName']}")

    print("\n2. Gerando Painéis Interativos (HTML)...")
    
    # O pulo do gato: custom_labels=True força os gráficos a usarem os nomes do Gemma
    
    # Mapa de Distância Intertópica (Mostra se os assuntos estão se sobrepondo)
    fig_mapa = topic_model.visualize_topics(custom_labels=True)
    fig_mapa.write_html("relatorio_mapa.html")
    print(" ✔️ relatorio_mapa.html gerado.")

    # Gráfico de Barras (Mostra o nome do Tópico vs. as Palavras que o compõem)
    fig_barras = topic_model.visualize_barchart(top_n_topics=32, n_words=6, custom_labels=True)
    fig_barras.write_html("relatorio_barras.html")
    print(" ✔️ relatorio_barras.html gerado.")
    
    # Hierarquia (Mostra como tópicos específicos se agrupam em "Super Categorias")
    fig_hierarquia = topic_model.visualize_hierarchy(top_n_topics=50, custom_labels=True)
    fig_hierarquia.write_html("relatorio_hierarquia.html")
    print(" ✔️ relatorio_hierarquia.html gerado.")

    print("\nAnálise concluída! Abra os arquivos HTML no seu navegador.")

if __name__ == "__main__":
    gerar_relatorios()
