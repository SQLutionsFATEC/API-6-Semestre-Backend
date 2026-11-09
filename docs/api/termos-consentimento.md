# Versionamento e manipulação de termos de consentimento (LGPD)

Este documento descreve como a aplicação armazena, versiona e manipula os **Termos de Consentimento** e suas **Cláusulas** sem nunca perder o histórico de versões anteriores, e como essa estrutura se relaciona com backups e restaurações do sistema.

---

## 1. Modelo conceitual e versionamento imutável

Chamamos de **Termo** um conjunto fechado de itens no qual o usuário pode consentir ou não em determinado momento, e de **Cláusula** cada item individual pertencente ao termo.

Para preservar o histórico completo (exigência da LGPD para auditoria e rastreabilidade de consentimento), **nenhum termo ou cláusula é editado in-place (`UPDATE`) ou excluído (`DELETE`)**:

```text
┌───────────────────┐       ┌────────────────────────┐       ┌──────────────────────┐
│       termo       │       │     clausula_termo     │       │       clausula       │
├───────────────────┤       ├────────────────────────┤       ├──────────────────────┤
│ id_termo (PK)     │◄──────┤ id_termo (FK)          │       │ id_clausula (PK)     │
│ data_criacao      │       │ id_clausula (FK)       ├──────►│ requisito            │
└───────────────────┘       └────────────────────────┘       │ desc                 │
                                                             │ data_criacao         │
                                                             │ obrigatoria          │
                                                             └──────────────────────┘
```

### Tabelas

| Tabela | Coluna | Tipo | Papel |
|---|---|---|---|
| `termo` | `id_termo` | `BIGSERIAL` (PK) | Identificador sequencial da versão do termo (o maior ID é o termo em vigor) |
| `termo` | `data_criacao` | `DATE` | Data em que a versão do termo foi gerada |
| `clausula` | `id_clausula` | `BIGSERIAL` (PK) | Identificador único da versão da cláusula |
| `clausula` | `requisito` | `TEXT` | Identificador funcional consultado pelas funcionalidades (ex.: `coleta_nome`, `coleta_uso_email`) |
| `clausula` | `desc` | `TEXT` | Texto descritivo da cláusula apresentado ao titular dos dados |
| `clausula` | `data_criacao` | `DATE` | Data de criação da cláusula |
| `clausula` | `obrigatoria` | `BOOLEAN` | Indica se o aceite da cláusula é obrigatório (`true`) ou opcional (`false`) |
| `clausula_termo` | `id_termo` | `BIGINT` (FK) | Referência para `termo.id_termo` |
| `clausula_termo` | `id_clausula` | `BIGINT` (FK) | Referência para `clausula.id_clausula` |

> **Observação:** como `Termo` possui um `ManyToManyField('Clausula', through='ClausulaTermo')`, ao associar cláusulas a um termo via ORM (`novo_termo.clausulas.set(...)` ou `.add(...)`), o Django preenche automaticamente a tabela associativa `clausula_termo`.

---

## 2. Estado preliminar (Seed inicial)

Ao aplicar as migrations na inicialização da aplicação (`0008_termo_clausula_clausulatermo`), caso não exista nenhum termo cadastrado, é criado automaticamente o **Termo #1** contendo duas cláusulas iniciais:

| `requisito` | `desc` | `obrigatoria` |
|---|---|---|
| `coleta_nome` | `Coleta de nome` | `True` (obrigatória) |
| `coleta_uso_email` | `Coleta e uso do email` | `False` (opcional) |

A função `garantir_termo_inicial()` na camada de serviço também assegura de forma idempotente que esse termo preliminar exista caso o banco tenha sido recriado.

---

## 3. Regras de evolução de versão

1. **Consulta do termo em vigor:**
   O sistema seleciona sempre o registro de `Termo` com o **maior `id_termo`** e recupera as `Clausula` associadas a ele através de `ClausulaTermo`.
2. **Adição de uma ou mais cláusulas:**
   - As novas instâncias de `Clausula` são criadas;
   - **Apenas um** novo `Termo` é criado (mesmo quando múltiplas cláusulas são adicionadas simultaneamente);
   - São criados os vínculos em `ClausulaTermo` ligando o novo `Termo` a todas as cláusulas que pertenciam ao termo anterior **mais** as novas cláusulas.
3. **Remoção de uma ou mais cláusulas:**
   - As cláusulas removidas **não são apagadas** da tabela `clausula`;
   - **Apenas um** novo `Termo` é criado;
   - São criados os vínculos em `ClausulaTermo` ligando o novo `Termo` somente às cláusulas remanescentes.
4. **Atualização de uma cláusula:**
   - Uma **nova** linha é inserida em `clausula` com os atributos atualizados (preservando a linha antiga inalterada para manter íntegros os termos passados);
   - Um **novo** `Termo` é criado;
   - São criados os vínculos em `ClausulaTermo` substituindo a cláusula antiga pela nova e mantendo todas as demais cláusulas que faziam parte do termo anterior.

---

## 4. Exemplo de uso da API Interna (Camada de Serviço)

A manipulação de termos e cláusulas é realizada internamente pelo módulo [`api.services.termo_consentimento`](../../django/api/services/termo_consentimento.py) (ou pela fachada `TermoConsentimentoService`), sem exposição de rotas HTTP.

### 4.1. Obter o termo atual e suas cláusulas

```python
from api.services.termo_consentimento import (
    listar_clausulas_atuais,
    obter_termo_atual,
)

termo = obter_termo_atual()
clausulas = listar_clausulas_atuais()

for clausula in clausulas:
    print(clausula.id_clausula, clausula.requisito, clausula.obrigatoria)
```

### 4.2. Criar uma ou mais cláusulas

```python
from api.services.termo_consentimento import criar_clausula, criar_clausulas

# Criando uma única cláusula (gera 1 nova versão de Termo)
novo_termo = criar_clausula(
    requisito='compartilhamento_parceiros',
    desc='Compartilhamento de dados com parceiros',
    obrigatoria=False,
)

# Criando múltiplas cláusulas em lote (gera apenas 1 nova versão de Termo)
novo_termo = criar_clausulas([
    {
        'requisito': 'notificacoes_sms',
        'desc': 'Envio de notificações via SMS',
        'obrigatoria': False,
    },
    {
        'requisito': 'auditoria_seguranca',
        'desc': 'Registro de logs para auditoria de segurança',
        'obrigatoria': True,
    },
])
```

### 4.3. Remover uma ou mais cláusulas do termo atual

```python
from api.services.termo_consentimento import remover_clausula, remover_clausulas

# Removendo uma cláusula (por ID ou instância de Clausula)
novo_termo = remover_clausula(id_clausula)

# Removendo múltiplas cláusulas de uma só vez (gera apenas 1 novo Termo)
novo_termo = remover_clausulas([id_clausula_1, id_clausula_2])
```

### 4.4. Atualizar uma cláusula do termo atual

```python
from api.services.termo_consentimento import atualizar_clausula

# Cria uma nova Clausula e um novo Termo, mantendo a cláusula antiga intacta no histórico
novo_termo = atualizar_clausula(
    clausula_ou_id=id_clausula_email,
    desc='Coleta e uso do email para alertas críticos e relatórios',
    obrigatoria=True,
)
```

---

## 5. Gerenciamento via CLI (`manage.py gerenciar_termos`)

Para facilitar operações manuais, auditorias e rotinas operacionais sem precisar abrir o shell do Django, foi implementado o comando de gerenciamento:

📁 [`django/api/management/commands/gerenciar_termos.py`](../../django/api/management/commands/gerenciar_termos.py)

O comando faz o consumo direto de todas as funções da camada de serviço (`garantir_termo_inicial`, `obter_termo_atual`, `listar_clausulas_atuais`, `criar_clausula`, `criar_clausulas`, `atualizar_clausula`, `remover_clausula` e `remover_clausulas`).

> [!IMPORTANT]
> Ao executar em ambiente com Docker (padrão do projeto), **navegue até a pasta `deploy/`** antes de executar os comandos:
> ```bash
> cd deploy
> docker compose exec backend python manage.py gerenciar_termos <acao> [opcoes]
> ```
> *(Caso execute a partir da raiz do repositório, inclua a flag `-f deploy/docker-compose.yaml`).*

### 5.1. Inicializar termo preliminar (Seed manual / idempotente)

```bash
cd deploy
docker compose exec backend python manage.py gerenciar_termos inicializar
```
Garante a existência do Termo preliminar (Termo #1 com `coleta_nome` e `coleta_uso_email`) se o banco estiver vazio; caso já exista algum termo, não altera o banco e exibe o estado atual.

### 5.2. Listar o termo em vigor e suas cláusulas

```bash
cd deploy
docker compose exec backend python manage.py gerenciar_termos listar
```
Exibe o ID do termo atual, data de criação e cada cláusula ativa com seu respectivo `id_clausula`, tipo (`[OBRIGATÓRIA]` ou `[OPCIONAL]`), identificador funcional e descrição (utilizando `listar_clausulas_atuais()`).

### 5.3. Criar cláusulas

**Pela linha de comando (única cláusula via `criar_clausula`):**
```bash
cd deploy
docker compose exec backend python manage.py gerenciar_termos criar --requisito "coleta_telefone" --desc "Coleta de telefone celular para SMS"
docker compose exec backend python manage.py gerenciar_termos criar --requisito "termos_servico" --desc "Termos de Uso da Plataforma" --obrigatoria
```

**Em lote via arquivo JSON (via `criar_clausulas`):**
Você pode preparar um arquivo `.json` (ex: [`exemplos_clausulas.json`](../../django/api/management/commands/exemplos_clausulas.json)) contendo uma ou mais cláusulas:

```json
[
  {
    "requisito": "coleta_telefone",
    "desc": "Coleta de telefone celular para contato operacional e segurança",
    "obrigatoria": false
  },
  {
    "requisito": "cookies_analiticos",
    "desc": "Armazenamento de cookies para fins de métricas de navegação",
    "obrigatoria": false
  }
]
```

E executá-lo (informando o caminho dentro do container, onde o código da pasta `django/` fica mapeado em `/app`):
```bash
cd deploy
docker compose exec backend python manage.py gerenciar_termos criar --json "api/management/commands/exemplos_clausulas.json"
```

> [!WARNING]
> **Atenção aos caminhos de arquivo no Docker:**
> Como o comando executa dentro do container onde o diretório raiz da aplicação é `/app` (conteúdo de `django/`), **não utilize** caminhos do host como `../django/...`. 
> Utilize o caminho relativo interno (ex: `api/management/commands/exemplos_clausulas.json`) ou absoluto (`/app/api/management/commands/exemplos_clausulas.json`). Se o arquivo JSON estiver fora da pasta `django/`, coloque-o dentro de `django/` para que o container tenha acesso.

### 5.4. Atualizar cláusula existente (via `atualizar_clausula`)

Atualiza qualquer campo de uma cláusula vigente (gerando um novo Termo e preservando a cláusula anterior intacta no histórico):

```bash
cd deploy
# Atualizar a descrição
docker compose exec backend python manage.py gerenciar_termos atualizar 2 --desc "Coleta e uso do email para relatórios semanais"

# Alterar para obrigatória ou opcional
docker compose exec backend python manage.py gerenciar_termos atualizar 2 --obrigatoria
docker compose exec backend python manage.py gerenciar_termos atualizar 2 --opcional

# Atualizar requisito e descrição simultaneamente
docker compose exec backend python manage.py gerenciar_termos atualizar 2 --requisito "coleta_email_corporativo" --desc "Email corporativo do usuário"
```

### 5.5. Remover cláusula(s)

Remove uma cláusula (via `remover_clausula`) ou múltiplas em lote (via `remover_clausulas`):

```bash
cd deploy
# Remover uma única cláusula
docker compose exec backend python manage.py gerenciar_termos remover 2

# Remover múltiplas cláusulas em lote (gera apenas 1 novo Termo)
docker compose exec backend python manage.py gerenciar_termos remover 2 3
```

---

## 6. Backup, restauração e preservação futura do histórico de consentimento

Conforme documentado em [backup-restore.md](backup-restore.md), a restauração de um dump antigo do banco principal (`app.dump`) via `pg_restore --clean` sobrescreve o estado do banco da aplicação para o instante em que o backup foi tirado.

Para garantir que **nenhuma revogação de consentimento seja perdida em uma restauração de backup**:

1. **Imutabilidade estrutural (Append-Only):**
   Como `termo`, `clausula` e `clausula_termo` nunca sofrem `UPDATE` nem `DELETE`, qualquer versão criada apenas acrescenta novas linhas.
2. **Histórico de consentimento do usuário como log de eventos (Event Sourcing / Append-Only) ou no banco independente (`tombstones`):**
   Quando a tabela de histórico de consentimento do usuário for implementada em tarefas futuras:
   - Cada aceite ou revogação deve ser gravado como um **evento imutável** com carimbo de tempo (`timestamp`), nunca sobrescrevendo o registro anterior. O estado vigente de permissão de um usuário para um `requisito` será sempre determinado pelo evento de maior `timestamp`.
   - Para impedir que um `restore.sh` de um backup antigo apague uma revogação feita após o backup, o histórico de consentimento (junto ao catálogo de termos/cláusulas referenciados) pode seguir o mesmo padrão de **união (`INSERT ... ON CONFLICT DO NOTHING`)** utilizado pelo `tombstones.csv` em `deploy/scripts/backup.sh` e `deploy/scripts/restore.sh` (ou residir diretamente no banco independente `tombstones`). Dessa forma, mesmo que um backup anterior à revogação seja restaurado, o registro mais recente de revogação prevalece.

---

## 7. Testes automatizados

Os testes unitários que validam a camada de serviço e o comando CLI de gerenciamento estão em:

```bash
# Testes do serviço
pytest api/tests_unit/test_termo_consentimento_service.py -v

# Testes do comando manage.py gerenciar_termos
pytest api/tests_unit/test_gerenciar_termos_command.py -v
```

