"""Autenticação de tokens de acesso emitidos pelo Keycloak.

O backend valida o access token (JWT RS256) localmente, a partir do JWK Set
publicado pelo Keycloak, sem consultar o serviço em cada requisição:

    Navegador -> Token JWT -> Django (valida assinatura RS256 + iss + exp)
                                    -> request.user (claims do token)

O Keycloak é a fonte da verdade dos usuários: não há modelagem de usuário no
banco do Django. O `request.user` é um objeto leve montado a partir dos claims

    - sub / preferred_username / name / email
    - realm_access.roles -> nivel_acesso (basico, comercial, militar, operador)
    - claim 'setor' (atributo do usuário: tecnico, normativo, juridico, qualitativo)

Valores não informados são normalizados para os padrões de negócio
(basico / tecnico). Os valores são capitalizados para manter compatibilidade
com a hierarquia de `api.services.authorization_service`.
"""

import threading
import time

import requests
from jose import jwt
from jose.exceptions import JOSEError
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from django.conf import settings

# Níveis de acesso válidos (realm roles) e setores (atributo do usuário)
NIVEIS_ACESSO = ('basico', 'comercial', 'militar', 'operador')
SETORES = ('tecnico', 'normativo', 'juridico', 'qualitativo')

NIVEL_PADRAO = 'basico'
SETOR_PADRAO = 'tecnico'
JWKS_PATH = '/protocol/openid-connect/certs'


class KeycloakUser:
    """Usuário autenticado pelo Keycloak, montado a partir dos claims do token."""

    def __init__(self, claims):
        self.id = claims.get('sub', '')
        self.username = claims.get('preferred_username', claims.get('sub', ''))
        self.nome = claims.get('name') or ' '.join(
            parte
            for parte in [
                claims.get('given_name', ''),
                claims.get('family_name', ''),
            ]
            if parte
        )
        self.email = claims.get('email', '')
        self.roles = list(claims.get('realm_access', {}).get('roles', []))

        # Nivel de acesso: primeira realm role de negócio presente no token.
        # Caso nenhuma role de nível esteja presente, aplica-se o padrão 'basico'.
        self.nivel_acesso = NIVEL_PADRAO
        for nivel in NIVEIS_ACESSO:
            if nivel in self.roles:
                self.nivel_acesso = nivel

        # Setor: atributo de usuário exposto como claim. Caso ausente,
        # aplica-se o padrão 'tecnico'.
        self.setor = claims.get('setor') or SETOR_PADRAO

    # Nomes capitalizados para casar com NIVEL_HIERARQUIA/SETOR_PADRAO
    # de api.services.authorization_service (ex.: 'Basico', 'Tecnico').
    @property
    def nivel(self):
        return self.nivel_acesso.capitalize()

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def has_role(self, nome_role):
        """Indica se o usuário possui a realm role informada (ex.: 'admin')."""
        return nome_role in self.roles

    def __str__(self):
        return self.username or self.id


# Cache do JWK Set com lock e TTL para evitar consulta ao Keycloak por requisição.
_jwks_cache = {'jwks': None, 'emissao': 0.0}
_jwks_lock = threading.Lock()


def limpar_cache_jwks():
    """Limpa o cache do JWK Set (utilizado pelos testes)."""
    with _jwks_lock:
        _jwks_cache['jwks'] = None
        _jwks_cache['emissao'] = 0.0


def obter_jwks():
    """Retorna o JWK Set do Keycloak, atualizando o cache após o TTL."""
    agora = time.time()
    with _jwks_lock:
        if _jwks_cache['jwks'] is not None:
            if agora - _jwks_cache['emissao'] < settings.KEYCLOAK_JWKS_TTL:
                return _jwks_cache['jwks']

        url = settings.KEYCLOAK_ISSUER + JWKS_PATH
        resposta = requests.get(url, timeout=10)
        resposta.raise_for_status()
        jwks = resposta.json()

        _jwks_cache['jwks'] = jwks
        _jwks_cache['emissao'] = agora
        return jwks


def obter_jwk(kid, jwks=None):
    """Localiza a chave do JWK Set pelo 'kid' do header do token.

    Recebe um segundo JWK Set por parâmetro para permitir nova busca em caso
    de rotação de chaves, sem atualizar o cache."""
    if jwks is None:
        jwks = obter_jwks()
    for jwk_chave in jwks.get('keys', []):
        if jwk_chave.get('kid') == kid:
            return jwk_chave
    return None


class KeycloakAuthentication(BaseAuthentication):
    """Autenticação Bearer com access token JWT emitido pelo Keycloak."""

    def authenticate_header(self, request):
        return 'Bearer realm="' + settings.KEYCLOAK_REALM + '"'

    def authenticate(self, request):
        header = get_authorization_header(request).split()

        if not header or header[0].lower() != b'bearer':
            # Sem token: passa para o próximo autenticador (ou falha 401).
            return None

        if len(header) != 2:
            raise AuthenticationFailed('Header de autorização inválido.')

        token = header[1].decode('utf-8')
        claims = self.validar_token(token)
        return (KeycloakUser(claims), token)

    def validar_token(self, token):
        """Valida assinatura, algoritmo, emissor e expiração; retorna os claims."""
        try:
            header = jwt.get_unverified_header(token)
        except JOSEError:
            raise AuthenticationFailed('Token de acesso inválido.')

        if header.get('alg') != 'RS256':
            raise AuthenticationFailed('Token assinado com algoritmo não suportado.')

        jwk_chave = obter_jwk(header.get('kid'))
        if jwk_chave is None:
            # O 'kid' pode ser novo após rotação de chaves: força recarga do cache.
            limpar_cache_jwks()
            jwk_chave = obter_jwk(header.get('kid'))
            if jwk_chave is None:
                raise AuthenticationFailed('Token de acesso inválido.')

        try:
            claims = jwt.decode(
                token,
                jwk_chave,
                algorithms=['RS256'],
                issuer=settings.KEYCLOAK_ISSUER,
                options={'verify_aud': False},
            )
        except JOSEError:
            # Engloba assinatura inválida, token expirado e emissor divergente.
            raise AuthenticationFailed(
                'Token de acesso inválido ou expirado.'
            )

        return claims


# Registra o autenticador no OpenAPI para o Swagger UI exibir o
# botão 'Authorize' com o token Bearer do Keycloak.
from drf_spectacular.extensions import OpenApiAuthenticationExtension  # noqa: E402
from drf_spectacular.plumbing import (  # noqa: E402
    build_bearer_security_scheme_object,
)


class KeycloakAuthenticationExtension(OpenApiAuthenticationExtension):
    target_class = 'api.authentication.keycloak.KeycloakAuthentication'
    name = 'KeycloakBearer'

    def get_security_definition(self, auto_schema):
        return build_bearer_security_scheme_object(
            header_name='Authorization',
            token_prefix='Bearer',
        )
