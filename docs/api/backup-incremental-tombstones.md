# Backup incremental do banco de tombstones (proposta)

> **Status: não implementado.** Este documento descreve, de forma resumida, como o backup incremental do banco auxiliar de usuários deletados funcionaria se fosse implementado. O backup completo descrito em [backup-restore.md](backup-restore.md) continua sendo o mecanismo vigente.

## 1. Motivação

O banco de tombstones é a garantia de que um usuário deletado não volta depois de restaurar um backup do Keycloak. Hoje ele só é copiado quando alguém executa [backup.sh](../../deploy/scripts/backup.sh); entre duas execuções, novas exclusões existem apenas no banco vivo. O incremental copiaria cada novo tombstone logo depois que ele fosse gravado, sem refazer o dump da tabela inteira.

O backup completo continua sendo o baseline; o incremental cobre apenas o intervalo entre duas execuções.

## 2. Como funcionaria

### 2.1 Marcação no banco

Duas colunas em `usuario_deletado`:

```sql
ALTER TABLE usuario_deletado
    ADD COLUMN seq BIGSERIAL UNIQUE,
    ADD COLUMN backup_exportado_em TIMESTAMPTZ;
```

`seq` ordena as linhas pendentes e serve apenas como cursor local. `backup_exportado_em` indica o que já foi copiado; a exportação seleciona somente `WHERE backup_exportado_em IS NULL AND confirmado_em IS NOT NULL`, pois tombstones pendentes ainda não provam uma exclusão concluída.

### 2.2 Exportação

1. Depois da confirmação do tombstone, o backend tenta exportar as pendências.
2. Seleciona as linhas confirmadas em ordem de `seq` e grava um segmento JSONL:

```json
{"v":1,"id_usuario_hash":"d69b528346b07755bdb88356c047f5339dc3d6989ca6e14a4a6a2ae71e1d5141","deletado_em":"2026-10-21T18:50:39.123456Z","confirmado_em":"2026-10-21T18:50:40.654321Z","origem":"operador","exportado_em":"2026-10-21T18:50:41.654321Z"}
```

3. Gera um SHA-256 do arquivo e um manifest que aponta para o hash do segmento anterior.
4. Marca as linhas como exportadas.
5. Se algo falhar, um cron repete a exportação a cada minuto. A exclusão no Keycloak não depende do backup.

Se o processo cair depois de gravar o segmento e antes de marcar as linhas, a próxima execução reexporta; o replay deduplica.

Com mais de uma réplica do backend, um advisory lock do PostgreSQL garante que só uma exportação rode por vez. No ambiente de demonstração existe uma única instância.

### 2.3 Restauração

Antes da purga, o [restore.sh](../../deploy/scripts/restore.sh) passaria a:

1. validar os checksums e a cadeia de manifests;
2. aplicar os registros confirmados com `INSERT ... ON CONFLICT (id_usuario_hash) DO UPDATE`;
3. conferir se todo registro do ledger existe na tabela;
4. executar `purge_deleted_users --verificar`.

Se o ledger estiver ausente ou corrompido, o restore deve abortar. Registros na tabela que não estão no ledger são permitidos: são tombstones mais novos e ficam pendentes de exportação.

## 3. Cuidados

- O destino do backup precisa ficar fora do volume do banco; em produção, em outro host ou storage com versionamento.
- A retenção é indefinida: apagar o ledger reabre a possibilidade de um usuário voltar.
- O hash é pseudonimizado; restrinja o acesso e use criptografia em repouso.
- Monitore linhas não exportadas (`backup_exportado_em IS NULL`) e tombstones pendentes (`confirmado_em IS NULL`) e alerte se envelhecerem.
