import requests
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiResponse, extend_schema

from api.models import UsuarioDeletado
from api.permissions import IsAdminRole, IsOperadorOrAdminRole
from api.serializers.usuario_serializer import (
    UsuarioCreateSerializer,
    UsuarioSerializer,
    UsuarioUpdateSerializer,
    UsuarioPerfilUpdateSerializer,
)
from api.services import delecao_usuario, keycloak_admin

from .perfil_api import _resposta_erro_keycloak


class UsuariosView(APIView):
    """Lista/cria usuários (admin) e deleta a própria conta (autenticado)."""

    def get_permissions(self):
        if self.request.method == 'PATCH':
            return [IsAuthenticated()]
        
        if self.request.method == 'DELETE':
            return [IsAuthenticated()]
        
        return [IsAuthenticated(), IsAdminRole()]

    @extend_schema(
        summary='Lista usuários do Keycloak (admin)',
        description=(
            'Retorna os usuários cadastrados no realm, com nome, email, '
            'nivel_acesso e setor. O parâmetro busca filtra por trecho do '
            'nome, email ou username. Acesso restrito à realm role admin '
            '(retorna 403 sem a role).'
        ),
        responses={
            200: UsuarioSerializer(many=True),
            401: OpenApiResponse(description='Usuário não autenticado.'),
            403: OpenApiResponse(description='Usuário sem a role admin.'),
            502: OpenApiResponse(description='Falha de comunicação com o Keycloak.'),
        },
    )
    def get(self, request):
        busca = request.query_params.get('busca')
        try:
            usuarios = keycloak_admin.listar_usuarios(busca=busca)
            for usuario in usuarios:
                usuario['realmRoles'] = keycloak_admin.listar_papeis_realm_usuario(
                    usuario.get('id', '')
                )
        except (keycloak_admin.KeycloakAdminException, requests.RequestException) as erro:
            return _resposta_erro_keycloak(erro)

        return Response(
            UsuarioSerializer(usuarios, many=True).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary='Cria um usuário no Keycloak (admin)',
        description=(
            'Cria um usuário com nome, email e senha temporária. A senha é '
            'temporária (temporary=True), então o usuário é obrigado a '
            'redefini-la no primeiro login. '
            'nivel_acesso (basico/comercial/militar/operador) vira realm role '
            '(padrão basico) e setor (tecnico/normativo/juridico/qualitativo) '
            'vira atributo do usuário (padrão tecnico). '
            'Acesso restrito à realm role admin.'
        ),
        request=UsuarioCreateSerializer,
        responses={
            201: UsuarioSerializer,
            400: OpenApiResponse(description='Dados inválidos (ex.: email duplicado).'),
            401: OpenApiResponse(description='Usuário não autenticado.'),
            403: OpenApiResponse(description='Usuário sem a role admin.'),
            502: OpenApiResponse(description='Falha de comunicação com o Keycloak.'),
        },
    )
    def post(self, request):
        serializer = UsuarioCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dados = serializer.validated_data

        try:
            usuario = keycloak_admin.criar_usuario(
                nome=dados['nome'],
                sobrenome=dados['sobrenome'],
                email=dados['email'],
                senha_temporaria=dados['senha_temporaria'],
                nivel_acesso=dados['nivel_acesso'],
                setor=dados['setor'],
            )
            usuario['realmRoles'] = keycloak_admin.listar_papeis_realm_usuario(
                usuario.get('id', '')
            )
        except (keycloak_admin.KeycloakAdminException, requests.RequestException) as erro:
            return _resposta_erro_keycloak(erro)

        return Response(
            UsuarioSerializer(usuario).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(
        summary='Atualiza o próprio perfil',
        description='Permite que o usuário autenticado edite seu próprio nome e email.',
        request=UsuarioPerfilUpdateSerializer,
        responses={
            200: UsuarioSerializer,
            400: OpenApiResponse(description='Dados inválidos.'),
            401: OpenApiResponse(description='Usuário não autenticado.'),
            502: OpenApiResponse(description='Falha de comunicação com o Keycloak.'),
        },
    )
    def patch(self, request):
        serializer = UsuarioPerfilUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            usuario = keycloak_admin.atualizar_usuario(
                request.user.id, **serializer.validated_data
            )
            usuario['realmRoles'] = keycloak_admin.listar_papeis_realm_usuario(request.user.id)
        except (keycloak_admin.KeycloakAdminException, requests.RequestException) as erro:
            return _resposta_erro_keycloak(erro)

        return Response(UsuarioSerializer(usuario).data, status=status.HTTP_200_OK)


class UsuarioDetalheView(APIView):
    """Lê, modifica e anonimiza um usuário do realm (admin/operador)."""

    permission_classes = [IsAuthenticated, IsOperadorOrAdminRole]

    def _buscar(self, id_usuario):
        usuario = keycloak_admin.obter_usuario(id_usuario)
        usuario['realmRoles'] = keycloak_admin.listar_papeis_realm_usuario(id_usuario)
        return usuario

    @extend_schema(
        summary='Consulta os campos e permissões de um usuário',
        description=(
            'Lê os campos do usuário, incluindo nivel_acesso (realm role, '
            'ex.: operador) e setor (atributo, ex.: juridico). É a leitura '
            'usada para verificar permissões do usuário no backend.'
        ),
        responses={
            200: UsuarioSerializer,
            401: OpenApiResponse(description='Usuário não autenticado.'),
            403: OpenApiResponse(description='Requer nível Operador ou Admin.'),
            404: OpenApiResponse(description='Usuário não encontrado no Keycloak.'),
            502: OpenApiResponse(description='Falha de comunicação com o Keycloak.'),
        },
    )
    def get(self, request, id_usuario):
        try:
            usuario = self._buscar(id_usuario)
        except (keycloak_admin.KeycloakAdminException, requests.RequestException) as erro:
            return _resposta_erro_keycloak(erro)

        return Response(UsuarioSerializer(usuario).data, status=status.HTTP_200_OK)

    @extend_schema(
        summary='Modifica campos de um usuário (admin/operador)',
        description=(
            'Modifica nome, sobrenome, email, setor (atributo do usuário), '
            'nivel_acesso (realm role, ex.: de basico para operador) e/ou '
            'senha. Se a nova senha for temporária (senha_temporaria=true, '
            'padrão), o usuário é obrigado a trocá-la no próximo login. '
            'Acesso restrito à realm role admin ou operador.'
        ),
        request=UsuarioUpdateSerializer,
        responses={
            200: UsuarioSerializer,
            400: OpenApiResponse(description='Dados inválidos.'),
            401: OpenApiResponse(description='Usuário não autenticado.'),
            403: OpenApiResponse(description='Requer nível Operador ou Admin.'),
            404: OpenApiResponse(description='Usuário não encontrado no Keycloak.'),
            502: OpenApiResponse(description='Falha de comunicação com o Keycloak.'),
        },
    )
    def patch(self, request, id_usuario):
        serializer = UsuarioUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            usuario = keycloak_admin.atualizar_usuario(
                id_usuario, **serializer.validated_data
            )
            usuario['realmRoles'] = keycloak_admin.listar_papeis_realm_usuario(id_usuario)
        except (keycloak_admin.KeycloakAdminException, requests.RequestException) as erro:
            return _resposta_erro_keycloak(erro)

        return Response(UsuarioSerializer(usuario).data, status=status.HTTP_200_OK)

    @extend_schema(
        operation_id='usuarios_delete_detail',
        summary='Anonimiza um usuário do Keycloak (admin/operador)',
        description=(
            'Anonimiza o usuário especificado no Keycloak: substitui nome, '
            'e-mail e username por valores genéricos, desabilita a conta e '
            'remove credenciais, roles e grupos. Registra um tombstone em um '
            'banco independente, confirmado após a anonimização, para que os '
            'dados pessoais não reapareçam após a restauração de um backup. '
            'Um e-mail de comprovação é enviado ao endereço cadastrado. '
            'Acesso restrito à realm role admin ou operador.'
        ),
        responses={
            204: OpenApiResponse(description='Usuário anonimizado com sucesso.'),
            401: OpenApiResponse(description='Usuário não autenticado.'),
            403: OpenApiResponse(description='Requer nível Operador ou Admin.'),
            404: OpenApiResponse(description='Usuário não encontrado no Keycloak.'),
            502: OpenApiResponse(description='Falha de comunicação com o Keycloak.'),
        },
    )
    def delete(self, request, id_usuario):
        try:
            delecao_usuario.anonimizar_usuario(
                id_usuario,
                origem=UsuarioDeletado.ORIGEM_OPERADOR,
            )
        except (keycloak_admin.KeycloakAdminException, requests.RequestException) as erro:
            return _resposta_erro_keycloak(erro)

        return Response(status=status.HTTP_204_NO_CONTENT)