"""Cliente da Admin REST API do Keycloak (CRUD de usuários e permissões).

O backend usa este serviço para ler e editar usuários no Keycloak, que é a
fonte da verdade de identidade da aplicação. A autenticação do cliente usa o
service account (client credentials) de um client confidencial do próprio
realm, com apenas as roles de realm-management necessárias para o CRUD de
usuários — nunca o admin do realm master. Configurável pelas variáveis:

    KEYCLOAK_URL, KEYCLOAK_REALM,
    KEYCLOAK_BACKEND_CLIENT_ID, KEYCLOAK_BACKEND_CLIENT_SECRET

Referência da API: https://www.keycloak.org/docs-api/latest/rest-api/

Endpoints usados:

    POST   /realms/{realm}/protocol/openid-connect/token
                -> token do service account (grant_type 'client_credentials')
    GET    /admin/realms/{realm}/users
    POST   /admin/realms/{realm}/users
    GET    /admin/realms/{realm}/users/{id}
    PUT    /admin/realms/{realm}/users/{id}
    GET    /admin/realms/{realm}/users/{id}/credentials
    DELETE /admin/realms/{realm}/users/{id}/credentials/{credentialId}
    GET    /admin/realms/{realm}/users/{id}/groups
    DELETE /admin/realms/{realm}/users/{id}/groups/{groupId}
    POST   /admin/realms/{realm}/users/{id}/logout
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


def _url_token():
    return (
        settings.KEYCLOAK_URL.rstrip('/')
        + '/realms/'
        + settings.KEYCLOAK_REALM
        + TOKEN_PATH
    )


def obter_token_admin(force=False):
    """Retorna um access token de service account para a Admin REST API.

    O token é emitido no próprio realm da aplicação (grant_type
    'client_credentials') pelo client confidencial cujo service account tem
    apenas as roles de realm-management necessárias. É reutilizado até pouco
    antes de expirar, então um único POST é feito por intervalo de renovação."""
    with _token_lock:
        agora = time.time()
        if not force and _token_cache['token'] and agora < _token_cache['expiracao']:
            return _token_cache['token']

        resposta = requests.post(
            _url_token(),
            data={
                'grant_type': 'client_credentials',
                'client_id': settings.KEYCLOAK_BACKEND_CLIENT_ID,
                'client_secret': settings.KEYCLOAK_BACKEND_CLIENT_SECRET,
            },
            timeout=15,
        )
        if resposta.status_code != 200:
            raise KeycloakAdminException(
                'Não foi possível autenticar o service account na Admin API do Keycloak.',
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
    """Lista os usuários do realm, opcionalmente filtrando por busca textual.

    Contas de service account (prefixo 'service-account-') são de
    infraestrutura, não usuários da aplicação: o Keycloak 26 já costuma
    omiti-las da listagem, mas o filtro garante que nunca apareçam nas telas
    de administração."""
    resposta = _requisitar(
        'GET',
        _url_admin_realm() + '/users',
        params={'search': busca or '', 'first': inicio, 'max': maximo},
    )
    usuarios = _verificar(resposta, 'listar usuários').json()
    return [
        usuario
        for usuario in usuarios
        if not str(usuario.get('username', '')).startswith('service-account-')
    ]


def obter_usuario(id_usuario):
    """Lê os campos de um usuário (nome, email, atributos, etc.) pelo id."""
    if not id_usuario:
        raise KeycloakAdminException(
            'Id de usuário ausente.', codigo_status=404, resposta=''
        )
    resposta = _requisitar('GET', f'{_url_admin_realm()}/users/{id_usuario}')
    if resposta.status_code == 404:
        raise KeycloakAdminException(
            'Usuário não encontrado no Keycloak.',
            codigo_status=404,
            resposta=resposta.text,
        )
    return _verificar(resposta, 'obter usuário').json()


def criar_usuario(nome, sobrenome, email, senha_temporaria,
                  nivel_acesso=NIVEL_PADRAO, setor=SETOR_PADRAO):
    """Cria um usuário no realm com senha temporária, nível e setor.

    nivel_acesso vira realm role (padrão 'basico') e setor vira atributo do
    usuário (padrão 'tecnico'). A senha é criada com temporary=True: o usuário
    é obrigado a trocá-la no primeiro login.

    O Keycloak 26 ignora o campo 'realmRoles' no payload de criação, então a
    role de nível é atribuída em uma chamada dedicada a role-mappings/realm."""
    _validar_nivel(nivel_acesso)
    _validar_setor(setor)

    payload = {
        'username': email,
        'email': email,
        'firstName': nome,
        'lastName': sobrenome,
        'enabled': True,
        'attributes': {'setor': [setor]},
        'credentials': [
            {'type': 'password', 'value': senha_temporaria, 'temporary': True}
        ],
    }

    resposta = _requisitar('POST', f'{_url_admin_realm()}/users', json=payload)
    _verificar(resposta, 'criar usuário')

    id_criado = resposta.headers.get('Location', '').rsplit('/', 1)[-1]
    papel = obter_role(nivel_acesso)
    _verificar(
        _requisitar(
            'POST',
            f'{_url_admin_realm()}/users/{id_criado}/role-mappings/realm',
            json=[{'id': papel['id'], 'name': papel['name']}],
        ),
        'atribuir role de nível ao usuário criado',
    )
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

    # O PUT da Admin API substitui a representação inteira do usuário:
    # campos ausentes viram valores vazios. Preservamos os atuais.
    atual = obter_usuario(id_usuario)
    for campo_padrao, padrao in (
        ('firstName', atual.get('firstName')),
        ('lastName', atual.get('lastName')),
        ('email', atual.get('email')),
    ):
        payload.setdefault(campo_padrao, padrao)

    if payload:
        resposta = _requisitar('PUT', f'{_url_admin_realm()}/users/{id_usuario}', json=payload)
        _verificar(resposta, 'atualizar usuário')

    if senha is not None:
        definir_senha(id_usuario, senha, temporaria=senha_temporaria)
        if not payload:
            return obter_usuario(id_usuario)

    return obter_usuario(id_usuario)


def anonimizar_usuario(id_usuario, sufixo):
    """Substitui os dados pessoais do usuário e desabilita a conta.

    A conta continua existindo no Keycloak para que o tombstone consiga
    reconhecê-la em um backup restaurado, mas passa a ter username, e-mail e
    nome genéricos, atributos vazios, nenhuma credencial, nenhuma realm role e
    nenhum grupo. As sessões abertas são encerradas.

    ``sufixo`` deve ser determinístico e único por usuário (o hash do id); ele
    entra no username e no e-mail para evitar colisões entre contas
    anonimizadas.
    """
    if not id_usuario or not sufixo:
        raise ValueError('Id e sufixo são obrigatórios para anonimizar o usuário.')

    username = f'anonimizado-{sufixo}'
    # O local part do e-mail tem limite de 64 caracteres no Keycloak; o hash
    # SHA-256 tem exatamente 64, então ele é usado sem o prefixo do username.
    email = f'{sufixo}@invalid.local'
    payload = {
        'username': username,
        'email': email,
        'firstName': 'Anonimizado',
        'lastName': '',
        'enabled': False,
        'emailVerified': False,
        'attributes': {},
        'requiredActions': [],
    }
    resposta = _requisitar(
        'PUT', f'{_url_admin_realm()}/users/{id_usuario}', json=payload
    )
    if resposta.status_code == 404:
        raise KeycloakAdminException(
            'Usuário não encontrado no Keycloak.',
            codigo_status=404,
            resposta=resposta.text,
        )
    _verificar(resposta, 'anonimizar usuário')

    _encerrar_sessoes(id_usuario)
    _remover_credenciais(id_usuario)
    _remover_papeis_realm(id_usuario)
    _remover_grupos(id_usuario)
    return payload


def usuario_esta_anonimizado(usuario, sufixo):
    """Indica se a representação do usuário não contém mais dados pessoais."""
    if not usuario or not sufixo:
        return False
    username = f'anonimizado-{sufixo}'
    return (
        usuario.get('username') == username
        and usuario.get('email') == f'{sufixo}@invalid.local'
        and usuario.get('enabled') is False
        and (usuario.get('firstName') or '') == 'Anonimizado'
        and not (usuario.get('lastName') or '')
        and not (usuario.get('attributes') or {})
        and not (usuario.get('requiredActions') or [])
    )


def _encerrar_sessoes(id_usuario):
    """Encerra as sessões abertas; 404 significa que não havia sessão."""
    resposta = _requisitar(
        'POST', f'{_url_admin_realm()}/users/{id_usuario}/logout'
    )
    if resposta.status_code != 404:
        _verificar(resposta, 'encerrar sessões do usuário')


def _remover_credenciais(id_usuario):
    """Remove senhas e demais credenciais do usuário."""
    credenciais = listar_credenciais(id_usuario)
    for credencial in credenciais:
        id_credencial = credencial.get('id')
        if not id_credencial:
            continue
        _verificar(
            _requisitar(
                'DELETE',
                f'{_url_admin_realm()}/users/{id_usuario}/credentials/{id_credencial}',
            ),
            'remover credencial do usuário',
        )


def listar_credenciais(id_usuario):
    """Lista as credenciais (senha, OTP etc.) do usuário."""
    resposta = _requisitar(
        'GET', f'{_url_admin_realm()}/users/{id_usuario}/credentials'
    )
    return _verificar(resposta, 'listar credenciais do usuário').json()


def _remover_papeis_realm(id_usuario):
    """Remove todas as realm roles atribuídas ao usuário."""
    papeis = listar_papeis_realm_usuario(id_usuario)
    if papeis:
        _verificar(
            _requisitar(
                'DELETE',
                f'{_url_admin_realm()}/users/{id_usuario}/role-mappings/realm',
                json=papeis,
            ),
            'remover roles do usuário',
        )


def _remover_grupos(id_usuario):
    """Remove o usuário de todos os grupos."""
    grupos = listar_grupos_usuario(id_usuario)
    for grupo in grupos:
        id_grupo = grupo.get('id')
        if not id_grupo:
            continue
        _verificar(
            _requisitar(
                'DELETE',
                f'{_url_admin_realm()}/users/{id_usuario}/groups/{id_grupo}',
            ),
            'remover usuário do grupo',
        )


def listar_grupos_usuario(id_usuario):
    """Lista os grupos aos quais o usuário pertence."""
    resposta = _requisitar(
        'GET', f'{_url_admin_realm()}/users/{id_usuario}/groups'
    )
    return _verificar(resposta, 'listar grupos do usuário').json()


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
