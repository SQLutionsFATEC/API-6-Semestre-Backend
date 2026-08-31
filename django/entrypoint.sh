#!/bin/bash

# Define a "constante" uma única vez
SEPARATOR="=================================================="

echo "$SEPARATOR"
echo "🛠️ INICIANDO DATABASE MIGRATIONS..."
echo "$SEPARATOR"

# Executa o comando e captura o resultado
if python manage.py smart_migrate; then
    echo "✅ SUCESSO: Migrations aplicadas perfeitamente."
    echo "$SEPARATOR"
else
    echo "❌ FATAL ERROR: Falha ao aplicar as migrations!" >&2
    echo "O container não pode subir com o banco desatualizado/quebrado." >&2
    
    echo "$SEPARATOR" >&2
    exit 1
fi

if [[ "$RUN_SEED" = "true" ]] || [[ "$RUN_SEED" = "True" ]] || [[ "$RUN_SEED" = "1" ]] || [[ "$RUN_SEED" = "TRUE" ]]; then
    echo "Checking if database is empty..."
    if python manage.py shell -c "import sys; from api.models import DimPrograma; sys.exit(1 if DimPrograma.objects.exists() else 0)"; then
        echo "Database is empty. Running dynamic seed with 2 programs and 5 projects..."
        python manage.py seed_dynamic --programs=2 --projects=5
    else
        echo "Database is not empty. Skipping seed."
    fi
fi

echo "Starting server..."
exec "$@"