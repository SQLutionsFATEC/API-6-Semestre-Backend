from django.db import migrations

import api.models.documento_chunk


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0007_usuariodeletado_confirmado_em'),
    ]

    operations = [
        migrations.RunSQL(
            sql='UPDATE documento_chunk SET embedding = NULL;',
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AlterField(
            model_name='documentochunk',
            name='embedding',
            field=api.models.documento_chunk.VectorField(
                blank=True,
                dimensions=256,
                help_text='Embedding vetorial do chunk com 256 dimensões',
                null=True,
            ),
        ),
    ]
