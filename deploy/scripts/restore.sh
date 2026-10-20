#!/usr/bin/env bash
# Restauração de backup garantindo que usuários deletados NÃO voltem.
#
# Uso:
#   bash deploy/scripts/restore.sh <diretorio-do-backup> [--yes]
#
# Fluxo:
#   1. valida arquivos e checksums do backup;
#   2. para backend e Keycloak;
#   3. restaura o banco da aplicação e o banco do Keycloak;
#   4. restaura a mídia;
#   5. mescla (união) os tombstones do backup no banco independente — nunca
#      remove tombstones já existentes;
#   6. sobe o Keycloak/backend e executa purge_deleted_users --verificar,
#      que remove do Keycloak restaurado todo usuário tombstoned e falha se
#      algum deles continuar existindo.
#
# O banco de tombstones em si NUNCA é restaurado por cima do banco vivo.

set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

BACKUP_DIR=''
CONFIRMAR=1

for argumento in "$@"; do
    case "$argumento" in
        --yes|-y) CONFIRMAR=0 ;;
        -*) die "opção desconhecida: $argumento" ;;
        *)
            [[ -z "$BACKUP_DIR" ]] || die 'informe apenas um diretório de backup.'
            BACKUP_DIR="$argumento"
            ;;
    esac
done

[[ -n "$BACKUP_DIR" ]] || die 'uso: restore.sh <diretorio-do-backup> [--yes]'
[[ -d "$BACKUP_DIR" ]] || die "diretório não encontrado: $BACKUP_DIR"
BACKUP_DIR="$(cd "$BACKUP_DIR" && pwd)"

for arquivo in app.dump keycloak.dump tombstones.dump; do
    [[ -s "$BACKUP_DIR/$arquivo" ]] || die "arquivo ausente ou vazio: $arquivo"
done
# tombstones.csv pode ser vazio quando o backup foi feito antes de qualquer
# exclusão; o arquivo precisa existir.
[[ -f "$BACKUP_DIR/tombstones.csv" ]] || die 'arquivo ausente: tombstones.csv'

if [[ -f "$BACKUP_DIR/SHA256SUMS" ]]; then
    log 'Verificando checksums...'
    while read -r checksum arquivo; do
        [[ -n "${arquivo:-}" ]] || continue
        [[ -f "$BACKUP_DIR/$arquivo" ]] || die "arquivo listado não existe: $arquivo"
        calculado="$(sha256_of "$BACKUP_DIR/$arquivo")"
        [[ "$calculado" == "$checksum" ]] || die "checksum inválido: $arquivo"
    done < "$BACKUP_DIR/SHA256SUMS"
fi

if [[ "$CONFIRMAR" -eq 1 ]]; then
    printf 'ATENÇÃO: esta operação sobrescreve o banco da aplicação e o banco do Keycloak.\n'
    read -r -p 'Continuar? [s/N] ' resposta
    [[ "$resposta" =~ ^[sS]$ ]] || die 'cancelado pelo usuário.'
fi

require_running_service "$APP_DB_SERVICE"
require_running_service "$KEYCLOAK_DB_SERVICE"
require_running_service "$TOMBSTONE_DB_SERVICE"

log 'Parando backend e Keycloak...'
"${COMPOSE[@]}" stop "$BACKEND_SERVICE" "$KEYCLOAK_SERVICE" >/dev/null 2>&1 || true

log 'Restaurando banco da aplicação...'
"${COMPOSE[@]}" exec -T "$APP_DB_SERVICE" sh -c \
    'exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges --single-transaction' \
    < "$BACKUP_DIR/app.dump"

log 'Restaurando banco do Keycloak...'
"${COMPOSE[@]}" exec -T "$KEYCLOAK_DB_SERVICE" sh -c \
    'exec pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --no-privileges --single-transaction' \
    < "$BACKUP_DIR/keycloak.dump"

if [[ -s "$BACKUP_DIR/media.tar.gz" ]]; then
    log 'Restaurando arquivos de mídia...'
    tar xzf "$BACKUP_DIR/media.tar.gz" -C "$DEPLOY_DIR/../django"
fi

# Garante que a tabela usuario_deletado exista no banco independente antes de
# mesclar os tombstones do backup. O entrypoint também roda as migrations.
log 'Aplicando migrations (incluindo banco de tombstones)...'
# O entrypoint do backend roda as migrations do banco da aplicação e do banco
# de tombstones; a chamada explícita garante o schema do tombstones mesmo se
# o entrypoint for alterado no futuro.
"${COMPOSE[@]}" run --rm --no-deps -T "$BACKEND_SERVICE" \
    python manage.py migrate --database=tombstones --noinput

log 'Mesclando tombstones do backup (união, sem apagar registros atuais)...'
TMP_DIR="$(mktemp -d "$DEPLOY_DIR/.restore-tombstones-XXXXXX")"
trap 'rm -rf "$TMP_DIR"' EXIT
cp "$BACKUP_DIR/tombstones.csv" "$TMP_DIR/tombstones.csv"

cat > "$TMP_DIR/merge_tombstones.sql" <<'SQL'
\set ON_ERROR_STOP on
CREATE TEMP TABLE usuario_deletado_restore (
    id_usuario_hash varchar(64),
    deletado_em timestamptz,
    origem varchar(20)
);
\copy usuario_deletado_restore FROM '/tmp/tombstones.csv' WITH (FORMAT csv)
INSERT INTO usuario_deletado (id_usuario_hash, deletado_em, origem)
SELECT id_usuario_hash, deletado_em, origem
FROM usuario_deletado_restore
ON CONFLICT (id_usuario_hash) DO NOTHING;
DROP TABLE usuario_deletado_restore;
SQL

"${COMPOSE[@]}" cp "$TMP_DIR/tombstones.csv" "$TOMBSTONE_DB_SERVICE:/tmp/tombstones.csv"
"${COMPOSE[@]}" cp "$TMP_DIR/merge_tombstones.sql" "$TOMBSTONE_DB_SERVICE:/tmp/merge_tombstones.sql"
"${COMPOSE[@]}" exec -T "$TOMBSTONE_DB_SERVICE" sh -c \
    'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /tmp/merge_tombstones.sql'

log 'Subindo Keycloak e backend...'
"${COMPOSE[@]}" up -d "$KEYCLOAK_SERVICE" "$BACKEND_SERVICE" >/dev/null

log 'Aguardando o backend ficar pronto...'
pronto=0
for _ in $(seq 1 90); do
    if "${COMPOSE[@]}" exec -T "$BACKEND_SERVICE" python manage.py check >/dev/null 2>&1; then
        pronto=1
        break
    fi
    sleep 2
done
[[ "$pronto" -eq 1 ]] || die 'o backend não ficou pronto a tempo.'

log 'Removendo do Keycloak restaurado os usuários que constam como deletados...'
"${COMPOSE[@]}" exec -T "$BACKEND_SERVICE" \
    python manage.py purge_deleted_users --verificar --aguardar 180

log 'Restauração concluída: nenhum usuário deletado foi restaurado.'
