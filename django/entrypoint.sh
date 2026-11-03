#!/bin/bash
set -e

SEPARATOR="=================================================="

echo "$SEPARATOR"
echo "🛠️ INICIANDO DATABASE MIGRATIONS..."
echo "$SEPARATOR"

if python manage.py migrate --noinput; then
    echo "✅ SUCESSO: migrations aplicadas."
    echo "$SEPARATOR"
else
    echo "❌ FATAL ERROR: falha ao aplicar as migrations." >&2
    echo "$SEPARATOR" >&2
    exit 1
fi

# O banco de tombstones é independente do banco da aplicação e precisa das
# próprias migrations (apenas o model UsuarioDeletado é criado nele).
echo "$SEPARATOR"
echo "🛠️ INICIANDO DATABASE MIGRATIONS (tombstones)..."
echo "$SEPARATOR"

if python manage.py migrate --database=tombstones --noinput; then
    echo "✅ SUCESSO: migrations do banco de tombstones aplicadas."
    echo "$SEPARATOR"
else
    echo "❌ FATAL ERROR: falha ao aplicar as migrations do banco de tombstones." >&2
    echo "$SEPARATOR" >&2
    exit 1
fi

if [[ "$#" -gt 0 ]]; then
    echo "$SEPARATOR"
    echo "🚀 Executando comando do container:"
    echo "$*"
    echo "$SEPARATOR"

    exec "$@"
fi

echo "ℹ️ Nenhum comando adicional informado ao container."
