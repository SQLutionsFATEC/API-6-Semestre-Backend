#!/bin/bash
set -e

# Permite que o usuário da aplicação crie o banco de testes do Django.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;
    ALTER ROLE "$POSTGRES_USER" CREATEDB;
EOSQL

# Mantém a extensão disponível também em bancos de teste criados a partir do template.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname template1 <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;
EOSQL