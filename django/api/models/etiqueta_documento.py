from django.db import models


class EtiquetaDocumento(models.Model):
    """
    Tabela intermediária (Etiqueta_Documento) para relacionar Documentos e Etiquetas (N:N).
    """
    id_documento = models.ForeignKey(
        'Documento',
        on_delete=models.CASCADE,
        db_column='id_documento',
        related_name='etiquetas_relacao'
    )
    id_etiqueta = models.ForeignKey(
        'Etiqueta',
        on_delete=models.CASCADE,
        db_column='id_etiqueta',
        related_name='documentos_relacao'
    )

    class Meta:
        db_table = 'etiqueta_documento'
        unique_together = (('id_documento', 'id_etiqueta'),)
        verbose_name = 'Etiqueta do Documento'
        verbose_name_plural = 'Etiquetas do Documento'

    def __str__(self):
        return f"Documento #{self.id_documento_id} - Etiqueta #{self.id_etiqueta_id}"
