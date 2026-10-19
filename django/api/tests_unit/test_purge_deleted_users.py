"""Testes do comando purge_deleted_users (prova pós-restauração de backup)."""

from io import StringIO

import pytest
import requests
from django.core.management import call_command
from django.core.management.base import CommandError

from api.management.commands import purge_deleted_users as comando
from api.services import keycloak_admin
from api.services.delecao_usuario import registrar_usuario_deletado
from api.services.keycloak_admin import KeycloakAdminException


def _mock_listar(monkeypatch, usuarios):
    """Faz listar_usuarios paginar sobre a lista mutável informada."""
    chamadas = []

    def listar(inicio=0, maximo=100):
        chamadas.append((inicio, maximo))
        return [dict(usuario) for usuario in usuarios[inicio:inicio + maximo]]

    monkeypatch.setattr(keycloak_admin, 'listar_usuarios', listar)
    return chamadas


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_purga_remove_somente_usuarios_tombstoned_e_verifica(monkeypatch):
    registrar_usuario_deletado('u-deletado')
    usuarios = [{'id': 'u-deletado'}, {'id': 'u-vivo'}]
    _mock_listar(monkeypatch, usuarios)
    removidos = []

    def deletar(id_usuario):
        removidos.append(id_usuario)
        usuarios[:] = [u for u in usuarios if u['id'] != id_usuario]

    monkeypatch.setattr(keycloak_admin, 'deletar_usuario', deletar)
    saida = StringIO()

    call_command('purge_deleted_users', '--verificar', stdout=saida)

    assert removidos == ['u-deletado']
    assert 'nenhum usuário deletado foi restaurado' in saida.getvalue()
    assert usuarios == [{'id': 'u-vivo'}]


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_dry_run_nao_deleta(monkeypatch):
    registrar_usuario_deletado('u-deletado')
    _mock_listar(monkeypatch, [{'id': 'u-deletado'}])
    removidos = []
    monkeypatch.setattr(
        keycloak_admin, 'deletar_usuario', lambda id_usuario: removidos.append(id_usuario)
    )
    saida = StringIO()

    call_command('purge_deleted_users', '--dry-run', stdout=saida)

    assert removidos == []
    assert 'seriam removidos' in saida.getvalue()


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_verificacao_falha_quando_usuario_restaurado_permanece(monkeypatch):
    registrar_usuario_deletado('u-deletado')
    _mock_listar(monkeypatch, [{'id': 'u-deletado'}])
    # Simula uma deleção que não surtiu efeito no Keycloak.
    monkeypatch.setattr(keycloak_admin, 'deletar_usuario', lambda id_usuario: None)

    with pytest.raises(CommandError, match='VERIFICAÇÃO FALHOU'):
        call_command('purge_deleted_users', '--verificar', stdout=StringIO())


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_404_na_delecao_e_idempotente(monkeypatch):
    registrar_usuario_deletado('u-deletado')
    _mock_listar(monkeypatch, [{'id': 'u-deletado'}])

    def deletar_ja_ausente(id_usuario):
        raise KeycloakAdminException('Não encontrado.', codigo_status=404)

    monkeypatch.setattr(keycloak_admin, 'deletar_usuario', deletar_ja_ausente)
    saida = StringIO()

    call_command('purge_deleted_users', stdout=saida)

    assert '0 usuário(s) deletado(s) removido(s)' in saida.getvalue()


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_aguardar_keycloak_ficar_disponivel(monkeypatch):
    registrar_usuario_deletado('u-deletado')
    usuarios = [{'id': 'u-deletado'}]
    tentativas = {'quantidade': 0}

    def listar(inicio=0, maximo=100):
        tentativas['quantidade'] += 1
        if tentativas['quantidade'] == 1:
            raise requests.ConnectionError('Keycloak iniciando')
        return [dict(usuario) for usuario in usuarios[inicio:inicio + maximo]]

    monkeypatch.setattr(keycloak_admin, 'listar_usuarios', listar)
    monkeypatch.setattr(comando.time, 'sleep', lambda segundos: None)
    monkeypatch.setattr(keycloak_admin, 'deletar_usuario', lambda id_usuario: None)

    call_command('purge_deleted_users', '--aguardar', '5', stdout=StringIO())

    # 1 tentativa falha + 1 página com o usuário + 1 página vazia.
    assert tentativas['quantidade'] == 3


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_erro_nao_temporario_encerra_com_falha(monkeypatch):
    registrar_usuario_deletado('u-deletado')

    def listar(inicio=0, maximo=100):
        raise KeycloakAdminException('Realm inválido.', codigo_status=404)

    monkeypatch.setattr(keycloak_admin, 'listar_usuarios', listar)

    with pytest.raises(CommandError, match='Falha ao consultar o Keycloak'):
        call_command('purge_deleted_users', '--aguardar', '5', stdout=StringIO())


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_sem_tombstones_nao_consulta_keycloak(monkeypatch):
    def listar(**kwargs):
        raise AssertionError('Não deveria consultar o Keycloak.')

    monkeypatch.setattr(keycloak_admin, 'listar_usuarios', listar)
    saida = StringIO()

    call_command('purge_deleted_users', '--verificar', stdout=saida)

    assert 'Nenhum usuário deletado registrado' in saida.getvalue()
