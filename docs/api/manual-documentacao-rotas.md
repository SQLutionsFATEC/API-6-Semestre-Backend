# Manual de documentação das rotas da API

Este manual define como documentar novas rotas usando Django REST Framework e `drf-spectacular`.

## 1. Acessar a documentação

Com o backend em execução:

- Swagger UI: `http://localhost:8000/api/docs/`
- Schema OpenAPI: `http://localhost:8000/api/schema/`

O Swagger UI permite consultar os endpoints, visualizar parâmetros e executar requisições. O schema OpenAPI pode ser usado por ferramentas de geração de clientes e validação.

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

## 8. Deleção de usuários (LGPD)

As rotas de exclusão removem o usuário fisicamente do Keycloak e registram um
**tombstone anonimizado** (SHA-256 do id) em um banco independente. Esse
registro impede que a conta reapareça após a restauração de um backup. O fluxo
completo de backup/restauração está em
[backup-restore.md](backup-restore.md).

| Rota | Método | Quem pode | Respostas |
|---|---|---|---|
| `/api/usuarios/` | DELETE | qualquer usuário autenticado | `204`, `401`, `404`, `502` |
| `/api/usuarios/{id_usuario}/` | DELETE | realm role `operador` | `204`, `401`, `403`, `404`, `502` |

- A barra final é opcional nas duas rotas (`/api/usuarios` também funciona).
- `404` indica que o usuário não existe no Keycloak; o tombstone não é criado.
- `403` na rota por id indica que o token não possui a role `operador` (a role
  `admin` isolada não é suficiente).
- `502` indica falha de comunicação com o Keycloak. Se a falha ocorrer depois
  do tombstone, ele é preservado: o usuário não ressuscita em um restore.
- O e-mail de comprovação da exclusão é enviado ao endereço cadastrado. Em
  desenvolvimento o backend de e-mail padrão é o console; em produção
  configure `EMAIL_BACKEND`/`EMAIL_HOST` (ver `deploy/.env.example`).

Declare no Swagger os status realmente retornados:

```python
@extend_schema(
    operation_id='usuarios_delete_detail',
    summary='Deleta um usuário do Keycloak (operador)',
    description=(
        'Remove fisicamente o usuário, registra um tombstone anonimizado e '
        'envia e-mail de comprovação. Acesso restrito à role operador.'
    ),
    responses={
        204: OpenApiResponse(description='Usuário deletado com sucesso.'),
        401: OpenApiResponse(description='Usuário não autenticado.'),
        403: OpenApiResponse(description='Usuário sem a role operador.'),
        404: OpenApiResponse(description='Usuário não encontrado no Keycloak.'),
        502: OpenApiResponse(description='Falha de comunicação com o Keycloak.'),
    },
)
def delete(self, request, id_usuario):
    ...
```

> Use `operation_id` explícito nas duas rotas de deleção: sem ele, o
> `drf-spectacular` gera o mesmo id de operação para ambas e o schema emite
> aviso de colisão.

## 9. Convenções do projeto

- Mantenha as rotas sob o prefixo `/api/`.
- Use nomes em português consistentes com os recursos existentes.
- Use `id_documento` e `id_etiqueta` quando esses forem os identificadores do recurso.
- Descreva filtros, paginação, exemplos e mensagens de erro em português.
- Não remova a documentação das rotas existentes ao alterar uma view.
- Atualize o serializer quando o contrato de entrada ou saída mudar.
- Evite duplicar manualmente no schema o que já é inferido pelo serializer.
