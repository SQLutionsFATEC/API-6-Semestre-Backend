"""Testes das rotas DELETE /api/usuarios e DELETE /api/usuarios/{id}."""

import pytest
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from api.authentication.keycloak import KeycloakUser
from api.models import UsuarioDeletado
from api.services import keycloak_admin
from api.services.delecao_usuario import hash_id_usuario, usuario_esta_deletado
from api.services.keycloak_admin import KeycloakAdminException

ID_PROPRIO = 'id-usuario-comum'
ID_ALVO = 'id-usuario-alvo'

CLAIMS_USUARIO = {
    'sub': ID_PROPRIO,
    'preferred_username': 'maria',
    'name': 'Maria Silva',
    'email': 'maria@example.com',
    'realm_access': {'roles': ['basico']},
}

CLAIMS_OPERADOR = {
    'sub': 'id-operador',
    'preferred_username': 'operador',
    'name': 'Operador',
    'email': 'operador@example.com',
    'realm_access': {'roles': ['operador']},
}

CLAIMS_ADMIN_SEM_OPERADOR = {
    'sub': 'id-admin',
    'preferred_username': 'admin',
    'name': 'Admin',
    'email': 'admin@example.com',
    'realm_access': {'roles': ['admin']},
}

USUARIO_ALVO = {
    'id': ID_ALVO,
    'username': 'alvo@example.com',
    'firstName': 'Alvo',
    'lastName': 'Silva',
    'email': 'alvo@example.com',
    'enabled': True,
}


@pytest.fixture(autouse=True)
def email_em_memoria(settings):
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    mail.outbox.clear()
    yield
    mail.outbox.clear()


@pytest.fixture
def keycloak_fake(monkeypatch):
    """Substitui leitura/anonimização do Keycloak por fakes controláveis."""
    chamadas = {'obter': [], 'anonimizar': []}
    estado = {
        'usuario': dict(USUARIO_ALVO),
        'erro_obter': None,
        'erro_anonimizar': None,
    }

    def obter(id_usuario):
        chamadas['obter'].append(id_usuario)
        if estado['erro_obter'] is not None:
            raise estado['erro_obter']
        return dict(estado['usuario'], id=id_usuario)

    def anonimizar(id_usuario, sufixo):
        chamadas['anonimizar'].append(id_usuario)
        if estado['erro_anonimizar'] is not None:
            raise estado['erro_anonimizar']

    monkeypatch.setattr(keycloak_admin, 'obter_usuario', obter)
    monkeypatch.setattr(keycloak_admin, 'anonimizar_usuario', anonimizar)
    return chamadas, estado


def _cliente(usuario=None):
    cliente = APIClient()
    if usuario is not None:
        cliente.force_authenticate(user=usuario)
    return cliente


def test_delete_sem_autenticacao_retorna_401():
    cliente = _cliente()

    resposta_propria = cliente.delete(reverse('usuarios'))
    resposta_detalhe = cliente.delete(reverse('usuario-detalhe', args=['qualquer']))

    assert resposta_propria.status_code == status.HTTP_401_UNAUTHORIZED
    assert resposta_detalhe.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_deletar_propria_conta(keycloak_fake):
    chamadas, _ = keycloak_fake
    cliente = _cliente(KeycloakUser(CLAIMS_USUARIO))

    resposta = cliente.delete(reverse('usuarios'))

    assert resposta.status_code == status.HTTP_204_NO_CONTENT
    assert chamadas['anonimizar'] == [ID_PROPRIO]
    assert usuario_esta_deletado(ID_PROPRIO) is True
    registro = UsuarioDeletado.objects.using('tombstones').get(
        id_usuario_hash=hash_id_usuario(ID_PROPRIO)
    )
    assert registro.origem == UsuarioDeletado.ORIGEM_AUTOATENDIMENTO
    assert registro.confirmado_em is not None
    assert len(mail.outbox) == 1


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_deletar_propria_conta_na_rota_sem_barra_final(keycloak_fake):
    cliente = _cliente(KeycloakUser(CLAIMS_USUARIO))

    resposta = cliente.delete('/api/usuarios')

    assert resposta.status_code == status.HTTP_204_NO_CONTENT
    assert usuario_esta_deletado(ID_PROPRIO) is True


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_deletar_propria_conta_inexistente_retorna_404(keycloak_fake):
    _, estado = keycloak_fake
    estado['erro_obter'] = KeycloakAdminException(
        'Usuário não encontrado.', codigo_status=404
    )
    cliente = _cliente(KeycloakUser(CLAIMS_USUARIO))

    resposta = cliente.delete(reverse('usuarios'))

    assert resposta.status_code == status.HTTP_404_NOT_FOUND
    assert usuario_esta_deletado(ID_PROPRIO) is False


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_deletar_por_id_sem_role_operador_retorna_403(keycloak_fake):
    chamadas, _ = keycloak_fake
    cliente = _cliente(KeycloakUser(CLAIMS_USUARIO))

    resposta = cliente.delete(reverse('usuario-detalhe', args=[ID_ALVO]))

    assert resposta.status_code == status.HTTP_403_FORBIDDEN
    assert resposta.json()['detail'] == (
        'Somente usuários com a role Operador ou Admin podem acessar este recurso.'
    )
    assert chamadas['anonimizar'] == []
    assert usuario_esta_deletado(ID_ALVO) is False


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_admin_sem_role_operador_pode_deletar_por_id(keycloak_fake):
    chamadas, _ = keycloak_fake
    cliente = _cliente(KeycloakUser(CLAIMS_ADMIN_SEM_OPERADOR))

    resposta = cliente.delete(reverse('usuario-detalhe', args=[ID_ALVO]))

    assert resposta.status_code == status.HTTP_204_NO_CONTENT
    assert chamadas['anonimizar'] == [ID_ALVO]
    assert usuario_esta_deletado(ID_ALVO) is True


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_operador_deleta_usuario_por_id(keycloak_fake):
    chamadas, _ = keycloak_fake
    cliente = _cliente(KeycloakUser(CLAIMS_OPERADOR))

    resposta = cliente.delete(reverse('usuario-detalhe', args=[ID_ALVO]))

    assert resposta.status_code == status.HTTP_204_NO_CONTENT
    assert chamadas['anonimizar'] == [ID_ALVO]
    registro = UsuarioDeletado.objects.using('tombstones').get(
        id_usuario_hash=hash_id_usuario(ID_ALVO)
    )
    assert registro.origem == UsuarioDeletado.ORIGEM_OPERADOR
    assert registro.confirmado_em is not None
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ['alvo@example.com']


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_operador_deleta_usuario_por_id_na_rota_sem_barra_final(keycloak_fake):
    cliente = _cliente(KeycloakUser(CLAIMS_OPERADOR))

    resposta = cliente.delete(f'/api/usuarios/{ID_ALVO}')

    assert resposta.status_code == status.HTTP_204_NO_CONTENT
    assert usuario_esta_deletado(ID_ALVO) is True


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_operador_deleta_usuario_inexistente_retorna_404(keycloak_fake):
    _, estado = keycloak_fake
    estado['erro_obter'] = KeycloakAdminException(
        'Usuário não encontrado.', codigo_status=404
    )
    cliente = _cliente(KeycloakUser(CLAIMS_OPERADOR))

    resposta = cliente.delete(reverse('usuario-detalhe', args=[ID_ALVO]))

    assert resposta.status_code == status.HTTP_404_NOT_FOUND
    assert usuario_esta_deletado(ID_ALVO) is False


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_falha_no_keycloak_retorna_502_e_mantem_tombstone_pendente(keycloak_fake):
    _, estado = keycloak_fake
    estado['erro_anonimizar'] = KeycloakAdminException(
        'Falha no Keycloak.', codigo_status=500
    )
    cliente = _cliente(KeycloakUser(CLAIMS_OPERADOR))

    resposta = cliente.delete(reverse('usuario-detalhe', args=[ID_ALVO]))

    assert resposta.status_code == status.HTTP_502_BAD_GATEWAY
    assert usuario_esta_deletado(ID_ALVO) is False
    registro = UsuarioDeletado.objects.using('tombstones').get(
        id_usuario_hash=hash_id_usuario(ID_ALVO)
    )
    assert registro.confirmado_em is None
