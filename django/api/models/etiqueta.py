from django.db import models


class Etiqueta(models.Model):
    """
    Modelo para armazenamento de Etiquetas.
    Representa as tags/etiquetas aplicadas aos documentos.
    """
    id_etiqueta = models.BigAutoField(primary_key=True)
    nome = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = 'etiqueta'
        verbose_name = 'Etiqueta'
        verbose_name_plural = 'Etiquetas'

    def __str__(self):
        return self.nome
