from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase
from unittest.mock import patch
from api.models import Vazamento

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