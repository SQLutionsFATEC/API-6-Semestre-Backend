#!/bin/bash

# Define a "constante" uma única vez
SEPARATOR="=================================================="

echo "$SEPARATOR"
echo "🛠️ INICIANDO DATABASE MIGRATIONS..."
echo "$SEPARATOR"

# Executa o comando e captura o resultado
if python manage.py migrate; then
    echo "✅ SUCESSO: Migrations aplicadas perfeitamente."
    echo "$SEPARATOR"
else
    echo "❌ FATAL ERROR: Falha ao aplicar as migrations!" >&2
    echo "O container não pode subir com o banco desatualizado/quebrado." >&2
    
    echo "$SEPARATOR" >&2
    exit 1
fi

echo "Starting server..."
exec "$@"