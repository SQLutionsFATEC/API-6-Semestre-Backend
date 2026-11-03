import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0003_alter_documentochunk_embedding'),
    ]

    operations = [
        migrations.AddField(
            model_name='documento',
            name='data_criacao',
            field=models.DateTimeField(
                auto_now_add=True,
                default=django.utils.timezone.now,
                help_text='Criado automaticamente no primeiro salvamento',
            ),
            preserve_default=False,
        ),
    ]