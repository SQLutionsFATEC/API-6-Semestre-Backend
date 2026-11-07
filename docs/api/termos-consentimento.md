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

## 5. Backup, restauração e preservação futura do histórico de consentimento

Conforme documentado em [backup-restore.md](backup-restore.md), a restauração de um dump antigo do banco principal (`app.dump`) via `pg_restore --clean` sobrescreve o estado do banco da aplicação para o instante em que o backup foi tirado.

Para garantir que **nenhuma revogação de consentimento seja perdida em uma restauração de backup**:

1. **Imutabilidade estrutural (Append-Only):**
   Como `termo`, `clausula` e `clausula_termo` nunca sofrem `UPDATE` nem `DELETE`, qualquer versão criada apenas acrescenta novas linhas.
2. **Histórico de consentimento do usuário como log de eventos (Event Sourcing / Append-Only) ou no banco independente (`tombstones`):**
   Quando a tabela de histórico de consentimento do usuário for implementada em tarefas futuras:
   - Cada aceite ou revogação deve ser gravado como um **evento imutável** com carimbo de tempo (`timestamp`), nunca sobrescrevendo o registro anterior. O estado vigente de permissão de um usuário para um `requisito` será sempre determinado pelo evento de maior `timestamp`.
   - Para impedir que um `restore.sh` de um backup antigo apague uma revogação feita após o backup, o histórico de consentimento (junto ao catálogo de termos/cláusulas referenciados) pode seguir o mesmo padrão de **união (`INSERT ... ON CONFLICT DO NOTHING`)** utilizado pelo `tombstones.csv` em `deploy/scripts/backup.sh` e `deploy/scripts/restore.sh` (ou residir diretamente no banco independente `tombstones`). Dessa forma, mesmo que um backup anterior à revogação seja restaurado, o registro mais recente de revogação prevalece.

---

## 6. Testes automatizados

Os testes unitários que validam o estado preliminar e todos os cenários de versionamento (criação de 1 e 2 cláusulas, remoção de 1 e 2 cláusulas e atualização de cláusula) estão em:

```bash
pytest api/tests_unit/test_termo_consentimento_service.py -v
```

