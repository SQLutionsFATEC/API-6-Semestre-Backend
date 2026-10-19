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

from api.models import UsuarioDeletado

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
