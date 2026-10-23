from django.db import models


class UsuarioDeletado(models.Model):
    """Prova anonimizada de que um usuário foi deletado.

    O id do Keycloak (UUID) NÃO é armazenado: guarda-se apenas seu hash
    SHA-256. Assim o banco de tombstones não contém dado pessoal diretamente
    identificável, mas ainda permite reconhecer o mesmo usuário em um backup
    restaurado do Keycloak e removê-lo novamente.

    O registro nasce pendente e só é confirmado depois que o Keycloak
    confirma a remoção. Apenas tombstones confirmados são usados pelo purge.

    Este model vive exclusivamente no banco 'tombstones' (ver
    api.db_routers.TombstoneRouter).
    """

    ORIGEM_AUTOATENDIMENTO = 'autoatendimento'
    ORIGEM_OPERADOR = 'operador'
    ORIGENS = (
        (ORIGEM_AUTOATENDIMENTO, 'Autoatendimento'),
        (ORIGEM_OPERADOR, 'Operador'),
    )

    id_usuario_hash = models.CharField(
        max_length=64,
        primary_key=True,
        help_text='SHA-256 do id do usuário no Keycloak (nunca o id em claro).',
    )
    deletado_em = models.DateTimeField(auto_now_add=True)
    confirmado_em = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text='Quando a exclusão no Keycloak foi confirmada; nulo enquanto pendente.',
    )
    origem = models.CharField(max_length=20, choices=ORIGENS, default='api')

    class Meta:
        db_table = 'usuario_deletado'
        verbose_name = 'Usuário deletado'
        verbose_name_plural = 'Usuários deletados'

    def __str__(self):
        return self.id_usuario_hash
