#!/bin/bash
set -e

# O entrypoint do MySQL do Docker passa as variáveis do .env 
# $MYSQL_USER e $MYSQL_DATABASE estão disponíveis.

# Vamos garantir permissões dinâmicas para o banco de teste baseado na variável
mysql -u root -p"${MYSQL_ROOT_PASSWORD}" <<-EOSQL
    GRANT ALL PRIVILEGES ON \`test_${MYSQL_DATABASE}\`.* TO '${MYSQL_USER}'@'%';
    FLUSH PRIVILEGES;
EOSQL
