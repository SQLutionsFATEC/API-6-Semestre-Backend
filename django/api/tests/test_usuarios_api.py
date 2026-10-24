from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from unittest.mock import patch, MagicMock
from api.services.keycloak_admin import KeycloakAdminException

class UsuarioUpdateTests(APITestCase):

    def setUp(self):
        # Cria objetos fake de usuário que tenham o método has_role
        self.user_comum = MagicMock()
        self.user_comum.has_role.side_effect = lambda role: role == 'basico'
        self.user_comum.is_authenticated = True

        self.user_operador = MagicMock()
        self.user_operador.has_role.side_effect = lambda role: role == 'operador'
        self.user_operador.is_authenticated = True

        self.user_admin = MagicMock()
        self.user_admin.has_role.side_effect = lambda role: role == 'admin'
        self.user_admin.is_authenticated = True

    def test_patch_perfil_sem_autenticacao_retorna_401(self):
        url = reverse('perfil')
        response = self.client.patch(url, {'nome': 'Teste'})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_patch_usuario_inexistente_retorna_404(self):
        # Simula a atualização no Keycloak falhando com erro 404
        with patch('api.views.usuarios_api.keycloak_admin.atualizar_usuario') as mock_atualizar:
            mock_atualizar.side_effect = KeycloakAdminException(codigo_status=404, mensagem="Usuário não encontrado")
            
            self.client.force_authenticate(user=self.user_admin)
            url = reverse('usuario-detalhe', kwargs={'id_usuario': '999'})
            response = self.client.patch(url, {'nome': 'Nome'})
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_admin_sem_permissao_operador_retorna_403(self):
        # Usuário comum tentando acessar a rota de operador/admin
        self.client.force_authenticate(user=self.user_comum)
        url = reverse('usuario-detalhe', kwargs={'id_usuario': '999'})
        response = self.client.patch(url, {'nome': 'Hack'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_patch_perfil_nome_invalido_retorna_400(self):
        self.client.force_authenticate(user=self.user_comum)
        url = reverse('perfil')
        response = self.client.patch(url, {'nome': 'Nome123'}) # Número no nome
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_perfil_email_invalido_retorna_400(self):
        self.client.force_authenticate(user=self.user_comum)
        url = reverse('perfil')
        response = self.client.patch(url, {'email': 'email_invalido'}) # Sem @
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)