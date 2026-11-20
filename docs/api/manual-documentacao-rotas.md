# Manual de documentação das rotas da API

Este manual define como documentar novas rotas usando Django REST Framework e `drf-spectacular`.

## 1. Acessar a documentação

Com o backend em execução:

- Swagger UI: `http://localhost:8000/api/docs/`
- Schema OpenAPI: `http://localhost:8000/api/schema/`

O Swagger UI permite consultar os endpoints, visualizar parâmetros e executar requisições. O schema OpenAPI pode ser usado por ferramentas de geração de clientes e validação.

As rotas de documentos exigem um access token do Keycloak no cabeçalho:

```http
Authorization: Bearer <access-token>
```

Sem token, as rotas retornam `401 Unauthorized`. A listagem, os filtros, a
consulta por ID e a consulta de etiquetas exigem apenas autenticação válida.
Upload, edição, exclusão e vínculo de etiquetas exigem que o token contenha o
nível de acesso `operador`; caso contrário, a API retorna `403 Forbidden`.

Para gerar e validar o schema localmente:

```bash
cd django
python manage.py spectacular --file /tmp/openapi-schema.yml --validate
```

A dependência `drf-spectacular` e a configuração do schema já estão registradas no projeto. Não é necessário criar uma rota manual para cada método de um `ModelViewSet`: o router e os serializers fornecem grande parte da documentação automaticamente.

## 2. Onde documentar uma rota

A documentação deve ficar próxima da implementação da rota, no viewset correspondente:

- `django/api/views/documento_api.py`
- `django/api/views/etiqueta_api.py`
- `django/api/views/usuarios_api.py`
- `django/api/views/perfil_api.py`
- `django/api/views/chat_api.py`

Use `@extend_schema` quando a rota tiver parâmetros, payload, respostas ou comportamento que não possa ser inferido com segurança.

Exemplo mínimo:

```python
from drf_spectacular.utils import OpenApiResponse, extend_schema

@extend_schema(
    summary="Lista os documentos",
    description="Retorna os documentos disponíveis para consulta.",
    responses={200: DocumentoSerializer(many=True)},
)
def list(self, request, *args, **kwargs):
    ...
```

## 3. Documentar parâmetros de consulta

Declare cada parâmetro com nome, tipo, localização e obrigatoriedade. Parâmetros de consulta usam `location=OpenApiParameter.QUERY`.

```python
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema

@extend_schema(
    parameters=[
        OpenApiParameter(
            name="nome",
            type=OpenApiTypes.STR,
            location=OpenApiParameter.QUERY,
            description="Filtra pelo nome do documento.",
            required=False,
        ),
        OpenApiParameter(
            name="page",
            type=OpenApiTypes.INT,
            location=OpenApiParameter.QUERY,
            description="Número da página.",
            required=False,
            default=1,
        ),
    ],
)
```

Para parâmetros de caminho, use `location=OpenApiParameter.PATH` e documente o mesmo nome usado na URL, por exemplo `id_documento`.

## 4. Documentar payloads de requisição

Prefira um serializer para payloads reutilizados ou com validações próprias. Para payloads pequenos e exclusivos de uma rota, é possível declarar o objeto diretamente:

```python
@extend_schema(
    request={
        "application/json": {
            "type": "object",
            "required": ["id_documento", "id_etiqueta"],
            "properties": {
                "id_documento": {"type": "integer", "example": 1},
                "id_etiqueta": {"type": "integer", "example": 1},
            },
        }
    },
)
```

O exemplo deve refletir o formato realmente aceito pela view. Campos obrigatórios no schema devem ser obrigatórios também na validação da aplicação.

## 5. Documentar respostas e erros

Descreva os status HTTP relevantes e, quando possível, associe cada resposta ao serializer correspondente:

```python
@extend_schema(
    responses={
        200: EtiquetaSerializer(many=True),
        400: OpenApiResponse(description="Dados inválidos."),
        404: OpenApiResponse(description="Recurso não encontrado."),
    },
)
```

Use os códigos efetivamente retornados pela rota. Para respostas customizadas, informe a estrutura no `description` ou crie um serializer de resposta. Não documente `200` para uma operação que retorna `201`, por exemplo.

## 6. ViewSets e ações customizadas

O `DefaultRouter` gera automaticamente as operações padrão de um `ModelViewSet`:

- `GET /api/recurso/`
- `POST /api/recurso/`
- `GET /api/recurso/{id}/`
- `PUT /api/recurso/{id}/`
- `PATCH /api/recurso/{id}/`
- `DELETE /api/recurso/{id}/`

Para ações adicionais, use `@action` e documente-a com `@extend_schema`:

```python
@action(methods=["GET"], url_path="historico", detail=True)
@extend_schema(
    summary="Consulta o histórico",
    responses={200: HistoricoSerializer(many=True)},
)
def historico(self, request, id_documento=None):
    ...
```

Mantenha `@action` antes de `@extend_schema`, como nas ações existentes do projeto.

## 7. Upload de arquivos

Para uma rota que recebe arquivo, declare `multipart/form-data` e use um serializer com `FileField`:

```python
@extend_schema(
    request={"multipart/form-data": DocumentoUploadSerializer},
    responses={201: DocumentoSerializer},
)
```

O serializer deve definir o nome, o tipo e a obrigatoriedade do arquivo. A documentação não deve afirmar que o arquivo é opcional se a view rejeita requisições sem ele.

No upload de documentos, `nome` e `nivel` são obrigatórios. O arquivo (`data`) deve ser PDF ou DOCX válido; `tipo_arquivo` é inferido pela extensão, mas, se enviado, deve corresponder ao arquivo. `setor` pode ser informado pelo operador ou omitido para classificação automática. Em ambos os casos, o setor final é persistido no documento e também associado como etiqueta. O campo `etiquetas` é opcional e recebe uma lista de strings.

Exemplo de payload valido:

```json
{
  "nome": "Política de Segurança.pdf",
  "nivel": "Restrito",
  "etiquetas": ["segurança", "interno"],
  "data": "arquivo.pdf"
}
```

O registro expõe `data_criacao`, preenchida uma única vez, e `data_atualizacao`, atualizada a cada salvamento.

## 8. Anonimização de usuários (LGPD)

As rotas de exclusão anonimizam o usuário no Keycloak — substituem nome, e-mail e username por valores genéricos, desabilitam a conta e removem credenciais, roles e grupos — e registram um **tombstone anonimizado** (SHA-256 do id) em um banco independente. O registro nasce pendente e só é confirmado depois que o Keycloak conclui a anonimização; apenas confirmados impedem que os dados pessoais reapareçam após a restauração de um backup. O fluxo completo de backup/restauração está em [backup-restore.md](backup-restore.md).

| Rota | Método | Quem pode | Respostas |
|---|---|---|---|
| `/api/usuarios/` | DELETE | qualquer usuário autenticado | `204`, `401`, `404`, `502` |
| `/api/usuarios/{id_usuario}/` | DELETE | realm role `operador` ou `admin` | `204`, `401`, `403`, `404`, `502` |

- A barra final é opcional nas duas rotas (`/api/usuarios` também funciona).
- `404` indica que o usuário não existe no Keycloak; o tombstone não é criado.
- `403` na rota por id indica que o token não possui a role `operador` nem a role `admin`.
- `502` indica falha de comunicação com o Keycloak. Se a falha ocorrer depois do tombstone, ele fica **pendente** e não conta como anonimização concluída; o usuário pode tentar novamente.
- O e-mail de comprovação da exclusão é enviado ao endereço cadastrado. Em desenvolvimento o backend de e-mail padrão é o console; em produção configure `EMAIL_BACKEND`/`EMAIL_HOST` (ver `deploy/.env.example`).

Declare no Swagger os status realmente retornados:

```python
@extend_schema(
    operation_id='usuarios_delete_detail',
    summary='Anonimiza um usuário do Keycloak (admin/operador)',
    description=(
        'Anonimiza o usuário, registra um tombstone pendente, o confirma após '
        'a anonimização e envia e-mail de comprovação. '
        'Acesso restrito às roles admin ou operador.'
    ),
    responses={
        204: OpenApiResponse(description='Usuário anonimizado com sucesso.'),
        401: OpenApiResponse(description='Usuário não autenticado.'),
        403: OpenApiResponse(description='Usuário sem as roles admin e operador.'),
        404: OpenApiResponse(description='Usuário não encontrado no Keycloak.'),
        502: OpenApiResponse(description='Falha de comunicação com o Keycloak.'),
    },
)
def delete(self, request, id_usuario):
    ...
```

> Use `operation_id` explícito nas duas rotas de deleção: sem ele, o `drf-spectacular` gera o mesmo id de operação para ambas e o schema emite aviso de colisão.

## 9. Solicitações de acesso a documentos

As solicitações são persistidas na tabela `solicitacao_acesso`. O documento
possui uma chave estrangeira para `documento`; `usuario_id` é o `sub` do
usuário no Keycloak, pois os usuários não são armazenados em uma tabela local.
A combinação de documento e usuário é única, portanto uma segunda solicitação
não cria outro registro.

| Rota | Método | Quem pode | Respostas |
|---|---|---|---|
| `/api/solicitacoes-acesso/` | POST | usuário autenticado não operador | `201` nova solicitação, `200` já existente, `400`, `401`, `403` |
| `/api/solicitacoes-acesso/` | GET | operador | lista paginada, `401`, `403` |
| `/api/solicitacoes-acesso/{id}/` | PATCH | operador | altera `approved`, `200`, `400`, `401`, `403`, `404` |

Exemplos de payload:

```json
// POST
{"documento_id": 42}

// PATCH
{"approved": true}
```

O GET usa paginação por `page` e retorna `count`, `next`, `previous` e
`results`:

```text
GET /api/solicitacoes-acesso/?page=2
```

Para verificar se um usuário possui acesso especial a um documento, consulte
uma solicitação aprovada para os dois identificadores:

```sql
SELECT 1
FROM solicitacao_acesso
WHERE documento_id = 42
  AND usuario_id = 'sub-do-usuario-no-keycloak'
  AND approved = TRUE;
```

Se a consulta retornar uma linha, a solicitação foi aprovada. No Django, a
mesma verificação pode ser feita com:

```python
SolicitacaoAcesso.objects.filter(
    documento_id=id_documento,
    usuario_id=request.user.id,
    approved=True,
).exists()
```

## 10. Conversa com o Chat (RAG)

A rota `/api/chat` (`POST`) realiza busca semântica contextualizada e geração de respostas em linguagem natural com o método RAG (Retrieval-Augmented Generation).

| Rota | Método | Quem pode | Respostas |
|---|---|---|---|
| `/api/chat` | POST | qualquer usuário autenticado | `200`, `400`, `401` |

- Aceita apenas o método `POST` (com ou sem barra final: `/api/chat` ou `/api/chat/`).
- Exige autenticação Bearer do Keycloak (`401 Unauthorized` caso não autenticado).
- Extrai os substantivos da última mensagem de `context` utilizando NLP com `spaCy` (`TaggingService.nlp_texto`) para buscar os trechos de documentos mais relevantes à mensagem atual.
- Filtra estritamente pelos documentos aos quais o usuário possui acesso (`verificar_acesso` por setor/nível ou Operador, além de solicitações aprovadas em `SolicitacaoAcesso`).
- Utiliza os **três documentos mais relevantes** no método RAG para gerar a resposta em linguagem natural, sem timeout restritivo na requisição.

Exemplo de payload:

```json
{
  "context": [
    "mensagem 1",
    "resposta do sistema",
    "resposta do usuario"
  ]
}
```

Exemplo de resposta (`200 OK`):

```json
{
  "response": "Resposta gerada em linguagem natural com base nos documentos acessíveis...",
  "documents": [
    {
      "id_documento": 1,
      "nome": "Manual Técnico.pdf",
      "setor": "Tecnico",
      "nivel": "Basico",
      "pagina": 1,
      "conteudo": "Trecho relevante do documento..."
    }
  ]
}
```

## 11. Convenções do projeto

- Mantenha as rotas sob o prefixo `/api/`.
- Use nomes em português consistentes com os recursos existentes.
- Use `id_documento` e `id_etiqueta` quando esses forem os identificadores do recurso.
- Descreva filtros, paginação, exemplos e mensagens de erro em português.
- Não remova a documentação das rotas existentes ao alterar uma view.
- Atualize o serializer quando o contrato de entrada ou saída mudar.
- Evite duplicar manualmente no schema o que já é inferido pelo serializer.
