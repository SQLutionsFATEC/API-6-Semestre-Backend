from django.db import models


class Termo(models.Model):
    """
    Modelo para armazenamento de Termos de Consentimento versionados.
    O termo em vigor é sempre o de maior id_termo.
    """
    id_termo = models.BigAutoField(primary_key=True)
    data_criacao = models.DateField(
        auto_now_add=True,
        help_text="Criado automaticamente no primeiro salvamento"
    )

    clausulas = models.ManyToManyField(
        'Clausula',
        through='ClausulaTermo',
        related_name='termos'
    )

    class Meta:
        db_table = 'termo'
        verbose_name = 'Termo'
        verbose_name_plural = 'Termos'

    def __str__(self):
        return f"Termo #{self.id_termo}"

