#!/bin/bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUPS_DIR="${BASE_DIR}/backups"
RESTORE_SCRIPT="${BASE_DIR}/scripts/restore.sh"
TRIGGER_FILE="${BACKUPS_DIR}/TRIGGER_RESTORE.flag"

echo "=================================================="
echo "👀 Monitorando vazamentos na pasta: ${BACKUPS_DIR}"
echo "=================================================="

while true; do
    if [ -f "$TRIGGER_FILE" ]; then
        echo ""
        echo "🚨 VAZAMENTO DETECTADO! Iniciando processo de restauração..."
        
        LATEST_BACKUP=$(ls -1d "${BACKUPS_DIR}"/*/ 2>/dev/null | sort -r | head -n 1)
        
        if [ -z "$LATEST_BACKUP" ]; then
            echo "❌ Nenhum backup encontrado em ${BACKUPS_DIR}."
        else
            echo "🔄 Usando backup mais recente: ${LATEST_BACKUP}"

            if bash "$RESTORE_SCRIPT" "$LATEST_BACKUP" --yes; then
                echo "✅ Restauração concluída com sucesso!"
            else
                echo "❌ Falha durante a restauração. Verifique os logs acima."
            fi
        fi
        
        rm -f "$TRIGGER_FILE"
        echo ""
        echo "👀 Voltando a monitorar..."
        echo "=================================================="
    fi
    sleep 3
done