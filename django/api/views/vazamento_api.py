from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated

from api.models import Vazamento
from api.serializers.vazamento_serializer import VazamentoSerializer
from api.services import keycloak_admin


def _executar_restauracao_backup():
    """
    Placeholder para o fluxo de restauração de backups.
    Substitua pelo comando/serviço real de backup da equipe.
    """
    print("[BACKUP] Iniciando restauração de backups devido a vazamento...")


class VazamentoView(APIView):
    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated()]
        return [AllowAny()]

    def get(self, request):
        vazamento_recente = Vazamento.objects.first()

        if not vazamento_recente:
            return Response(
                {"detail": "Nenhum incidente de vazamento registrado."},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = VazamentoSerializer(vazamento_recente)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        try:
            roles = keycloak_admin.listar_papeis_realm_usuario(request.user.id)
            if 'operador' not in roles:
                return Response(
                    {"detail": "Você não tem permissão para registrar vazamentos."},
                    status=status.HTTP_403_FORBIDDEN
                )
        except Exception:
            return Response(
                {"detail": "Erro ao verificar permissões no Keycloak."},
                status=status.HTTP_502_BAD_GATEWAY
            )

        vazamento = Vazamento.objects.create()
        _executar_restauracao_backup()

        serializer = VazamentoSerializer(vazamento)
        return Response(serializer.data, status=status.HTTP_201_CREATED)