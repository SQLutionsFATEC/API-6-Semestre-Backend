#!/usr/bin/env bash
# Backup da aplicação: banco da aplicação, banco do Keycloak (usuários),
# banco de tombstones (prova de exclusões) e arquivos de mídia.
#
# Uso:
#   bash deploy/scripts/backup.sh [diretorio-de-destino]
#
# O destino padrão é deploy/backups/<timestamp-utc>.
#
# Importante: o banco de tombstones NÃO é restaurado por cima do banco vivo no
# restore. O dump completo dele é uma cópia de recuperação de desastre; no
# restore é usado o CSV, mesclado com união (nunca removendo tombstones).

set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

DEST="${1:-$DEPLOY_DIR/backups/$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$DEST"
DEST="$(cd "$DEST" && pwd)"

require_running_service "$APP_DB_SERVICE"
require_running_service "$KEYCLOAK_DB_SERVICE"
require_running_service "$TOMBSTONE_DB_SERVICE"

log "Gerando backup em $DEST"

log 'Dump do banco da aplicação (documentos, etiquetas, chunks)...'
"${COMPOSE[@]}" exec -T "$APP_DB_SERVICE" sh -c \
    'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' \
    > "$DEST/app.dump"

log 'Dump do banco do Keycloak (usuários, roles, credenciais)...'
"${COMPOSE[@]}" exec -T "$KEYCLOAK_DB_SERVICE" sh -c \
    'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' \
    > "$DEST/keycloak.dump"

log 'Dump do banco de tombstones (recuperação de desastre)...'
"${COMPOSE[@]}" exec -T "$TOMBSTONE_DB_SERVICE" sh -c \
    'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' \
    > "$DEST/tombstones.dump"

log 'Exportando tombstones em CSV (usado no restore com união)...'
"${COMPOSE[@]}" exec -T "$TOMBSTONE_DB_SERVICE" sh -c \
    'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
        -c "COPY (SELECT id_usuario_hash, deletado_em, origem FROM usuario_deletado ORDER BY deletado_em) TO STDOUT WITH (FORMAT csv)"' \
    > "$DEST/tombstones.csv"

for arquivo in app.dump keycloak.dump tombstones.dump; do
    [[ -s "$DEST/$arquivo" ]] || die "dump vazio: $arquivo"
done
# tombstones.csv pode ser vazio quando ainda não há nenhuma exclusão.
[[ -f "$DEST/tombstones.csv" ]] || die 'CSV de tombstones não foi gerado.'

# Verifica que os dumps são legíveis pelo pg_restore antes de considerar o
# backup válido.
"${COMPOSE[@]}" exec -T "$APP_DB_SERVICE" pg_restore --list \
    < "$DEST/app.dump" > /dev/null
"${COMPOSE[@]}" exec -T "$KEYCLOAK_DB_SERVICE" pg_restore --list \
    < "$DEST/keycloak.dump" > /dev/null
"${COMPOSE[@]}" exec -T "$TOMBSTONE_DB_SERVICE" pg_restore --list \
    < "$DEST/tombstones.dump" > /dev/null

if service_running "$BACKEND_SERVICE"; then
    log 'Arquivando arquivos de mídia...'
    "${COMPOSE[@]}" exec -T "$BACKEND_SERVICE" sh -c 'cd /app && exec tar czf - media' \
        > "$DEST/media.tar.gz"
else
    warn "backend não está rodando; arquivos de mídia não foram incluídos."
    rm -f "$DEST/media.tar.gz"
fi

log 'Gerando checksums...'
{
    for arquivo in app.dump keycloak.dump tombstones.dump tombstones.csv media.tar.gz; do
        if [[ -f "$DEST/$arquivo" ]]; then
            printf '%s  %s\n' "$(sha256_of "$DEST/$arquivo")" "$arquivo"
        fi
    done
} > "$DEST/SHA256SUMS"

GIT_COMMIT="$(git -C "$DEPLOY_DIR/.." rev-parse HEAD 2>/dev/null || echo 'desconhecido')"
{
    printf '{\n'
    printf '  "criado_em": "%s",\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf '  "git_commit": "%s",\n' "$GIT_COMMIT"
    printf '  "arquivos": ['
    primeiro=1
    for arquivo in app.dump keycloak.dump tombstones.dump tombstones.csv media.tar.gz; do
        if [[ -f "$DEST/$arquivo" ]]; then
            if [[ "$primeiro" -eq 0 ]]; then printf ','; fi
            primeiro=0
            printf '\n    "%s"' "$arquivo"
        fi
    done
    printf '\n  ]\n'
    printf '}\n'
} > "$DEST/manifest.json"

log "Backup concluído: $DEST"
ls -lh "$DEST"
