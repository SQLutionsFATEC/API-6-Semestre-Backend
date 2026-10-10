# Autenticação e Gestão de Usuários com Keycloak

Este diretório contém a Prova de Conceito (POC) do sistema de **Autenticação e Gestão de Usuários** construído para centralizar a identidade da aplicação em um provedor externo.

O objetivo é autenticar o usuário no **Keycloak**, validar o token de acesso no backend e usar as informações do provedor (roles de nível e atributo de setor) para decidir o que cada usuário pode **ver, editar e acessar**. A POC também cobre a edição do próprio perfil e um fluxo de exclusão de usuário compatível com a LGPD.

## Contexto da Solução

Enquanto a busca semântica (banco vetorial) e a categorização (Machine Learning) focam no **conteúdo dos documentos**, este sistema foca em **quem acessa o quê**. Ele existe para substituir o usuário local do Django por um provedor de identidade centralizado, sem `createsuperuser` e sem sessão.

Para resolver isso, utilizamos:
* **Keycloak 26:** provedor de identidade (IdP) e fonte da verdade dos dados do usuário, com o realm `poc` importado de `realm-export.json`.
* **Django REST Framework:** valida o access token (JWT RS256) localmente e aplica a regra de autorização, sem consultar o Keycloak a cada requisição.
* **React + Vite:** frontend que faz login via `keycloak-js` com **authorization code + PKCE**.
* **PostgreSQL:** banco do Keycloak (serviço `keycloak-db`), que mantém o realm persistente entre reinicializações e é acessível de fora do Docker.

## Estrutura de Identidade

A autorização não fica no frontend nem no Keycloak: é uma **regra de negócio do Django** que decide, a cada requisição, cruzando as informações do token com as do documento.

* **Nível de acesso = role de realm** (`basico`, `comercial`, `militar`, `operador`), lida do **token**: as roles do claim `realm_access` viram `request.user.nivel`.
* **Setor = atributo de usuário** (`tecnico`, `normativo`, `juridico`, `qualitativo`), lido do **token** (claim `setor`, via protocol mapper no client emissor) e persistido como atributo no Keycloak.
* **Admin REST API:** usada apenas em `GET/PATCH /api/perfil/` e `GET/PATCH /api/usuarios/`, para ler e editar o usuário no Keycloak — ela **não** participa da regra de acesso.
* **Regra de acesso a documentos:** `operador` acessa tudo; fora disso, o acesso é automático apenas se o setor do usuário for o do documento **e** o ordinal do nível do usuário for maior ou igual ao do documento; em qualquer outra combinação, o usuário precisa **requisitar** o acesso a um operador.

Além de `operador` (decide requisições e acessa tudo) e dos 4 níveis de documento, o realm declara a role `admin`, usada só para gerir usuários pela página `/usuarios`.

## Funcionamento

O fluxo principal da Autenticação é:

```text
Navegador (React)
      ↓
Login (authorization code + PKCE)
      ↓
Keycloak (realm "poc")
      ↓
Access token (JWT)
      ↓
Backend Django/DRF (valida RS256 + iss + exp)
      ↓
Regra de autorização do Django (nível × setor)
      ↓
Documento liberado ou requisição ao operador
```

O backend **valida o token localmente** (assinatura RS256 via JWK set, além de `iss` e `exp`), identificando o usuário pelo claim `sub`. A leitura e a edição do perfil vêm da **Admin API**, e não das claims do token: o access token só é reemitido no _refresh_ seguinte, então uma edição ficaria invisível por alguns instantes se a leitura usasse as claims.

## Resultado esperado

Após o login, o frontend exibe o perfil do usuário e permite editá-lo; a gravação é enviada pela Admin API até o Keycloak. A regra de acesso passa a liberar somente os documentos compatíveis com o nível e o setor do usuário autenticado.

Exemplo de verificação do fluxo:

```text
👤 Usuário  : appuser (nível básico, setor Técnico)
📄 Perfil   : nome, e-mail, username, sub e roles lidos de GET /api/perfil/
💾 Edição   : sobrenome salvo pela Admin API persiste no Keycloak
🔓 Acesso   : apenas os documentos básicos do Técnico ficam liberados
🔒 Bloqueio : documentos de outro setor exigem requisição a um operador
```

Exclusão de usuário (LGPD), quando aplicada:

```text
🗑️  appuser excluído do realm + "tombstone" gravado no diário de exclusões
📝  Requisições do usuário ficam anônimas no banco do Django
♻️  aplicar_exclusoes é idempotente e reaplica o diário após qualquer restore
```

Com os dados modelados dessa forma, a autenticação fica pronta para ser adotada pelo projeto-alvo, bastando apontar a regra de autorização para o `Documento` já existente.

## Estrutura no projeto

Os recursos de Autenticação e Gestão de Usuários podem ser executados e auditados de forma independente. O ambiente contém:

```text
keycloak-poc/
├── docker-compose.yml       # keycloak + keycloak-db + backend + frontend
├── keycloak/
│   ├── realm-export.json    # realm declarativo (importado no start)
│   └── exclusoes.json       # diário de exclusões LGPD (vazio por padrão)
├── backend/                 # Django + DRF
│   └── api/
│       ├── authentication/keycloak.py   # validação do JWT (JWKS)
│       ├── services/keycloak_admin.py   # Admin API (ler/editar usuário)
│       ├── services/autorizacao.py      # regra de acesso a documentos
│       ├── services/exclusoes.py        # exclusões LGPD + diário
│       ├── management/commands/         # seed_documentos, excluir_usuario, aplicar_exclusoes
│       └── views/                       # health, perfil, documentos, requisicoes, usuarios
└── frontend/                # React + Vite
    └── src/
        ├── auth/              # keycloak-js, AuthProvider, RotaComRole
        ├── services/          # axios + services de documentos, requisicoes, usuarios
        └── pages/             # Documentos, Requisicoes, Usuarios, Perfil
```

## Repositório Oficial do Keycloak POC

Todo o código-fonte executável desta Prova de Conceito, contendo o `docker-compose.yml`, o realm declarativo, o backend Django e o frontend React, está isolado no repositório de desenvolvimento da POC.

🔗 Acessar código-fonte e instruções de execução:
Repositório: Keycloak POC - Autenticação e Gestão de Usuários
https://github.com/d-broder/keycloack-poc
