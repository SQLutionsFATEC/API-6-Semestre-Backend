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

if [[ "$RUN_SEED" = "true" ]] || \
   [[ "$RUN_SEED" = "True" ]] || \
   [[ "$RUN_SEED" = "1" ]] || \
   [[ "$RUN_SEED" = "TRUE" ]]; then

    echo "🌱 RUN_SEED habilitado."

    # Mantém o comportamento de seed existente quando houver
    # comandos de seed configurados para o projeto.
    if python manage.py help seed_dynamic >/dev/null 2>&1; then
        echo "Executando seed_dynamic..."
        python manage.py seed_dynamic
    else
        echo "⚠️ Comando seed_dynamic não encontrado. Seed ignorado."
    fi
fi

if [ "$#" -gt 0 ]; then
    echo "$SEPARATOR"
    echo "🚀 Executando comando do container:"
    echo "$*"
    echo "$SEPARATOR"

    exec "$@"
fi

echo "ℹ️ Nenhum comando adicional informado ao container."
