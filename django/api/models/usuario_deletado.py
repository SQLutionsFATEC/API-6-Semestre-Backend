from django.db import models


class UsuarioDeletado(models.Model):
    """Prova anonimizada de que um usuário foi deletado.

    O id do Keycloak (UUID) NÃO é armazenado: guarda-se apenas seu hash
    SHA-256. Assim o banco de tombstones não contém dado pessoal diretamente
    identificável, mas ainda permite reconhecer o mesmo usuário em um backup
    restaurado do Keycloak e removê-lo novamente.

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
    origem = models.CharField(max_length=20, choices=ORIGENS, default='api')

    class Meta:
        db_table = 'usuario_deletado'
        verbose_name = 'Usuário deletado'
        verbose_name_plural = 'Usuários deletados'

    def __str__(self):
        return self.id_usuario_hash
