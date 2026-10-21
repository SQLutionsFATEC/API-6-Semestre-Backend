# Autenticação e Gestão de Usuários com Keycloak (Card 39)

Este documento explica como o backend usa o **Keycloak** como fonte de verdade de identidade e como interagir com ele via **Admin REST API** para fazer o CRUD de usuários e ler suas permissões.

- README da prova de conceito original do Keycloak, que originou esta implementação: [docs/keycloak_poc/README.md](../keycloak_poc/README.md)
- Manual de documentação de rotas (Swagger): [docs/api/manual-documentacao-rotas.md](../api/manual-documentacao-rotas.md)

## 1. Subindo o Keycloak

O serviço está definido em [deploy/docker-compose.yaml](../../deploy/docker-compose.yaml):

```bash
cd deploy
docker compose -f docker-compose.yaml up -d keycloak keycloak-db
```

- **Dashboard do Keycloak:** http://localhost:8080
- **Perfil administrador:** `admin` / `admin` (configurável por `KC_BOOTSTRAP_ADMIN_USERNAME` / `KC_BOOTSTRAP_ADMIN_PASSWORD` no `deploy/.env`).
- No primeiro start o realm **`sqlutions`** é importado automaticamente de [deploy/keycloak/realm-export.json](../../deploy/keycloak/realm-export.json).
- Usuário de exemplo já criado no realm: login `usuario` (ou `usuario@example.com`) e senha `usuario`, nível `basico` e setor `tecnico`. O atributo `setor` é um atributo gerenciado do **perfil declarativo de usuários** do realm (componente `declarative-user-profile` no realm-export).

## 2. Estrutura de identidade no realm `sqlutions`

Não há modelagem de usuário no banco do Django: o Keycloak é a fonte da verdade. As regras de negócio são:

| Campo de negócio | Onde vive no Keycloak | Valores | Padrão |
|---|---|---|---|
| `nome` | campo `firstName` (e `lastName`) do usuário | livre | — |
| `email` | campo `email` do usuário (nos usuários criados pelo backend, o `username` é o próprio e-mail) | e-mail | — |
| `nivel_acesso` | **realm role**: `basico`, `comercial`, `militar`, `operador` | — | `basico` (role default do realm) |
| `setor` | **atributo do usuário** exposto como claim `setor` no JWT via protocol mapper | `tecnico`, `normativo`, `juridico`, `qualitativo` | `tecnico` |
| administração | realm role `admin` | — | — |

Clients do realm:

- `frontend` (public) — login via authorization code + PKCE (os testes de ponta a ponta também usam direct access grants, que está ligado no client); possui um protocol mapper que copia o atributo `setor` do usuário para o claim `setor` do access token.
- `backend` (confidencial, com service account habilitado) — resource server: é este backend Django, que valida o JWT localmente (RS256 via JWKS, `iss` e `exp`) e usa o service account para chamar a Admin REST API.

## 3. Token do service account (Admin REST API)

Todas as chamadas à Admin REST API exigem um token. O backend usa o **service account (client credentials)** do client confidencial `backend`, que vive no próprio realm `sqlutions` e cujo service account tem apenas as roles de `realm-management` necessárias para o CRUD de usuários. O perfil `admin:admin` do realm master serve **somente** para o Dashboard, na administração manual — não é usado em runtime pela aplicação.

```bash
# Base em uso pelo backend: http://keycloak:8080 (host local: http://localhost:8080)
curl -s -X POST "http://localhost:8080/realms/sqlutions/protocol/openid-connect/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=backend&client_secret=backend-secret"
```

A resposta contém `access_token`; use-o no header de todas as chamadas abaixo:

```bash
TOKEN="<access_token>"
curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:8080/admin/realms/sqlutions/users"
```

> O backend Django já faz isso automaticamente via [django/api/services/keycloak_admin.py](../../django/api/services/keycloak_admin.py) (credenciais em `KEYCLOAK_BACKEND_CLIENT_ID` / `KEYCLOAK_BACKEND_CLIENT_SECRET`).
>
> O `client_secret` padrão (`backend-secret`) está no realm-export apenas para facilitar o setup local. Em produção, rotacione o secret no Keycloak e injete o valor por variável de ambiente/secret manager.

## 4. CRUD de usuários pela Admin API

Nos exemplos, `REALM=sqlutions` e `KC=http://localhost:8080`.

### 4.1 Criar usuário (com senha temporária)

```bash
curl -s -X POST "$KC/admin/realms/$REALM/users" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "novo.usuario@example.com",
    "email": "novo.usuario@example.com",
    "firstName": "Novo",
    "lastName": "Usuario",
    "enabled": true,
    "attributes": { "setor": ["tecnico"] },
    "credentials": [
      { "type": "password", "value": "senha-provisoria", "temporary": true }
    ]
  }'
```

- `temporary: true` marca a senha como **temporária**: o usuário é obrigado a trocá-la no primeiro login.
- **Atenção (Keycloak 26):** o campo `realmRoles` do payload de criação é _ignorado_ — a role de nível deve ser atribuída depois, no endpoint `role-mappings/realm` (ver 4.3). Por padrão de negócio, um usuário criado sem roles adicionais começa como nível `basico` (role default do realm) e setor `tecnico`.
- **Atenção (perfil declarativo):** o perfil declarativo do Keycloak 26 exige `firstName` **e** `lastName` preenchidos para aceitar o login direto; o contrário devolve `"error": "invalid_grant", "error_description": "Account is not fully set up"` (a mesma mensagem aparece quando há required actions pendentes, ex.: senha temporária).
- Em sucesso a resposta é `201 Created` com header `Location: .../users/<id>` (o `id` é o `sub` usado pelo backend).

### 4.2 Ler os campos de um usuário

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$KC/admin/realms/$REALM/users/<id>"
```

Retorna a `UserRepresentation`: `firstName`, `lastName`, `email`, `enabled`, `attributes` (onde está o `setor`), etc. Para listar/buscar usuários:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$KC/admin/realms/$REALM/users?search=maria&first=0&max=100"
```

### 4.3 Modificar campos de um usuário

Campos básicos (`PUT` em `/users/<id>`):

```bash
curl -s -X PUT "$KC/admin/realms/$REALM/users/<id>" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "firstName": "Nome Novo", "email": "novo@email.com" }'
```

> **Atenção:** o `PUT` da Admin API substitui a **representação inteira** do usuário — campos ausentes no corpo viram valores vazios. Envie também `firstName`, `lastName` e `email` que não devem ser perdidos (o backend faz esse merge automaticamente em [django/api/services/keycloak_admin.py](../../django/api/services/keycloak_admin.py)).

**Setor** (campo de negócio — atributo do usuário):

```bash
curl -s -X PUT "$KC/admin/realms/$REALM/users/<id>" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "attributes": { "setor": ["juridico"] } }'
```

**Nível de acesso** (campo de negócio — realm role). Primeiro remova o nível atual, depois atribua o novo em `role-mappings/realm`:

```bash
# 1. Listar roles atuais (veja 5.1) e montar o payload de remoção
curl -s -X DELETE "$KC/admin/realms/$REALM/users/<id>/role-mappings/realm" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '[{ "id": "<id-da-role-basico>", "name": "basico" }]'

# 2. Buscar o id da nova role e atribuir
curl -s -H "Authorization: Bearer $TOKEN" \
  "$KC/admin/realms/$REALM/roles/operador"   # retorna { "id": ..., "name": "operador" }

curl -s -X POST "$KC/admin/realms/$REALM/users/<id>/role-mappings/realm" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '[{ "id": "<id-da-role-operador>", "name": "operador" }]'
```

**Senha (nova) — inclusive temporária.** Endpoint dedicado `PUT /users/<id>/reset-password`:

```bash
curl -s -X PUT "$KC/admin/realms/$REALM/users/<id>/reset-password" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "type": "password", "value": "nova-senha", "temporary": true }'
```

- `temporary: true` → usuário deve trocar a senha no próximo login.
- Alternativa sem definir senha: enviar por e-mail um link de redefinição (ação `UPDATE_PASSWORD`):

```bash
curl -s -X PUT "$KC/admin/realms/$REALM/users/<id>/execute-actions-email" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '["UPDATE_PASSWORD"]'
```

### 4.4 Deletar usuário

```bash
curl -s -X DELETE "$KC/admin/realms/$REALM/users/<id>" \
  -H "Authorization: Bearer $TOKEN"
```

Em sucesso responde `204 No Content`.

## 5. Lendo as permissões de um usuário

### 5.1 Pela Admin API (roles do usuário)

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$KC/admin/realms/$REALM/users/<id>/role-mappings/realm"
```

Resposta (lista de roles; backend mapeia o que importa):

```json
[
  { "id": "...", "name": "operador", "description": "..." },
  { "id": "...", "name": "offline_access" }
]
```

- Se a lista contém `operador` → usuário é operador (acessa tudo e gerencia requisições de acesso).
- O `nivel_acesso` é a role entre `basico`/`comercial`/`militar`/`operador` (ordinal define o grau de documento visível junto ao setor).
- O `setor` vem do campo `attributes.setor` da resposta do usuário (4.2).

### 5.2 Pelo access token (sem chamada à Admin API)

O JWT validado pelo backend já carrega as permissões (decode com [jwt.io](https://jwt.io) ou `GET $KC/realms/$REALM/protocol/openid-connect/userinfo`):

```json
{
  "sub": "9b1deb4d-...",
  "preferred_username": "maria@example.com",
  "email": "maria@example.com",
  "setor": "juridico",
  "realm_access": { "roles": ["operador"] }
}
```

No backend, depois da autenticação, `request.user` expõe `id`, `username`, `nome`, `email`, `nivel_acesso`, `setor` e `has_role('operador')` ([api/authentication/keycloak.py](../../django/api/authentication/keycloak.py)).

## 6. Interagindo pelo backend (rotas novas)

As rotas abaixo usam o token Bearer do Keycloak e a Admin REST API; estão documentadas no Swagger (**http://localhost:8000/api/docs/**):

| Rota | Método | Quem pode | O que faz |
|---|---|---|---|
| `/api/perfil/` | GET | usuário autenticado | lê o próprio perfil (nome, email, nivel_acesso, setor) |
| `/api/perfil/` | PATCH | usuário autenticado | altera o próprio nome/email |
| `/api/usuarios/` | GET | role `admin` | lista usuários (filtro `?busca=`) |
| `/api/usuarios/` | POST | role `admin` | cria usuário com senha temporária, nivel_acesso e setor |
| `/api/usuarios/{id_usuario}/` | GET | role `admin` | lê campos e permissões de um usuário |
| `/api/usuarios/{id_usuario}/` | PATCH | role `admin` | altera campos (incl. setor, nivel_acesso e senha temporária) |
| `/api/usuarios/` | DELETE | usuário autenticado | deleta a própria conta (autoatendimento) |
| `/api/usuarios/{id_usuario}/` | DELETE | role `operador` | deleta o usuário do realm e grava tombstone |

> As rotas de deleção também aceitam o caminho sem barra final (`/api/usuarios` e `/api/usuarios/{id_usuario}`). A deleção por id exige a role `operador`; a role `admin` isolada não é suficiente.

Exemplos de uso para desenvolvimento (com token do **usuário**, não do admin):

```bash
# Perfil do usuário autenticado
curl -s -H "Authorization: Bearer $USER_TOKEN" http://localhost:8000/api/perfil/

# Criar usuário (admin do projeto, ex.: token de um usuário com role admin)
curl -s -X POST http://localhost:8000/api/usuarios/ \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "nome": "Jose Almeida",
    "sobrenome": "Souza",
    "email": "jose@example.com",
    "senha_temporaria": "trocar-depois",
    "nivel_acesso": "operador",
    "setor": "qualitativo"
  }'

# Trocar o nível de um usuário para operador + senha temporária
curl -s -X PATCH http://localhost:8000/api/usuarios/<id>/ \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "nivel_acesso": "operador", "senha": "trocando-123", "senha_temporaria": true }'
```

## 7. Exclusão de usuários e banco de tombstones

A exclusão é **física**: o usuário é removido do Keycloak (nome, e-mail, senha, roles e atributos). Para garantir que ele não volte após a restauração de um backup, cada exclusão grava um tombstone em um banco independente (`tombstone-db`, alias Django `tombstones`). O tombstone contém apenas o SHA-256 do id do Keycloak, a data e a origem (`autoatendimento`/`operador`) — nunca nome, e-mail ou o id em claro.

- `DELETE /api/usuarios/` — o próprio usuário autenticado deleta a conta.
- `DELETE /api/usuarios/{id}/` — exige a realm role `operador`; retorna `403` sem ela e `404` se o usuário não existir.
- O e-mail de comprovação da exclusão é enviado ao endereço cadastrado (LGPD). Em dev o backend de e-mail é o console; configure SMTP em produção.

Após restaurar um backup do Keycloak, execute:

```bash
cd deploy
docker compose exec -T backend python manage.py purge_deleted_users --verificar --aguardar 180
```

O comando remove do Keycloak restaurado todos os usuários tombstoned e falha (exit code 1) se algum deles continuar existindo. Os scripts de backup e restauração que automatizam esse fluxo estão documentados em [docs/api/backup-restore.md](../api/backup-restore.md).

## 8. Variáveis de ambiente do backend

| Variável | Padrão | Uso |
|---|---|---|
| `KEYCLOAK_URL` | `http://keycloak:8080` | base para validar JWT e chamar a Admin API |
| `KEYCLOAK_REALM` | `sqlutions` | realm do projeto |
| `KEYCLOAK_ISSUER` | `{KEYCLOAK_URL}/realms/{realm}` | claim `iss` esperado no token |
| `KEYCLOAK_BACKEND_CLIENT_ID` | `backend` | client confidencial cujo service account acessa a Admin REST API |
| `KEYCLOAK_BACKEND_CLIENT_SECRET` | `backend-secret` (só dev) | secret do service account (rotacionar fora de dev) |
| `KEYCLOAK_JWKS_TTL` | `300` | intervalo de cache do JWK Set (segundos) |
| `DELETED_USERS_DB_NAME` | `deleted_users_db` | banco independente de tombstones |
| `DELETED_USERS_DB_USER` | mesmo do banco da aplicação | usuário do banco de tombstones |
| `DELETED_USERS_DB_PASSWORD` | mesma do banco da aplicação | senha do banco de tombstones |
| `DELETED_USERS_DB_HOST` | `tombstone-db` | host do banco de tombstones |
| `DELETED_USERS_DB_PORT` | `5432` | porta do banco de tombstones |
| `EMAIL_BACKEND` | console (dev) | backend de e-mail da comprovação de exclusão |
| `DEFAULT_FROM_EMAIL` | `nao-responda@sqlutions.example.com` | remetente da comprovação |
