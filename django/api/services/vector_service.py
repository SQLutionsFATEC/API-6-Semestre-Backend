from __future__ import annotations

import io
import logging
import os
import re
import shutil
from time import perf_counter
from pathlib import Path
from typing import Iterable, List, Tuple

from django.db import transaction

import pymupdf
import pytesseract
from PIL import Image
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownTextSplitter
import requests


logger = logging.getLogger(__name__)

OCR_DPI = int(os.getenv('OCR_DPI', '150'))
OCR_LANGUAGE = os.getenv('TESSERACT_LANG', 'eng')
LLAMA_CPP_HOST = os.getenv('LLAMA_CPP_HOST', 'http://llama-cpp:8080').rstrip('/')
LLAMA_CPP_EMBEDDING_ENDPOINT = os.getenv(
    'LLAMA_CPP_EMBEDDING_ENDPOINT',
    '/v1/embeddings',
).strip('/')
LLAMA_CPP_TIMEOUT = float(os.getenv('LLAMA_CPP_TIMEOUT', '120'))
EMBEDDING_BATCH_SIZE = int(os.getenv('EMBEDDING_BATCH_SIZE', '8'))
EMBEDDING_BATCH_MAX_CHARS = int(
    os.getenv('EMBEDDING_BATCH_MAX_CHARS', '6000')
)
EMBEDDING_DIMENSIONS = 256
MAX_COSINE_DISTANCE = 0.62
HTTP_SESSION = requests.Session()

if os.getenv('TESSERACT_CMD'):
    pytesseract.pytesseract.tesseract_cmd = os.getenv('TESSERACT_CMD')
elif not shutil.which('tesseract'):
    for caminho_tesseract in (
        Path(r'C:\Program Files\Tesseract-OCR\tesseract.exe'),
        Path(r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe'),
    ):
        if caminho_tesseract.exists():
            pytesseract.pytesseract.tesseract_cmd = str(caminho_tesseract)
            break


class VectorService:
    """Serviço responsável pela extração de contexto em Markdown, chunking e embeddings."""

    @staticmethod
    def _remover_marca_everyspec(texto: str) -> str:
        marca = r'(?im)^\s*.*Downloaded\s+from.*everyspec\.com.*(?:\r?\n|$)'
        texto = re.sub(marca, '', texto)
        return re.sub(r'\n\s*\n\s*\n+', '\n\n', texto)

    @staticmethod
    def _extrair_texto_ocr(pagina, dpi: int = 150) -> str:
        try:
            pix = pagina.get_pixmap(dpi=dpi, alpha=False)
            imagem = Image.open(io.BytesIO(pix.tobytes('png')))
            return pytesseract.image_to_string(imagem, lang=OCR_LANGUAGE)
        except pytesseract.TesseractNotFoundError as error:
            raise RuntimeError(
                'Tesseract não encontrado. Instale-o e coloque-o no PATH ou defina '
                'a variável TESSERACT_CMD com o caminho de tesseract.exe.'
            ) from error

    @classmethod
    def gerar_embedding(
        cls,
        texto: str,
        dimensao: int = EMBEDDING_DIMENSIONS,
        prefixo: str = 'search_document',
    ) -> List[float]:
        texto = (texto or '').strip()
        if not texto:
            logger.info(
                'embedding etapa=texto_vazio dimensao=%d prefixo=%s',
                dimensao,
                prefixo,
            )
            return [0.0 for _ in range(dimensao)]

        inicio = perf_counter()
        logger.info(
            'embedding etapa=solicitacao_inicio caracteres=%d dimensao=%d prefixo=%s',
            len(texto),
            dimensao,
            prefixo,
        )
        try:
            resposta = HTTP_SESSION.post(
                f'{LLAMA_CPP_HOST}/{LLAMA_CPP_EMBEDDING_ENDPOINT}',
                json={
                    'model': 'nomic-embed-text-v1.5',
                    'input': [f'{prefixo}: {texto}'],
                },
                timeout=LLAMA_CPP_TIMEOUT,
            )
            resposta.raise_for_status()
            payload = resposta.json()
        except requests.HTTPError as error:
            detalhe = error.response.text[:500] if error.response is not None else ''
            raise RuntimeError(
                f'Não foi possível gerar o embedding no llama.cpp: {detalhe}'
            ) from error
        except (requests.RequestException, ValueError) as error:
            raise RuntimeError(
                'Não foi possível gerar o embedding no llama.cpp.'
            ) from error

        embeddings = cls._extrair_embeddings(payload)
        if len(embeddings) != 1:
            raise RuntimeError('Resposta inválida do llama.cpp para um embedding.')
        resultado = cls._reduzir_embedding(embeddings[0], dimensao)
        logger.info(
            'embedding etapa=solicitacao_concluida dimensao=%d duracao_s=%.3f',
            dimensao,
            perf_counter() - inicio,
        )
        return resultado

    @staticmethod
    def _extrair_embeddings(payload) -> List[List[float]]:
        if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
            raise RuntimeError('Resposta inválida do llama.cpp para embeddings.')

        itens = sorted(
            payload['data'],
            key=lambda item: item.get('index', 0) if isinstance(item, dict) else 0,
        )
        embeddings = [
            item.get('embedding', [])
            for item in itens
            if isinstance(item, dict)
        ]
        normalizados = []
        for embedding in embeddings:
            if (
                isinstance(embedding, list)
                and len(embedding) == 1
                and isinstance(embedding[0], list)
            ):
                embedding = embedding[0]
            normalizados.append(embedding)
        return normalizados

    @staticmethod
    def _reduzir_embedding(embedding, dimensao: int) -> List[float]:
        if not isinstance(embedding, list) or len(embedding) < dimensao:
            raise RuntimeError(
                f'Embedding inválido: esperado pelo menos {dimensao} dimensões.'
            )
        try:
            return [float(item) for item in embedding[:dimensao]]
        except (TypeError, ValueError) as error:
            raise RuntimeError(
                'Embedding inválido: os valores precisam ser numéricos.'
            ) from error

    @classmethod
    def gerar_embeddings(
        cls,
        textos: List[str],
        dimensao: int = EMBEDDING_DIMENSIONS,
        prefixo: str = 'search_document',
    ) -> List[List[float]]:
        if not textos:
            return []

        inicio = perf_counter()
        logger.info(
            'embedding etapa=lote_inicio quantidade=%d caracteres=%d prefixo=%s',
            len(textos),
            sum(len(texto) for texto in textos),
            prefixo,
        )
        try:
            resposta = HTTP_SESSION.post(
                f'{LLAMA_CPP_HOST}/{LLAMA_CPP_EMBEDDING_ENDPOINT}',
                json={
                    'model': 'nomic-embed-text-v1.5',
                    'input': [f'{prefixo}: {texto.strip()}' for texto in textos],
                },
                timeout=LLAMA_CPP_TIMEOUT,
            )
            resposta.raise_for_status()
            payload = resposta.json()
        except requests.HTTPError as error:
            detalhe = error.response.text[:500] if error.response is not None else ''
            raise RuntimeError(
                f'Não foi possível gerar os embeddings no llama.cpp: {detalhe}'
            ) from error
        except (requests.RequestException, ValueError) as error:
            raise RuntimeError(
                'Não foi possível gerar os embeddings no llama.cpp.'
            ) from error

        embeddings = cls._extrair_embeddings(payload)
        if len(embeddings) != len(textos):
            raise RuntimeError(
                'Resposta do llama.cpp não contém um embedding para cada chunk.'
            )
        resultado = [
            cls._reduzir_embedding(embedding, dimensao)
            for embedding in embeddings
        ]
        logger.info(
            'embedding etapa=lote_concluido quantidade=%d dimensao=%d duracao_s=%.3f',
            len(textos),
            dimensao,
            perf_counter() - inicio,
        )
        return resultado

    @staticmethod
    def _extrair_markdown_por_pagina(caminho_pdf: str) -> List[Tuple[int, str]]:
        inicio = perf_counter()
        paginas_ocr = 0
        try:
            paginas: List[Tuple[int, str]] = []
            with pymupdf.open(caminho_pdf) as pdf:
                for indice_pagina, pagina in enumerate(pdf):
                    texto = pagina.get_text('text').strip()
                    if indice_pagina == 0:
                        texto = VectorService._remover_marca_everyspec(texto)
                    if not texto:
                        texto_ocr = VectorService._extrair_texto_ocr(
                            pagina,
                            dpi=OCR_DPI,
                        ).strip()
                        paginas_ocr += 1
                        if texto_ocr:
                            texto = (
                                VectorService._remover_marca_everyspec(texto_ocr)
                                if indice_pagina == 0
                                else texto_ocr
                            )

                    if texto and texto.strip():
                        paginas.append((indice_pagina + 1, texto))
            logger.info(
                'vector etapa=extracao caminho=%s paginas=%d paginas_ocr=%d '
                'duracao_s=%.3f',
                caminho_pdf,
                len(paginas),
                paginas_ocr,
                perf_counter() - inicio,
            )
            return paginas
        except Exception as error:
            logger.exception(
                'embedding etapa=extracao_falha caminho=%s',
                caminho_pdf,
            )
            raise RuntimeError(f'Falha ao extrair o PDF: {caminho_pdf}') from error

    @staticmethod
    def _extrair_docx_por_pagina(caminho_docx: str) -> List[Tuple[int, str]]:
        from docx import Document as WordDocument

        documento_word = WordDocument(caminho_docx)
        partes = [paragrafo.text for paragrafo in documento_word.paragraphs]
        partes.extend(
            celula.text
            for tabela in documento_word.tables
            for linha in tabela.rows
            for celula in linha.cells
        )
        texto = '\n'.join(parte for parte in partes if parte).strip()
        logger.info(
            'embedding etapa=extracao_docx_concluida caminho=%s paginas=%d caracteres=%d',
            caminho_docx,
            1 if texto else 0,
            len(texto),
        )
        return [(1, texto)] if texto else []

    @classmethod
    def extrair_paginas(cls, caminho: str) -> List[Tuple[int, str]]:
        caminho_path = Path(caminho)
        if not caminho or not caminho_path.exists():
            return []
        if caminho_path.suffix.lower() == '.docx':
            return cls._extrair_docx_por_pagina(caminho)
        return cls._extrair_markdown_por_pagina(caminho)

    @classmethod
    def processar_documento(
        cls,
        documento,
        caminho_pdf: str | None = None,
        chunk_size: int = 700,
        chunk_overlap: int = 50,
        batch_size: int = 50,
        paginas: List[Tuple[int, str]] | None = None,
    ) -> int:
        if documento is None:
            return 0

        caminho = caminho_pdf or getattr(getattr(documento, 'data', None), 'path', None)
        if not caminho or not Path(caminho).exists():
            return 0

        from api.models import DocumentoChunk

        paginas = paginas if paginas is not None else cls.extrair_paginas(caminho)
        if not paginas:
            logger.warning(
                'embedding etapa=sem_paginas documento_id=%s caminho=%s',
                getattr(documento, 'id_documento', None),
                caminho,
            )
            return 0

        chunks_para_salvar: List[DocumentoChunk] = []
        chunks_pendentes: List[Tuple[int, str]] = []
        tamanho_lote_pendente = 0
        total_salvo = 0
        inicio_processamento = perf_counter()
        duracao_persistencia = 0.0
        nome_arquivo = Path(caminho).name
        splitter = MarkdownTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

        try:
            for numero_pagina, markdown_texto in paginas:
                if not markdown_texto or not markdown_texto.strip():
                    continue

                documentos = splitter.split_documents([
                    Document(
                        page_content=markdown_texto,
                        metadata={'page_number': numero_pagina},
                    )
                ])
                chunks = [chunk.page_content for chunk in documentos]
                logger.info(
                    'embedding etapa=chunks_criados documento_id=%s pagina=%d quantidade=%d',
                    documento.id_documento,
                    numero_pagina,
                    len(chunks),
                )

                for chunk in chunks:
                    texto_chunk = f'Documento: {nome_arquivo}.\n{chunk}'.strip()
                    texto_chunk = texto_chunk.replace('\x00', '')
                    if not texto_chunk:
                        continue
                    chunks_pendentes.append((numero_pagina, texto_chunk))
                    tamanho_lote_pendente += len(texto_chunk)

                    if (
                        len(chunks_pendentes) >= EMBEDDING_BATCH_SIZE
                        or tamanho_lote_pendente >= EMBEDDING_BATCH_MAX_CHARS
                    ):
                        logger.info(
                            'embedding etapa=lote_disparado documento_id=%s quantidade=%d '
                            'caracteres=%d',
                            documento.id_documento,
                            len(chunks_pendentes),
                            tamanho_lote_pendente,
                        )
                        embeddings = cls.gerar_embeddings(
                            [texto for _, texto in chunks_pendentes],
                        )
                        for (pagina, texto), embedding in zip(
                            chunks_pendentes,
                            embeddings,
                        ):
                            chunks_para_salvar.append(
                                DocumentoChunk(
                                    id_documento=documento,
                                    pagina=pagina,
                                    conteudo=texto,
                                    embedding=embedding,
                                )
                            )
                        chunks_pendentes.clear()
                        tamanho_lote_pendente = 0

                        if len(chunks_para_salvar) >= batch_size:
                            inicio_persistencia = perf_counter()
                            with transaction.atomic():
                                DocumentoChunk.objects.bulk_create(chunks_para_salvar)
                            duracao_persistencia += (
                                perf_counter() - inicio_persistencia
                            )
                            total_salvo += len(chunks_para_salvar)
                            logger.info(
                                'embedding etapa=chunks_persistidos documento_id=%s '
                                'quantidade=%d total=%d',
                                documento.id_documento,
                                len(chunks_para_salvar),
                                total_salvo,
                            )
                            chunks_para_salvar.clear()

            if chunks_pendentes:
                logger.info(
                    'embedding etapa=lote_final_disparado documento_id=%s quantidade=%d '
                    'caracteres=%d',
                    documento.id_documento,
                    len(chunks_pendentes),
                    tamanho_lote_pendente,
                )
                embeddings = cls.gerar_embeddings(
                    [texto for _, texto in chunks_pendentes],
                )
                for (pagina, texto), embedding in zip(chunks_pendentes, embeddings):
                    chunks_para_salvar.append(
                        DocumentoChunk(
                            id_documento=documento,
                            pagina=pagina,
                            conteudo=texto,
                            embedding=embedding,
                        )
                    )

            if chunks_para_salvar:
                inicio_persistencia = perf_counter()
                with transaction.atomic():
                    DocumentoChunk.objects.bulk_create(chunks_para_salvar)
                duracao_persistencia += perf_counter() - inicio_persistencia
                total_salvo += len(chunks_para_salvar)
                logger.info(
                    'embedding etapa=chunks_persistidos documento_id=%s '
                    'quantidade=%d total=%d',
                    documento.id_documento,
                    len(chunks_para_salvar),
                    total_salvo,
                )
            logger.info(
                'embedding etapa=processamento_concluido documento_id=%s total_chunks=%d duracao_s=%.3f '
                'persistencia_s=%.3f',
                documento.id_documento,
                total_salvo,
                perf_counter() - inicio_processamento,
                duracao_persistencia,
            )
        except Exception:
            logger.exception(
                'embedding etapa=falha documento_id=%s',
                documento.id_documento,
            )
            DocumentoChunk.objects.filter(id_documento=documento).delete()
            raise

        return total_salvo

    @classmethod
    def buscar_contexto(cls, pergunta: str, categoria: str | None = None, limite: int = 5):
        from api.models import DocumentoChunk

        pergunta = (pergunta or '').strip()
        if not pergunta:
            return []

        queryset = DocumentoChunk.objects.select_related('id_documento')

        if categoria:
            queryset = queryset.filter(id_documento__etiquetas__nome__icontains=categoria)

        queryset = queryset.distinct()

        try:
            from pgvector.django import CosineDistance
            from django.db.models import Q

            embedding = cls.gerar_embedding(pergunta, prefixo='search_query')
            distancia = CosineDistance('embedding', embedding)
            queryset = queryset.annotate(distancia=distancia).filter(
                Q(conteudo__icontains=pergunta) | Q(distancia__lt=0.72)
            ).order_by('distancia')[:limite]
        except Exception:
            queryset = queryset.filter(conteudo__icontains=pergunta).order_by('id_chunk')[:limite]

        return list(
            queryset.values(
                'id_chunk',
                'pagina',
                'conteudo',
                'id_documento_id',
                'id_documento__nome',
            )
        )
