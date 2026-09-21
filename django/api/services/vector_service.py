from __future__ import annotations

import hashlib
import io
import shutil
from pathlib import Path
from typing import Iterable, List, Tuple

from django.db import transaction

import pymupdf
import pytesseract
from PIL import Image


if not shutil.which('tesseract'):
    for caminho_tesseract in (
        Path(r'C:\Program Files\Tesseract-OCR\tesseract.exe'),
        Path(r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe'),
    ):
        if caminho_tesseract.exists():
            pytesseract.pytesseract.tesseract_cmd = str(caminho_tesseract)
            break


try:
    from langchain_core.documents import Document
    from langchain_text_splitters import MarkdownTextSplitter
except Exception:  # pragma: no cover - dependência opcional em alguns ambientes
    Document = None
    MarkdownTextSplitter = None

try:
    import pymupdf4llm
except Exception:  # pragma: no cover
    pymupdf4llm = None

try:
    import ollama
except Exception:  # pragma: no cover
    ollama = None


class VectorService:
    """Serviço responsável pela extração de contexto em Markdown, chunking e embeddings."""

    @staticmethod
    def _extrair_texto_ocr(pagina, dpi: int = 150) -> str:
        try:
            pix = pagina.get_pixmap(dpi=dpi, alpha=False)
            imagem = Image.open(io.BytesIO(pix.tobytes('png')))
            try:
                return pytesseract.image_to_string(imagem, lang='por+eng')
            except pytesseract.TesseractError:
                return pytesseract.image_to_string(imagem, lang='eng')
        except Exception:
            return ''

    @staticmethod
    def _fallback_embedding(texto: str, dimensao: int = 768) -> List[float]:
        if not texto:
            return [0.0 for _ in range(dimensao)]

        digest = hashlib.sha256(texto.encode('utf-8')).digest()
        valores: List[float] = []
        for indice in range(dimensao):
            byte = digest[indice % len(digest)]
            fator = ((byte + indice * 17) % 1000) / 1000.0
            valores.append(round(fator, 6))
        return valores

    @classmethod
    def gerar_embedding(cls, texto: str, dimensao: int = 768) -> List[float]:
        texto = (texto or '').strip()
        if not texto:
            return [0.0 for _ in range(dimensao)]

        try:
            if ollama is None:
                import ollama as ollama_lib
                ollama = ollama_lib

            resposta = ollama.embeddings(model='nomic-embed-text', prompt=texto)
            if hasattr(resposta, 'embedding'):
                embedding = resposta.embedding
            elif isinstance(resposta, dict):
                if 'embedding' in resposta:
                    embedding = resposta['embedding']
                elif 'data' in resposta and resposta['data']:
                    embedding = resposta['data'][0].get('embedding', [])
                else:
                    embedding = []
            else:
                embedding = []

            if isinstance(embedding, list) and len(embedding) == dimensao:
                return [float(item) for item in embedding]
        except Exception:
            pass

        return cls._fallback_embedding(texto, dimensao)

    @staticmethod
    def _extrair_markdown_por_pagina(caminho_pdf: str) -> List[Tuple[int, str]]:
        markdown_por_pagina = {}
        try:
            if pymupdf4llm is not None:
                resultado = pymupdf4llm.to_markdown(caminho_pdf, page_chunks=True)
                if isinstance(resultado, dict):
                    for indice, conteudo in enumerate(resultado.values(), start=1):
                        if conteudo:
                            markdown_por_pagina[indice] = str(conteudo)
                elif isinstance(resultado, list):
                    for item in resultado:
                        if isinstance(item, dict):
                            numero_pagina = item.get('page') or item.get('pagina') or 1
                            conteudo = item.get('text') or item.get('conteudo') or ''
                            markdown_por_pagina[int(numero_pagina)] = str(conteudo)
                        else:
                            markdown_por_pagina[1] = str(item)

            pdf = pymupdf.open(caminho_pdf)
            paginas: List[Tuple[int, str]] = []
            for indice_pagina in range(len(pdf)):
                numero_pagina = indice_pagina + 1
                texto = markdown_por_pagina.get(numero_pagina, '')
                if len(texto.strip()) < 80:
                    texto = pdf[indice_pagina].get_text('text')
                if len((texto or '').strip()) < 80:
                    texto = VectorService._extrair_texto_ocr(pdf[indice_pagina])
                if texto and texto.strip():
                    paginas.append((numero_pagina, texto))
            pdf.close()
            return paginas
        except Exception:
            return []

    @classmethod
    def processar_documento(cls, documento, caminho_pdf: str | None = None, chunk_size: int = 900, chunk_overlap: int = 150) -> int:
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

        for numero_pagina, markdown_texto in paginas:
            if not markdown_texto or not markdown_texto.strip():
                continue

            if MarkdownTextSplitter is None:
                chunks = [markdown_texto]
            else:
                splitter = MarkdownTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
                if Document is None:
                    chunks = [markdown_texto]
                else:
                    documento_langchain = Document(
                        page_content=f'{documento.nome}\n\n{markdown_texto}',
                        metadata={'page': numero_pagina, 'documento': documento.nome},
                    )
                    chunks = splitter.split_documents([documento_langchain])
                    chunks = [chunk.page_content for chunk in chunks]

            for chunk in chunks:
                texto_chunk = f'{documento.nome}\n\n{chunk}'.strip()
                embedding = cls.gerar_embedding(texto_chunk)
                chunks_para_salvar.append(
                    DocumentoChunk(
                        id_documento=documento,
                        pagina=numero_pagina,
                        conteudo=texto_chunk,
                        embedding=embedding,
                    )
                )

        if chunks_para_salvar:
            with transaction.atomic():
                DocumentoChunk.objects.bulk_create(chunks_para_salvar)

        return len(chunks_para_salvar)

    @classmethod
    def buscar_contexto(cls, pergunta: str, categoria: str | None = None, limite: int = 5):
        from api.models import DocumentoChunk

        pergunta = (pergunta or '').strip()
        if not pergunta:
            return []

        embedding = cls.gerar_embedding(pergunta)
        queryset = DocumentoChunk.objects.select_related('id_documento')

        if categoria:
            queryset = queryset.filter(id_documento__etiquetas__nome__icontains=categoria)

        queryset = queryset.distinct()

        try:
            from pgvector.django import CosineDistance

            queryset = queryset.order_by(CosineDistance('embedding', embedding))[:limite]
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
