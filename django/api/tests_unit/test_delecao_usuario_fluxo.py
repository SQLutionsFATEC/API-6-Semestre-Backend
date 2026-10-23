"""Testes do fluxo de anonimização com tombstone e e-mail de comprovação."""

import pytest
from django.core import mail

from api.models import UsuarioDeletado
from api.services import delecao_usuario, keycloak_admin
from api.services.delecao_usuario import (
    anonimizar_usuario,
    hash_id_usuario,
    listar_hashes_usuarios_deletados,
    usuario_esta_deletado,
)
from api.services.keycloak_admin import KeycloakAdminException

ID_USUARIO = '9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d'

USUARIO = {
    'id': ID_USUARIO,
    'username': 'maria@example.com',
    'firstName': 'Maria',
    'lastName': 'Silva',
    'email': 'maria@example.com',
    'enabled': True,
}


@pytest.fixture(autouse=True)
def email_em_memoria(settings):
    """Substitui o envio real de e-mail por uma caixa de saída em memória."""
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    mail.outbox.clear()
    yield
    mail.outbox.clear()


def _mock_obter(monkeypatch, usuario=None, erro=None):
    def obter(id_usuario):
        if erro is not None:
            raise erro
        return dict(usuario or USUARIO, id=id_usuario)

    monkeypatch.setattr(keycloak_admin, 'obter_usuario', obter)


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_anonimizar_cria_tombstone_pendente_antes_de_alterar_o_keycloak(monkeypatch):
    chamadas = []

    def anonimizar(id_usuario, sufixo):
        registro = UsuarioDeletado.objects.using('tombstones').get()
        chamadas.append((id_usuario, sufixo, registro.confirmado_em))

    _mock_obter(monkeypatch)
    monkeypatch.setattr(keycloak_admin, 'anonimizar_usuario', anonimizar)

    usuario = anonimizar_usuario(ID_USUARIO, origem=UsuarioDeletado.ORIGEM_OPERADOR)

    assert usuario['id'] == ID_USUARIO
    # O tombstone já existia, mas ainda pendente, quando o Keycloak foi chamado.
    assert chamadas == [(ID_USUARIO, hash_id_usuario(ID_USUARIO), None)]
    assert usuario_esta_deletado(ID_USUARIO) is True

    registro = UsuarioDeletado.objects.using('tombstones').get()
    assert registro.origem == UsuarioDeletado.ORIGEM_OPERADOR
    assert registro.confirmado_em is not None


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_anonimizar_envia_email_de_comprovacao(monkeypatch):
    _mock_obter(monkeypatch)
    monkeypatch.setattr(
        keycloak_admin, 'anonimizar_usuario', lambda id_usuario, sufixo: None
    )

    anonimizar_usuario(ID_USUARIO)

    assert usuario_esta_deletado(ID_USUARIO) is True
    assert len(mail.outbox) == 1
    mensagem = mail.outbox[0]
    assert mensagem.to == ['maria@example.com']
    assert 'anonimizada' in mensagem.subject
    assert 'comprovação' in mensagem.body
    assert 'Maria' in mensagem.body


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_usuario_inexistente_retorna_404_sem_criar_tombstone(monkeypatch):
    _mock_obter(
        monkeypatch,
        erro=KeycloakAdminException('Usuário não encontrado.', codigo_status=404),
    )
    chamadas = []
    monkeypatch.setattr(
        keycloak_admin,
        'anonimizar_usuario',
        lambda id_usuario, sufixo: chamadas.append(id_usuario),
    )

    with pytest.raises(KeycloakAdminException) as erro:
        anonimizar_usuario(ID_USUARIO)

    assert erro.value.codigo_status == 404
    assert chamadas == []
    assert usuario_esta_deletado(ID_USUARIO) is False
    assert mail.outbox == []


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_falha_no_keycloak_deixa_tombstone_pendente(monkeypatch):
    _mock_obter(monkeypatch)

    def anonimizar(id_usuario, sufixo):
        raise KeycloakAdminException('Falha no Keycloak.', codigo_status=500)

    monkeypatch.setattr(keycloak_admin, 'anonimizar_usuario', anonimizar)

    with pytest.raises(KeycloakAdminException):
        anonimizar_usuario(ID_USUARIO)

    # A intenção fica registrada, mas não conta como exclusão concluída.
    registro = UsuarioDeletado.objects.using('tombstones').get()
    assert registro.confirmado_em is None
    assert usuario_esta_deletado(ID_USUARIO) is False
    assert listar_hashes_usuarios_deletados() == []
    assert mail.outbox == []


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_retry_apos_falha_confirma_tombstone(monkeypatch):
    _mock_obter(monkeypatch)
    tentativas = {'quantidade': 0}

    def anonimizar(id_usuario, sufixo):
        tentativas['quantidade'] += 1
        if tentativas['quantidade'] == 1:
            raise KeycloakAdminException('Falha no Keycloak.', codigo_status=500)

    monkeypatch.setattr(keycloak_admin, 'anonimizar_usuario', anonimizar)

    with pytest.raises(KeycloakAdminException):
        anonimizar_usuario(ID_USUARIO)
    assert usuario_esta_deletado(ID_USUARIO) is False

    anonimizar_usuario(ID_USUARIO)

    assert tentativas['quantidade'] == 2
    assert usuario_esta_deletado(ID_USUARIO) is True
    assert len(mail.outbox) == 1


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_anonimizacao_404_apos_leitura_confirma_como_ja_deletado(monkeypatch):
    _mock_obter(monkeypatch)

    def anonimizar(id_usuario, sufixo):
        raise KeycloakAdminException('Usuário não encontrado.', codigo_status=404)

    monkeypatch.setattr(keycloak_admin, 'anonimizar_usuario', anonimizar)

    usuario = anonimizar_usuario(ID_USUARIO)

    assert usuario['id'] == ID_USUARIO
    assert usuario_esta_deletado(ID_USUARIO) is True
    assert len(mail.outbox) == 1


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_falha_de_email_nao_desfaz_a_anonimizacao(monkeypatch):
    _mock_obter(monkeypatch)
    monkeypatch.setattr(
        keycloak_admin, 'anonimizar_usuario', lambda id_usuario, sufixo: None
    )

    def send_mail_com_falha(*args, **kwargs):
        raise RuntimeError('SMTP indisponível')

    monkeypatch.setattr(delecao_usuario, 'send_mail', send_mail_com_falha)

    usuario = anonimizar_usuario(ID_USUARIO)

    assert usuario['id'] == ID_USUARIO
    assert usuario_esta_deletado(ID_USUARIO) is True
    registro = UsuarioDeletado.objects.using('tombstones').get()
    assert registro.confirmado_em is not None


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_usuario_sem_email_nao_impede_a_anonimizacao(monkeypatch):
    _mock_obter(monkeypatch, usuario=dict(USUARIO, email=''))
    monkeypatch.setattr(
        keycloak_admin, 'anonimizar_usuario', lambda id_usuario, sufixo: None
    )

    usuario = anonimizar_usuario(ID_USUARIO)

    assert usuario['id'] == ID_USUARIO
    assert usuario_esta_deletado(ID_USUARIO) is True
    assert len(mail.outbox) == 0
