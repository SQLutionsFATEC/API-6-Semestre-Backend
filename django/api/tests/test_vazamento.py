from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase
from unittest.mock import patch, mock_open
from api.models import Vazamento
from io import StringIO
from django.core.management import call_command
import os

UserModel = get_user_model()

class VazamentoViewTests(APITestCase):
    def setUp(self):
        self.url = '/api/vazamentos/'
        self.vazamento = Vazamento.objects.create()
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
        Vazamento.objects.all().delete()
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

    def test_modelo_vazamento_str(self):
        vazamento = Vazamento.objects.first()
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