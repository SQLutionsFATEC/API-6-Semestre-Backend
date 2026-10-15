"""Testes unitários do cliente da Admin REST API do Keycloak.

Todas as chamadas HTTP são simuladas com fakes de requests, sem acesso
real ao Keycloak."""

import pytest

from api.services import keycloak_admin
from api.services.keycloak_admin import (
    KeycloakAdminException,
    criar_usuario,
    atualizar_usuario,
    deletar_usuario,
    definir_senha,
    listar_papeis_realm_usuario,
    listar_papeis_usuario,
    listar_usuarios,
    limpar_token_admin,
    obter_token_admin,
    obter_usuario,
    trocar_nivel_acesso,
)

ID_USUARIO = 'id-usuario-9'


class RespostaFake:
    def __init__(self, status_code=200, dados=None, headers=None, text=''):
        self.status_code = status_code
        self._json = dados if dados is not None else {}
        self.headers = headers or {}
        self.text = text or ''

    def json(self):
        return self._json


@pytest.fixture(autouse=True)
def token_simulado(monkeypatch):
    """Simula a obtenção do token do administrador."""
    resposta = RespostaFake(
        status_code=200,
        dados={'access_token': 'token-admin', 'expires_in': 600},
    )
    chamados = []

    def post_simulado(url, data=None, timeout=None):
        chamados.append((url, data))
        return resposta

    monkeypatch.setattr(keycloak_admin.requests, 'post', post_simulado)
    limpar_token_admin()
    yield chamados
    limpar_token_admin()


@pytest.fixture
def envio(monkeypatch):
    """Captura todas as requisições (metodo, url, kwargs) e devolve respostas."""
    respostas = []

    def enfileirar(*respostas_previstas):
        respostas.extend(respostas_previstas)
        return respostas_previstas

    feitas = []

    def request_simulado(metodo, url, headers=None, timeout=None, **kwargs):
        feitas.append({'metodo': metodo, 'url': url, **kwargs})
        if not respostas:
            raise AssertionError('Requisição inesperada: ' + metodo + ' ' + url)
        return respostas.pop(0)

    monkeypatch.setattr(keycloak_admin.requests, 'request', request_simulado)
    return feitas, enfileirar


def test_token_admin_obtido_e_reutilizado(token_simulado):
    primeiro = obter_token_admin()
    segundo = obter_token_admin()

    assert primeiro == 'token-admin'
    assert segundo == 'token-admin'
    assert len(token_simulado) == 1  # apenas um POST de token


def test_criar_usuario_monta_payload_com_senha_temporaria(envio):
    feitas, enfileirar = envio
    enfileirar(
        RespostaFake(status_code=201, headers={'Location': '/users/' + ID_USUARIO}),
        # GET /roles/<nome> para obter o id da role
        RespostaFake(status_code=200, dados={'id': 'role-1', 'name': 'comercial'}),
        # POST /users/<id>/role-mappings/realm para atribuir a role
        RespostaFake(status_code=204),
        RespostaFake(status_code=200, dados={'id': ID_USUARIO, 'username': 'novo@exemplo.com'}),
    )

    usuario = criar_usuario(
        'Novo', 'Usuário', 'novo@exemplo.com', 'senha-provisoria',
        nivel_acesso='comercial', setor='qualitativo',
    )

    assert usuario['id'] == ID_USUARIO
    autenticada, role, atribuicao, leitura = feitas
    payload = autenticada['json']
    assert autenticada['metodo'] == 'POST'
    assert payload['firstName'] == 'Novo'
    assert payload['lastName'] == 'Usuário'
    assert payload['email'] == 'novo@exemplo.com'
    assert payload['attributes'] == {'setor': ['qualitativo']}
    credencial = payload['credentials'][0]
    assert credencial['value'] == 'senha-provisoria'
    assert credencial['temporary'] is True
    # A role de nível é atribuída por chamada dedicada (Keycloak 26
    # ignora 'realmRoles' no payload de criação)
    assert atribuicao['metodo'] == 'POST'
    assert atribuicao['url'].endswith('/role-mappings/realm')
    assert atribuicao['json'] == [{'id': 'role-1', 'name': 'comercial'}]
    assert leitura['metodo'] == 'GET'


def test_criar_usuario_aplica_padroes_de_negocio(envio):
    feitas, enfileirar = envio
    enfileirar(
        RespostaFake(status_code=201, headers={'Location': '/users/' + ID_USUARIO}),
        RespostaFake(status_code=200, dados={'id': 'role-1', 'name': 'basico'}),
        RespostaFake(status_code=204),
        RespostaFake(status_code=200, dados={'id': ID_USUARIO}),
    )

    criar_usuario('Padrão', 'Negócio', 'padrao@exemplo.com', 'senha')

    payload = feitas[0]['json']
    assert payload['attributes'] == {'setor': ['tecnico']}
    assert feitas[2]['json'] == [{'id': 'role-1', 'name': 'basico'}]


def test_criar_usuario_com_nivel_invalido_levanta_erro(envio):
    _, enfileirar = envio

    with pytest.raises(ValueError):
        criar_usuario('X', 'Y', 'x@exemplo.com', 'senha', nivel_acesso='raiz')


def test_criar_usuario_com_setor_invalido_levanta_erro(envio):
    _, enfileirar = envio

    with pytest.raises(ValueError):
        criar_usuario('X', 'Y', 'x@exemplo.com', 'senha', setor='rh')


def test_obter_usuario_retorna_campos(envio):
    feitas, enfileirar = envio
    enfileirar(RespostaFake(status_code=200, dados={'id': ID_USUARIO, 'email': 'a@b.com'}))

    usuario = obter_usuario(ID_USUARIO)

    assert usuario['email'] == 'a@b.com'
    assert feitas[0]['url'].endswith('/users/' + ID_USUARIO)


def test_listar_usuarios_passa_filtro_de_busca(envio):
    feitas, enfileirar = envio
    enfileirar(RespostaFake(status_code=200, dados=[]))

    listar_usuarios(busca='maria', inicio=10, maximo=5)

    assert feitas[0]['params'] == {'search': 'maria', 'first': 10, 'max': 5}


def test_atualizar_usuario_muda_nome_email_setor_e_senha(envio):
    feitas, enfileirar = envio
    enfileirar(
        # GET do usuário atual (para o merge que preserva os campos)
        RespostaFake(status_code=200, dados={'id': ID_USUARIO, 'lastName': 'Antigo'}),
        RespostaFake(status_code=204),          # PUT dos campos
        RespostaFake(status_code=204),          # PUT /reset-password
        RespostaFake(status_code=200, dados={'id': ID_USUARIO}),
    )

    atualizar_usuario(
        ID_USUARIO,
        nome='Nome Novo',
        email='novo@exemplo.com',
        setor='normativo',
        senha='nova-senha',
        senha_temporaria=False,
    )

    metodos = [(chamada['metodo'], chamada['url']) for chamada in feitas]
    assert ('GET', keycloak_admin._url_admin_realm() + '/users/' + ID_USUARIO) == metodos[0]
    assert ('PUT', keycloak_admin._url_admin_realm() + '/users/' + ID_USUARIO) == metodos[1]
    assert metodos[2][0] == 'PUT'
    assert metodos[2][1].endswith('/reset-password')
    payload = feitas[1]['json']
    assert payload['firstName'] == 'Nome Novo'
    assert payload['email'] == 'novo@exemplo.com'
    assert payload['attributes'] == {'setor': ['normativo']}
    payload_senha = feitas[2]['json']
    assert payload_senha == {'type': 'password', 'value': 'nova-senha', 'temporary': False}
    # Campos não enviados são preservados no PUT (representação completa)
    assert feitas[1]['json']['lastName'] == 'Antigo'


def test_atualizar_usuario_somente_senha_mantem_campos_e_muda_senha(envio):
    feitas, enfileirar = envio
    enfileirar(
        # leitura p/ merge (preserva firstName/lastName/email)
        RespostaFake(status_code=200, dados={
            'id': ID_USUARIO, 'firstName': 'Joao',
            'lastName': 'Soares', 'email': 'soares@x.com',
        }),
        RespostaFake(status_code=204),                            # PUT dos campos
        RespostaFake(status_code=204),                            # PUT /reset-password
        RespostaFake(status_code=200, dados={'id': ID_USUARIO}),  # leitura final
    )

    atualizar_usuario(ID_USUARIO, senha='so-senha')

    metodos = [chamada['metodo'] for chamada in feitas]
    assert metodos == ['GET', 'PUT', 'PUT', 'GET']
    assert feitas[1]['json']['firstName'] == 'Joao'
    assert feitas[2]['url'].endswith('/reset-password')


def test_atualizar_usuario_preserva_campos_quando_muda_somente_setor(envio):
    feitas, enfileirar = envio
    enfileirar(
        RespostaFake(status_code=200, dados={
            'id': ID_USUARIO, 'firstName': 'Maria', 'lastName': 'Silva',
            'email': 'maria@x.com',
        }),
        RespostaFake(status_code=204),  # PUT com payload mesclado
        RespostaFake(status_code=200, dados={'id': ID_USUARIO}),
    )

    atualizar_usuario(ID_USUARIO, setor='qualitativo')

    payload = feitas[1]['json']
    assert payload['attributes'] == {'setor': ['qualitativo']}
    assert payload['firstName'] == 'Maria'
    assert payload['lastName'] == 'Silva'
    assert payload['email'] == 'maria@x.com'


def test_trocar_nivel_acesso_remove_antiga_e_atribui_nova(envio):
    feitas, enfileirar = envio
    enfileirar(
        # GET(role-mappings/realm) -> role atual basico
        RespostaFake(status_code=200, dados=[
            {'id': 'r1', 'name': 'basico'},
            {'id': 'r2', 'name': 'offline_access'},
        ]),
        # DELETE da role antiga
        RespostaFake(status_code=204),
        # GET da definição da nova role
        RespostaFake(status_code=200, dados={'id': 'r3', 'name': 'operador'}),
        # POST atribuindo a nova role
        RespostaFake(status_code=204),
    )

    trocar_nivel_acesso(ID_USUARIO, 'operador')

    metodos = [chamada['metodo'] for chamada in feitas]
    assert metodos == ['GET', 'DELETE', 'GET', 'POST']
    removidos = feitas[1]['json']
    atribuido = feitas[3]['json'][0]
    assert removidos == [{'id': 'r1', 'name': 'basico'}]
    assert atribuido['name'] == 'operador'


def test_deletar_usuario_chama_delete(envio):
    feitas, enfileirar = envio
    enfileirar(RespostaFake(status_code=204))

    deletar_usuario(ID_USUARIO)

    assert feitas[0]['metodo'] == 'DELETE'


def test_deletar_usuario_inexistente_levanta_404(envio):
    _, enfileirar = envio
    enfileirar(RespostaFake(status_code=404, text='not found'))

    with pytest.raises(KeycloakAdminException) as erro:
        deletar_usuario(ID_USUARIO)

    assert erro.value.codigo_status == 404


def test_definir_senha_temporaria(envio):
    feitas, enfileirar = envio
    enfileirar(RespostaFake(status_code=204))

    definir_senha(ID_USUARIO, 'temporaria-123', temporaria=True)

    assert feitas[0]['json'] == {
        'type': 'password', 'value': 'temporaria-123', 'temporary': True
    }


def test_listar_papeis_usuario_retorna_permissões(envio):
    feitas, enfileirar = envio
    enfileirar(RespostaFake(status_code=200, dados={'realmMappings': [{'name': 'operador'}]}))

    papeis = listar_papeis_usuario(ID_USUARIO)

    assert papeis['realmMappings'][0]['name'] == 'operador'
    assert feitas[0]['url'].endswith('/role-mappings')


def test_listar_papeis_realm_usuario(envio):
    feitas, enfileirar = envio
    enfileirar(RespostaFake(status_code=200, dados=[{'name': 'basico'}]))

    papeis = listar_papeis_realm_usuario(ID_USUARIO)

    assert papeis == [{'name': 'basico'}]
    assert feitas[0]['url'].endswith('/role-mappings/realm')


def test_resposta_com_erro_levanta_excecao(envio):
    _, enfileirar = envio
    enfileirar(RespostaFake(status_code=409, text='conflict'))

    with pytest.raises(KeycloakAdminException) as erro:
        obter_usuario('qualquer')

    assert erro.value.codigo_status == 409
