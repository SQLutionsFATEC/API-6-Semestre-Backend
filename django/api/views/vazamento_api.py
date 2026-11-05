import os
import subprocess
import glob
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated

from api.models import Vazamento
from api.serializers.vazamento_serializer import VazamentoSerializer
from api.services import keycloak_admin

logger = logging.getLogger(__name__)

RESTORE_SCRIPT_PATH = os.environ.get("RESTORE_SCRIPT_PATH", "/app/deploy/scripts/restore.sh")
BACKUP_BASE_DIR = os.environ.get("BACKUP_BASE_DIR", "/app/backups")


def _executar_restauracao_backup():
    logger.warning("[BACKUP] Iniciando restauração de backups devido a vazamento...")

    if not os.path.exists(BACKUP_BASE_DIR):
        logger.error(f"[BACKUP] Pasta de backups não existe: {BACKUP_BASE_DIR}")
        return

    subpastas = sorted(glob.glob(os.path.join(BACKUP_BASE_DIR, "*")), reverse=True)
    if not subpastas:
        logger.error(f"[BACKUP] Nenhum backup encontrado em {BACKUP_BASE_DIR}")
        return

    backup_dir = subpastas[0]
    logger.info(f"[BACKUP] Usando backup em: {backup_dir}")

    if not os.path.exists(RESTORE_SCRIPT_PATH):
        logger.error(f"[BACKUP] Script não encontrado: {RESTORE_SCRIPT_PATH}")
        return

    try:
        subprocess.run(
            ["bash", RESTORE_SCRIPT_PATH, backup_dir, "--yes"],
            check=True,
            capture_output=True,
            text=True,
        )
        logger.info("[BACKUP] Restauração concluída com sucesso.")
    except subprocess.CalledProcessError as e:
        logger.error(f"[BACKUP] Falha na restauração: {e.stderr}")
        raise Exception("Falha ao executar a restauração de backup.")


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
            _executar_restauracao_backup()
        except Exception:
            return Response(
                {"detail": "Vazamento registrado, mas falha ao iniciar a restauração de backup."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        serializer = VazamentoSerializer(vazamento)
        return Response(serializer.data, status=status.HTTP_201_CREATED)