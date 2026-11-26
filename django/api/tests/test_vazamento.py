from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.db import connections
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase
from unittest.mock import patch, mock_open

from api.db_routers import VAZAMENTO_DB
from api.management.commands import generate_leak
from api.models import Vazamento
from api.serializers.vazamento_serializer import VazamentoSerializer
from api.services import aviso_vazamento
from api.views import vazamento_api
from io import StringIO

UserModel = get_user_model()


class VazamentoViewTests(APITestCase):
    # Os avisos de vazamento vivem no banco independente 'leaks'.
    databases = {'default', VAZAMENTO_DB}

    def setUp(self):
        self.url = '/api/vazamentos/'
        self.vazamento = Vazamento.objects.using(VAZAMENTO_DB).create()
        self.user = UserModel.objects.create_user(
            username='testuser',
            password='testpassword'
        )

    @patch('api.views.vazamento_api._sinalizar_restauracao_backup')
    def test_get_retorna_vazamento_mais_recente(self, mock_sinalizar):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.vazamento.id))

    def test_get_sem_vazamentos_retorna_404(self):
        Vazamento.objects.using(VAZAMENTO_DB).all().delete()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch('api.views.vazamento_api._sinalizar_restauracao_backup')
    def test_post_sem_autenticacao_retorna_401(self, mock_sinalizar):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch('api.views.vazamento_api.keycloak_admin.listar_papeis_realm_usuario')
    @patch('api.views.vazamento_api._sinalizar_restauracao_backup')
    def test_post_usuario_comum_retorna_403(self, mock_sinalizar, mock_roles):
        mock_roles.return_value = ['usuario']
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch('api.views.vazamento_api.keycloak_admin.listar_papeis_realm_usuario')
    @patch('api.views.vazamento_api._sinalizar_restauracao_backup')
    def test_post_operador_retorna_201(self, mock_sinalizar, mock_roles):
        mock_roles.return_value = ['operador']
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mock_sinalizar.assert_called_once()
        self.assertTrue(
            Vazamento.objects.using(VAZAMENTO_DB).filter(pk=response.data['id']).exists()
        )

    @patch('api.views.vazamento_api.keycloak_admin.listar_papeis_realm_usuario')
    def test_post_falha_keycloak_retorna_502(self, mock_roles):
        mock_roles.side_effect = Exception("Erro de conexão simulado")
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)

    @patch('api.views.vazamento_api.keycloak_admin.listar_papeis_realm_usuario')
    @patch('api.views.vazamento_api._sinalizar_restauracao_backup')
    def test_post_falha_ao_criar_flag_retorna_500(self, mock_sinalizar, mock_roles):
        # Simula o operador, mas faz a criação do arquivo de sinalização falhar
        mock_roles.return_value = ['operador']
        mock_sinalizar.side_effect = Exception("Falha ao criar o arquivo de flag")

        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    @patch('api.management.commands.generate_leak._sinalizar_restauracao_backup')
    def test_comando_generate_leak(self, mock_sinalizar):
        out = StringIO()
        call_command('generate_leak', stdout=out)
        self.assertIn('Incidente registrado com sucesso!', out.getvalue())
        mock_sinalizar.assert_called_once()

    @patch('api.management.commands.generate_leak._sinalizar_restauracao_backup')
    def test_comando_generate_leak_grava_no_banco_de_vazamentos(self, mock_sinalizar):
        antes = Vazamento.objects.using(VAZAMENTO_DB).count()
        call_command('generate_leak', stdout=StringIO())
        self.assertEqual(Vazamento.objects.using(VAZAMENTO_DB).count(), antes + 1)

    def test_vazamento_e_gravado_apenas_no_banco_de_leaks(self):
        self.assertTrue(
            Vazamento.objects.using(VAZAMENTO_DB).filter(pk=self.vazamento.pk).exists()
        )
        # A tabela não existe no banco principal: uma restauração de backup do
        # banco da aplicação não pode apagar o registro do vazamento.
        self.assertNotIn(
            'vazamentos', connections['default'].introspection.table_names()
        )

    def test_timestamp_registra_data_e_hora_completas(self):
        vazamento = Vazamento.objects.using(VAZAMENTO_DB).create()

        self.assertIsNotNone(vazamento.timestamp.tzinfo)
        self.assertLess(
            abs(timezone.now() - vazamento.timestamp), timedelta(minutes=1)
        )
        # O valor exposto pela API é um datetime completo (data + hora), não
        # apenas a data.
        self.assertIn('T', VazamentoSerializer(vazamento).data['timestamp'])

    def test_modelo_vazamento_str(self):
        vazamento = Vazamento.objects.using(VAZAMENTO_DB).first()
        self.assertTrue(str(vazamento).startswith('Vazamento'))

    @patch('api.views.vazamento_api.keycloak_admin.listar_papeis_realm_usuario')
    @patch('api.views.vazamento_api.os.makedirs')
    @patch('builtins.open', new_callable=mock_open)
    def test_post_cria_arquivo_de_flag(self, mock_file, mock_makedirs, mock_roles):
        """Garante que o arquivo TRIGGER_RESTORE.flag é criado quando não há erros."""
        mock_roles.return_value = ['operador']
        self.client.force_authenticate(user=self.user)

        response = self.client.post(self.url)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        # Verifica se o open() foi chamado com o nome do arquivo correto
        mock_file.assert_called_once_with('/app/backups/TRIGGER_RESTORE.flag', 'w')


# ============================================================
# Aviso por e-mail aos usuários afetados pelo vazamento
# ============================================================

USUARIOS_DO_REALM = [
    {'id': '1', 'username': 'maria@example.com', 'email': 'maria@example.com'},
    {'id': '2', 'username': 'joao@example.com', 'email': 'joao@example.com'},
    {'id': '3', 'username': 'anonimizado-abc', 'email': 'abc@invalid.local'},
    {
        'id': '4',
        'username': 'service-account-backend',
        'email': 'servico@example.com',
    },
    {'id': '5', 'username': 'sem-email', 'email': ''},
    {
        'id': '6',
        'username': 'integracao',
        'email': 'integracao@example.com',
        'attributes': {'serviceAccountClientId': ['backend']},
    },
]

DESTINATARIOS_ELEGIVEIS = ['maria@example.com', 'joao@example.com']

no_banco_de_vazamentos = pytest.mark.django_db(databases=['default', VAZAMENTO_DB])


@pytest.fixture(autouse=True)
def caixa_de_saida(settings):
    """Substitui o envio real por uma caixa de saída em memória (locmem)."""
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    if hasattr(mail, 'outbox'):
        mail.outbox.clear()
    yield
    if hasattr(mail, 'outbox'):
        mail.outbox.clear()


def _mensagens():
    return list(getattr(mail, 'outbox', []))


def _patch_usuarios(monkeypatch, usuarios=None):
    usuarios = USUARIOS_DO_REALM if usuarios is None else usuarios

    def listar_usuarios(busca=None, inicio=0, maximo=100):
        return usuarios if inicio == 0 else []

    monkeypatch.setattr(
        aviso_vazamento.keycloak_admin, 'listar_usuarios', listar_usuarios
    )


def _cliente_autenticado():
    usuario = UserModel.objects.create_user(
        username='operador', password='senha-teste'
    )
    cliente = APIClient()
    cliente.force_authenticate(user=usuario)
    return cliente


def _send_mail_com_falha(*args, **kwargs):
    raise RuntimeError('SMTP indisponível')


def _capturar_erros(monkeypatch):
    """Registra as mensagens logadas como erro (o logger 'api' não propaga)."""
    erros = []
    monkeypatch.setattr(
        aviso_vazamento.logger, 'exception', lambda mensagem, *args, **kwargs: erros.append(mensagem)
    )
    return erros


@no_banco_de_vazamentos
def test_generate_leak_envia_um_email_por_destinatario_elegivel(monkeypatch):
    _patch_usuarios(monkeypatch)
    monkeypatch.setattr(
        generate_leak, '_sinalizar_restauracao_backup', lambda: None
    )

    call_command('generate_leak', stdout=StringIO())

    mensagens = _mensagens()
    assert [mensagem.to for mensagem in mensagens] == [
        [email] for email in DESTINATARIOS_ELEGIVEIS
    ]

    vazamento = Vazamento.objects.using(VAZAMENTO_DB).first()
    momento = timezone.localtime(vazamento.timestamp).strftime(
        '%d/%m/%Y às %H:%M:%S'
    )
    for mensagem in mensagens:
        assert mensagem.subject == aviso_vazamento.ASSUNTO
        assert momento in mensagem.body
        for dado in aviso_vazamento.DADOS_AFETADOS:
            assert dado in mensagem.body
        assert 'troque a senha' in mensagem.body
        assert settings.SUPORTE_EMAIL in mensagem.body


@no_banco_de_vazamentos
def test_listar_destinatarios_ignora_invalid_local_e_service_accounts(monkeypatch):
    _patch_usuarios(monkeypatch)

    destinatarios = aviso_vazamento.listar_destinatarios()

    assert destinatarios == DESTINATARIOS_ELEGIVEIS
    assert not any(email.endswith('@invalid.local') for email in destinatarios)


def test_montar_mensagem_nao_expoe_detalhe_interno():
    vazamento = Vazamento(timestamp=timezone.now())

    _, mensagem = aviso_vazamento.montar_mensagem(vazamento)

    for detalhe in ('leaks', 'keycloak', 'pg_restore', 'TRIGGER_RESTORE'):
        assert detalhe not in mensagem


@no_banco_de_vazamentos
def test_generate_leak_sem_destinatarios_nao_falha(monkeypatch):
    _patch_usuarios(monkeypatch, usuarios=[])
    monkeypatch.setattr(
        generate_leak, '_sinalizar_restauracao_backup', lambda: None
    )
    out = StringIO()

    call_command('generate_leak', stdout=out)

    assert 'Incidente registrado com sucesso!' in out.getvalue()
    assert 'enviado para 0 destinatário(s)' in out.getvalue()
    assert _mensagens() == []


@no_banco_de_vazamentos
def test_falha_de_envio_nao_impede_registro_e_flag(monkeypatch):
    _patch_usuarios(monkeypatch)
    erros = _capturar_erros(monkeypatch)
    flag = []
    monkeypatch.setattr(
        generate_leak,
        '_sinalizar_restauracao_backup',
        lambda: flag.append(True),
    )
    monkeypatch.setattr(aviso_vazamento, 'send_mail', _send_mail_com_falha)
    antes = Vazamento.objects.using(VAZAMENTO_DB).count()
    out = StringIO()

    call_command('generate_leak', stdout=out)

    assert Vazamento.objects.using(VAZAMENTO_DB).count() == antes + 1
    assert flag == [True]
    assert 'Incidente registrado com sucesso!' in out.getvalue()
    assert any('Falha ao enviar o aviso de vazamento' in erro for erro in erros)


@no_banco_de_vazamentos
def test_falha_do_keycloak_nao_impede_registro_e_flag(monkeypatch):
    def listar_usuarios_com_falha(**kwargs):
        raise RuntimeError('Keycloak indisponível')

    monkeypatch.setattr(
        aviso_vazamento.keycloak_admin, 'listar_usuarios', listar_usuarios_com_falha
    )
    erros = _capturar_erros(monkeypatch)
    flag = []
    monkeypatch.setattr(
        generate_leak,
        '_sinalizar_restauracao_backup',
        lambda: flag.append(True),
    )
    antes = Vazamento.objects.using(VAZAMENTO_DB).count()

    call_command('generate_leak', stdout=StringIO())

    assert Vazamento.objects.using(VAZAMENTO_DB).count() == antes + 1
    assert flag == [True]
    assert any('Falha ao listar os usuários' in erro for erro in erros)
    assert _mensagens() == []


@no_banco_de_vazamentos
def test_post_operador_envia_os_mesmos_avisos(monkeypatch):
    _patch_usuarios(monkeypatch)
    monkeypatch.setattr(
        vazamento_api.keycloak_admin,
        'listar_papeis_realm_usuario',
        lambda *args, **kwargs: ['operador'],
    )
    monkeypatch.setattr(
        vazamento_api, '_sinalizar_restauracao_backup', lambda: None
    )

    resposta = _cliente_autenticado().post('/api/vazamentos/')

    assert resposta.status_code == status.HTTP_201_CREATED
    mensagens = _mensagens()
    assert [mensagem.to for mensagem in mensagens] == [
        [email] for email in DESTINATARIOS_ELEGIVEIS
    ]
    vazamento = Vazamento.objects.using(VAZAMENTO_DB).get(pk=resposta.data['id'])
    momento = timezone.localtime(vazamento.timestamp).strftime(
        '%d/%m/%Y às %H:%M:%S'
    )
    for mensagem in mensagens:
        assert mensagem.subject == aviso_vazamento.ASSUNTO
        assert momento in mensagem.body
        assert 'documentos' in mensagem.body


@no_banco_de_vazamentos
def test_post_falha_de_envio_mantem_201_e_cria_flag(monkeypatch):
    _patch_usuarios(monkeypatch)
    erros = _capturar_erros(monkeypatch)
    monkeypatch.setattr(
        vazamento_api.keycloak_admin,
        'listar_papeis_realm_usuario',
        lambda *args, **kwargs: ['operador'],
    )
    flag = []
    monkeypatch.setattr(
        vazamento_api,
        '_sinalizar_restauracao_backup',
        lambda: flag.append(True),
    )
    monkeypatch.setattr(aviso_vazamento, 'send_mail', _send_mail_com_falha)

    resposta = _cliente_autenticado().post('/api/vazamentos/')

    assert resposta.status_code == status.HTTP_201_CREATED
    assert flag == [True]
    assert Vazamento.objects.using(VAZAMENTO_DB).filter(pk=resposta.data['id']).exists()
    assert any('Falha ao enviar o aviso de vazamento' in erro for erro in erros)


@no_banco_de_vazamentos
def test_post_sem_autenticacao_nao_envia_email(monkeypatch):
    _patch_usuarios(monkeypatch)

    resposta = APIClient().post('/api/vazamentos/')

    assert resposta.status_code == status.HTTP_401_UNAUTHORIZED
    assert _mensagens() == []


@no_banco_de_vazamentos
def test_post_sem_role_operador_nao_envia_email(monkeypatch):
    _patch_usuarios(monkeypatch)
    monkeypatch.setattr(
        vazamento_api.keycloak_admin,
        'listar_papeis_realm_usuario',
        lambda *args, **kwargs: ['usuario'],
    )

    resposta = _cliente_autenticado().post('/api/vazamentos/')

    assert resposta.status_code == status.HTTP_403_FORBIDDEN
    assert _mensagens() == []


@no_banco_de_vazamentos
def test_post_com_falha_no_keycloak_nao_envia_email(monkeypatch):
    _patch_usuarios(monkeypatch)

    def falha(*args, **kwargs):
        raise RuntimeError('Keycloak fora do ar')

    monkeypatch.setattr(
        vazamento_api.keycloak_admin, 'listar_papeis_realm_usuario', falha
    )

    resposta = _cliente_autenticado().post('/api/vazamentos/')

    assert resposta.status_code == status.HTTP_502_BAD_GATEWAY
    assert _mensagens() == []
