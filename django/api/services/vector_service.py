from __future__ import annotations

import io
import os
import re
import shutil
from pathlib import Path
from typing import Iterable, List, Tuple

from django.db import transaction

import pymupdf
import pytesseract
from PIL import Image
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownTextSplitter
import pymupdf4llm
import requests


OCR_MIN_CHARS = int(os.getenv('OCR_MIN_CHARS', '50'))
OCR_DPI = int(os.getenv('OCR_DPI', '150'))
OCR_LANGUAGE = os.getenv('TESSERACT_LANG', 'por+eng')
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
            return [0.0 for _ in range(dimensao)]

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
        return cls._reduzir_embedding(embeddings[0], dimensao)

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
        return [
            cls._reduzir_embedding(embedding, dimensao)
            for embedding in embeddings
        ]

    @staticmethod
    def _extrair_markdown_por_pagina(caminho_pdf: str) -> List[Tuple[int, str]]:
        try:
            markdown_pages = pymupdf4llm.to_markdown(
                caminho_pdf,
                page_chunks=True,
                use_ocr=False,
            )
            paginas: List[Tuple[int, str]] = []
            with pymupdf.open(caminho_pdf) as pdf:
                for indice_pagina, pagina_markdown in enumerate(markdown_pages):
                    texto = pagina_markdown.get('text', '')
                    if indice_pagina == 0:
                        texto = VectorService._remover_marca_everyspec(texto)
                    if len(texto.strip()) < OCR_MIN_CHARS:
                        pagina = pdf[indice_pagina]
                        texto_direto = pagina.get_text('text').strip()
                        if len(texto_direto) >= OCR_MIN_CHARS:
                            texto = texto_direto
                        else:
                            texto_ocr = VectorService._extrair_texto_ocr(
                                pagina,
                                dpi=OCR_DPI,
                            ).strip()
                            if texto_ocr:
                                texto = (
                                    VectorService._remover_marca_everyspec(texto_ocr)
                                    if indice_pagina == 0
                                    else texto_ocr
                                )

                    if texto and texto.strip():
                        metadata = pagina_markdown.get('metadata', {})
                        numero_pagina = metadata.get('page_number', indice_pagina + 1)
                        paginas.append((numero_pagina, texto))
            return paginas
        except Exception as error:
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
        return [(1, texto)] if texto else []

    @classmethod
    def processar_documento(
        cls,
        documento,
        caminho_pdf: str | None = None,
        chunk_size: int = 700,
        chunk_overlap: int = 50,
        batch_size: int = 50,
    ) -> int:
        if documento is None:
            return 0

        caminho = caminho_pdf or getattr(getattr(documento, 'data', None), 'path', None)
        if not caminho or not Path(caminho).exists():
            return 0

        from api.models import DocumentoChunk

        if Path(caminho).suffix.lower() == '.docx':
            paginas = cls._extrair_docx_por_pagina(caminho)
        else:
            paginas = cls._extrair_markdown_por_pagina(caminho)
        if not paginas:
            return 0

        chunks_para_salvar: List[DocumentoChunk] = []
        chunks_pendentes: List[Tuple[int, str]] = []
        tamanho_lote_pendente = 0
        total_salvo = 0
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
                            with transaction.atomic():
                                DocumentoChunk.objects.bulk_create(chunks_para_salvar)
                            total_salvo += len(chunks_para_salvar)
                            chunks_para_salvar.clear()

            if chunks_pendentes:
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
                with transaction.atomic():
                    DocumentoChunk.objects.bulk_create(chunks_para_salvar)
                total_salvo += len(chunks_para_salvar)
        except Exception:
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
