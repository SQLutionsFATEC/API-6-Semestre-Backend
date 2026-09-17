import io
import re
from pathlib import Path
import joblib
import pymupdf
import pytesseract
from PIL import Image
from django.conf import settings

import shutil

# Configura o caminho do binário tesseract no Windows se não estiver diretamente no PATH
if not shutil.which("tesseract"):
    for c in [
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe")
    ]:
        if c.exists():
            pytesseract.pytesseract.tesseract_cmd = str(c)
            break

# ==============================================================================
# IMPORTANTE!!!
# POR QUE ESTE ARQUIVO É NECESSÁRIO SE O MODELO JÁ FOI TREINADO?
# ==============================================================================
# O arquivo modelo_categorizacao_etiqueta.joblib armazena apenas os pesos e
# vocabulários aprendidos durante o treinamento (TfidfVectorizer + LinearSVC).
# Contudo, ele NÃO contém código para abrir arquivos PDF binários ou aplicar regex.
#
# Quando um novo documento PDF é enviado via API REST:
# 1. O arquivo chega como um PDF binário em disco. O modelo de ML exige texto.
# 2. O MLService extrai o texto do PDF (PyMuPDF com OCR Tesseract para documentos escaneados).
# 3. O MLService aplica a mesma limpeza de texto (regex) feita no treinamento.
# 4. Carrega o modelo (.joblib) em memória apenas uma vez (Singleton).
# 5. Vetoriza o texto limpo e chama a predição para definir a etiqueta do documento.
# ==============================================================================


class MLService:
    _artefato = None

    @classmethod
    def _carregar_modelo(cls):
        """Carrega o arquivo modelo_categorizacao_etiqueta.joblib na memória."""
        if cls._artefato is None:
            caminhos_possiveis = [
                Path("/docs/ml_etiqueta/artifacts/modelo_categorizacao_etiqueta.joblib"),
                Path(__file__).resolve().parent.parent.parent.parent / "docs" / "ml_etiqueta" / "artifacts" / "modelo_categorizacao_etiqueta.joblib",
            ]
            try:
                caminhos_possiveis.append(settings.BASE_DIR.parent / "docs" / "ml_etiqueta" / "artifacts" / "modelo_categorizacao_etiqueta.joblib")
            except Exception:
                pass

            caminho_encontrado = None
            for p in caminhos_possiveis:
                if p.exists():
                    caminho_encontrado = p
                    break

            if not caminho_encontrado:
                raise FileNotFoundError(
                    f"Modelo de ML não encontrado em nenhum dos caminhos previstos. Tentativas: {[str(c) for c in caminhos_possiveis]}"
                )

            cls._artefato = joblib.load(caminho_encontrado)
        return cls._artefato

    @staticmethod
    def limpar_texto(texto: str) -> str:
        r"""
        Réplica EXATA da função limpar_texto do notebook:
        - Converte para minúsculas
        - Substitui \n e \t por espaços
        - Remove URLs e e-mails
        - Remove termos específicos (downloaded from, everyspec, etc)
        - Remove caracteres especiais (mantendo a-z0-9\s-)
        - Remove espaços duplicados
        """
        if not texto:
            return ""

        texto = texto.lower()
        texto = texto.replace("\n", " ")
        texto = texto.replace("\t", " ")

        # Remove URLs completas
        texto = re.sub(r"https?://\S+|www\.\S+", " ", texto)

        # Remove endereços de e-mail
        texto = re.sub(r"\S+@\S+", " ", texto)

        # Remove frases comuns de download encontradas nos PDFs
        texto = re.sub(r"\bdownloaded\s+from\b", " ", texto)

        # Remove termos que representam lixo de URLs e fontes de download
        texto = re.sub(r"\b(?:https?|www|com|everyspec)\b", " ", texto)

        # Remove caracteres especiais (mantém a-z, 0-9, espaços e hífen)
        texto = re.sub(r"[^a-z0-9\s-]", " ", texto)

        # Remove espaços repetidos
        texto = re.sub(r"\s+", " ", texto)

        return texto.strip()

    @classmethod
    def extrair_texto_pdf(
        cls,
        caminho: str,
        max_paginas: int = 30,
        min_caracteres_pagina: int = 80,
        min_texto_total: int = 10000,
        dpi_ocr: int = 150
    ) -> str:
        """
        Leitura híbrida: PyMuPDF + Tesseract OCR para páginas escaneadas.
        Exibe logs detalhados do progresso de extração por página.
        """
        textos = []
        paginas_texto = 0
        paginas_ocr = 0

        try:
            pdf = pymupdf.open(caminho)

            if not pdf.is_pdf:
                pdf.close()
                raise ValueError("O arquivo informado não é um PDF válido.")

            limite = min(len(pdf), max_paginas)

            for numero_pagina in range(limite):
                pagina = pdf[numero_pagina]

                # 1. Tenta extração normal via PyMuPDF
                texto_pagina = pagina.get_text("text")
                texto_pagina_limpo = cls.limpar_texto(texto_pagina)

                # Se encontrou texto suficiente na página, utiliza extração normal
                if len(texto_pagina_limpo) >= min_caracteres_pagina:
                    textos.append(texto_pagina)
                    paginas_texto += 1
                else:
                    # 2. Executa OCR com Tesseract
                    try:
                        pix = pagina.get_pixmap(dpi=dpi_ocr, alpha=False)
                        imagem = Image.open(io.BytesIO(pix.tobytes("png")))
                        texto_ocr = pytesseract.image_to_string(imagem, lang="eng")
                        textos.append(texto_ocr)
                        paginas_ocr += 1
                    except pytesseract.TesseractNotFoundError:
                        pass
                    except Exception as e_ocr:
                        pass

                # 3. Verifica se atingiu quantidade suficiente de texto útil
                texto_atual = cls.limpar_texto(" ".join(textos))
                if len(texto_atual) >= min_texto_total:
                    break

            pdf.close()

        except Exception as erro:
            return ""

        texto_final = " ".join(textos).strip()
        return texto_final

    @classmethod
    def classificar_documento(
        cls,
        caminho_pdf: str,
        limite_confianca: float = 0.3
    ) -> str:
        """
        Classifica o PDF utilizando TF-IDF + modelo treinado (.joblib).
        Exibe logs detalhados das etapas de decisão.
        """
        caminho = Path(caminho_pdf)
        if not caminho.exists():
            return "NAO_CLASSIFICADO"

        # 1. Extrai o texto
        texto = cls.extrair_texto_pdf(str(caminho))

        # Caso 1: nenhum texto foi extraído
        if len(texto.strip()) == 0:
            return "NAO_CLASSIFICADO"

        # 2. Limpa o texto
        texto_limpo = cls.limpar_texto(texto)

        # Caso 2: pouco conteúdo útil após limpeza (< 100 caracteres)
        if len(texto_limpo) < 100:
            return "NAO_CLASSIFICADO"

        # 3. Carrega o modelo
        artefato = cls._carregar_modelo()
        vectorizer = artefato["vectorizer"]
        modelo = artefato["model"]

        # 4. Transforma utilizando o TF-IDF treinado
        texto_tfidf = vectorizer.transform([texto_limpo])

        # Caso 3: nenhum termo reconhecido pelo TF-IDF
        if texto_tfidf.nnz == 0:
            return "NAO_CLASSIFICADO"

        # 5. Obtém os scores das classes via decision_function
        scores = modelo.decision_function(texto_tfidf)[0]
        indice_classe = scores.argmax()
        maior_score = round(float(scores[indice_classe]), 4)
        classe_candidata = modelo.classes_[indice_classe]

        # Caso 4: verifica se o maior score atinge o limite mínimo de confiança (0.3)
        if maior_score < limite_confianca:
            return "NAO_CLASSIFICADO"

        return classe_candidata
