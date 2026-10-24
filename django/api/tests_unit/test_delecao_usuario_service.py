"""Testes do registro anonimizado de usuários deletados."""

import hashlib

import pytest

from api.models import UsuarioDeletado
from api.services.delecao_usuario import (
    confirmar_usuario_deletado,
    hash_id_usuario,
    listar_hashes_usuarios_deletados,
    registrar_usuario_deletado,
    usuario_esta_deletado,
)

ID_USUARIO = '9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d'


def test_hash_e_deterministico_e_tem_64_caracteres():
    primeiro = hash_id_usuario(ID_USUARIO)
    segundo = hash_id_usuario(ID_USUARIO)

    assert primeiro == segundo
    assert len(primeiro) == 64
    assert primeiro == hashlib.sha256(ID_USUARIO.encode('utf-8')).hexdigest()


def test_hashes_de_ids_diferentes_sao_diferentes():
    assert hash_id_usuario('usuario-a') != hash_id_usuario('usuario-b')


def test_hash_rejeita_id_vazio():
    with pytest.raises(ValueError):
        hash_id_usuario('')


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_registrar_grava_somente_o_hash_no_banco_de_tombstones():
    registro, criado = registrar_usuario_deletado(
        ID_USUARIO, origem=UsuarioDeletado.ORIGEM_AUTOATENDIMENTO
    )

    assert criado is True
    assert registro.id_usuario_hash == hash_id_usuario(ID_USUARIO)
    assert registro.id_usuario_hash != ID_USUARIO
    assert registro.origem == UsuarioDeletado.ORIGEM_AUTOATENDIMENTO
    assert registro.confirmado_em is None

    # O id em claro não é persistido em nenhum campo.
    assert UsuarioDeletado.objects.using('tombstones').count() == 1
    assert (
        UsuarioDeletado.objects.using('tombstones')
        .filter(id_usuario_hash=ID_USUARIO)
        .exists()
        is False
    )


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_registrar_e_idempotente_e_preserva_origem():
    primeiro, criado_primeiro = registrar_usuario_deletado(
        ID_USUARIO, origem=UsuarioDeletado.ORIGEM_OPERADOR
    )
    segundo, criado_segundo = registrar_usuario_deletado(
        ID_USUARIO, origem=UsuarioDeletado.ORIGEM_AUTOATENDIMENTO
    )

    assert criado_primeiro is True
    assert criado_segundo is False
    assert primeiro.id_usuario_hash == segundo.id_usuario_hash
    assert segundo.origem == UsuarioDeletado.ORIGEM_OPERADOR
    assert UsuarioDeletado.objects.using('tombstones').count() == 1


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_registrar_pendente_nao_conta_como_deletado():
    assert usuario_esta_deletado(ID_USUARIO) is False

    registrar_usuario_deletado(ID_USUARIO)

    assert usuario_esta_deletado(ID_USUARIO) is False
    assert listar_hashes_usuarios_deletados() == []


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_confirmar_usuario_deletado_pendente():
    registrar_usuario_deletado(ID_USUARIO)

    assert confirmar_usuario_deletado(ID_USUARIO) is True
    assert usuario_esta_deletado(ID_USUARIO) is True
    assert hash_id_usuario(ID_USUARIO) in listar_hashes_usuarios_deletados()
    assert confirmar_usuario_deletado(ID_USUARIO) is False


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_confirmar_sem_registro_nao_cria_tombstone():
    assert confirmar_usuario_deletado(ID_USUARIO) is False
    assert UsuarioDeletado.objects.using('tombstones').count() == 0


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_listar_hashes_retorna_somente_confirmados():
    registrar_usuario_deletado('usuario-a')
    registrar_usuario_deletado('usuario-b')
    confirmar_usuario_deletado('usuario-b')

    hashes = listar_hashes_usuarios_deletados()

    assert hashes == [hash_id_usuario('usuario-b')]


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_usuario_esta_deletado_exige_confirmacao():
    registrar_usuario_deletado('usuario-a')
    confirmar_usuario_deletado('usuario-a')
    registrar_usuario_deletado('usuario-b')

    assert usuario_esta_deletado('usuario-a') is True
    assert usuario_esta_deletado('usuario-b') is False
