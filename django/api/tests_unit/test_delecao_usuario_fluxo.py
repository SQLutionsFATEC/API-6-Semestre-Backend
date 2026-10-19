"""Testes do fluxo de deleção física com tombstone e e-mail de comprovação."""

import pytest
from django.core import mail

from api.models import UsuarioDeletado
from api.services import delecao_usuario, keycloak_admin
from api.services.delecao_usuario import deletar_usuario, usuario_esta_deletado
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
def test_deletar_grava_tombstone_antes_de_remover_do_keycloak(monkeypatch):
    chamadas = []

    def deletar(id_usuario):
        chamadas.append((id_usuario, usuario_esta_deletado(id_usuario)))

    _mock_obter(monkeypatch)
    monkeypatch.setattr(keycloak_admin, 'deletar_usuario', deletar)

    usuario = deletar_usuario(ID_USUARIO, origem=UsuarioDeletado.ORIGEM_OPERADOR)

    assert usuario['id'] == ID_USUARIO
    # O tombstone já existia no momento em que o Keycloak foi chamado.
    assert chamadas == [(ID_USUARIO, True)]
    assert usuario_esta_deletado(ID_USUARIO) is True

    registro = UsuarioDeletado.objects.using('tombstones').get()
    assert registro.origem == UsuarioDeletado.ORIGEM_OPERADOR


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_deletar_envia_email_de_comprovacao(monkeypatch):
    _mock_obter(monkeypatch)
    monkeypatch.setattr(keycloak_admin, 'deletar_usuario', lambda id_usuario: None)

    deletar_usuario(ID_USUARIO)

    assert len(mail.outbox) == 1
    mensagem = mail.outbox[0]
    assert mensagem.to == ['maria@example.com']
    assert 'excluída permanentemente' in mensagem.subject
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
        keycloak_admin, 'deletar_usuario', lambda id_usuario: chamadas.append(id_usuario)
    )

    with pytest.raises(KeycloakAdminException) as erro:
        deletar_usuario(ID_USUARIO)

    assert erro.value.codigo_status == 404
    assert chamadas == []
    assert usuario_esta_deletado(ID_USUARIO) is False
    assert mail.outbox == []


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_falha_no_keycloak_preserva_tombstone_para_nao_ressuscitar(monkeypatch):
    _mock_obter(monkeypatch)

    def deletar(id_usuario):
        raise KeycloakAdminException('Falha no Keycloak.', codigo_status=500)

    monkeypatch.setattr(keycloak_admin, 'deletar_usuario', deletar)

    with pytest.raises(KeycloakAdminException):
        deletar_usuario(ID_USUARIO)

    # O tombstone permanece: uma restauração futura não traz o usuário de volta.
    assert usuario_esta_deletado(ID_USUARIO) is True
    assert mail.outbox == []


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_falha_de_email_nao_desfaz_a_exclusao(monkeypatch):
    _mock_obter(monkeypatch)
    monkeypatch.setattr(keycloak_admin, 'deletar_usuario', lambda id_usuario: None)

    def send_mail_com_falha(*args, **kwargs):
        raise RuntimeError('SMTP indisponível')

    monkeypatch.setattr(delecao_usuario, 'send_mail', send_mail_com_falha)

    usuario = deletar_usuario(ID_USUARIO)

    assert usuario['id'] == ID_USUARIO
    assert usuario_esta_deletado(ID_USUARIO) is True


@pytest.mark.django_db(databases=['default', 'tombstones'])
def test_usuario_sem_email_nao_impede_a_exclusao(monkeypatch):
    _mock_obter(monkeypatch, usuario=dict(USUARIO, email=''))
    monkeypatch.setattr(keycloak_admin, 'deletar_usuario', lambda id_usuario: None)

    usuario = deletar_usuario(ID_USUARIO)

    assert usuario['id'] == ID_USUARIO
    assert usuario_esta_deletado(ID_USUARIO) is True
    assert len(mail.outbox) == 0
