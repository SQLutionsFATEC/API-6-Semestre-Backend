import requests
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiResponse, extend_schema

from api.serializers.usuario_serializer import (
    UsuarioPerfilUpdateSerializer,
    UsuarioSerializer,
)
from api.services import keycloak_admin


def _resposta_erro_keycloak(erro):
    """Converte falhas da Admin REST API em respostas HTTP coerentes."""
    if isinstance(erro, requests.RequestException):
        return Response(
            {'erro': 'Falha ao comunicar com o serviço de autenticação.'},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    if erro.codigo_status == 404:
        return Response(
            {'erro': 'Usuário não encontrado no Keycloak.'},
            status=status.HTTP_404_NOT_FOUND,
        )
    if erro.codigo_status == 400:
        return Response(
            {'erro': 'Dados inválidos para o Keycloak.', 'detalhe': erro.resposta},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return Response(
        {'erro': 'Falha ao comunicar com o serviço de autenticação.'},
        status=status.HTTP_502_BAD_GATEWAY,
    )


class PerfilView(APIView):
    """Retorna e atualiza o perfil do usuário autenticado (token Bearer)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary='Consulta o perfil do usuário autenticado',
        description=(
            'Retorna os campos do usuário (nome, email, nivel_acesso e setor) '
            'lidos da Admin REST API do Keycloak a partir do id (claim sub) '
            'presente no access token. '
            'nivel_acesso: basico, comercial, militar ou operador (realm role). '
            'setor: tecnico, normativo, juridico ou qualitativo (atributo do usuário). '
            'Requer token Bearer; retorna 401 sem autenticação.'
        ),
        responses={
            200: UsuarioSerializer,
            401: OpenApiResponse(description='Usuário não autenticado ou token inválido.'),
            404: OpenApiResponse(description='Usuário não encontrado no Keycloak.'),
            502: OpenApiResponse(description='Falha de comunicação com o Keycloak.'),
        },
    )
    def get(self, request):
        try:
            usuario = keycloak_admin.obter_usuario(request.user.id)
            usuario['realmRoles'] = keycloak_admin.listar_papeis_realm_usuario(
                request.user.id
            )
        except (keycloak_admin.KeycloakAdminException, requests.RequestException) as erro:
            return _resposta_erro_keycloak(erro)

        return Response(UsuarioSerializer(usuario).data, status=status.HTTP_200_OK)

    @extend_schema(
        summary='Atualiza o perfil do usuário autenticado',
        description=(
            'Modifica o próprio nome e/ou email do usuário autenticado na '
            'Admin REST API do Keycloak. Para alterar setor ou nivel_acesso '
            'de qualquer usuário, o admin deve usar PATCH /api/usuarios/{id_usuario}/.'
        ),
        request=UsuarioPerfilUpdateSerializer,
        responses={
            200: UsuarioSerializer,
            400: OpenApiResponse(description='Dados inválidos.'),
            401: OpenApiResponse(description='Usuário não autenticado ou token inválido.'),
            404: OpenApiResponse(description='Usuário não encontrado no Keycloak.'),
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
            usuario['realmRoles'] = keycloak_admin.listar_papeis_realm_usuario(
                request.user.id
            )
        except (keycloak_admin.KeycloakAdminException, requests.RequestException) as erro:
            return _resposta_erro_keycloak(erro)

        return Response(UsuarioSerializer(usuario).data, status=status.HTTP_200_OK)
