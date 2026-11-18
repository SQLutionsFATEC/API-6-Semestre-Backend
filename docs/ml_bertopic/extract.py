import fitz  # PyMuPDF
import multiprocessing as mp
import psycopg2
import re
import os
import spacy
import torch
import threading
import time

from tesserocr import PyTessBaseAPI, PSM, OEM
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from psycopg2.extras import execute_values
from PIL import Image
from tqdm import tqdm

os.environ["OMP_THREAD_LIMIT"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

thread_local = threading.local()
TESSDATA_PATH = "/usr/share/tesseract-ocr/5/tessdata"
if not os.path.exists(TESSDATA_PATH):
    TESSDATA_PATH = "/usr/share/tesseract-ocr/4.00/tessdata"
if not os.path.exists(TESSDATA_PATH):
    TESSDATA_PATH = None
OCR_MAX_WORKERS = 10
OCR_DPI = 95
FORCE_OCR = False
# 1. Carrega o spaCy globalmente para os workers (sem parser/ner para poupar RAM)
nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])
nlp.max_length = 5500000 

# 2. Set de busca rápida O(1) para palavras inúteis
PALAVRAS_LIXO = {
    "everyspec", "downloaded", "www", "com", "https", "http", "from",
    "shall", "verify", "version", "did", "associated", "use", "current",
    "check", "applicable", "dated", "yes", "information", "operations"
}

DB_PARAMS = {
    "dbname": "db", 
    "user": "postgres", 
    "password": "senha", 
    "host": "localhost"
}

def setup_database():
    with psycopg2.connect(**DB_PARAMS) as conn:
        with conn.cursor() as cur:
            cur.execute('''
                CREATE UNLOGGED TABLE IF NOT EXISTS documentos_raw (
                    id SERIAL PRIMARY KEY,
                    file_path TEXT UNIQUE,
                    conteudo TEXT,
                    status TEXT,
                    mensagem_erro TEXT
                );
                
                CREATE UNLOGGED TABLE IF NOT EXISTS documento_etiqueta (
                    documento_id INTEGER REFERENCES documentos_raw(id),
                    topico_id INTEGER,
                    nome_etiqueta TEXT
                );
            ''')
        conn.commit()

def limpar_texto(texto):
    """Limpa ruídos via Regex e extrai apenas substantivos via spaCy em fatias seguras."""
    texto = texto.lower().replace('\x00', '').replace('\0', '').replace("\n", " ").replace("\t", " ")
    texto = re.sub(r"https?://\S+|www\.\S+", " ", texto)
    texto = re.sub(r"\S+@\S+", " ", texto)
    texto = re.sub(r"\bdownloaded\s+from\b", " ", texto)
    texto = re.sub(r"\b(?:https?|www|com|everyspec)\b", " ", texto)
    texto = re.sub(r"[^a-z0-9\s-]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()

    if not texto:
        raise Exception("Documento vazio encontrado.")

    substantivos = []
    TAMANHO_CHUNK = 500000  # Processa no máximo 500 mil caracteres por vez

    for i in range(0, len(texto), TAMANHO_CHUNK):
        chunk = texto[i : i + TAMANHO_CHUNK]
        doc = nlp(chunk)
        for token in doc:
            if token.pos_ == "NOUN" and len(token.text) >= 3 and token.is_alpha and token.lemma_ not in PALAVRAS_LIXO:
                substantivos.append(token.lemma_)
        del doc, chunk

    texto_final = " ".join(substantivos)

    if not texto_final:
        raise Exception("Documento ficou vazio após filtragem de substantivos.")

    return texto_final

def get_tesseract_api():
    """Ensures each thread has exactly ONE persistent instance of Tesseract."""
    if not hasattr(thread_local, "api"):
        api = PyTessBaseAPI(path=TESSDATA_PATH, lang="eng", oem=OEM.LSTM_ONLY)
        api.SetVariable("load_system_dawg", "0")
        api.SetVariable("load_freq_dawg", "0")
        api.SetVariable("tessedit_do_invert", "0")
        api.SetPageSegMode(PSM.SINGLE_BLOCK)
        api.SetVariable("classify_enable_learning", "0")
        api.SetVariable("classify_enable_adaptive_matcher", "0")
        thread_local.api = api
    return thread_local.api

def ocr_single_image_optimized(img_index, image_data):
    api = get_tesseract_api()
    width, height, stride, samples = image_data
    api.SetImageBytes(samples, width, height, 1, stride)
    text = api.GetUTF8Text()
    api.Clear()
    return img_index, text.strip()

def _extrair_texto(file_path):
    # print("Extraindo texto...")
    t = time.time()
    try:
        doc = fitz.open(file_path)
        texto_paginas = []
        imagens_ocr = {}
        for pagina in doc:
            texto = pagina.get_text("text").strip()
            texto_paginas.append(texto)

            if FORCE_OCR or len(texto) < 50:
                # print(f"Página insuficiente. Adicionando à lista de OCR {len(texto)}")
                pix = pagina.get_pixmap(dpi=OCR_DPI, colorspace=fitz.csGRAY)
                imagens_ocr[len(texto_paginas) - 1] = (
                    pix.width,
                    pix.height,
                    pix.stride,
                    bytes(pix.samples),
                )
        doc.close()

        if imagens_ocr:
            indices = list(imagens_ocr.keys())
            
            for indice in indices:
                image_data = imagens_ocr[indice]
                # print(f"OCR: {indice}/{len(indices)} páginas (single-threaded)")
                _, texto_ocr = ocr_single_image_optimized(indice, image_data)
                texto_paginas[indice] = texto_ocr


        texto_bruto = "\n".join(texto_paginas)
        texto_limpo = limpar_texto(texto_bruto)
        return texto_limpo
    except Exception as e:
        print(f"Erro na extração: {e}")
        return None

def extrair_texto(file_path):
    caminho_str = str(file_path)
    try:
        texto_limpo = _extrair_texto(file_path)
        
        if len(texto_limpo) < 50:
             return (caminho_str, None, "ERRO", "PDF sem texto legível ou sem substantivos suficientes")
             
        return (caminho_str, texto_limpo, "SUCESSO", None)
    except Exception as e:
        return (caminho_str, None, "ERRO", str(e))

def iniciar_extracao(diretorio_pdfs, tamanho_lote=100):
    setup_database()
    todos_pdfs = list(Path(diretorio_pdfs).rglob("*.pdf"))
    
    with psycopg2.connect(**DB_PARAMS) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT file_path FROM documentos_raw")
            ja_processados = {row[0] for row in cur.fetchall()}
            
    pdfs_pendentes = [pdf for pdf in todos_pdfs if str(pdf) not in ja_processados]
    print(f"Iniciando extração contínua de {len(pdfs_pendentes)} PDFs...")
    
    num_workers = os.cpu_count() 
    buffer_db = []
    
    # Abre a conexão com o banco UMA vez para todo o processo
    with psycopg2.connect(**DB_PARAMS) as conn:
        with conn.cursor() as cur:
            with mp.Pool(processes=num_workers, maxtasksperchild=1) as pool:
                
                # Passamos a lista INTEIRA. Os workers nunca vão parar de puxar arquivos até o fim.
                iterador = pool.imap_unordered(extrair_texto, pdfs_pendentes)
                
                # O tqdm agora mostra o progresso global de 0 a 100%
                for resultado in tqdm(iterador, total=len(pdfs_pendentes), desc="Processando", unit="pdf"):
                    buffer_db.append(resultado)
                    
                    # Quando a sacola bate 500, despejamos no banco de dados. 
                    # Os workers continuam processando os próximos PDFs em paralelo a este insert.
                    if len(buffer_db) >= tamanho_lote:
                        execute_values(cur, '''
                            INSERT INTO documentos_raw (file_path, conteudo, status, mensagem_erro)
                            VALUES %s ON CONFLICT (file_path) DO NOTHING
                        ''', buffer_db)
                        conn.commit()
                        buffer_db.clear() # Limpa a sacola para o próximo ciclo
                
                # Limpa a "rebarba" (os últimos arquivos que não formaram um lote de 500)
                if buffer_db:
                    execute_values(cur, '''
                        INSERT INTO documentos_raw (file_path, conteudo, status, mensagem_erro)
                        VALUES %s ON CONFLICT (file_path) DO NOTHING
                    ''', buffer_db)
                    conn.commit()
                    
    print("\nExtração finalizada com sucesso!")

if __name__ == "__main__":
    DIRETORIO = "./ArquivosEveryspec" 
    iniciar_extracao(DIRETORIO)
