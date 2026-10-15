"""Cliente da Admin REST API do Keycloak (CRUD de usuários e permissões).

O backend usa este serviço para ler e editar usuários no Keycloak, que é a
fonte da verdade de identidade da aplicação. A autenticação do cliente é
feita com o perfil administrador do realm master (admin/admin por padrão),
configurável pelas variáveis:

    KEYCLOAK_URL, KEYCLOAK_REALM,
    KEYCLOAK_ADMIN_USERNAME, KEYCLOAK_ADMIN_PASSWORD

Referência da API: https://www.keycloak.org/docs-api/latest/rest-api/

Endpoints usados:

    POST   /realms/master/protocol/openid-connect/token
                -> token do admin (client_id 'admin-cli')
    GET    /admin/realms/{realm}/users
    POST   /admin/realms/{realm}/users
    GET    /admin/realms/{realm}/users/{id}
    PUT    /admin/realms/{realm}/users/{id}
    DELETE /admin/realms/{realm}/users/{id}
    PUT    /admin/realms/{realm}/users/{id}/reset-password
    PUT    /admin/realms/{realm}/users/{id}/execute-actions-email
    GET    /admin/realms/{realm}/users/{id}/role-mappings[.../realm]
    POST   /admin/realms/{realm}/users/{id}/role-mappings/realm
    DELETE /admin/realms/{realm}/users/{id}/role-mappings/realm
    GET    /admin/realms/{realm}/roles/{role}
"""

import threading
import time

import requests
from django.conf import settings

MASTER_REALM = 'master'
ADMIN_CLIENT_ID = 'admin-cli'
TOKEN_PATH = '/protocol/openid-connect/token'
USERS_PATH = '/admin/realms/{realm}/users'

# Valores válidos (e padrões de negócio) dos campos de nível de acesso e setor
NIVEIS_ACESSO = ('basico', 'comercial', 'militar', 'operador')
SETORES = ('tecnico', 'normativo', 'juridico', 'qualitativo')
NIVEL_PADRAO = 'basico'
SETOR_PADRAO = 'tecnico'

# Cache do token do administrador em memória de processo
_token_cache = {'token': None, 'expiracao': 0.0}
_token_lock = threading.Lock()


class KeycloakAdminException(Exception):
    """Erro levantado quando a Admin REST API do Keycloak responde com falha."""

    def __init__(self, mensagem, codigo_status=None, resposta=None):
        super().__init__(mensagem)
        self.codigo_status = codigo_status
        self.resposta = resposta


def _url_admin_realm():
    return (
        settings.KEYCLOAK_URL.rstrip('/')
        + '/admin/realms/'
        + settings.KEYCLOAK_REALM
    )


def _url_token_master():
    return (
        settings.KEYCLOAK_URL.rstrip('/')
        + '/realms/'
        + MASTER_REALM
        + TOKEN_PATH
    )


def obter_token_admin(force=False):
    """Retorna um access token de administrador do realm master.

    O token é reutilizado até pouco antes de expirar, então um único POST é
    feito por intervalo de renovação."""
    with _token_lock:
        agora = time.time()
        if not force and _token_cache['token'] and agora < _token_cache['expiracao']:
            return _token_cache['token']

        resposta = requests.post(
            _url_token_master(),
            data={
                'grant_type': 'password',
                'client_id': ADMIN_CLIENT_ID,
                'username': settings.KEYCLOAK_ADMIN_USERNAME,
                'password': settings.KEYCLOAK_ADMIN_PASSWORD,
            },
            timeout=15,
        )
        if resposta.status_code != 200:
            raise KeycloakAdminException(
                'Não foi possível obter o token do administrador no Keycloak.',
                codigo_status=resposta.status_code,
                resposta=resposta.text,
            )

        dados = resposta.json()
        _token_cache['token'] = dados['access_token']
        _token_cache['expiracao'] = agora + max(int(dados.get('expires_in', 60)) - 30, 5)
        return _token_cache['token']


def limpar_token_admin():
    """Limpa o cache do token de administrador (utilizado pelos testes)."""
    with _token_lock:
        _token_cache['token'] = None
        _token_cache['expiracao'] = 0.0


def _cabecalhos():
    return {
        'Authorization': 'Bearer ' + obter_token_admin(),
        'Content-Type': 'application/json',
    }


def _requisitar(metodo, url, **kwargs):
    """Executa uma chamada à Admin API; renova o token uma vez em caso de 401."""
    resposta = requests.request(metodo, url, headers=_cabecalhos(), timeout=15, **kwargs)
    if resposta.status_code == 401:
        obter_token_admin(force=True)
        resposta = requests.request(metodo, url, headers=_cabecalhos(), timeout=15, **kwargs)
    return resposta


def _verificar(resposta, descricao):
    if resposta.status_code >= 400:
        raise KeycloakAdminException(
            f'Falha na Admin REST API do Keycloak ({descricao})',
            codigo_status=resposta.status_code,
            resposta=resposta.text,
        )
    return resposta


# ============================================================
# CRUD de usuários
# ============================================================

def listar_usuarios(busca=None, inicio=0, maximo=100):
    """Lista os usuários do realm, opcionalmente filtrando por busca textual."""
    resposta = _requisitar(
        'GET',
        _url_admin_realm() + '/users',
        params={'search': busca or '', 'first': inicio, 'max': maximo},
    )
    return _verificar(resposta, 'listar usuários').json()


def obter_usuario(id_usuario):
    """Lê os campos de um usuário (nome, email, atributos, etc.) pelo id."""
    resposta = _requisitar('GET', f'{_url_admin_realm()}/users/{id_usuario}')
    if resposta.status_code == 404:
        raise KeycloakAdminException(
            'Usuário não encontrado no Keycloak.',
            codigo_status=404,
            resposta=resposta.text,
        )
    return _verificar(resposta, 'obter usuário').json()


def criar_usuario(nome, email, senha_temporaria,
                  nivel_acesso=NIVEL_PADRAO, setor=SETOR_PADRAO):
    """Cria um usuário no realm com senha temporária, nível e setor.

    nivel_acesso vira realm role (padrão 'basico') e setor vira atributo do
    usuário (padrão 'tecnico'). A senha é criada com temporary=True: o usuário
    é obrigado a trocá-la no primeiro login."""
    _validar_nivel(nivel_acesso)
    _validar_setor(setor)

    payload = {
        'username': email,
        'email': email,
        'firstName': nome,
        'enabled': True,
        'realmRoles': [nivel_acesso],
        'attributes': {'setor': [setor]},
        'credentials': [
            {'type': 'password', 'value': senha_temporaria, 'temporary': True}
        ],
    }

    resposta = _requisitar('POST', f'{_url_admin_realm()}/users', json=payload)
    _verificar(resposta, 'criar usuário')

    id_criado = resposta.headers.get('Location', '').rsplit('/', 1)[-1]
    return obter_usuario(id_criado)


def atualizar_usuario(id_usuario, **campos):
    """Modifica campos de um usuário no Keycloak.

    Campos de negócio tratados de forma dedicada:
      - 'nome' / 'sobrenome' -> firstName / lastName
      - 'setor'              -> atributo 'setor'
      - 'nivel_acesso'       -> realm role
      - 'senha'              -> PUT /reset-password (temporária se 'senha_temporaria')
    Outros campos (ex.: 'email', 'enabled') vão direto no payload do PUT.
    """
    senha = campos.pop('senha', None)
    senha_temporaria = campos.pop('senha_temporaria', True)
    nivel = campos.pop('nivel_acesso', None)
    setor = campos.pop('setor', None)

    payload = dict(campos)
    if 'nome' in payload:
        payload['firstName'] = payload.pop('nome')
    if 'sobrenome' in payload:
        payload['lastName'] = payload.pop('sobrenome')

    if setor is not None:
        _validar_setor(setor)
        payload['attributes'] = dict(payload.get('attributes') or {})
        payload['attributes']['setor'] = [setor]

    if nivel is not None:
        trocar_nivel_acesso(id_usuario, nivel)

    if payload:
        resposta = _requisitar('PUT', f'{_url_admin_realm()}/users/{id_usuario}', json=payload)
        _verificar(resposta, 'atualizar usuário')

    if senha is not None:
        definir_senha(id_usuario, senha, temporaria=senha_temporaria)
        if not payload:
            return obter_usuario(id_usuario)

    return obter_usuario(id_usuario)


def deletar_usuario(id_usuario):
    """Deleta o usuário do realm."""
    resposta = _requisitar('DELETE', f'{_url_admin_realm()}/users/{id_usuario}')
    if resposta.status_code == 404:
        raise KeycloakAdminException(
            'Usuário não encontrado no Keycloak.',
            codigo_status=404,
            resposta=resposta.text,
        )
    _verificar(resposta, 'deletar usuário')


def definir_senha(id_usuario, senha, temporaria=True):
    """Define a senha do usuário, podendo exigir troca no próximo login."""
    payload = {'type': 'password', 'value': senha, 'temporary': temporaria}
    resposta = _requisitar(
        'PUT',
        f'{_url_admin_realm()}/users/{id_usuario}/reset-password',
        json=payload,
    )
    _verificar(resposta, 'definir senha')


def enviar_email_definicao_senha(id_usuario, redirect_uri=None, duracao_validade=None):
    """Envia por e-mail o link para o usuário definir a própria senha."""
    params = {}
    if redirect_uri:
        params['redirect_uri'] = redirect_uri
    if duracao_validade:
        params['lifespan'] = str(duracao_validade)
    resposta = _requisitar(
        'PUT',
        f'{_url_admin_realm()}/users/{id_usuario}/execute-actions-email',
        json=['UPDATE_PASSWORD'],
        params=params,
    )
    _verificar(resposta, 'enviar e-mail de definição de senha')


# ============================================================
# Nivel de acesso e permissões (realm roles)
# ============================================================

def _validar_nivel(nivel_acesso):
    if nivel_acesso not in NIVEIS_ACESSO:
        raise ValueError('nivel_acesso deve ser um de: ' + ', '.join(NIVEIS_ACESSO) + '.')


def _validar_setor(setor):
    if setor not in SETORES:
        raise ValueError('setor deve ser um de: ' + ', '.join(SETORES) + '.')


def trocar_nivel_acesso(id_usuario, nivel_acesso):
    """Troca o nivel_acesso do usuário: remove a role atual e atribui a nova."""
    _validar_nivel(nivel_acesso)

    mappings = listar_papeis_realm_usuario(id_usuario)
    url = f'{_url_admin_realm()}/users/{id_usuario}/role-mappings/realm'
    a_remover = [
        {'id': papel.get('id'), 'name': papel.get('name')}
        for papel in mappings
        if papel.get('name') in NIVEIS_ACESSO and papel.get('name') != nivel_acesso
    ]
    if a_remover:
        _verificar(_requisitar('DELETE', url, json=a_remover), 'remover role')

    papel_alvo = obter_role(nivel_acesso)
    _verificar(
        _requisitar('POST', url, json=[{'id': papel_alvo['id'], 'name': papel_alvo['name']}]),
        'atribuir role',
    )


def obter_role(nome_role):
    """Retorna a definição (id, name, etc.) de uma realm role pelo nome."""
    resposta = _requisitar('GET', f'{_url_admin_realm()}/roles/{nome_role}')
    if resposta.status_code == 404:
        raise KeycloakAdminException(
            f'Role não encontrada no realm: {nome_role}',
            codigo_status=404,
            resposta=resposta.text,
        )
    return _verificar(resposta, 'obter role').json()


def listar_papeis_usuario(id_usuario):
    """Lê todas as role mappings do usuário (realm, client, etc.).

    É por aqui que se descobre as permissões do usuário: as realm roles de
    nível (basico, comercial, militar, operador) e a role admin."""
    resposta = _requisitar(
        'GET', f'{_url_admin_realm()}/users/{id_usuario}/role-mappings'
    )
    return _verificar(resposta, 'listar role mappings').json()


def listar_papeis_realm_usuario(id_usuario):
    """Lê apenas as realm roles aplicadas ao usuário."""
    resposta = _requisitar(
        'GET', f'{_url_admin_realm()}/users/{id_usuario}/role-mappings/realm'
    )
    return _verificar(resposta, 'listar realm roles').json()
