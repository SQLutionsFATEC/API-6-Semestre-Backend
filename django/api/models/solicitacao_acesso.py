from django.db import models

from .documento import Documento


class SolicitacaoAcesso(models.Model):
    id = models.BigAutoField(primary_key=True)
    documento = models.ForeignKey(
        Documento,
        on_delete=models.CASCADE,
        related_name='solicitacoes_acesso',
        db_column='documento_id',
    )
    usuario_id = models.CharField(max_length=255)
    data_solicitacao = models.DateTimeField(auto_now_add=True)
    approved = models.BooleanField(default=False)

    class Meta:
        db_table = 'solicitacao_acesso'
        ordering = ['-data_solicitacao', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['documento', 'usuario_id'],
                name='solicitacao_acesso_documento_usuario_uniq',
            ),
        ]

    def __str__(self):
        return f'Solicitação #{self.id} - documento #{self.documento_id}'
