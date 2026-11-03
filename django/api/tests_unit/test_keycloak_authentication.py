"""Testes unitários da autenticação via Keycloak.

Os tokens são gerados localmente com uma chave RSA de teste e o JWK Set
consultado pelo autenticador é simulado (sem chamada real ao Keycloak).
"""

import base64
import time

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import RequestFactory
from jose import jwt
from rest_framework.exceptions import AuthenticationFailed

from django.conf import settings
from api.authentication.keycloak import (
    KeycloakAuthentication,
    KeycloakUser,
    limpar_cache_jwks,
    obter_jwks,
)


def _numero_para_base64url(numero):
    """Codifica um inteiro (modulus/exponent) no formato base64url."""
    tamanho = (numero.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(numero.to_bytes(tamanho, 'big')).rstrip(b'=').decode()


def _construir_jwk(chave_rsa, kid):
    publico = chave_rsa.private_numbers().public_numbers
    return {
        'kty': 'RSA',
        'kid': kid,
        'alg': 'RS256',
        'use': 'sig',
        'n': _numero_para_base64url(publico.n),
        'e': _numero_para_base64url(publico.e),
    }


class _Resposta:
    def __init__(self, dados):
        self._dados = dados

    def raise_for_status(self):
        return None

    def json(self):
        return self._dados


@pytest.fixture(scope='module')
def par_chaves():
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return {'chave': chave, 'jwk': _construir_jwk(chave, 'chave-teste')}


@pytest.fixture(autouse=True)
def jwks_simulado(monkeypatch, par_chaves):
    """Simula a resposta do endpoint do JWK Set do Keycloak."""
    jwks = {'keys': [par_chaves['jwk']]}

    def get_simulado(url, timeout=None):
        return _Resposta(jwks)

    monkeypatch.setattr('api.authentication.keycloak.requests.get', get_simulado)
    limpar_cache_jwks()
    yield jwks
    limpar_cache_jwks()


@pytest.fixture
def autenticador():
    return KeycloakAuthentication()


def _token(par_chaves, claims=None, assinado_com_outra_chave=False):
    agora = int(time.time())
    conteudo = {
        'sub': 'id-usuario-1',
        'preferred_username': 'usuario.teste',
        'name': 'Usuário Teste',
        'email': 'teste@example.com',
        'setor': 'tecnico',
        'realm_access': {'roles': ['basico', 'offline_access']},
        'iss': settings.KEYCLOAK_ISSUER,
        'iat': agora,
        'exp': agora + 300,
    }
    conteudo.update(claims or {})

    if assinado_com_outra_chave:
        outra = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return jwt.encode(conteudo, outra, algorithm='RS256', headers={'kid': 'chave-teste'})

    return jwt.encode(
        conteudo, par_chaves['chave'], algorithm='RS256', headers={'kid': 'chave-teste'}
    )


def _requisicao_com_token(token):
    factory = RequestFactory()
    return factory.get('/api/documentos/', HTTP_AUTHORIZATION='Bearer ' + token)


def test_token_valido_autentica_usuario(par_chaves, autenticador):
    requisicao = _requisicao_com_token(_token(par_chaves))

    usuario, token = autenticador.authenticate(requisicao)

    assert usuario.id == 'id-usuario-1'
    assert usuario.username == 'usuario.teste'
    assert usuario.nome == 'Usuário Teste'
    assert usuario.email == 'teste@example.com'
    assert usuario.is_authenticated is True


def test_token_valido_mapeia_nivel_e_setor(par_chaves, autenticador):
    token = _token(
        par_chaves,
        claims={'realm_access': {'roles': ['comercial']}, 'setor': 'juridico'},
    )
    usuario, _ = autenticador.authenticate(_requisicao_com_token(token))

    # nivel capitalizado para casar com authorization_service;
    # setor em minúsculas, conforme a regra de negócio
    assert usuario.nivel_acesso == 'comercial'
    assert usuario.nivel == 'Comercial'
    assert usuario.setor == 'juridico'


def test_sem_role_de_nivel_aplica_padrao_basico(par_chaves, autenticador):
    token = _token(par_chaves, claims={'realm_access': {'roles': ['offline_access']}})
    usuario, _ = autenticador.authenticate(_requisicao_com_token(token))

    assert usuario.nivel_acesso == 'basico'
    assert usuario.nivel == 'Basico'


def test_sem_claim_de_setor_aplica_padrao_tecnico(par_chaves, autenticador):
    token = _token(par_chaves, claims={'setor': None})
    usuario, _ = autenticador.authenticate(_requisicao_com_token(token))

    assert usuario.setor == 'tecnico'


def test_has_role_indica_operador_e_admin(par_chaves, autenticador):
    token = _token(par_chaves, claims={'realm_access': {'roles': ['operador']}})
    usuario, _ = autenticador.authenticate(_requisicao_com_token(token))

    assert usuario.has_role('operador') is True
    assert usuario.has_role('admin') is False


def test_token_sem_bearer_nao_autentica(autenticador):
    factory = RequestFactory()
    requisicao = factory.get('/api/documentos/')

    assert autenticador.authenticate(requisicao) is None


def test_header_malformado_levanta_erro(autenticador):
    factory = RequestFactory()
    requisicao = factory.get('/api/documentos/', HTTP_AUTHORIZATION='Bearer')

    with pytest.raises(AuthenticationFailed):
        autenticador.authenticate(requisicao)


def test_token_expirado_e_rejeitado(par_chaves, autenticador):
    agora = int(time.time())
    token = _token(par_chaves, claims={'exp': agora - 1000})
    requisicao = _requisicao_com_token(token)

    with pytest.raises(AuthenticationFailed):
        autenticador.authenticate(requisicao)


def test_token_com_iss_divergente_e_rejeitado(par_chaves, autenticador):
    token = _token(par_chaves, claims={'iss': 'https://outro-emissor'})
    requisicao = _requisicao_com_token(token)

    with pytest.raises(AuthenticationFailed):
        autenticador.authenticate(requisicao)


def test_token_com_assinatura_invalida_e_rejeitado(par_chaves, autenticador):
    token = _token(par_chaves, assinado_com_outra_chave=True)
    requisicao = _requisicao_com_token(token)

    with pytest.raises(AuthenticationFailed):
        autenticador.authenticate(requisicao)


def test_header_do_token_deve_ser_rs256(par_chaves):
    header = jwt.get_unverified_header(_token(par_chaves))
    assert header['alg'] == 'RS256'
    assert header['kid'] == 'chave-teste'


def test_kid_desconhecido_forca_recarga_do_jwks(monkeypatch, par_chaves, autenticador):
    nova = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk_nova = _construir_jwk(nova, 'chave-nova')

    agora = int(time.time())
    token = jwt.encode(
        {
            'sub': 'id-usuario-rotacao',
            'iss': settings.KEYCLOAK_ISSUER,
            'exp': agora + 300,
        },
        nova,
        algorithm='RS256',
        headers={'kid': 'chave-nova'},
    )

    # JWK Set em cache ainda sem a chave nova...
    monkeypatch.setattr(
        'api.authentication.keycloak.requests.get',
        lambda url, timeout=None: _Resposta({'keys': []}),
    )
    limpar_cache_jwks()

    # ...mas a recarga do autenticador encontra a chave no JWK Set atualizado.
    monkeypatch.setattr(
        'api.authentication.keycloak.requests.get',
        lambda url, timeout=None: _Resposta({'keys': [jwk_nova]}),
    )

    usuario, _ = autenticador.authenticate(_requisicao_com_token(token))
    assert usuario.id == 'id-usuario-rotacao'


def test_cache_do_jwks_evita_consultas_repetidas(monkeypatch, par_chaves):
    chamadas = {'qtd': 0}

    def get_simulado(url, timeout=None):
        chamadas['qtd'] += 1
        return _Resposta({'keys': [par_chaves['jwk']]})

    monkeypatch.setattr('api.authentication.keycloak.requests.get', get_simulado)
    limpar_cache_jwks()

    obter_jwks()
    obter_jwks()

    assert chamadas['qtd'] == 1


def test_keycloakuser_str_retorna_username():
    usuario = KeycloakUser({'sub': 'abc', 'preferred_username': 'joao'})
    assert str(usuario) == 'joao'


def test_authenticate_header_informado_por_autenticador(autenticador):
    cabecalho = autenticador.authenticate_header(None)
    assert 'Bearer' in cabecalho
    assert settings.KEYCLOAK_REALM in cabecalho
