# Ambiente de Testes de Integração | SQLutions

**Responsável:** DevOps — Testes de Integração (SCRUM-88)  
**Escopo:** Validação de integração entre API (Django) + Banco de Dados (MySQL)  
**Última atualização:** 2026-06-22  

---

## 1. Objetivo

Este documento define o **ambiente oficial de testes de integração** do projeto SQLutions.

O objetivo é validar, de forma automatizada e reproduzível:

- Comunicação entre API Django e MySQL
- Execução correta de migrations
- Integridade das queries e serializers
- Fluxo completo de dados entre camadas (API → Banco → Resposta HTTP)
- Execução de testes críticos de ETL integrados ao banco

Este ambiente NÃO testa lógica isolada (unit tests) nem infraestrutura de observabilidade.

---

## 2. Conceito de Teste de Integração neste projeto

Os testes de integração validam o sistema funcionando como um todo, incluindo:

- Requisições HTTP reais via Django Test Client
- Persistência e leitura de dados no MySQL
- Execução de migrations antes dos testes
- Regras de negócio aplicadas na camada de API
- Fluxo parcial de ETL conectado ao banco

### O que NÃO é considerado integração aqui:

- Funções isoladas sem banco de dados (unitários)
- Testes de UI/frontend
- Monitoramento (Prometheus / Grafana)
- Testes de infraestrutura

---

## 3. Arquitetura do ambiente

O ambiente de testes é isolado e descartável, garantindo reprodutibilidade.

### Serviços utilizados:

| Serviço        | Função |
|----------------|--------|
| mysql-test     | Banco de dados MySQL isolado |
| backend-test   | API Django executando migrations + testes |

---

## 4. Estrutura de execução

O ambiente segue a sequência automatizada:

1. Build das imagens Docker
2. Subida do MySQL isolado
3. Healthcheck do banco (aguarda readiness)
4. Execução das migrations Django
5. Execução dos testes de integração
6. Geração de relatório de cobertura
7. Encerramento automático do ambiente

---

## 5. Como executar o ambiente

Na raiz do backend:

```bash
cd deploy

docker compose -f docker-compose.test.yml --env-file .env up --build --abort-on-container-exit

docker compose -f docker-compose.test.yml down -v
```
## 6. O que é validado nos testes de integração
### API + Banco de Dados
- Criação e leitura de registros reais no MySQL
- Validação de filtros e queries ORM
- Serialização de respostas HTTP
- Status codes corretos (200, 404, 405)

### Regras de negócio

- Cálculos aplicados corretamente nas views
- Agregações e filtros por projeto/programa
- Validação de estados e condições de dados

### ETL (integração parcial)
- Execução de pipeline de carga
- Validação de dados carregados no banco
- Integridade básica entre extração e persistência


## 7. Cobertura de código

A cobertura é gerada automaticamente via pytest-cov:

```js
pytest api/tests/ etl/tests/test_extraction.py \
  --cov=api --cov=etl \
  --cov-report=term-missing \
  --cov-report=xml
```


| Campo   | Significado             |
| ------- | ----------------------- |
| Stmts   | Linhas executáveis      |
| Miss    | Linhas não executadas   |
| Cover   | Percentual de cobertura |
| Missing | Linhas sem execução     |

### Importante

A cobertura mede apenas código de produção (api e etl), não arquivos de teste.

---
## 8. Garantias do ambiente

Este ambiente garante:

- Reprodutibilidade total (mesmo resultado em qualquer máquina)
- Isolamento completo do banco de dados
- Execução determinística dos testes
- Independência de frontend e monitoramento
- Limpeza automática após execução

---

## 9. Relação com outros ambientes
| Ambiente                 | Finalidade                            |
| ------------------------ | ------------------------------------- |
| docker-compose.test.yml  | Testes de integração (este documento) |
| docker-compose.yaml      | Desenvolvimento completo              |
| docker-compose.prod.yaml | Ambiente de produção                  |

---

## 10. Estrutura de diretórios

```js
backend/
└── deploy/
    ├── docker-compose.yaml
    ├── docker-compose.prod.yaml
    ├── docker-compose.test.yml   ← ambiente de integração
    ├── integration-testing-environment.md ← Documentação
    ├── backend/
    ├── frontend/
    ├── monitoring/
    └── mysql/
```

---
## 11. Papel no ciclo DevOps

O ambiente de integração representa a etapa central do ciclo de qualidade, onde o desenvolvedor implementa e mantém o código com testes automatizados, enquanto o tester valida a qualidade funcional por meio dos cenários de teste e dos resultados executados no ambiente de integração automatizado.

Este ambiente valida o comportamento real da aplicação com banco de dados, garante que alterações não quebrem fluxos críticos e serve como base confiável para validação antes da produção.

---
## 12. Resultado esperado

Ao final da execução:

- Todos os testes de integração devem passar
- Banco deve ser inicializado e destruído corretamente
- Cobertura deve ser gerada automaticamente
- Nenhum serviço externo é necessário além de Docker

---
## 13. Responsabilidade

Este ambiente é mantido pela pelo DevOps (SCRUM-88) e deve ser:

- Reproduzível por qualquer desenvolvedor
- Independente de IDE ou sistema operacional
- Baseado exclusivamente em Docker

---
## 14. Conclusão

Este ambiente garante a validação contínua da integração entre API e banco de dados,
assegurando estabilidade funcional do sistema e previsibilidade do comportamento em diferentes ambientes.

Ele representa o ponto central de confiança entre desenvolvimento e validação do sistema.
