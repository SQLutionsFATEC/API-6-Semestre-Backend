from django.db import models


class ClausulaTermo(models.Model):
    """
    Tabela intermediária (Clausula_Termo) para relacionar Termos e Cláusulas (N:N).
    """
    id_clausula = models.ForeignKey(
        'Clausula',
        on_delete=models.CASCADE,
        db_column='id_clausula',
        related_name='termos_relacao'
    )
    id_termo = models.ForeignKey(
        'Termo',
        on_delete=models.CASCADE,
        db_column='id_termo',
        related_name='clausulas_relacao'
    )

    class Meta:
        db_table = 'clausula_termo'
        unique_together = (('id_clausula', 'id_termo'),)
        verbose_name = 'Cláusula do Termo'
        verbose_name_plural = 'Cláusulas do Termo'

    def __str__(self):
        return f"Termo #{self.id_termo_id} - Cláusula #{self.id_clausula_id}"

