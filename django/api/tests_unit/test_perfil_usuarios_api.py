"""Testes das rotas /api/perfil/ e /api/usuarios/ com Admin API simulada."""

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from api.authentication.keycloak import KeycloakUser
from api.services.delecao_usuario import hash_id_usuario
from api.services.keycloak_admin import KeycloakAdminException

CLAIMS_USUARIO = {
    'sub': 'id-usuario-comum',
    'preferred_username': 'maria',
    'name': 'Maria Silva',
    'email': 'maria@example.com',
    'realm_access': {'roles': ['basico']},
}

CLAIMS_ADMIN = {
    'sub': 'id-usuario-admin',
    'preferred_username': 'admin.projeto',
    'name': 'Admin Projeto',
    'email': 'admin@example.com',
    'realm_access': {'roles': ['admin', 'operador']},
}

USUARIO_REPRESENTACAO = {
    'id': 'id-usuario-comum',
    'username': 'maria',
    'firstName': 'Maria',
    'lastName': 'Silva',
    'email': 'maria@example.com',
    'enabled': True,
    'attributes': {'setor': ['tecnico']},
    'realmRoles': ['basico'],
}

USUARIO_REPRESENTACAO_ADMIN = {
    'id': 'id-usuario-admin',
    'username': 'admin.projeto',
    'firstName': 'Admin',
    'email': 'admin@example.com',
    'enabled': True,
    'attributes': {'setor': ['normativo']},
    'realmRoles': ['admin', 'operador'],
}


def _cliente_com(usuario=None):
    cliente = APIClient()
    if usuario is not None:
        cliente.force_authenticate(user=usuario)
    return cliente


@pytest.fixture
def mock_admin(monkeypatch):
    """Substitui as funções da Admin API por fakes configuráveis."""

    def definir(**fakes):
        for nome, fake in fakes.items():
            monkeypatch.setattr(
                f'api.services.keycloak_admin.{nome}', fake, raising=False
            )

    return definir


def test_perfil_sem_autenticacao_retorna_401():
    cliente = _cliente_com()

    resposta = cliente.get(reverse('perfil'))

    assert resposta.status_code == status.HTTP_401_UNAUTHORIZED


def test_perfil_retorna_campos_de_negocio(mock_admin):
    mock_admin(
        obter_usuario=lambda id_usuario: dict(USUARIO_REPRESENTACAO),
        listar_papeis_realm_usuario=lambda id_usuario: [{'name': 'basico'}],
    )
    cliente = _cliente_com()
    cliente.force_authenticate(user=KeycloakUser(CLAIMS_USUARIO))

    resposta = cliente.get(reverse('perfil'))

    dados = resposta.json()
    assert resposta.status_code == status.HTTP_200_OK
    assert dados['id'] == 'id-usuario-comum'
    assert dados['nome'] == 'Maria'
    assert dados['email'] == 'maria@example.com'
    assert dados['nivel_acesso'] == 'basico'
    assert dados['setor'] == 'tecnico'


def test_perfil_patch_altera_nome(mock_admin):
    def atualizar(id_usuario, **campos):
        assert id_usuario == 'id-usuario-comum'
        assert campos == {'nome': 'Maria Antonieta'}
        atualizado = dict(USUARIO_REPRESENTACAO)
        atualizado['firstName'] = 'Maria Antonieta'
        return atualizado

    mock_admin(
        atualizar_usuario=atualizar,
        listar_papeis_realm_usuario=lambda id_usuario: [{'name': 'basico'}],
    )

    cliente = _cliente_com()
    cliente.force_authenticate(user=KeycloakUser(CLAIMS_USUARIO))

    resposta = cliente.patch(reverse('perfil'), {'nome': 'Maria Antonieta'}, format='json')

    dados = resposta.json()
    assert resposta.status_code == status.HTTP_200_OK
    assert dados['nome'] == 'Maria Antonieta'

    mock_admin(atualizar_usuario=atualizar)

    cliente = _cliente_com()
    cliente.force_authenticate(user=KeycloakUser(CLAIMS_USUARIO))

    resposta = cliente.patch(reverse('perfil'), {'nome': 'Maria Antonieta'}, format='json')

    dados = resposta.json()
    assert resposta.status_code == status.HTTP_200_OK
    assert dados['nome'] == 'Maria Antonieta'


def test_perfil_patch_rejeita_campos_de_negocio(mock_admin):
    cliente = _cliente_com()
    cliente.force_authenticate(user=KeycloakUser(CLAIMS_USUARIO))

    resposta = cliente.patch(
        reverse('perfil'), {'setor': 'juridico', 'nome': 'X'}, format='json'
    )

    assert resposta.status_code == status.HTTP_400_BAD_REQUEST


def test_patch_meu_perfil_sucesso_retorna_200(mock_admin):
    def atualizar(id_usuario, **campos):
        assert id_usuario == 'id-usuario-comum'
        assert campos == {'nome': 'Maria Editada'}
        atualizado = dict(USUARIO_REPRESENTACAO)
        atualizado['firstName'] = 'Maria Editada'
        return atualizado

    mock_admin(
        atualizar_usuario=atualizar,
        listar_papeis_realm_usuario=lambda id_usuario: [{'name': 'basico'}],
    )

    cliente = _cliente_com()
    cliente.force_authenticate(user=KeycloakUser(CLAIMS_USUARIO))

    resposta = cliente.patch(reverse('usuarios'), {'nome': 'Maria Editada'}, format='json')

    assert resposta.status_code == status.HTTP_200_OK
    assert resposta.json()['nome'] == 'Maria Editada'


def test_usuarios_exige_role_admin(mock_admin):
    cliente = _cliente_com()
    cliente.force_authenticate(user=KeycloakUser(CLAIMS_USUARIO))

    resposta = cliente.get(reverse('usuarios'))

    assert resposta.status_code == status.HTTP_403_FORBIDDEN
    assert resposta.json()['detail'] == (
        'Somente usuários com a role admin podem acessar este recurso.'
    )


def test_usuarios_lista_usuarios(mock_admin):
    def papeis(id_usuario):
        return [{"name": "admin"}, {"name": "operador"}] \
            if id_usuario == 'id-usuario-admin' else [{'name': 'basico'}]

    mock_admin(
        listar_usuarios=lambda busca=None: [dict(USUARIO_REPRESENTACAO)],
        listar_papeis_realm_usuario=papeis,
    )
    cliente = _cliente_com()
    cliente.force_authenticate(user=KeycloakUser(CLAIMS_ADMIN))

    resposta = cliente.get(reverse('usuarios'))

    dados = resposta.json()
    assert resposta.status_code == status.HTTP_200_OK
    assert len(dados) == 1
    assert dados[0]['nivel_acesso'] == 'basico'


def test_usuarios_cria_usuario_com_senha_temporaria(mock_admin):
    def criar(nome, sobrenome, email, senha_temporaria, nivel_acesso='basico', setor='tecnico'):
        assert nome == 'Jose Almeida'
        assert sobrenome == 'Souza'
        assert email == 'jose@example.com'
        assert senha_temporaria == 'senha-temp'
        assert nivel_acesso == 'operador'
        assert setor == 'tecnico'
        return dict(USUARIO_REPRESENTACAO, id='id-novo', email=email)

    mock_admin(
        criar_usuario=criar,
        listar_papeis_realm_usuario=lambda id_usuario: [{'name': 'operador'}],
    )
    cliente = _cliente_com()
    cliente.force_authenticate(user=KeycloakUser(CLAIMS_ADMIN))

    resposta = cliente.post(
        reverse('usuarios'),
        {
            'nome': 'Jose Almeida',
            'sobrenome': 'Souza',
            'email': 'jose@example.com',
            'senha_temporaria': 'senha-temp',
            'nivel_acesso': 'operador',
        },
        format='json',
    )

    dados = resposta.json()
    assert resposta.status_code == status.HTTP_201_CREATED
    assert dados['nivel_acesso'] == 'operador'
    assert dados['setor'] == 'tecnico'


def test_usuarios_cria_usuario_rejeita_nivel_invalido(mock_admin):
    cliente = _cliente_com()
    cliente.force_authenticate(user=KeycloakUser(CLAIMS_ADMIN))

    resposta = cliente.post(
        reverse('usuarios'),
        {
            'nome': 'Jose',
            'sobrenome': 'Souza',
            'email': 'jose@example.com',
            'senha_temporaria': 'senha-temp',
            'nivel_acesso': 'raiz',
        },
        format='json',
    )

    assert resposta.status_code == status.HTTP_400_BAD_REQUEST


def test_usuario_detalhe_ler_permissoes(mock_admin):
    def papeis(id_usuario):
        return [{'name': 'operador'}]

    mock_admin(
        obter_usuario=lambda id_usuario: dict(
            USUARIO_REPRESENTACAO_ADMIN, id=id_usuario
        ),
        listar_papeis_realm_usuario=papeis,
    )
    cliente = _cliente_com()
    cliente.force_authenticate(user=KeycloakUser(CLAIMS_ADMIN))

    resposta = cliente.get(reverse('usuario-detalhe', args=['id-usuario-admin']))

    dados = resposta.json()
    assert resposta.status_code == status.HTTP_200_OK
    assert dados['nivel_acesso'] == 'operador'
    assert dados['setor'] == 'normativo'


def test_usuario_detalhe_patch_troca_senha_temporaria(mock_admin):
    def atualizar(id_usuario, **campos):
        assert campos == {
            'setor': 'qualitativo',
            'senha': 'nova-senha',
            'senha_temporaria': True,
        }
        atualizado = dict(USUARIO_REPRESENTACAO)
        atualizado['id'] = id_usuario
        atualizado['attributes'] = {'setor': ['qualitativo']}
        return atualizado

    mock_admin(
        atualizar_usuario=atualizar,
        listar_papeis_realm_usuario=lambda id_usuario: [{'name': 'basico'}],
    )
    cliente = _cliente_com()
    cliente.force_authenticate(user=KeycloakUser(CLAIMS_ADMIN))

    resposta = cliente.patch(
        reverse('usuario-detalhe', args=['id-usuario-comum']),
        {'setor': 'qualitativo', 'senha': 'nova-senha'},
        format='json',
    )

    dados = resposta.json()
    assert resposta.status_code == status.HTTP_200_OK
    assert dados['setor'] == 'qualitativo'


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_usuario_detalhe_anonimiza(mock_admin, settings):
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    anonimizados = []

    def anonimizar(id_usuario, sufixo):
        anonimizados.append((id_usuario, sufixo))

    mock_admin(
        obter_usuario=lambda id_usuario: dict(USUARIO_REPRESENTACAO),
        anonimizar_usuario=anonimizar,
    )
    cliente = _cliente_com()
    cliente.force_authenticate(user=KeycloakUser(CLAIMS_ADMIN))

    resposta = cliente.delete(reverse('usuario-detalhe', args=['id-usuario-comum']))

    assert resposta.status_code == status.HTTP_204_NO_CONTENT
    assert anonimizados == [
        ('id-usuario-comum', hash_id_usuario('id-usuario-comum'))
    ]


def test_usuario_detalhe_404_quando_inexistente(mock_admin):
    def obter(id_usuario):
        raise KeycloakAdminException('Usuário não encontrado no Keycloak.', codigo_status=404)

    mock_admin(obter_usuario=obter)
    cliente = _cliente_com()
    cliente.force_authenticate(user=KeycloakUser(CLAIMS_ADMIN))

    resposta = cliente.get(reverse('usuario-detalhe', args=['nao-existe']))

    assert resposta.status_code == status.HTTP_404_NOT_FOUND


def test_usuario_detalhe_502_quando_keycloak_falha(mock_admin):
    def obter(id_usuario):
        raise KeycloakAdminException('Falhou.', codigo_status=500, resposta='boom')

    mock_admin(obter_usuario=obter)
    cliente = _cliente_com()
    cliente.force_authenticate(user=KeycloakUser(CLAIMS_ADMIN))

    resposta = cliente.get(reverse('usuario-detalhe', args=['qualquer']))

    assert resposta.status_code == status.HTTP_502_BAD_GATEWAY