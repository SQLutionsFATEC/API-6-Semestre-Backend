import django.db.models.deletion
from django.db import migrations, models

try:
    from pgvector.django import HnswIndex, VectorField
    HAS_PGVECTOR = True
except Exception:  # pragma: no cover
    HAS_PGVECTOR = False

    class VectorField(models.JSONField):
        def __init__(self, *args, dimensions=None, **kwargs):
            self.dimensions = dimensions
            super().__init__(*args, **kwargs)

    HnswIndex = None


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(
            sql='CREATE EXTENSION IF NOT EXISTS vector',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.CreateModel(
            name='DocumentoChunk',
            fields=[
                ('id_chunk', models.BigAutoField(primary_key=True, serialize=False)),
                ('pagina', models.IntegerField(default=1, help_text='Número da página do documento original')),
                ('conteudo', models.TextField(help_text='Texto do chunk em Markdown')),
                ('embedding', VectorField(blank=True, dimensions=768, help_text='Embedding vetorial do chunk com 768 dimensões', null=True)),
                ('id_documento', models.ForeignKey(db_column='id_documento', on_delete=django.db.models.deletion.CASCADE, related_name='chunks', to='api.documento')),
            ],
            options={
                'verbose_name': 'Documento Chunk',
                'verbose_name_plural': 'Documentos Chunk',
                'db_table': 'documento_chunk',
            },
        ),
        migrations.AddIndex(
            model_name='documentochunk',
            index=models.Index(fields=['id_documento', 'pagina'], name='idx_doc_chunk_pag'),
        ),
    ]

    if HAS_PGVECTOR and HnswIndex is not None:
        operations.append(
            migrations.AddIndex(
                model_name='documentochunk',
                index=HnswIndex(fields=['embedding'], name='idx_doc_chunk_emb_hnsw', opclasses=['vector_cosine_ops']),
            )
        )
