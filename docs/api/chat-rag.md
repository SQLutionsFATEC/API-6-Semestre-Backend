# Documentação e Guia de Utilização — Rota de Conversa com o Chat (`/api/chat`)

Este documento descreve o funcionamento, a arquitetura e como utilizar a rota `/api/chat` para conversação contextualizada sobre documentos utilizando **NLP (spaCy)** e **RAG (Retrieval-Augmented Generation)**.

---

## 1. Visão Geral do Funcionamento

A rota `POST /api/chat` permite que um usuário autenticado converse com o assistente sobre o acervo de documentos da aplicação. A cada mensagem enviada, o fluxo executa as seguintes etapas:

1. **Autenticação (`401 Unauthorized`)**:
   - Valida o token JWT Bearer emitido pelo Keycloak (`KeycloakAuthentication`). Caso o usuário não esteja autenticado ou o token seja inválido/expirado, a rota retorna `401 Unauthorized`.

2. **Controle Estrito de Acesso aos Documentos**:
   - Antes e durante a busca e geração RAG, apenas documentos que o usuário atual possui permissão de acesso são considerados.
   - Um documento é considerado acessível para o usuário quando:
     - Passa pela regra padrão de autorização (`verificar_acesso` em `django/api/services/authorization_service.py`): `(Setor Usuário == Setor Documento E Nível Usuário >= Nível Documento) OU Nível Usuário == Operador`; **OU**
     - Possui uma solicitação de acesso especial aprovada para aquele usuário na tabela `solicitacao_acesso` (`SolicitacaoAcesso` com `approved=True`).

3. **Extração de Substantivos via NLP (`spaCy`)**:
   - A partir da mensagem atual do usuário (último item da lista `context`), o serviço `ChatService.extrair_substantivos_mensagem` utiliza o modelo do `spaCy` (`TaggingService.nlp_texto`) para extrair e lematizar os substantivos relevantes.
   - Caso a frase não produza substantivos filtráveis pelo pipeline (ex.: siglas curtas), o texto original limpo é utilizado como fallback seguro.

4. **Busca Semântica por Contexto (Top 3 Documentos Mais Relevantes)**:
   - Utilizando os termos extraídos da mensagem atual, o serviço consulta a base vetorial (`DocumentoChunk` via `pgvector` e `VectorService.gerar_embedding`), restrita **exclusivamente** aos IDs de documentos acessíveis pelo usuário.
   - Os trechos mais próximos semanticamente são agrupados por documento e limitados aos **3 documentos mais relevantes** à mensagem atual.

5. **Geração de Resposta em Linguagem Natural (Método RAG) sem Timeout**:
   - O método `ChatService.gerar_resposta_rag` monta o prompt do sistema com o conteúdo dos **três documentos mais relevantes** e todo o histórico da conversa (`context`), alternando os papéis `user` e `assistant`.
   - A chamada ao servidor de inferência (`llama.cpp` compatível com `/v1/chat/completions`) e o servidor Gunicorn (`--timeout 0`) são configurados sem timeout restritivo para evitar que requisições mais longas sofram queda por tempo limite.

---

## 2. Especificação do Endpoint

- **URL**: `/api/chat` (ou `/api/chat/`)
- **Método Permitido**: `POST` (qualquer outro método como `GET`, `PUT`, `PATCH` ou `DELETE` retorna `405 Method Not Allowed`)
- **Autenticação**: `Bearer <access_token_keycloak>`
- **Documentação Swagger UI**: `http://localhost:8000/api/docs/`

### Estrutura do Body da Requisição (`application/json`)

O corpo da requisição deve conter a chave `context` com uma lista de strings representando o histórico da conversa, onde o último elemento é a mensagem atual do usuário:

```json
{
  "context": [
    "mensagem 1",
    "resposta do sistema",
    "resposta do usuario"
  ]
}
```

### Estrutura da Resposta (`200 OK`)

```json
{
  "response": "Com base nos manuais técnicos disponíveis para o seu perfil, o procedimento de manutenção exige...",
  "documents": [
    {
      "id_documento": 12,
      "nome": "Manual_Manutencao.pdf",
      "setor": "Tecnico",
      "nivel": "Basico",
      "pagina": 4,
      "conteudo": "Documento: Manual_Manutencao.pdf.\n# Capítulo 2..."
    }
  ]
}
```

### Códigos de Status HTTP

| Código | Descrição |
|---|---|
| `200 OK` | Resposta gerada com sucesso em linguagem natural via RAG e lista dos até 3 documentos utilizados. |
| `400 Bad Request` | Payload inválido (ex.: campo `context` ausente, lista vazia ou elementos que não sejam strings válidas). |
| `401 Unauthorized` | Usuário não autenticado ou token Bearer ausente/inválido (`Unauthenticated`). |
| `405 Method Not Allowed` | Método HTTP diferente de `POST`. |

---

## 3. Exemplos de Como Utilizar

### Exemplo 1: Via `cURL`

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Authorization: Bearer SEU_TOKEN_KEYCLOAK" \
  -H "Content-Type: application/json" \
  -d '{
    "context": [
      "Hello, I need information from the maintenance manuals.",
      "Hello! Which topic would you like to search?",
      "What causes surface corrosion and pitting on polished blades?"
    ]
  }'
```

### Exemplo 2: Via `JavaScript / Fetch` (Frontend)

```javascript
async function enviarMensagemChat(historicoContexto, accessToken) {
  const response = await fetch("http://localhost:8000/api/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${accessToken}`,
    },
    body: JSON.stringify({
      context: historicoContexto,
    }),
  });

  if (response.status === 401) {
    throw new Error("Usuário não autenticado (401 Unauthenticated)");
  }

  if (!response.ok) {
    const erro = await response.json();
    throw new Error(JSON.stringify(erro));
  }

  return await response.json();
}
```

### Exemplo 3: Via Swagger UI

1. Suba o ambiente com Docker Compose:
   ```bash
   cd deploy
   docker compose up -d --build
   ```
2. Acesse `http://localhost:8000/api/docs/`.
3. Clique no botão **Authorize** no topo da página e informe o token JWT Bearer obtido no Keycloak.
4. Localize o endpoint **`POST /api/chat`**, clique em **Try it out**, preencha o JSON com `{"context": ["mensagem 1", "resposta do sistema", "resposta do usuario"]}` e clique em **Execute**.

---

## 4. Variáveis de Ambiente Opcionais (Configuração do RAG)

O serviço utiliza por padrão a infraestrutura do `llama.cpp` já configurada no projeto, podendo ser customizado via variáveis de ambiente:

| Variável | Valor Padrão | Descrição |
|---|---|---|
| `LLAMA_CPP_CHAT_HOST` | Valor de `LLAMA_CPP_HOST` (`http://llama-cpp:8080`) | Host do servidor LLM para geração de chat. |
| `LLAMA_CPP_CHAT_ENDPOINT` | `/v1/chat/completions` | Endpoint compatível com OpenAI Chat Completions. |
| `LLAMA_CPP_CHAT_MODEL` | `gemma-4-E4B-it` | Nome do modelo utilizado na geração RAG. |
| `LLAMA_CPP_CHAT_TIMEOUT` | `None` (sem timeout) | Tempo limite em segundos (vazio/`None` desativa o timeout para evitar quedas em gerações longas). |

---

## 5. Arquivos Criados e Atualizados no Projeto

- **`django/api/services/chat_service.py`**: Implementação do `ChatService` (extração de substantivos via `spaCy`, validação de acesso por usuário + `SolicitacaoAcesso`, busca contextual dos 3 documentos mais relevantes e método RAG sem timeout).
- **`django/api/serializers/chat_serializer.py`**: Serializers de entrada (`ChatRequestSerializer`) e saída (`ChatResponseSerializer`, `ChatDocumentoRelevanteSerializer`).
- **`django/api/views/chat_api.py`**: View `ChatView` (`POST /api/chat`) com autenticação obrigatória e documentação `@extend_schema` do `drf-spectacular` (Swagger).
- **`django/api/urls.py`**: Registro da rota `/api/chat`.
- **`django/api/tests_unit/test_chat_api.py`**: Testes automatizados validando autenticação (`401`), restrição ao método `POST` (`405`), validação de body (`400`), extração de substantivos com `spaCy`, filtragem estrita por acesso do usuário, limite de 3 documentos no RAG e ausência de timeout.
- **`docs/api/manual-documentacao-rotas.md`**: Atualizado com a seção da rota `/api/chat`.
