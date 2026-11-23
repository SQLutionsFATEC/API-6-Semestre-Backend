import joblib
import pandas as pd
import torch

# --- O TRUQUE PARA SSH SEM GPU ---
# Salvamos a função original do PyTorch
original_torch_load = torch.load

# Criamos uma função interceptadora que sempre injeta map_location='cpu'
def safe_cpu_load(*args, **kwargs):
    kwargs['map_location'] = 'cpu'
    return original_torch_load(*args, **kwargs)

# Substituímos a função original pela nossa versão segura
torch.load = safe_cpu_load
# ---------------------------------

def gerar_relatorios():
    print("1. Carregando o modelo (Forçando tensores para a CPU)...")
    topic_model = joblib.load('modelo_categorias_named.joblib')
    
    # Restaura o comportamento normal do PyTorch
    torch.load = original_torch_load

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
    
    fig_mapa = topic_model.visualize_topics(custom_labels=True)
    fig_mapa.write_html("relatorio_mapa.html")
    print(" ✔️ relatorio_mapa.html gerado.")

    fig_barras = topic_model.visualize_barchart(top_n_topics=32, n_words=6, custom_labels=True)
    fig_barras.write_html("relatorio_barras.html")
    print(" ✔️ relatorio_barras.html gerado.")
    
    fig_hierarquia = topic_model.visualize_hierarchy(top_n_topics=50, custom_labels=True)
    fig_hierarquia.write_html("relatorio_hierarquia.html")
    print(" ✔️ relatorio_hierarquia.html gerado.")

    print("\nAnálise concluída! Abra os arquivos HTML no seu navegador.")

if __name__ == "__main__":
    gerar_relatorios()
