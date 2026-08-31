# Testing Guide

Guia prático para desenvolvedores que precisam rodar, entender ou escrever testes no projeto.

---

## Índice

1. [Visão geral](#1-visão-geral)
2. [Pré-requisitos](#2-pré-requisitos)
3. [Como rodar os testes](#3-como-rodar-os-testes)
4. [Interpretando os resultados](#4-interpretando-os-resultados)
5. [Cobertura de código](#5-cobertura-de-código)
6. [Escrevendo novos testes](#6-escrevendo-novos-testes)
7. [Referência rápida de ferramentas](#7-referência-rápida-de-ferramentas)

---

## 1. Visão geral

O projeto possui duas camadas de testes que se complementam:

| Camada | O que valida | Velocidade | Onde fica |
|---|---|---|---|
| **Unitário** | Lógica isolada: fórmulas, regras, algoritmos | Muito rápido (ms) | `*/tests_unit/` |
| **Integração** | Endpoints HTTP + banco de dados | Mais lento (segundos) | `*/tests/test_*.py` |

A regra de ouro: **se um teste unitário falha junto com um de integração, o problema está na lógica. Se só o de integração falha, o problema está na camada de infraestrutura** (query, serialização, rota).

```
Teste de integração falha
        │
        ├── Teste unitário também falha → problema na lógica de negócio
        │
        └── Teste unitário passa → problema na infraestrutura (ORM, view, serialização)
```

---

## 2. Pré-requisitos

Certifique-se de que o ambiente virtual está ativo e as dependências instaladas:

```bash
# Ativar ambiente virtual
source venv/bin/activate          # Linux/macOS
venv\Scripts\activate             # Windows

# Instalar dependências de teste
pip install pytest pytest-django pytest-cov
```

Verifique se o `pytest.ini` ou `setup.cfg` está configurado com o Django settings:

```ini
# pytest.ini
[pytest]
DJANGO_SETTINGS_MODULE = core.settings
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

---

## 3. Como rodar os testes

### Todos os testes

```bash
pytest
```

### Apenas testes unitários (recomendado durante desenvolvimento)

São muito mais rápidos — sem banco, sem HTTP. Use durante o ciclo de escrita de código.

```bash
pytest api/tests_unit/ etl/tests_unit/ -v
```

### Apenas testes de integração

```bash
pytest api/tests/ --ignore=api/tests/unit/ etl/tests/test_extraction.py -v
```

### Um arquivo específico

```bash
pytest api/tests_unit/test_unit_alertas.py -v
```

### Uma classe específica

```bash
pytest api/tests_unit/test_unit_alertas.py::TestAdicionaPedidoAtrasado -v
```

### Um teste específico

```bash
pytest api/tests_unit/test_unit_alertas.py::TestAdicionaPedidoAtrasado::test_dias_atraso_calculado_corretamente -v
```

### Filtrar por palavra-chave (útil para temas)

```bash
pytest -k "alertas" -v
pytest -k "empenho or compra" -v
pytest -k "not integracao" -v
```

### Parar no primeiro erro

```bash
pytest -x
```

### Ver print() e logs durante o teste

```bash
pytest -s
```

### Rodar apenas testes que falharam na última execução

```bash
pytest --lf
```

---

## 4. Interpretando os resultados

### Saída normal

```
PASSED api/tests_unit/test_unit_alertas.py::TestAdicionaPedidoAtrasado::test_pedido_aberto_atrasado_e_adicionado
PASSED api/tests_unit/test_unit_alertas.py::TestAdicionaPedidoAtrasado::test_previsao_hoje_nao_e_atraso
FAILED api/tests_unit/test_unit_alertas.py::TestAdicionaPedidoAtrasado::test_status_concluido_ignorado
```

### Lendo uma falha

```
FAILED api/tests_unit/test_unit_alertas.py::TestAdicionaPedidoAtrasado::test_status_concluido_ignorado

    def test_status_concluido_ignorado_mesmo_com_data_passada(self):
        lista = []
        compra = make_compra(status="Concluída")
>       _adiciona_pedido_atrasado(lista, compra, HOJE, ONTEM, "concluída")
        assert lista == []
E       AssertionError: assert [{'numero_pedido': 'PED01', ...}] == []
```

Como diagnosticar:

1. O nome do teste descreve a condição e o resultado esperado
2. O `>` indica a linha que causou a falha
3. O `E` mostra o valor real versus o esperado
4. **Teste unitário falha** → problema está na lógica da função
5. **Só o teste de integração falha** → problema está na query, rota ou serialização

### Símbolos do pytest

| Símbolo | Significado |
|---|---|
| `.` | Passou |
| `F` | Falhou (assertion incorreta) |
| `E` | Erro inesperado (exception não tratada) |
| `s` | Pulado (skip) |
| `x` | Falha esperada (xfail) |

---

## 5. Cobertura de código

### Gerar relatório

```bash
# Resumo no terminal com linhas não cobertas
pytest --cov=api --cov=etl --cov-report=term-missing

# Relatório HTML interativo (recomendado)
pytest --cov=api --cov=etl --cov-report=html
# Abrir: htmlcov/index.html
```

### Lendo o relatório terminal

```
Name                                      Stmts   Miss  Cover   Missing
-----------------------------------------------------------------------
api/views/alertas.py                         87     12    86%   45-47, 89
api/views/compras.py                         54      8    85%   67-71
etl/transformations/transformers.py          61      4    93%   102, 118
etl/validators/integrity.py                  10      0   100%
```

- **Stmts**: total de linhas executáveis
- **Miss**: linhas não executadas por nenhum teste
- **Cover**: percentual coberto
- **Missing**: números das linhas sem cobertura — verifique se contêm lógica de negócio

> Linhas sem cobertura que contêm lógica de negócio são um alerta real.
> Linhas de log, print de debug ou tratamento de erro genérico são aceitáveis sem cobertura.

### Metas sugeridas por camada

| Camada | Meta mínima |
|---|---|
| `etl/validators/integrity.py` | 100% |
| `etl/transformations/transformers.py` | > 90% |
| `api/views/*.py` | > 80% |
| `etl/loaders/loader.py` | > 70% |
| `api/management/commands/` | Coberto por integração |

---

## 6. Escrevendo novos testes

### Ao criar um novo endpoint, crie dois arquivos

**1. Teste de integração** em `api/tests/test_<nome>.py`:

```python
from django.test import TestCase, Client
from api.models import DimProjeto, ...

class NovoEndpointViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        # Criar apenas os dados mínimos necessários

    def test_sucesso_com_dados(self):
        response = self.client.get(f'/api/rota/{self.projeto.codigo_projeto}/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['campo'], valor_esperado)

    def test_sucesso_sem_dados(self):
        # Projeto existe mas sem dados nas tabelas Fato
        response = self.client.get(f'/api/rota/{self.projeto_vazio.codigo_projeto}/')
        self.assertEqual(response.status_code, 200)

    def test_not_found(self):
        response = self.client.get('/api/rota/CODIGO-INVALIDO/')
        self.assertEqual(response.status_code, 404)

    def test_wrong_method(self):
        response = self.client.post(f'/api/rota/{self.projeto.codigo_projeto}/')
        self.assertEqual(response.status_code, 405)
```

**2. Teste unitário** em `api/tests_unit/test_unit_<nome>.py`:

```python
# Sem banco, sem HTTP — apenas lógica pura
import pytest

def test_regra_caminho_feliz(self):
    ...

def test_caso_de_borda_valor_zero(self):
    ...

def test_fallback_para_valor_nulo(self):
    ...

def test_limite_exato_da_regra(self):
    ...
```

### Checklist antes de commitar um teste

- [ ] O nome descreve a condição E o resultado esperado (`test_<condição>_<resultado>`)
- [ ] O teste tem um assert principal claro
- [ ] Testes unitários não usam banco (`TestCase` do Django) nem `Client()`
- [ ] Casos de borda cobertos: `None`, lista vazia, zero, valor exatamente no limite
- [ ] O teste quebra se eu remover ou inverter a lógica que ele protege
- [ ] Não há lógica condicional dentro do teste (um `if` dentro de um teste é sinal de que ele deveria ser dois testes)

### Padrão de nomenclatura

```python
# Formato: test_<condição>_<resultado_esperado>

# Bons exemplos
test_pedido_atrasado_e_adicionado_a_lista
test_data_previsao_none_nao_causa_erro
test_lista_vazia_retorna_zero
test_status_concluido_ignorado_mesmo_atrasado

# Ruins
test_1
test_funciona
test_alertas
test_verifica_pedido
```

### Usando MagicMock para objetos do ORM

Quando a função recebe um objeto Django mas você não quer banco:

```python
from unittest.mock import MagicMock

def make_compra(numero="PED01", status="Aberto"):
    compra = MagicMock()
    compra.numero_pedido = numero
    compra.status = status
    compra.solicitacao.prioridade = "Alta"
    return compra
```

### Injetando datas fixas nos testes

Nunca use `date.today()` dentro de um teste — o resultado muda a cada dia. Passe a data como parâmetro:

```python
HOJE = date(2024, 6, 15)
ONTEM = HOJE - timedelta(days=1)

# Ruim
resultado = minha_funcao(entrada)  # usa date.today() internamente

# Bom
resultado = minha_funcao(entrada, hoje=HOJE)  # data injetada, resultado determinístico
```

---

## 7. Referência rápida de ferramentas

| Ferramenta | Uso | Quando usar |
|---|---|---|
| `pytest` | Runner principal | Sempre |
| `django.test.TestCase` | Testes com banco de dados | Testes de integração |
| `django.test.Client` | Simula requisições HTTP | Testes de integração |
| `unittest.mock.MagicMock` | Objetos falsos sem banco | Testes unitários com atributos ORM |
| `unittest.mock.patch` | Substituir função em tempo de teste | Mockar `date.today()`, `_dim_data_para_date` |
| `pytest.raises` | Verificar exceções esperadas | Testar `ValueError`, `404`, regras de negócio |
| `pd.DataFrame` | Dados tabulares para ETL | Testes unitários dos transformers |

---

*Última atualização: Mai/2026*