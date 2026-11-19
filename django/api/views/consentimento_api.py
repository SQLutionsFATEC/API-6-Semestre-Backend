"""Endpoints HTTP para consulta e alteração de consentimentos do usuário."""
import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import Clausula, Consentimento
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
    """
    Monta o dicionário com o termo em vigor e o estado de cada cláusula para um
    usuário. Se `id_usuario` for None (uso no GET sem id), todas as cláusulas
    aparecem com `aceita=None`.
    """
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
    """
    Endpoints da rota /api/consentimento.

    GET  /api/consentimento            -> Termo atual + estado do usuário logado.
    GET  /api/consentimento/<id>       -> Termo atual + estado do usuário <id>.
    PATCH /api/consentimento           -> Altera consentimento do usuário logado.
    """
    permission_classes = [IsAuthenticated]

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

    def patch(self, request):
        serializer = ConsentimentoUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            usuario_id = request.user.id
            if not usuario_id:
                return Response(
                    {"detail": "Não foi possível identificar o usuário."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            aceites = [id_c for id_c, v in serializer.validated_data.items() if v]
            recusas = [id_c for id_c, v in serializer.validated_data.items() if not v]

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