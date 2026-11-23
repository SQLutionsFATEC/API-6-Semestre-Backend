import logging
import re
from pathlib import Path
import joblib
import pymupdf
from django.conf import settings

from api.services.ocr_service import extract_page_text

logger = logging.getLogger(__name__)

# Suprime avisos do motor C do MuPDF no console (ex: 'format error: No default Layer config'),
# que acontecem quando o PyMuPDF tenta ler PDFs escaneados ou com camadas fora do padrão,
# garantindo que o console não seja poluído já que o OCR/fallback trata esses casos.
try:
    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
except Exception:
    pass

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
        """Carrega o modelo de categorização em memória."""
        if cls._artefato is None:
            caminho_modelo = Path(settings.ML_MODEL_PATH)
            logger.info('categorizacao etapa=carregamento_modelo caminho=%s', caminho_modelo)
            if not caminho_modelo.exists():
                raise FileNotFoundError(
                    f"Modelo de ML não encontrado em: {caminho_modelo}"
                )

            cls._artefato = joblib.load(caminho_modelo)
            logger.info('categorizacao etapa=modelo_carregado caminho=%s', caminho_modelo)

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

        logger.info(
            'categorizacao etapa=extracao_pdf_inicio caminho=%s limite_paginas=%d',
            caminho,
            max_paginas,
        )
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
                        texto_ocr = extract_page_text(pagina, dpi=dpi_ocr)
                        textos.append(texto_ocr)
                        paginas_ocr += 1
                    except Exception as e_ocr:
                        logger.warning(
                            'categorizacao etapa=ocr_falha pagina=%d erro=%s',
                            numero_pagina + 1,
                            e_ocr,
                        )

                # 3. Verifica se atingiu quantidade suficiente de texto útil
                texto_atual = cls.limpar_texto(" ".join(textos))
                if len(texto_atual) >= min_texto_total:
                    break

            pdf.close()

        except Exception as erro:
            logger.exception(
                'categorizacao etapa=extracao_pdf_falha caminho=%s erro=%s',
                caminho,
                erro,
            )
            return ""

        texto_final = " ".join(textos).strip()
        logger.info(
            'categorizacao etapa=extracao_pdf_concluida caminho=%s paginas_texto=%d '
            'paginas_ocr=%d caracteres=%d',
            caminho,
            paginas_texto,
            paginas_ocr,
            len(texto_final),
        )
        return texto_final

    @classmethod
    def classificar_documento(
        cls,
        caminho_pdf: str,
        limite_confianca: float = 0.3,
        texto_extraido: str | None = None,
    ) -> str:
        """
        Classifica o PDF utilizando TF-IDF + modelo treinado (.joblib).
        Exibe logs detalhados das etapas de decisão.
        """
        caminho = Path(caminho_pdf)
        if not caminho.exists():
            logger.warning(
                'categorizacao etapa=arquivo_inexistente caminho=%s',
                caminho_pdf,
            )
            return "NAO_CLASSIFICADO"

        # 1. Usa o texto já extraído quando disponível para evitar OCR duplicado.
        if texto_extraido is not None:
            texto = texto_extraido
            logger.info(
                'categorizacao etapa=texto_reutilizado caminho=%s caracteres=%d',
                caminho.name,
                len(texto),
            )
        elif caminho.suffix.lower() == '.docx':
            from docx import Document as WordDocument

            documento_word = WordDocument(str(caminho))
            partes = [paragrafo.text for paragrafo in documento_word.paragraphs]
            partes.extend(
                celula.text
                for tabela in documento_word.tables
                for linha in tabela.rows
                for celula in linha.cells
            )
            texto = '\n'.join(parte for parte in partes if parte)
            logger.info(
                'categorizacao etapa=texto_docx_extraido caminho=%s caracteres=%d',
                caminho.name,
                len(texto),
            )
        else:
            logger.info('categorizacao etapa=extracao_texto caminho=%s', caminho.name)
            texto = cls.extrair_texto_pdf(str(caminho))
            logger.info(
                'categorizacao etapa=extracao_texto_concluida caminho=%s caracteres=%d',
                caminho.name,
                len(texto),
            )

        # Caso 1: nenhum texto foi extraído
        if len(texto.strip()) == 0:
            logger.warning(
                'categorizacao etapa=sem_texto_util caminho=%s',
                caminho.name,
            )
            return "NAO_CLASSIFICADO"

        # 2. Limpa o texto
        texto_limpo = cls.limpar_texto(texto)

        # Caso 2: pouco conteúdo útil após limpeza (< 100 caracteres)
        if len(texto_limpo) < 100:
            logger.warning(
                'categorizacao etapa=texto_insuficiente caminho=%s caracteres_limpos=%d',
                caminho.name,
                len(texto_limpo),
            )
            return "NAO_CLASSIFICADO"

        # 3. Carrega o modelo
        artefato = cls._carregar_modelo()
        vectorizer = artefato["vectorizer"]
        modelo = artefato["model"]

        # 4. Transforma utilizando o TF-IDF treinado
        texto_tfidf = vectorizer.transform([texto_limpo])

        # Caso 3: nenhum termo reconhecido pelo TF-IDF
        if texto_tfidf.nnz == 0:
            logger.warning(
                'categorizacao etapa=sem_termos_reconhecidos caminho=%s',
                caminho.name,
            )
            return "NAO_CLASSIFICADO"

        # 5. Obtém os scores das classes via decision_function
        scores = modelo.decision_function(texto_tfidf)[0]
        indice_classe = scores.argmax()
        maior_score = round(float(scores[indice_classe]), 4)
        classe_candidata = modelo.classes_[indice_classe]

        # Caso 4: verifica se o maior score atinge o limite mínimo de confiança (0.3)
        if maior_score < limite_confianca:
            logger.info(
                'categorizacao etapa=confianca_insuficiente caminho=%s score=%.4f '
                'limite=%.4f classe=%s',
                caminho.name,
                maior_score,
                limite_confianca,
                classe_candidata,
            )
            return "NAO_CLASSIFICADO"

        logger.info(
            'categorizacao etapa=predicao_concluida caminho=%s classe=%s score=%.4f',
            caminho.name,
            classe_candidata,
            maior_score,
        )
        return classe_candidata
