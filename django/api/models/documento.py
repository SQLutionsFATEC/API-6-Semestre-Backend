from django.db import models


class Documento(models.Model):
    """
    Modelo para armazenamento de Documentos.
    Guarda os metadados do documento e a referência ao arquivo físico.
    """
    id_documento = models.BigAutoField(primary_key=True)
    tipo_arquivo = models.CharField(max_length=50, help_text="Ex: pdf, docx, png")
    nome = models.CharField(max_length=255, help_text="Nome do documento")
    setor = models.CharField(max_length=100, help_text="Setor responsável pelo documento")
    data_atualizacao = models.DateTimeField(
        auto_now=True,
        help_text="Atualizado automaticamente no salvamento"
    )
    nivel = models.CharField(max_length=50, help_text="Nível de acesso ou sigilo do documento")
    data = models.FileField(upload_to='documentos/', help_text="Arquivo do documento")

    etiquetas = models.ManyToManyField(
        'Etiqueta',
        through='EtiquetaDocumento',
        related_name='documentos'
    )

    class Meta:
        db_table = 'documento'
        verbose_name = 'Documento'
        verbose_name_plural = 'Documentos'

    def __str__(self):
        return self.nome
