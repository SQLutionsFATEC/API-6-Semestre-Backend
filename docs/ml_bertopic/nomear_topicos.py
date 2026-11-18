import joblib
import json
import requests
import re

# O llama.cpp levanta um servidor compatível com a API da OpenAI na porta 8080
LLAMA_CPP_URL = "http://127.0.0.1:8080/v1/chat/completions"

def limpar_json(texto):
    """Remove blocos de markdown ```json ``` que a LLM pode adicionar."""
    texto = texto.strip()
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', texto, re.DOTALL)
    if match:
        return match.group(1)
    return texto

def nomear_topicos_llama():
    print("1. Carregando o modelo BERTopic...")
    topic_model = joblib.load('modelo_categorias_gpu.joblib')
    cpu_model = joblib.load('modelo_categorias_cpu.joblib')
    info_topicos = topic_model.get_topic_info()
    
    # Extrai apenas os tópicos válidos (ignorando o -1)
    topicos_validos = []
    for _, linha in info_topicos.iterrows():
        id_topico = linha['Topic']
        if id_topico == -1: continue
        
        # Pega as 7 palavras mais fortes para a IA ter contexto
        palavras = [p for p, _ in topic_model.get_topic(id_topico)[:7]]
        topicos_validos.append((id_topico, ", ".join(palavras)))

    novos_nomes = {-1: "Outliers"}
    tamanho_lote = 40  # Lote seguro para a LLM não "esquecer" itens nem quebrar o JSON
    
    print(f"\n2. Iniciando nomeação em lotes de {tamanho_lote} via Gemma (llama.cpp)...\n")

    for i in range(0, len(topicos_validos), tamanho_lote):
        lote = topicos_validos[i : i + tamanho_lote]
        
        # Monta a lista que a LLM vai ler
        texto_lote = "\n".join([f'"{tid}": Keywords: {kw}' for tid, kw in lote])
        
        prompt = f"""You are a military engineering taxonomy expert. 
Provide a highly specific, unique category name (1 to 3 words) for each item below based on its keywords.
Do NOT repeat names.

Input data:
{texto_lote}

Output ONLY a valid JSON dictionary where keys are the IDs (as strings) and values are the generated names. No conversational text."""

        payload = {
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2, # Temperatura baixa para nomes consistentes e JSON perfeito
            "max_tokens": 8000
        }

        print(f"Enviando lote {i//tamanho_lote + 1}... ", end="", flush=True)
        
        try:
            resposta = requests.post(LLAMA_CPP_URL, json=payload)
            resposta.raise_for_status()
            
            conteudo_llm = resposta.json()['choices'][0]['message']['content']
            json_limpo = limpar_json(conteudo_llm)
            
            dicionario_nomes = json.loads(json_limpo)
            
            for str_id, nome in dicionario_nomes.items():
                novos_nomes[int(str_id)] = nome.title()
                
            print("Sucesso!")
            
        except Exception as e:
            print(f"\nErro no lote {i//tamanho_lote + 1}. A LLM quebrou a estrutura: {e}")
            print("Resposta bruta da LLM:")
            print(conteudo_llm if 'conteudo_llm' in locals() else resposta.text)
            return # Interrompe para você arrumar se der erro grave

    print("\n3. Injetando os nomes no BERTopic e salvando...")
    topic_model.set_topic_labels(novos_nomes)
    cpu_model.set_topic_labels(novos_nomes)
    joblib.dump(topic_model, 'modelo_categorias_gpu_named.joblib')
    joblib.dump(cpu_model, 'modelo_categorias_cpu_named.joblib')
    
    print("\nExemplo dos novos nomes:")
    for k in list(novos_nomes.keys())[1:10]:
        print(f"Tópico {k:03d} -> {novos_nomes[k]}")

if __name__ == "__main__":
    nomear_topicos_llama()
