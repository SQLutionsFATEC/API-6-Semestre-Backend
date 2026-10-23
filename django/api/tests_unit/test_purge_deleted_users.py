"""Testes do comando purge_deleted_users (anonimização pós-restauração)."""

from io import StringIO

import pytest
import requests
from django.core.management import call_command
from django.core.management.base import CommandError

from api.management.commands import purge_deleted_users as comando
from api.services import keycloak_admin
from api.services.delecao_usuario import (
    confirmar_usuario_deletado,
    hash_id_usuario,
    registrar_usuario_deletado,
)
from api.services.keycloak_admin import KeycloakAdminException


def _registrar_confirmado(id_usuario):
    registrar_usuario_deletado(id_usuario)
    confirmar_usuario_deletado(id_usuario)


def _representacao_anonimizada(usuario):
    sufixo = hash_id_usuario(usuario['id'])
    return dict(
        usuario,
        username=f'anonimizado-{sufixo}',
        email=f'{sufixo}@invalid.local',
        firstName='Anonimizado',
        lastName='',
        enabled=False,
        attributes={},
        requiredActions=[],
    )


def _mock_listar(monkeypatch, usuarios):
    """Faz listar_usuarios paginar sobre a lista mutável informada."""
    chamadas = []

    def listar(inicio=0, maximo=100):
        chamadas.append((inicio, maximo))
        return [dict(usuario) for usuario in usuarios[inicio:inicio + maximo]]

    monkeypatch.setattr(keycloak_admin, 'listar_usuarios', listar)
    return chamadas


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_purga_anonimiza_somente_usuarios_tombstoned_e_verifica(monkeypatch):
    _registrar_confirmado('u-anonimizado')
    usuarios = [{'id': 'u-anonimizado'}, {'id': 'u-vivo'}]
    _mock_listar(monkeypatch, usuarios)
    anonimizados = []

    def anonimizar(id_usuario, sufixo):
        anonimizados.append((id_usuario, sufixo))
        for indice, usuario in enumerate(usuarios):
            if usuario['id'] == id_usuario:
                usuarios[indice] = _representacao_anonimizada(usuario)

    monkeypatch.setattr(keycloak_admin, 'anonimizar_usuario', anonimizar)
    saida = StringIO()

    call_command('purge_deleted_users', '--verificar', stdout=saida)

    assert anonimizados == [
        ('u-anonimizado', hash_id_usuario('u-anonimizado'))
    ]
    assert usuarios[0]['enabled'] is False
    assert usuarios[1] == {'id': 'u-vivo'}
    assert 'nenhum usuário tombstoned permanece com dados pessoais' in saida.getvalue()


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_dry_run_nao_anonimiza(monkeypatch):
    _registrar_confirmado('u-anonimizado')
    _mock_listar(monkeypatch, [{'id': 'u-anonimizado'}])
    anonimizados = []
    monkeypatch.setattr(
        keycloak_admin,
        'anonimizar_usuario',
        lambda id_usuario, sufixo: anonimizados.append(id_usuario),
    )
    saida = StringIO()

    call_command('purge_deleted_users', '--dry-run', stdout=saida)

    assert anonimizados == []
    assert 'seriam anonimizados' in saida.getvalue()


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_verificacao_falha_quando_usuario_ainda_tem_dados_pessoais(monkeypatch):
    _registrar_confirmado('u-anonimizado')
    _mock_listar(monkeypatch, [{'id': 'u-anonimizado'}])
    # Simula uma anonimização que não surtiu efeito no Keycloak.
    monkeypatch.setattr(
        keycloak_admin, 'anonimizar_usuario', lambda id_usuario, sufixo: None
    )

    with pytest.raises(CommandError, match='ainda possuem dados pessoais'):
        call_command('purge_deleted_users', '--verificar', stdout=StringIO())


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_404_na_anonimizacao_e_idempotente(monkeypatch):
    _registrar_confirmado('u-anonimizado')
    _mock_listar(monkeypatch, [{'id': 'u-anonimizado'}])

    def anonimizar_ja_ausente(id_usuario, sufixo):
        raise KeycloakAdminException('Não encontrado.', codigo_status=404)

    monkeypatch.setattr(keycloak_admin, 'anonimizar_usuario', anonimizar_ja_ausente)
    saida = StringIO()

    call_command('purge_deleted_users', stdout=saida)

    assert '0 usuário(s) anonimizado(s)' in saida.getvalue()


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_aguardar_keycloak_ficar_disponivel(monkeypatch):
    _registrar_confirmado('u-anonimizado')
    usuarios = [{'id': 'u-anonimizado'}]
    tentativas = {'quantidade': 0}

    def listar(inicio=0, maximo=100):
        tentativas['quantidade'] += 1
        if tentativas['quantidade'] == 1:
            raise requests.ConnectionError('Keycloak iniciando')
        return [dict(usuario) for usuario in usuarios[inicio:inicio + maximo]]

    monkeypatch.setattr(keycloak_admin, 'listar_usuarios', listar)
    monkeypatch.setattr(comando.time, 'sleep', lambda segundos: None)
    monkeypatch.setattr(
        keycloak_admin, 'anonimizar_usuario', lambda id_usuario, sufixo: None
    )

    call_command('purge_deleted_users', '--aguardar', '5', stdout=StringIO())

    # 1 tentativa falha + 1 página com o usuário + 1 página vazia.
    assert tentativas['quantidade'] == 3


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_erro_nao_temporario_encerra_com_falha(monkeypatch):
    _registrar_confirmado('u-anonimizado')

    def listar(inicio=0, maximo=100):
        raise KeycloakAdminException('Realm inválido.', codigo_status=404)

    monkeypatch.setattr(keycloak_admin, 'listar_usuarios', listar)

    with pytest.raises(CommandError, match='Falha ao consultar o Keycloak'):
        call_command('purge_deleted_users', '--aguardar', '5', stdout=StringIO())


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_tombstone_pendente_nao_e_anonimizado(monkeypatch):
    registrar_usuario_deletado('u-pendente')

    def listar(**kwargs):
        raise AssertionError('Não deveria consultar o Keycloak.')

    monkeypatch.setattr(keycloak_admin, 'listar_usuarios', listar)
    saida = StringIO()

    call_command('purge_deleted_users', '--verificar', stdout=saida)

    assert 'nada a anonimizar' in saida.getvalue()


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_purga_ignora_pendente_mesmo_com_outro_confirmado(monkeypatch):
    _registrar_confirmado('u-anonimizado')
    registrar_usuario_deletado('u-pendente')
    usuarios = [{'id': 'u-anonimizado'}, {'id': 'u-pendente'}]
    _mock_listar(monkeypatch, usuarios)
    anonimizados = []

    def anonimizar(id_usuario, sufixo):
        anonimizados.append(id_usuario)
        for indice, usuario in enumerate(usuarios):
            if usuario['id'] == id_usuario:
                usuarios[indice] = _representacao_anonimizada(usuario)

    monkeypatch.setattr(keycloak_admin, 'anonimizar_usuario', anonimizar)

    call_command('purge_deleted_users', stdout=StringIO())

    assert anonimizados == ['u-anonimizado']
    assert usuarios[1] == {'id': 'u-pendente'}


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_sem_tombstones_nao_consulta_keycloak(monkeypatch):
    def listar(**kwargs):
        raise AssertionError('Não deveria consultar o Keycloak.')

    monkeypatch.setattr(keycloak_admin, 'listar_usuarios', listar)
    saida = StringIO()

    call_command('purge_deleted_users', '--verificar', stdout=saida)

    assert 'nada a anonimizar' in saida.getvalue()
