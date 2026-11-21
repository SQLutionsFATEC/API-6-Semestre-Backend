"""Endpoints HTTP para consulta e alteração de consentimentos do usuário."""
import logging

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.serializers.consentimento_serializer import (
    ConsentimentoUpdateSerializer,
    TermoConsentimentoSerializer,
)
from api.services.consentimento import (
    consentir_clausulas,
    obter_consentimentos_usuario,
    rescindir_consentimento,
)
from api.services.termo_consentimento import obter_termo_atual

logger = logging.getLogger(__name__)


def _montar_payload_termo(id_usuario):
    termo = obter_termo_atual()

    if id_usuario:
        estado = {
            item['clausula'].id_clausula: item['acordo']
            for item in obter_consentimentos_usuario(id_usuario)
        }
    else:
        estado = {}

    clausulas = [
        {
            'id_clausula': clausula.id_clausula,
            'requisito': clausula.requisito,
            'desc': clausula.desc,
            'obrigatoria': clausula.obrigatoria,
            'aceita': estado.get(clausula.id_clausula),
        }
        for clausula in termo.clausulas.all().order_by('id_clausula')
    ]

    return {
        'id_termo': termo.id_termo,
        'data_criacao': termo.data_criacao,
        'clausulas': clausulas,
    }


class ConsentimentoView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary='Retorna o termo atual e o estado de consentimento do usuário',
        description='Se o ID do usuário não for informado na URL, retorna o estado do usuário logado.',
        parameters=[
            OpenApiParameter(
                name='id_usuario',
                type=str,
                location=OpenApiParameter.PATH,
                description='UUID do usuário no Keycloak.',
                required=False,
            )
        ],
        responses={
            200: TermoConsentimentoSerializer,
            401: OpenApiResponse(description='Não autenticado'),
        },
    )
    def get(self, request, id_usuario=None):
        try:
            if id_usuario is None:
                id_usuario = request.user.id

            if not id_usuario:
                return Response(
                    {"detail": "Não foi possível identificar o usuário."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            payload = _montar_payload_termo(id_usuario)
            serializer = TermoConsentimentoSerializer(payload)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception:
            logger.exception("Erro ao buscar consentimentos do usuário.")
            return Response(
                {"detail": "Não foi possível carregar os consentimentos."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(
        summary='Atualiza o consentimento do usuário logado',
        description='Aceita um objeto JSON onde a chave é o ID da cláusula e o valor é um boolean (true para aceitar, false para revogar).',
        request=ConsentimentoUpdateSerializer,
        responses={
            200: TermoConsentimentoSerializer,
            400: OpenApiResponse(description='Dados inválidos (ID não pertence ao termo atual ou valor não-boolean)'),
            401: OpenApiResponse(description='Não autenticado'),
        },
    )
    def patch(self, request):
        serializer = ConsentimentoUpdateSerializer()

        try:
            dados_validados = serializer.to_internal_value(request.data)
        except ValidationError as erro:
            detalhes = erro.detail
            if isinstance(detalhes, list):
                mensagem = "; ".join(str(m) for m in detalhes)
            elif isinstance(detalhes, dict):
                mensagem = "; ".join(
                    str(m) for v in detalhes.values() for m in (v if isinstance(v, list) else [v])
                )
            else:
                mensagem = str(detalhes)
            return Response(
                {"detail": mensagem},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            usuario_id = request.user.id
            if not usuario_id:
                return Response(
                    {"detail": "Não foi possível identificar o usuário."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            aceites = [id_c for id_c, v in dados_validados.items() if v]
            recusas = [id_c for id_c, v in dados_validados.items() if not v]

            if aceites:
                consentir_clausulas(usuario_id, aceites)
            if recusas:
                rescindir_consentimento(usuario_id, recusas)

            payload = _montar_payload_termo(usuario_id)
            return Response(payload, status=status.HTTP_200_OK)

        except ValueError as erro:
            return Response(
                {"detail": str(erro)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            logger.exception("Erro ao atualizar consentimentos.")
            return Response(
                {"detail": "Não foi possível atualizar os consentimentos."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )