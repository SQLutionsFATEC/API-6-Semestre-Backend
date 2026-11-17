import sys
import os
os.environ["OMP_THREAD_LIMIT"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

from concurrent.futures import ThreadPoolExecutor, as_completed
import fitz  # PyMuPDF
import re
import time
import spacy
import joblib
import torch
import numpy as np
import threading
from rapidocr_onnxruntime import RapidOCR

thread_local = threading.local()
OCR_MAX_WORKERS = 4
OCR_DPI = 95
FORCE_OCR = False
RAPIDOCR_USE_CLS = False
RAPIDOCR_INTRA_THREADS = 1
RAPIDOCR_INTER_THREADS = 1
# 1. Configuração do spaCy e Lista de Lixo
print("Carregando motor NLP (spaCy)...")
nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])
PALAVRAS_LIXO = {
    "everyspec", "downloaded", "www", "com", "https", "http", "from",
    "shall", "verify", "version", "did", "associated", "use", "current",
    "check", "applicable", "dated", "yes", "information", "operations"
}

def limpar_texto(texto):
    print("Limpando texto..")
    t = time.time()
    """Limpa ruídos e extrai substantivos com fatiamento para proteger a RAM."""
    texto = texto.lower().replace('\x00', '').replace('\0', '').replace("\n", " ").replace("\t", " ")
    texto = re.sub(r"https?://\S+|www\.\S+", " ", texto)
    texto = re.sub(r"\S+@\S+", " ", texto)
    texto = re.sub(r"\bdownloaded\s+from\b", " ", texto)
    texto = re.sub(r"\b(?:https?|www|com|everyspec)\b", " ", texto)
    texto = re.sub(r"[^a-z0-9\s-]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()

    if not texto: return ""

    substantivos = []
    TAMANHO_CHUNK = 500000

    for i in range(0, len(texto), TAMANHO_CHUNK):
        chunk = texto[i : i + TAMANHO_CHUNK]
        doc = nlp(chunk)
        for token in doc:
            if token.pos_ == "NOUN" and len(token.text) >= 3 and token.is_alpha and token.lemma_ not in PALAVRAS_LIXO:
                substantivos.append(token.lemma_)
        del doc, chunk

    print("Texto limpo em", round(time.time()-t, 2), "segundos")
    return " ".join(substantivos)

def get_rapidocr():
    """Keeps one RapidOCR engine per worker thread."""
    if not hasattr(thread_local, "ocr"):
        inicio = time.perf_counter()
        thread_local.ocr = RapidOCR(
            use_cls=RAPIDOCR_USE_CLS,
            intra_op_num_threads=RAPIDOCR_INTRA_THREADS,
            inter_op_num_threads=RAPIDOCR_INTER_THREADS,
        )
        print(
            f"[OCR][thread={threading.get_ident()}] "
            f"modelo inicializado em {time.perf_counter() - inicio:.2f}s",
            flush=True,
        )
    return thread_local.ocr

def ocr_single_image_optimized(img_index, image_data):
    inicio = time.perf_counter()
    print(f"[OCR][pagina={img_index + 1}] iniciando", flush=True)
    width, height, stride, samples = image_data
    image = np.frombuffer(samples, dtype=np.uint8).reshape((height, stride))
    image = image[:, :width]
    result, _ = get_rapidocr()(image)
    text = ""
    if result:
        text = "\n".join(item[1] for item in result if len(item) > 1)
    print(
        f"[OCR][pagina={img_index + 1}] terminou em "
        f"{time.perf_counter() - inicio:.2f}s ({len(result or [])} blocos)",
        flush=True,
    )
    return img_index, text.strip()

def extrair_texto(file_path):
    """Extrai texto do PDF e aplica OCR se necessário."""
    print("Extraindo texto...", flush=True)
    t = time.time()
    try:
        doc = fitz.open(file_path)
        texto_paginas = []
        imagens_ocr = {}
        for pagina in doc:
            texto = pagina.get_text("text").strip()
            texto_paginas.append(texto)

            if FORCE_OCR or len(texto) < 20:
                pix = pagina.get_pixmap(dpi=OCR_DPI, colorspace=fitz.csGRAY)
                imagens_ocr[len(texto_paginas) - 1] = (
                    pix.width,
                    pix.height,
                    pix.stride,
                    bytes(pix.samples),
                )
        doc.close()

        if imagens_ocr:
            max_workers = min(OCR_MAX_WORKERS, os.cpu_count() or 1, len(imagens_ocr))
            batch_size = max_workers * 2
            print(
                f"Executando OCR em paralelo com RapidOCR "
                f"({max_workers} threads; ONNX intra={RAPIDOCR_INTRA_THREADS}, "
                f"inter={RAPIDOCR_INTER_THREADS})...",
                flush=True,
            )

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                indices = list(imagens_ocr)
                for inicio in range(0, len(indices), batch_size):
                    inicio_lote = time.perf_counter()
                    primeiro = inicio + 1
                    ultimo = min(inicio + batch_size, len(indices))
                    print(
                        f"[OCR][lote={primeiro}-{ultimo}/{len(indices)}] "
                        "submetendo páginas",
                        flush=True,
                    )
                    tarefas = [
                        executor.submit(
                            ocr_single_image_optimized,
                            indice,
                            imagens_ocr[indice],
                        )
                        for indice in indices[inicio:inicio + batch_size]
                    ]

                    for tarefa in as_completed(tarefas):
                        indice, texto_ocr = tarefa.result()
                        texto_paginas[indice] = texto_ocr

                    pagina_final = min(inicio + batch_size, len(indices))
                    print(
                        f"[OCR][lote={primeiro}-{ultimo}/{len(indices)}] "
                        f"terminou em {time.perf_counter() - inicio_lote:.2f}s",
                        flush=True,
                    )

        texto_bruto = "\n".join(texto_paginas)
        print("Texto extraído em", round(time.time()-t, 2), "segundos", flush=True)
        return limpar_texto(texto_bruto)
    except Exception as e:
        print(f"Erro na extração: {e}")
        return None

print("Carregando modelo BERTopic...")
t = time.time()
device = "cpu" # "cuda" if torch.cuda.is_available() else "cpu"
topic_model = joblib.load('modelo_categorias_cpu_named.joblib')
print("Modelo carregado em", round(time.time() - t, 2), "segundos")

def classificar_pdf(file_path):
    print(f"\n[{file_path}]")
    print("1. Extraindo e processando texto...")
    t = time.time()
    texto_limpo = extrair_texto(file_path)

    if not texto_limpo:
        print("Erro: Nenhum texto útil encontrado no PDF.")
        return

    print(f"2. Calculando distribuição de tópicos (Aceleração: {device.upper()})...")
    
    # Parâmetros corrigidos para não estourar o limite do MiniLM e evitar diluição
    distribuicoes, _ = topic_model.approximate_distribution(
        [texto_limpo],
        window=50,
        stride=15
    )

    notas_topicos = distribuicoes[0]
    
    # Ordena do maior pro menor
    topicos_ranqueados = np.argsort(notas_topicos)[::-1]

    print("\n" + "="*50)
    print("🏷️  TOP ETIQUETAS DO DOCUMENTO (Nomes Oficiais)")
    print("="*50)

    etiquetas_adicionadas = 0

    for num_topico in topicos_ranqueados:
        probabilidade = notas_topicos[num_topico]
        
        # Ignora o tópico lixo (-1) e travas de segurança de 1%
        if num_topico == -1 or probabilidade < 0.01:
            continue
            
        info_topico = topic_model.get_topic_info(num_topico)
        
        if 'CustomName' in info_topico.columns:
            nome_oficial = info_topico['CustomName'].values[0]
        else:
            nome_oficial = info_topico['Name'].values[0]
            
        print(f" ✔️ {nome_oficial:<40} | Confiança: {probabilidade*100:.1f}%")
        
        etiquetas_adicionadas += 1
        
        # Limita aos 3 assuntos mais fortes
        if etiquetas_adicionadas >= 3:
            break

    if etiquetas_adicionadas == 0:
        print(" Nenhuma categoria atingiu a confiança mínima de 1%.")

    print("\n" + "="*50)
    print("Documento categorizado em", round(time.time()-t, 2), "segundos")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python categorize_one.py <caminho_do_pdf>")
        sys.exit(1)

    caminho_arquivo = sys.argv[1]
    if not os.path.exists(caminho_arquivo):
        print(f"Erro: Arquivo '{caminho_arquivo}' não encontrado.")
        sys.exit(1)

    classificar_pdf(caminho_arquivo)
