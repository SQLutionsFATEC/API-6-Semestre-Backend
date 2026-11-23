from django.db import models


class Consentimento(models.Model):
    """
    Histórico de consentimento do usuário (Append-Only).

    Nenhum registro é atualizado ou excluído. O estado atual (aceito/negado) é
    sempre determinado pelo registro mais recente (timestamp_consentimento) para
    cada par (id_usuario, id_clausula).
    """
    id_consentimento = models.BigAutoField(primary_key=True)
    timestamp_consentimento = models.DateTimeField(
        auto_now_add=True,
        help_text="Momento em que a ação de consentimento/revogação ocorreu"
    )
    id_clausula = models.ForeignKey(
        'Clausula',
        on_delete=models.PROTECT,
        db_column='id_clausula',
        related_name='consentimentos'
    )
    id_usuario = models.CharField(
        max_length=255,
        help_text="UUID do usuário no Keycloak (não há modelagem de usuário no Django)"
    )
    acordo = models.BooleanField(
        help_text="True para consentimento, False para revogação"
    )

    class Meta:
        db_table = 'consentimento'
        verbose_name = 'Consentimento'
        verbose_name_plural = 'Consentimentos'
        indexes = [
            # Otimiza a busca do último estado de consentimento do usuário
            models.Index(fields=['id_usuario', 'id_clausula', '-timestamp_consentimento']),
        ]

    def __str__(self):
        status = "Aceito" if self.acordo else "Negado"
        return f"User {self.id_usuario} - Cláusula #{self.id_clausula_id} - {status}"