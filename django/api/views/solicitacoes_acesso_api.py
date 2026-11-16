from django.db import IntegrityError
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import OpenApiResponse, extend_schema

from api.models import SolicitacaoAcesso
from api.permissions import IsOperador
from api.serializers.solicitacao_acesso_serializer import (
    SolicitacaoAcessoCreateSerializer,
    SolicitacaoAcessoSerializer,
    SolicitacaoAcessoUpdateSerializer,
)


class SolicitacoesAcessoView(APIView):
    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsOperador()]

    @extend_schema(
        summary='Solicita acesso a um documento',
        request=SolicitacaoAcessoCreateSerializer,
        responses={
            200: SolicitacaoAcessoSerializer,
            201: SolicitacaoAcessoSerializer,
            400: OpenApiResponse(description='Documento inválido.'),
            401: OpenApiResponse(description='Usuário não autenticado.'),
            403: OpenApiResponse(description='Operadores não podem criar solicitações.'),
        },
    )
    def post(self, request):
        has_role = getattr(request.user, 'has_role', lambda role: False)
        if has_role('operador'):
            return Response(
                {'detail': 'Operadores não podem criar solicitações de acesso.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = SolicitacaoAcessoCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        documento = serializer.validated_data['documento']

        try:
            solicitacao, criada = SolicitacaoAcesso.objects.get_or_create(
                documento=documento,
                usuario_id=request.user.id,
            )
        except IntegrityError:
            solicitacao = SolicitacaoAcesso.objects.get(
                documento=documento,
                usuario_id=request.user.id,
            )
            criada = False

        return Response(
            SolicitacaoAcessoSerializer(solicitacao).data,
            status=status.HTTP_201_CREATED if criada else status.HTTP_200_OK,
        )

    @extend_schema(
        summary='Lista solicitações de acesso',
        responses={
            200: SolicitacaoAcessoSerializer(many=True),
            401: OpenApiResponse(description='Usuário não autenticado.'),
            403: OpenApiResponse(description='Requer nível Operador.'),
        },
    )
    def get(self, request):
        paginator = PageNumberPagination()
        paginator.page_size = 10
        pagina = paginator.paginate_queryset(
            SolicitacaoAcesso.objects.select_related('documento'),
            request,
            view=self,
        )
        return paginator.get_paginated_response(
            SolicitacaoAcessoSerializer(pagina, many=True).data
        )


class SolicitacaoAcessoDetalheView(APIView):
    permission_classes = [IsAuthenticated, IsOperador]

    @extend_schema(
        summary='Aprova ou rejeita uma solicitação de acesso',
        request=SolicitacaoAcessoUpdateSerializer,
        responses={
            200: SolicitacaoAcessoSerializer,
            400: OpenApiResponse(description='Dados inválidos.'),
            401: OpenApiResponse(description='Usuário não autenticado.'),
            403: OpenApiResponse(description='Requer nível Operador.'),
            404: OpenApiResponse(description='Solicitação não encontrada.'),
        },
    )
    def patch(self, request, id_solicitacao):
        try:
            solicitacao = SolicitacaoAcesso.objects.get(pk=id_solicitacao)
        except SolicitacaoAcesso.DoesNotExist:
            return Response(
                {'detail': 'Solicitação não encontrada.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = SolicitacaoAcessoUpdateSerializer(
            solicitacao,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            SolicitacaoAcessoSerializer(solicitacao).data,
            status=status.HTTP_200_OK,
        )
