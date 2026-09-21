from django.db import models

try:
    from pgvector.django import HnswIndex as PGHnswIndex
    from pgvector.django import VectorField as PGVectorField

    HAS_PGVECTOR = True
except Exception:  # pragma: no cover - fallback para ambientes sem pgvector
    PGHnswIndex = None
    PGVectorField = None
    HAS_PGVECTOR = False

    class PGVectorField(models.JSONField):
        def __init__(self, *args, dimensions=None, **kwargs):
            self.dimensions = dimensions
            super().__init__(*args, **kwargs)


class VectorField(PGVectorField if HAS_PGVECTOR else models.JSONField):
    def __init__(self, *args, dimensions=None, **kwargs):
        self.dimensions = dimensions
        if HAS_PGVECTOR:
            super().__init__(*args, dimensions=dimensions, **kwargs)
        else:
            super().__init__(*args, **kwargs)


class DocumentoChunk(models.Model):
    """
    Armazena blocos de texto extraídos de um documento e seus embeddings vetoriais.
    """
    id_chunk = models.BigAutoField(primary_key=True)
    id_documento = models.ForeignKey(
        'Documento',
        on_delete=models.CASCADE,
        related_name='chunks',
        db_column='id_documento',
    )
    pagina = models.IntegerField(default=1, help_text='Número da página do documento original')
    conteudo = models.TextField(help_text='Texto do chunk em Markdown')
    embedding = VectorField(
        dimensions=768,
        help_text='Embedding vetorial do chunk com 768 dimensões',
        null=True,
        blank=True,
    )

    class Meta:
        db_table = 'documento_chunk'
        verbose_name = 'Documento Chunk'
        verbose_name_plural = 'Documentos Chunk'
        indexes = [
            models.Index(fields=['id_documento', 'pagina'], name='idx_documento_chunk_documento_pagina'),
        ]
        if HAS_PGVECTOR and PGHnswIndex is not None:
            indexes.append(
                PGHnswIndex(
                    fields=['embedding'],
                    name='idx_documento_chunk_embedding_hnsw',
                    opclasses=['vector_cosine_ops'],
                )
            )

    def __str__(self):
        return f'Chunk #{self.id_chunk} - Documento #{self.id_documento_id}'
