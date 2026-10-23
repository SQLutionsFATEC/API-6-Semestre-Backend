from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from unittest.mock import patch, MagicMock
from api.services.keycloak_admin import KeycloakAdminException

class UsuarioUpdateTests(APITestCase):

    def setUp(self):
        # Cria objetos fake de usuário que tenham o método has_role
        self.user_comum = MagicMock()
        self.user_comum.id = "123"
        self.user_comum.has_role.side_effect = lambda role: role == 'basico'
        self.user_comum.is_authenticated = True

        self.user_operador = MagicMock()
        self.user_operador.id = "456"
        self.user_operador.has_role.side_effect = lambda role: role == 'operador'
        self.user_operador.is_authenticated = True

        self.user_admin = MagicMock()
        self.user_admin.id = "789"
        self.user_admin.has_role.side_effect = lambda role: role == 'admin'
        self.user_admin.is_authenticated = True

    def test_patch_perfil_sem_autenticacao_retorna_401(self):
        url = reverse('perfil')
        response = self.client.patch(url, {'nome': 'Teste'})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_patch_usuario_inexistente_retorna_404(self):
        with patch('api.views.usuarios_api.keycloak_admin.atualizar_usuario') as mock_atualizar:
            mock_atualizar.side_effect = KeycloakAdminException(codigo_status=404, mensagem="Usuário não encontrado")
            
            self.client.force_authenticate(user=self.user_admin)
            url = reverse('usuario-detalhe', kwargs={'id_usuario': '999'})
            response = self.client.patch(url, {'nome': 'Nome'})
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_admin_sem_permissao_operador_retorna_403(self):
        self.client.force_authenticate(user=self.user_comum)
        url = reverse('usuario-detalhe', kwargs={'id_usuario': '999'})
        response = self.client.patch(url, {'nome': 'Hack'})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_patch_perfil_nome_invalido_retorna_400(self):
        self.client.force_authenticate(user=self.user_comum)
        url = reverse('perfil')
        response = self.client.patch(url, {'nome': 'Nome123'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_perfil_email_invalido_retorna_400(self):
        self.client.force_authenticate(user=self.user_comum)
        url = reverse('perfil')
        response = self.client.patch(url, {'email': 'email_invalido'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # 👇 NOVOS TESTES PARA COBRIR A ROTA /api/usuarios/ (USUARIOS VIEW) 👇

    @patch('api.views.usuarios_api.keycloak_admin.atualizar_usuario')
    def test_patch_meu_perfil_sucesso_retorna_200(self, mock_atualizar):
        # Mock do retorno do Keycloak
        mock_atualizar.return_value = {
            'id': '123',
            'firstName': 'Chico Editado',
            'lastName': 'Soluções',
            'email': 'chico@teste.com',
            'attributes': {'setor': ['tecnico']},
            'realmRoles': ['basico']
        }

        self.client.force_authenticate(user=self.user_comum)
        url = reverse('usuarios')
        response = self.client.patch(url, {'nome': 'Chico Editado'})
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_atualizar.assert_called_once_with("123", nome="Chico Editado")

    @patch('api.views.usuarios_api.keycloak_admin.atualizar_usuario')
    def test_patch_meu_perfil_nome_invalido_retorna_400(self, mock_atualizar):
        self.client.force_authenticate(user=self.user_comum)
        url = reverse('usuarios')
        response = self.client.patch(url, {'nome': 'Nome123'})
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_atualizar.assert_not_called()

    @patch('api.views.usuarios_api.keycloak_admin.atualizar_usuario')
    def test_patch_meu_perfil_falha_keycloak_retorna_502(self, mock_atualizar):
        mock_atualizar.side_effect = KeycloakAdminException(codigo_status=500, mensagem="Erro interno")
        
        self.client.force_authenticate(user=self.user_comum)
        url = reverse('usuarios')
        response = self.client.patch(url, {'nome': 'Chico'})
        
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)

    @patch('api.views.usuarios_api.keycloak_admin.atualizar_usuario')
    def test_patch_meu_perfil_sem_autenticacao_retorna_401(self, mock_atualizar):
        url = reverse('usuarios')
        response = self.client.patch(url, {'nome': 'Teste'})
        
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        mock_atualizar.assert_not_called()