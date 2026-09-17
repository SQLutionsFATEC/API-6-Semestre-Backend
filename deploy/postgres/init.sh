#!/bin/bash
set -e

# Permite que o usuário da aplicação crie o banco de testes do Django.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    ALTER ROLE "$POSTGRES_USER" CREATEDB;
EOSQL