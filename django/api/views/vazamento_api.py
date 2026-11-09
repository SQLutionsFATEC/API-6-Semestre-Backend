import os
import time
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated

from api.models import Vazamento
from api.serializers.vazamento_serializer import VazamentoSerializer
from api.services import keycloak_admin

logger = logging.getLogger(__name__)

BACKUP_BASE_DIR = os.environ.get("BACKUP_BASE_DIR", "/app/backups")

def _sinalizar_restauracao_backup():
    """
    Cria um arquivo de sinalização (flag) na pasta de backups.
    Um script externo (watcher.sh no host) ficará responsável por detectar
    este arquivo e executar o restore.sh de forma segura.
    """
    logger.warning("[BACKUP] Sinalizando necessidade de restauração devido a vazamento...")

    os.makedirs(BACKUP_BASE_DIR, exist_ok=True)
    
    trigger_file = os.path.join(BACKUP_BASE_DIR, "TRIGGER_RESTORE.flag")
    
    with open(trigger_file, "w") as f:
        f.write(f"Vazamento detectado em {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    logger.info(f"[BACKUP] Arquivo de gatilho criado em {trigger_file}. Aguardando restore externo.")


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
    
        try:
            _sinalizar_restauracao_backup()
        except Exception as e:
            logger.error(f"[BACKUP] Falha ao criar arquivo de sinalização: {e}")
            return Response(
                {"dsetail": "Vazamento registrado, mas falha ao sinalizar a restauração de backup."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        serializer = VazamentoSerializer(vazamento)
        return Response(serializer.data, status=status.HTTP_201_CREATED)