"""Registro anonimizado de usuários deletados (direito ao esquecimento).

O Keycloak é a fonte da verdade da identidade, mas um backup restaurado pode
trazer de volta um usuário já deletado. Para impedir isso, cada exclusão grava
um tombstone em um banco independente (alias 'tombstones'): apenas o hash
SHA-256 do id do Keycloak, nunca o id, nome ou e-mail.

O hash é determinístico, então o processo de restauração consegue reconhecer o
mesmo usuário em um backup e anonimizá-lo novamente. Como o id do Keycloak é
um UUID (alta entropia), o hash não é reversível na prática e o banco de
tombstones não guarda dado pessoal diretamente identificável.

O tombstone nasce pendente e só é confirmado depois que o Keycloak conclui a
anonimização. Uma falha no Keycloak deixa o registro pendente, que não é usado
pelo purge, e a operação pode ser tentada de novo.
"""

import hashlib
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from api.models import UsuarioDeletado
from api.services import keycloak_admin

logger = logging.getLogger(__name__)

TOMBSTONE_DB = 'tombstones'


def hash_id_usuario(id_usuario):
    """Retorna o SHA-256 hexadecimal do id do usuário no Keycloak."""
    if not id_usuario:
        raise ValueError('Id de usuário ausente para registrar o tombstone.')
    return hashlib.sha256(str(id_usuario).encode('utf-8')).hexdigest()


def registrar_usuario_deletado(id_usuario, origem=UsuarioDeletado.ORIGEM_AUTOATENDIMENTO):
    """Grava (de forma idempotente) um tombstone pendente para o usuário.

    Retorna ``(registro, criado)``. Chamadas repetidas para o mesmo id não
    duplicam o registro e preservam a origem do primeiro registro. A exclusão
    só passa a valer para o purge depois de ``confirmar_usuario_deletado``.
    """
    id_hash = hash_id_usuario(id_usuario)
    registro, criado = UsuarioDeletado.objects.using(TOMBSTONE_DB).get_or_create(
        id_usuario_hash=id_hash,
        defaults={'origem': origem},
    )
    return registro, criado


def confirmar_usuario_deletado(id_usuario):
    """Confirma um tombstone pendente após a anonimização no Keycloak.

    Retorna True se havia um tombstone pendente para o id e ele foi
    confirmado; False se o registro não existia ou já estava confirmado.
    """
    id_hash = hash_id_usuario(id_usuario)
    atualizados = (
        UsuarioDeletado.objects.using(TOMBSTONE_DB)
        .filter(id_usuario_hash=id_hash, confirmado_em__isnull=True)
        .update(confirmado_em=timezone.now())
    )
    return atualizados > 0


def listar_hashes_usuarios_deletados():
    """Lista os hashes dos usuários deletados já confirmados."""
    return list(
        UsuarioDeletado.objects.using(TOMBSTONE_DB)
        .filter(confirmado_em__isnull=False)
        .values_list('id_usuario_hash', flat=True)
    )


def usuario_esta_deletado(id_usuario):
    """Indica se o id informado possui um tombstone confirmado."""
    id_hash = hash_id_usuario(id_usuario)
    return (
        UsuarioDeletado.objects.using(TOMBSTONE_DB)
        .filter(id_usuario_hash=id_hash, confirmado_em__isnull=False)
        .exists()
    )


def anonimizar_usuario(id_usuario, origem=UsuarioDeletado.ORIGEM_AUTOATENDIMENTO):
    """Anonimiza os dados pessoais de um usuário, preservando a prova.

    O fluxo é:
      1. lê o usuário no Keycloak (404 se ele não existir);
      2. grava o tombstone como pendente;
      3. substitui os dados pessoais no Keycloak por valores genéricos,
         desabilita a conta e remove credenciais, roles e grupos;
      4. confirma o tombstone;
      5. envia o e-mail de comprovação da exclusão (LGPD).

    Se o Keycloak falhar, o tombstone permanece pendente e a exceção é
    propagada: a operação pode ser tentada novamente e o purge nunca trata um
    pendente como exclusão concluída. Se a anonimização retornar 404 depois de
    o usuário ter sido lido, outra requisição já o removeu; o tombstone é
    confirmado para que o resultado seja idempotente.

    O e-mail é best-effort: uma falha de SMTP não desfaz a anonimização já
    concluída, apenas é registrada no log.
    """
    usuario = keycloak_admin.obter_usuario(id_usuario)

    registrar_usuario_deletado(id_usuario, origem=origem)
    try:
        keycloak_admin.anonimizar_usuario(
            id_usuario, sufixo=hash_id_usuario(id_usuario)
        )
    except keycloak_admin.KeycloakAdminException as erro:
        if erro.codigo_status != 404:
            raise
        # O usuário sumiu entre a leitura e a anonimização: o objetivo foi
        # cumprido por outra requisição concorrente.
    confirmar_usuario_deletado(id_usuario)
    enviar_email_comprovacao(usuario)

    return usuario


def enviar_email_comprovacao(usuario):
    """Envia ao ex-titular a comprovação de que a conta foi anonimizada.

    Retorna True se a mensagem foi entregue ao backend de e-mail e False se
    não havia e-mail ou se o envio falhou. Nunca levanta exceção: a
    anonimização já ocorreu e não deve ser revertida por causa do e-mail.
    """
    email = (usuario or {}).get('email') or ''
    if not email or email.endswith('@invalid.local'):
        logger.warning(
            'Anonimização concluída sem e-mail de comprovação: usuário sem e-mail original.'
        )
        return False

    nome = (usuario or {}).get('firstName') or ''
    momento = timezone.localtime().strftime('%d/%m/%Y às %H:%M')
    assunto = 'Sua conta foi anonimizada'
    mensagem = (
        f'Olá{(", " + nome) if nome else ""},\n\n'
        'Registramos a anonimização da sua conta em '
        f'{momento}.\n\n'
        'Seus dados pessoais — nome, e-mail, credenciais, roles e atributos — '
        'foram removidos do sistema, e a conta foi desabilitada. O registro '
        'interno mantido para impedir que esses dados reapareçam em uma '
        'restauração de backup contém apenas um hash irreversível.\n\n'
        'Esta mensagem serve como comprovação da sua solicitação de exclusão. '
        'Se você não solicitou esta exclusão, entre em contato imediatamente '
        'com o suporte.\n\n'
        'Atenciosamente,\nEquipe SQLutions'
    )

    try:
        send_mail(
            assunto,
            mensagem,
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception(
            'Falha ao enviar o e-mail de comprovação de exclusão de usuário.'
        )
        return False
