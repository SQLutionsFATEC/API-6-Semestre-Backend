import pytest
from rest_framework import status
from rest_framework.test import APIClient

from api.authentication.keycloak import KeycloakUser
from api.models import Documento, SolicitacaoAcesso


pytestmark = pytest.mark.django_db


CLAIMS_USUARIO = {
    'sub': 'id-usuario-comum',
    'preferred_username': 'maria',
    'realm_access': {'roles': ['basico']},
}

CLAIMS_OPERADOR = {
    'sub': 'id-operador',
    'preferred_username': 'operador',
    'realm_access': {'roles': ['operador']},
}


@pytest.fixture
def documento():
    return Documento.objects.create(
        tipo_arquivo='pdf',
        nome='Documento de teste',
        setor='tecnico',
        nivel='Basico',
        data='documentos/teste.pdf',
    )


def _cliente(usuario=None):
    cliente = APIClient()
    if usuario is not None:
        cliente.force_authenticate(user=usuario)
    return cliente


def _url(documento=None):
    url = '/api/solicitacoes-acesso/'
    if documento is not None:
        return f'{url}{documento}/'
    return url


def test_solicitacao_post_sem_autenticacao_retorna_401(documento):
    resposta = _cliente().post(
        _url(),
        {'documento_id': documento.id_documento},
        format='json',
    )

    assert resposta.status_code == status.HTTP_401_UNAUTHORIZED


def test_solicitacao_post_cria_com_approved_false(documento):
    cliente = _cliente(KeycloakUser(CLAIMS_USUARIO))

    resposta = cliente.post(
        _url(),
        {'documento_id': documento.id_documento},
        format='json',
    )

    assert resposta.status_code == status.HTTP_201_CREATED
    assert resposta.json()['approved'] is False
    assert SolicitacaoAcesso.objects.count() == 1


def test_solicitacao_post_duplicado_retorna_200_sem_criar_outro(documento):
    cliente = _cliente(KeycloakUser(CLAIMS_USUARIO))
    payload = {'documento_id': documento.id_documento}

    primeira = cliente.post(_url(), payload, format='json')
    segunda = cliente.post(_url(), payload, format='json')

    assert primeira.status_code == status.HTTP_201_CREATED
    assert segunda.status_code == status.HTTP_200_OK
    assert segunda.json()['id'] == primeira.json()['id']
    assert SolicitacaoAcesso.objects.count() == 1


def test_solicitacao_post_operador_retorna_403(documento):
    cliente = _cliente(KeycloakUser(CLAIMS_OPERADOR))

    resposta = cliente.post(
        _url(),
        {'documento_id': documento.id_documento},
        format='json',
    )

    assert resposta.status_code == status.HTTP_403_FORBIDDEN


def test_solicitacao_get_exige_operador(documento):
    solicitacao = SolicitacaoAcesso.objects.create(
        documento=documento,
        usuario_id='id-usuario-comum',
    )

    resposta_comum = _cliente(KeycloakUser(CLAIMS_USUARIO)).get(_url())
    resposta_operador = _cliente(KeycloakUser(CLAIMS_OPERADOR)).get(_url())

    assert resposta_comum.status_code == status.HTTP_403_FORBIDDEN
    assert resposta_operador.status_code == status.HTTP_200_OK
    assert resposta_operador.json()['count'] == 1
    assert resposta_operador.json()['results'][0]['id'] == solicitacao.id


def test_solicitacao_patch_aprova_como_operador(documento):
    solicitacao = SolicitacaoAcesso.objects.create(
        documento=documento,
        usuario_id='id-usuario-comum',
    )
    cliente = _cliente(KeycloakUser(CLAIMS_OPERADOR))

    resposta = cliente.patch(
        _url(solicitacao.id),
        {'approved': True},
        format='json',
    )

    assert resposta.status_code == status.HTTP_200_OK
    assert resposta.json()['approved'] is True
    solicitacao.refresh_from_db()
    assert solicitacao.approved is True


def test_solicitacao_patch_usuario_comum_retorna_403(documento):
    solicitacao = SolicitacaoAcesso.objects.create(
        documento=documento,
        usuario_id='id-usuario-comum',
    )

    resposta = _cliente(KeycloakUser(CLAIMS_USUARIO)).patch(
        _url(solicitacao.id),
        {'approved': True},
        format='json',
    )

    assert resposta.status_code == status.HTTP_403_FORBIDDEN


def test_solicitacao_patch_sem_autenticacao_retorna_401():
    resposta = _cliente().patch(
        _url(1),
        {'approved': True},
        format='json',
    )

    assert resposta.status_code == status.HTTP_401_UNAUTHORIZED
