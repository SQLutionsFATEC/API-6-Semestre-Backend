"""Registro anonimizado de usuários deletados (direito ao esquecimento).

O Keycloak é a fonte da verdade da identidade, mas um backup restaurado pode
trazer de volta um usuário já deletado. Para impedir isso, cada exclusão grava
um tombstone em um banco independente (alias 'tombstones'): apenas o hash
SHA-256 do id do Keycloak, nunca o id, nome ou e-mail.

O hash é determinístico, então o processo de restauração consegue reconhecer o
mesmo usuário em um backup e removê-lo novamente. Como o id do Keycloak é um
UUID (alta entropia), o hash não é reversível na prática e o banco de
tombstones não guarda dado pessoal diretamente identificável.
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
    """Grava (de forma idempotente) o tombstone de um usuário deletado.

    Retorna ``(registro, criado)``. Chamadas repetidas para o mesmo id não
    duplicam o registro e preservam a origem do primeiro registro.
    """
    id_hash = hash_id_usuario(id_usuario)
    registro, criado = UsuarioDeletado.objects.using(TOMBSTONE_DB).get_or_create(
        id_usuario_hash=id_hash,
        defaults={'origem': origem},
    )
    return registro, criado


def listar_hashes_usuarios_deletados():
    """Lista os hashes de todos os usuários deletados registrados."""
    return list(
        UsuarioDeletado.objects.using(TOMBSTONE_DB).values_list(
            'id_usuario_hash', flat=True
        )
    )


def usuario_esta_deletado(id_usuario):
    """Indica se o id informado já possui um tombstone."""
    id_hash = hash_id_usuario(id_usuario)
    return (
        UsuarioDeletado.objects.using(TOMBSTONE_DB)
        .filter(id_usuario_hash=id_hash)
        .exists()
    )


def deletar_usuario(id_usuario, origem=UsuarioDeletado.ORIGEM_AUTOATENDIMENTO):
    """Deleta fisicamente um usuário, preservando a prova da exclusão.

    Ordem deliberada:
      1. lê o usuário no Keycloak (404 se ele não existir);
      2. grava o tombstone ANTES de deletar — se o Keycloak falhar depois, o
         hash permanece e o usuário não ressuscita em uma restauração;
      3. deleta o usuário do Keycloak (remoção física de nome, e-mail, senha,
         roles e demais dados pessoais);
      4. envia o e-mail de comprovação da exclusão (LGPD).

    O e-mail é best-effort: uma falha de SMTP não desfaz a exclusão já
    concluída, apenas é registrada no log.
    """
    usuario = keycloak_admin.obter_usuario(id_usuario)

    registrar_usuario_deletado(id_usuario, origem=origem)
    keycloak_admin.deletar_usuario(id_usuario)
    enviar_email_comprovacao(usuario)

    return usuario


def enviar_email_comprovacao(usuario):
    """Envia ao ex-titular a comprovação de que a conta foi excluída.

    Retorna True se a mensagem foi entregue ao backend de e-mail e False se
    não havia e-mail ou se o envio falhou. Nunca levanta exceção: a exclusão
    física já ocorreu e não deve ser revertida por causa do e-mail.
    """
    email = (usuario or {}).get('email') or ''
    if not email:
        logger.warning(
            'Exclusão concluída sem e-mail de comprovação: usuário sem e-mail cadastrado.'
        )
        return False

    nome = (usuario or {}).get('firstName') or ''
    momento = timezone.localtime().strftime('%d/%m/%Y às %H:%M')
    assunto = 'Sua conta foi excluída permanentemente'
    mensagem = (
        f'Olá{(", " + nome) if nome else ""},\n\n'
        'Registramos a exclusão permanente da sua conta em '
        f'{momento}.\n\n'
        'Todos os dados pessoais associados à conta foram removidos do sistema. '
        'O registro interno mantido para impedir que a conta reapareça em uma '
        'restauração de backup contém apenas um hash irreversível, sem nome, '
        'e-mail ou qualquer outro dado pessoal.\n\n'
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
