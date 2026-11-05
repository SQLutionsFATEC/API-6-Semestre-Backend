from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase
from unittest.mock import patch
from api.models import Vazamento
from io import StringIO
from django.core.management import call_command
import subprocess

UserModel = get_user_model()


class VazamentoViewTests(APITestCase):
    def setUp(self):
        self.url = '/api/vazamentos/'
        self.vazamento = Vazamento.objects.create()
        self.user = UserModel.objects.create_user(
            username='testuser',
            password='testpassword'
        )

    @patch('api.views.vazamento_api._executar_restauracao_backup')
    def test_get_retorna_vazamento_mais_recente(self, mock_backup):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], str(self.vazamento.id))

    def test_get_sem_vazamentos_retorna_404(self):
        Vazamento.objects.all().delete()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch('api.views.vazamento_api._executar_restauracao_backup')
    def test_post_sem_autenticacao_retorna_401(self, mock_backup):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch('api.views.vazamento_api.keycloak_admin.listar_papeis_realm_usuario')
    @patch('api.views.vazamento_api._executar_restauracao_backup')
    def test_post_usuario_comum_retorna_403(self, mock_backup, mock_roles):
        mock_roles.return_value = ['usuario']
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch('api.views.vazamento_api.keycloak_admin.listar_papeis_realm_usuario')
    @patch('api.views.vazamento_api._executar_restauracao_backup')
    def test_post_operador_retorna_201(self, mock_backup, mock_roles):
        mock_roles.return_value = ['operador']
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mock_backup.assert_called_once()

    @patch('api.views.vazamento_api.keycloak_admin.listar_papeis_realm_usuario')
    def test_post_falha_keycloak_retorna_502(self, mock_roles):
        mock_roles.side_effect = Exception("Erro de conexão simulado")
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)

    @patch('api.views.vazamento_api._executar_restauracao_backup')
    def test_post_falha_backup_retorna_500(self, mock_backup, *args):
        # Simula o operador, mas faz o script de backup falhar
        with patch('api.views.vazamento_api.keycloak_admin.listar_papeis_realm_usuario') as mock_roles:
            mock_roles.return_value = ['operador']
            mock_backup.side_effect = Exception("Falha no backup simulado")
            
            self.client.force_authenticate(user=self.user)
            response = self.client.post(self.url)
            self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    def test_comando_generate_leak(self):
        with patch('api.management.commands.generate_leak._executar_restauracao_backup') as mock_backup:
            out = StringIO()
            call_command('generate_leak', stdout=out)
            self.assertIn('Incidente registrado com sucesso!', out.getvalue())
            mock_backup.assert_called_once()

    def test_modelo_vazamento_str(self):
        vazamento = Vazamento.objects.first()
        self.assertTrue(str(vazamento).startswith('Vazamento'))

    @patch('api.views.vazamento_api.keycloak_admin.listar_papeis_realm_usuario')
    def test_post_script_nao_encontrado(self, mock_roles):
        mock_roles.return_value = ['operador']
        with patch('api.views.vazamento_api.os.path.exists') as mock_exists:
            mock_exists.return_value = False
            self.client.force_authenticate(user=self.user)
            response = self.client.post(self.url)
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch('api.views.vazamento_api.keycloak_admin.listar_papeis_realm_usuario')
    def test_post_sem_backups(self, mock_roles):
        mock_roles.return_value = ['operador']
        with patch('api.views.vazamento_api.os.path.exists') as mock_exists, \
             patch('api.views.vazamento_api.glob.glob') as mock_glob:
            mock_exists.return_value = True
            mock_glob.return_value = []
            self.client.force_authenticate(user=self.user)
            response = self.client.post(self.url)
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    @patch('api.views.vazamento_api.keycloak_admin.listar_papeis_realm_usuario')
    def test_post_falha_no_subprocess(self, mock_roles):
        mock_roles.return_value = ['operador']
        with patch('api.views.vazamento_api.os.path.exists') as mock_exists, \
             patch('api.views.vazamento_api.glob.glob') as mock_glob, \
             patch('api.views.vazamento_api.subprocess.run') as mock_run:
            mock_exists.return_value = True
            mock_glob.return_value = ['/app/backups/20261105T004517Z']
            mock_run.side_effect = subprocess.CalledProcessError(1, 'bash', stderr='erro')
            self.client.force_authenticate(user=self.user)
            response = self.client.post(self.url)
            self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)