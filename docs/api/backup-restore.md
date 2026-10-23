# Backup, restauração e direito ao esquecimento (Card 44)

Este documento descreve como a aplicação garante que um usuário deletado **não volte** depois de restaurar um backup do Keycloak ou do banco da aplicação.

## 1. Por que um banco separado?

O Keycloak é a fonte da verdade da identidade: nome, e-mail, senha, roles e atributos vivem no banco do Keycloak, não no banco do Django. Se alguém restaurar um backup antigo do Keycloak, um usuário que pediu exclusão pode reaparecer.

Para impedir isso existe um **banco independente de tombstones** (alias Django `tombstones`, serviço `tombstone-db` no compose):

```text
┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────────┐
│ Banco da aplicação  │   │ Banco do Keycloak   │   │ Banco de tombstones     │
│ documentos, tags,   │   │ usuários, roles,    │   │ SHA-256 do id + data +  │
│ chunks              │   │ credenciais         │   │ origem da exclusão      │
└─────────────────────┘   └─────────────────────┘   └─────────────────────────┘
        │                          │                            │
        └──── backup/restore ──────┴──── NUNCA é sobrescrito ───┘
```

O banco de tombstones não entra no fluxo normal de restauração. O script de restore apenas **mescla** os tombstones do backup (união), de modo que uma restauração antiga não consiga apagar exclusões mais recentes.

## 2. Anonimização

O tombstone guarda somente:

| Campo | Conteúdo |
|---|---|
| `id_usuario_hash` | SHA-256 do `id` (UUID) do usuário no Keycloak |
| `deletado_em` | data/hora em que a exclusão foi solicitada |
| `confirmado_em` | data/hora em que o Keycloak confirmou a remoção; `NULL` enquanto pendente |
| `origem` | `autoatendimento` ou `operador` |

O id, o nome e o e-mail **nunca** são gravados nesse banco. Como o id do Keycloak é um UUID (alta entropia), o hash não é reversível na prática e o banco de tombstones não contém dado pessoal diretamente identificável.

O tombstone é gravado antes do `DELETE` no Keycloak, mas nasce **pendente**. Ele só passa a valer como prova de exclusão depois que o Keycloak confirma a remoção; a purga e o backup consideram apenas tombstones **confirmados**. Se o Keycloak falhar, o registro pendente permanece para permitir nova tentativa, sem que o usuário seja tratado como deletado.

A exclusão física no Keycloak remove nome, e-mail, senha, roles, atributos e consentimentos associados à conta. O e-mail de comprovação da exclusão (LGPD) é enviado ao endereço lido no momento da exclusão; o endereço não é persistido no banco de tombstones.

## 3. Scripts

Os scripts ficam em `deploy/scripts/` e usam o `deploy/docker-compose.yaml`. Eles assumem os serviços `postgres`, `keycloak-db`, `tombstone-db`, `keycloak` e `backend` do compose de desenvolvimento usado na demonstração.

### 3.1 Backup

```bash
# a partir da raiz do repositório
bash deploy/scripts/backup.sh
# ou com destino explícito
bash deploy/scripts/backup.sh /caminho/do/backup
```

O diretório gerado contém:

| Arquivo | Conteúdo |
|---|---|
| `app.dump` | `pg_dump` custom do banco da aplicação |
| `keycloak.dump` | `pg_dump` custom do banco do Keycloak (inclui usuários) |
| `tombstones.dump` | `pg_dump` custom do banco de tombstones (recuperação de desastre) |
| `tombstones.csv` | exportação dos tombstones **confirmados**, usada no restore com união |
| `media.tar.gz` | arquivos de documentos (`/app/media`) quando o backend está rodando |
| `SHA256SUMS` | checksums dos arquivos |
| `manifest.json` | data, commit e lista de arquivos |

O script valida os dumps com `pg_restore --list` antes de considerá-los válidos. O `tombstones.csv` inclui apenas tombstones confirmados; os pendentes ficam no dump de recuperação de desastre, mas não são usados na união do restore.

O `backup.sh` é completo e sob demanda: o RPO do banco de tombstones é o intervalo entre duas execuções. Uma proposta de backup incremental por exclusão (não implementada) está descrita em [backup-incremental-tombstones.md](backup-incremental-tombstones.md).

### 3.2 Restauração

```bash
bash deploy/scripts/restore.sh deploy/backups/20261019T230000Z
# em automação, sem prompt:
bash deploy/scripts/restore.sh deploy/backups/20261019T230000Z --yes
```

Fluxo do script:

1. valida arquivos e checksums;
2. para `backend` e `keycloak`;
3. restaura `app.dump` e `keycloak.dump` com `pg_restore --clean`;
4. restaura `media.tar.gz`;
5. aplica as migrations (inclusive `--database=tombstones`);
6. copia `tombstones.csv` para o banco independente e faz `INSERT ... ON CONFLICT DO UPDATE` (união, nunca remoção; como o CSV só contém confirmados, um tombstone pendente com o mesmo hash é promovido a confirmado);
7. sobe o Keycloak e o backend;
8. executa:

```bash
python manage.py purge_deleted_users --verificar --aguardar 180
```

O comando `purge_deleted_users`:

- considera apenas tombstones **confirmados** — registros pendentes são ignorados, pois podem representar uma tentativa que não concluiu a remoção;
- lista **todos** os usuários do Keycloak restaurado (paginando antes de deletar, para a paginação não pular ninguém);
- calcula o SHA-256 de cada id e deleta quem está no banco de tombstones;
- com `--verificar`, relê o Keycloak e termina com **exit code 1** se algum usuário deletado ainda existir.

Se a verificação falhar, o restore termina com erro e a restauração não é considerada concluída.

## 4. Demonstração ponta a ponta

Sequência sugerida para apresentar o critério:

```bash
cd deploy

# 1. Suba o ambiente
docker compose up -d postgres tombstone-db keycloak-db keycloak backend

# 2. Crie um usuário de teste no Keycloak (Dashboard ou Admin API)

# 3. Faça o backup COM o usuário existindo
bash scripts/backup.sh

# 4. Delete o usuário pela API (com token de operador)
#    DELETE /api/usuarios/<id>   -> 204 e tombstone confirmado
#    ou peça ao próprio usuário: DELETE /api/usuarios/

# 5. Restaure o backup que ainda contém o usuário
bash scripts/restore.sh backups/<timestamp> --yes
```

Na etapa 5, o `pg_restore` traz o usuário de volta por alguns segundos, mas o comando de purga o remove novamente e imprime:

```text
Verificação concluída: nenhum usuário deletado foi restaurado.
```

Para inspecionar manualmente depois do restore:

```bash
docker compose exec -T backend python manage.py purge_deleted_users --dry-run
# 0 usuário(s) deletado(s) seriam removidos do Keycloak.
```

## 5. Variáveis de ambiente

| Variável | Padrão | Uso |
|---|---|---|
| `DELETED_USERS_DB_NAME` | `deleted_users_db` | nome do banco de tombstones |
| `DELETED_USERS_DB_USER` | mesmo usuário do banco da aplicação | usuário do banco de tombstones |
| `DELETED_USERS_DB_PASSWORD` | mesma senha do banco da aplicação | senha do banco de tombstones |
| `DELETED_USERS_DB_HOST` | `tombstone-db` (compose) | host do banco de tombstones |
| `DELETED_USERS_DB_PORT` | `5432` | porta do banco de tombstones |
| `EMAIL_BACKEND` | console (dev) | backend de e-mail; use SMTP em produção |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` | — | SMTP |
| `DEFAULT_FROM_EMAIL` | `nao-responda@sqlutions.example.com` | remetente da comprovação |

## 6. Limitações e cuidados

- **O banco de tombstones é a garantia.** Se ele for perdido ou restaurado para um estado antigo, um usuário deletado pode voltar. Faça backup dele separadamente, com retenção append-only, e restrinja o acesso.
- **Tombstones pendentes não são prova de exclusão.** Eles indicam que o tombstone foi criado, mas o Keycloak não confirmou a remoção. Se houver pendentes antigos, investigue antes de tratá-los como concluídos.
- **Backups antigos não distinguem pendentes.** O CSV de 3 colunas gerado antes desta mudança não tem `confirmado_em`; o restore trata essas linhas como confirmadas para preservar o comportamento anterior. Apenas backups novos excluem tombstones pendentes.
- **Nunca restaure `tombstones.dump` por cima do banco vivo.** O fluxo do `restore.sh` usa o CSV com união justamente para não remover tombstones mais recentes.
- O hash permite confirmar se um UUID conhecido foi deletado (ataque de confirmação), mas não revela a identidade a partir do banco. UUIDs têm entropia suficiente para inviabilizar busca por força bruta.
- Logs de eventos/auditoria do Keycloak e de proxies podem reter o id do usuário; a política de retenção desses logs é uma decisão operacional.
- O e-mail de comprovação é *best-effort*: a exclusão física já ocorreu quando ele é enviado. Falhas de SMTP são registradas no log, não desfazem a exclusão. Em produção, configure um SMTP real.
