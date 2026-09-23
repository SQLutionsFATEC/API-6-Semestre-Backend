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
import ollama


OCR_MIN_CHARS = 50
OCR_LANGUAGE = os.getenv('TESSERACT_LANG', 'por+eng')
EMBEDDING_MODEL = 'nomic-embed-text-v2-moe'
MAX_COSINE_DISTANCE = 0.62

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
        dimensao: int = 768,
        prefixo: str = 'search_document',
    ) -> List[float]:
        texto = (texto or '').strip()
        if not texto:
            return [0.0 for _ in range(dimensao)]

        try:
            resposta = ollama.embeddings(
                model=EMBEDDING_MODEL,
                prompt=f'{prefixo}: {texto}',
            )
            if hasattr(resposta, 'embedding'):
                embedding = resposta.embedding
            elif isinstance(resposta, dict):
                embedding = resposta.get('embedding', [])
            else:
                embedding = []
        except Exception as error:
            raise RuntimeError('Não foi possível gerar o embedding no Ollama.') from error

        if not isinstance(embedding, list) or len(embedding) != dimensao:
            raise RuntimeError(
                f'Embedding inválido: esperado {dimensao} dimensões.'
            )

        return [float(item) for item in embedding]

    @staticmethod
    def _extrair_markdown_por_pagina(caminho_pdf: str) -> List[Tuple[int, str]]:
        try:
            markdown_pages = pymupdf4llm.to_markdown(caminho_pdf, page_chunks=True)
            paginas: List[Tuple[int, str]] = []
            with pymupdf.open(caminho_pdf) as pdf:
                for indice_pagina, pagina_markdown in enumerate(markdown_pages):
                    texto = pagina_markdown.get('text', '')
                    if indice_pagina == 0:
                        texto = VectorService._remover_marca_everyspec(texto)
                    if len(texto.strip()) < OCR_MIN_CHARS:
                        texto_ocr = VectorService._extrair_texto_ocr(pdf[indice_pagina]).strip()
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

    @classmethod
    def processar_documento(
        cls,
        documento,
        caminho_pdf: str | None = None,
        chunk_size: int = 700,
        chunk_overlap: int = 100,
        batch_size: int = 50,
    ) -> int:
        if documento is None:
            return 0

        caminho = caminho_pdf or getattr(getattr(documento, 'data', None), 'path', None)
        if not caminho or not Path(caminho).exists():
            return 0

        from api.models import DocumentoChunk

        paginas = cls._extrair_markdown_por_pagina(caminho)
        if not paginas:
            return 0

        chunks_para_salvar: List[DocumentoChunk] = []
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
                    chunks_para_salvar.append(
                        DocumentoChunk(
                            id_documento=documento,
                            pagina=numero_pagina,
                            conteudo=texto_chunk,
                            embedding=cls.gerar_embedding(texto_chunk),
                        )
                    )

                    if len(chunks_para_salvar) >= batch_size:
                        with transaction.atomic():
                            DocumentoChunk.objects.bulk_create(chunks_para_salvar)
                        total_salvo += len(chunks_para_salvar)
                        chunks_para_salvar.clear()

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

        embedding = cls.gerar_embedding(pergunta, prefixo='search_query')
        queryset = DocumentoChunk.objects.select_related('id_documento')

        if categoria:
            queryset = queryset.filter(id_documento__etiquetas__nome__icontains=categoria)

        queryset = queryset.distinct()

        try:
            from pgvector.django import CosineDistance

            distancia = CosineDistance('embedding', embedding)
            queryset = queryset.annotate(distancia=distancia).filter(
                distancia__lt=MAX_COSINE_DISTANCE
            ).order_by('distancia')[:limite]
        except Exception:
            queryset = queryset.order_by('id_chunk')[:limite]

        return list(
            queryset.values(
                'id_chunk',
                'pagina',
                'conteudo',
                'id_documento_id',
                'id_documento__nome',
            )
        )
