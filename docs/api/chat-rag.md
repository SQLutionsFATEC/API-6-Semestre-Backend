# Documentação e Guia de Utilização — Rota de Conversa com o Chat (`/api/chat`)

Este documento descreve o funcionamento, a arquitetura e como utilizar a rota `/api/chat` para conversação contextualizada sobre documentos utilizando **NLP (spaCy)**, o **mecanismo de busca por contexto do sistema** e **RAG (Retrieval-Augmented Generation)** via **`llama.cpp`**.

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
   - A partir da mensagem atual do usuário (último item da lista `context`), o serviço `ChatService.extrair_substantivos_mensagem` chama o método `TaggingService.nlp_texto` (que utiliza o `spaCy` já configurado no projeto) para extrair os substantivos relevantes da mensagem.

4. **Busca por Contexto Reutilizando o Mecanismo Interno da Rota de Documentos (Top 3 Documentos)**:
   - O `ChatService.buscar_documentos_relevantes` utiliza o mecanismo de busca por contexto exposto em `DocumentoViewSet.filtrar_por_contexto` (em `django/api/views/documento_api.py`), que por sua vez consulta `VectorService.buscar_contexto` filtrando estritamente pelos IDs de documentos acessíveis ao usuário atual.
   - Retorna apenas os **3 documentos mais relevantes** à mensagem atual e seus respectivos trechos.

5. **Geração de Resposta em Linguagem Natural (Método RAG via `llama.cpp`) sem Timeout**:
   - O container `llama-cpp-model` baixa automaticamente dois modelos `.gguf` leves para o volume compartilhado `llamacppmodels`:
     - **`nomic-embed-text-v1.5.Q4_K_M.gguf`**: Usado pelo container `llama-cpp` exclusivamente para gerar os embeddings (vetores matemáticos de 256 dimensões).
     - **`qwen2.5-0.5b-instruct-q4_k_m.gguf`** (~390 MB): Modelo de linguagem super leve (0.5B parâmetros) carregado pelo serviço `llama-cpp-chat` para rodar rapidamente em CPU em qualquer máquina da equipe.
   - O método `ChatService.gerar_resposta_rag` envia os **três documentos mais relevantes** e o histórico da conversa (`context`) para `http://llama-cpp-chat:8080/v1/chat/completions` sem timeout restritivo (`timeout=None` e Gunicorn com `--timeout 0`).

---

## 2. Especificação do Endpoint

- **URL**: `/api/chat` (ou `/api/chat/`)
- **Método Permitido**: `POST` (qualquer outro método como `GET`, `PUT`, `PATCH` ou `DELETE` retorna `405 Method Not Allowed`)
- **Autenticação**: `Bearer <access_token_keycloak>`
- **Documentação Swagger UI**: `http://localhost:8000/api/docs/`

### Estrutura do Body da Requisição (`application/json`)

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
  "response": "Resposta em linguagem natural gerada pelo modelo no llama.cpp com base nos 3 documentos mais relevantes...",
  "documents": [
    {
      "id_documento": 4,
      "nome": "AC 20-37e.pdf",
      "setor": "juridico",
      "nivel": "Militar",
      "pagina": 8,
      "conteudo": "Documento: AC_20-37e.pdf.\n(1) Surface Corrosion..."
    }
  ]
}
```

---

## 3. Como Subir e Utilizar

1. **Subir os containers com Docker Compose**:
   ```bash
   cd deploy
   docker compose up -d --build
   ```
   *(O serviço `llama-cpp-model` baixará automaticamente o `nomic-embed-text-v1.5.Q4_K_M.gguf` para embeddings e o `qwen2.5-0.5b-instruct-q4_k_m.gguf` para o chat RAG, iniciando o `llama-cpp` e o `llama-cpp-chat`).*

2. **Testar via Swagger UI**:
   - Acesse `http://localhost:8000/api/docs/`.
   - Clique em **Authorize** e insira o token Bearer do Keycloak.
   - Execute o endpoint **`POST /api/chat`** enviando o campo `context`.

---

## 4. Variáveis de Ambiente (Configuração do Chat RAG no `llama.cpp`)

| Variável | Valor Padrão | Descrição |
|---|---|---|
| `LLAMA_CPP_CHAT_HOST` | `http://llama-cpp-chat:8080` | Host do container `llama.cpp` responsável pelo chat RAG. |
| `LLAMA_CPP_CHAT_MODEL_FILE` | `qwen2.5-0.5b-instruct-q4_k_m.gguf` | Arquivo `.gguf` leve baixado pelo `llama-cpp-model` e carregado no `llama-cpp-chat`. |
| `LLAMA_CPP_CHAT_MODEL_URL` | `https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf` | URL de download automático do modelo `.gguf` leve. |
| `LLAMA_CPP_CHAT_TIMEOUT` | `None` (sem timeout) | Tempo limite em segundos (`None` desativa o timeout para evitar quedas em gerações longas). |
