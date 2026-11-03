#!/usr/bin/env bash
# Funções compartilhadas pelos scripts de backup/restauração.
# Uso: source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$DEPLOY_DIR/docker-compose.yaml}"

COMPOSE=(docker compose -f "$COMPOSE_FILE")
if [[ -n "${COMPOSE_PROJECT_NAME:-}" ]]; then
    COMPOSE+=(-p "$COMPOSE_PROJECT_NAME")
fi

APP_DB_SERVICE="${APP_DB_SERVICE:-postgres}"
KEYCLOAK_DB_SERVICE="${KEYCLOAK_DB_SERVICE:-keycloak-db}"
TOMBSTONE_DB_SERVICE="${TOMBSTONE_DB_SERVICE:-tombstone-db}"
BACKEND_SERVICE="${BACKEND_SERVICE:-backend}"
KEYCLOAK_SERVICE="${KEYCLOAK_SERVICE:-keycloak}"

log() {
    printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"
}

warn() {
    printf '[%s] AVISO: %s\n' "$(date -u +%H:%M:%S)" "$*" >&2
}

die() {
    printf 'ERRO: %s\n' "$*" >&2
    exit 1
}

service_running() {
    [[ -n "$("${COMPOSE[@]}" ps --status running -q "$1" 2>/dev/null)" ]]
}

require_running_service() {
    service_running "$1" || die \
        "o serviço '$1' não está rodando. Suba o ambiente com: ${COMPOSE[*]} up -d $1"
}

sha256_of() {
    local arquivo="$1"
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$arquivo" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$arquivo" | awk '{print $1}'
    else
        die 'sha256sum ou shasum é necessário para gerar/verificar checksums.'
    fi
}
