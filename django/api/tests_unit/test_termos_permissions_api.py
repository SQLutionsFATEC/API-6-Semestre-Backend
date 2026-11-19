import pytest
from rest_framework import status
from rest_framework.test import APIClient

from api.authentication.keycloak import KeycloakUser
from api.models import Documento
from api.services.consentimento import consentir_clausulas
from api.services.termo_consentimento import obter_termo_atual


def _cliente(usuario):
    cliente = APIClient()
    cliente.force_authenticate(user=usuario)
    return cliente


def _usuario(id_usuario, roles=None):
    return KeycloakUser(
        {
            'sub': id_usuario,
            'preferred_username': id_usuario,
            'realm_access': {'roles': roles or ['basico']},
        }
    )


def _aceitar_clausulas_obrigatorias(id_usuario):
    termo = obter_termo_atual()
    ids = list(
        termo.clausulas.filter(obrigatoria=True).values_list('id_clausula', flat=True)
    )
    consentir_clausulas(id_usuario, ids)


@pytest.mark.django_db
@pytest.mark.parametrize(
    'url',
    [
        '/api/perfil/',
        '/api/documentos/',
        '/api/etiquetas/',
    ],
)
def test_rotas_protegidas_retorna_451_sem_aceite_dos_termos(url):
    resposta = _cliente(_usuario(f'usuario-sem-aceite-{url}')).get(url)

    assert resposta.status_code == 451


@pytest.mark.django_db
@pytest.mark.parametrize('url', ['/api/documentos/', '/api/etiquetas/'])
def test_rotas_protegidas_retorna_200_apos_aceite_dos_termos(url):
    usuario = _usuario(f'usuario-com-aceite-{url}')
    _aceitar_clausulas_obrigatorias(usuario.id)

    resposta = _cliente(usuario).get(url)

    assert resposta.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_documentos_prioriza_403_de_permissao_sobre_451():
    usuario = _usuario('usuario-sem-permissao', roles=['basico'])
    Documento.objects.create(
        tipo_arquivo='pdf',
        nome='Manual.pdf',
        setor='TI',
        nivel='basico',
        data='documentos/manual.pdf',
    )

    resposta = _cliente(usuario).post('/api/documentos/', {})

    assert resposta.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_rotas_protegidas_prioriza_401_sem_autenticacao():
    resposta = APIClient().get('/api/documentos/')

    assert resposta.status_code == status.HTTP_401_UNAUTHORIZED
