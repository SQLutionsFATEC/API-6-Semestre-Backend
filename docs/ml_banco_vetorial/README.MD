# Busca Semântica e Banco Vetorial



Este diretório contém a Prova de Conceito (POC) do sistema de **Indexação Vetorial** construído para viabilizar buscas semânticas exatas dentro do acervo de manuais e normativas.



O objetivo é processar documentos técnicos, extrair seu contexto, transformá-los em representações matemáticas (vetores) e armazená-los estruturalmente em um banco de dados **PostgreSQL (pgvector)**.## Contexto da Solução



Enquanto o modelo de Machine Learning (LinearSVC) foca em "etiquetar" e organizar o documento por macrocategorias (ex: normativo, técnico), este sistema foca em **preparar o conteúdo interno do arquivo** para buscas de alta precisão.



Atualmente, lidar com PDFs técnicos complexos (como manuais da FAA ou especificações MIL-STD) gera problemas de recuperação de dados em bancos tradicionais.



Para resolver isso, utilizamos:* **pymupdf4llm:** Para extrair o texto em formato Markdown, preservando a estrutura vital de tabelas e cabeçalhos.* **Embeddings Locais:** Os textos são convertidos em matemática pelo modelo `nomic-embed-text` via **Ollama** e salvos no banco, garantindo que os dados da empresa permaneçam 100% locais e seguros.## Estrutura do Banco de Dados



Para suportar o motor de IA sem duplicar arquivos, a modelagem foi construída como uma extensão da arquitetura existente no Django.



Foi criada uma entidade `DocumentoChunk` projetada para armazenar os blocos de texto fatiados. Ela se relaciona diretamente com a entidade base do sistema:* **Relacionamento:** A tabela possui uma Chave Estrangeira que aponta para o ID da tabela de `Documento`.* **Campos Vetoriais:** O campo principal armazena o `embedding` como um vetor de 768 dimensões.* **Filtros (Pre-filtering):** A filtragem por setores será feita dinamicamente através do relacionamento já existente entre `Documento` e a tabela `EtiquetaDocumento`.



Opcionalmente, a tabela pode utilizar um índice **HNSW (Hierarchical Navigable Small World)** para permitir buscas ultrarrápidas em milhares de blocos.## Funcionamento



O fluxo principal da Indexação Semântica é:```text

Documento PDF

↓

Extração p/ Markdown (pymupdf4llm)

↓

Divisão em Chunks (LangChain)

↓

Embeddings (nomic-embed-text via Ollama)

↓

Salvo no PostgreSQL (pgvector)

Resultado esperado

Ao executar o processo de indexação, o sistema fatia o documento de forma inteligente e popula o banco de dados. O resultado pode ser validado através de scripts de auditoria, comprovando a extração estruturada e a vetorização.

Exemplo de verificação do banco:

Plaintext



📊 TOTAL DE CHUNKS NO BANCO: 142 blocos de texto.



📂 AMOSTRA DE DADOS:

------------------------------------------------------------

🆔 ID do Chunk : 1

📄 Documento : AC-20-37E.pdf (Página 12)

📝 Texto : # Capítulo 3. Requisitos de Manutenção...

🔢 Embedding : 768 dimensões matemáticas geradas [0.012, -0.231, 0.054, ...]

Com os dados estruturados dessa forma, o banco de dados fica arquiteturalmente pronto para receber integrações futuras com motores de busca híbrida ou modelos de linguagem (LLMs).



Estrutura no projeto

Os recursos de Busca Vetorial podem ser executados e auditados de forma independente. O ambiente contém:

Plaintext



vectorial-database/

├── docker-compose.yml # Orquestração do banco pgvector local

├── init.sql # Script de criação automatizada de tabelas

├── indexar.py # Script de ingestão de PDFs, chunking e vetorização

└── verificar_banco.py # Auditoria de blocos salvos e validação dos vetores no banco

Repositório Oficial do Banco Vetorial

Todo o código-fonte executável desta Prova de Conceito, contendo os scripts Python, as rotinas do Docker e os artefatos de IA, está isolado no repositório de desenvolvimento da POC.

🔗 Acessar código-fonte e instruções de execução:

Repositório: Vectorial Database - POC

Resultado esperado
Ao executar o processo de indexação, o sistema fatia o documento de forma inteligente e popula o banco de dados. O resultado pode ser validado através de scripts de auditoria, comprovando a extração estruturada e a vetorização.

Exemplo de verificação do banco:

Plaintext
📊 TOTAL DE CHUNKS NO BANCO: 142 blocos de texto.

📂 AMOSTRA DE DADOS:
------------------------------------------------------------
🆔 ID do Chunk : 1
📄 Documento   : AC-20-37E.pdf (Página 12)
📝 Texto       : # Capítulo 3. Requisitos de Manutenção...
🔢 Embedding   : 768 dimensões matemáticas geradas [0.012, -0.231, 0.054, ...]
Com os dados estruturados dessa forma, o banco de dados fica arquiteturalmente pronto para receber integrações futuras com motores de busca híbrida ou modelos de linguagem (LLMs).

Estrutura no projeto
Os recursos de Busca Vetorial podem ser executados e auditados de forma independente. O ambiente contém:

Plaintext
vectorial-database/
├── docker-compose.yml       # Orquestração do banco pgvector local
├── init.sql                 # Script de criação automatizada de tabelas
├── indexar.py               # Script de ingestão de PDFs, chunking e vetorização
└── verificar_banco.py       # Auditoria de blocos salvos e validação dos vetores no banco
Repositório Oficial do Banco Vetorial
Todo o código-fonte executável desta Prova de Conceito, contendo os scripts Python, as rotinas do Docker e os artefatos de IA, está isolado no repositório de desenvolvimento da POC.

🔗 Acessar código-fonte e instruções de execução:
Repositório: Vectorial Database - POC
"""

filename = "inteligencia_artificial_busca_semantica.md"
with open(filename, "w", encoding="utf-8") as f:
f.write(markdown_content)

print(f"Created file: {filename}")


```text?code_stdout&code_event_index=1
Created file: inteligencia_artificial_busca_semantica.md

Your Markdown file is ready:

Ícone do app MD
inteligencia_artificial_busca_semantica
 MD 
The text has been properly formatted with Markdown syntax (headers, bullet points, and code blocks) to make it highly legible and easy to render in GitHub, GitLab, Obsidian, or any Markdown viewer.




O Gemini é uma IA e pode cometer erros.

Defining the Goal
# Inteligência Artificial — Busca Semântica e Banco Vetorial

Este diretório contém a Prova de Conceito (POC) do sistema de **Indexação Vetorial** construído para viabilizar buscas semânticas exatas dentro do acervo de manuais e normativas.

O objetivo é processar documentos técnicos, extrair seu contexto, transformá-los em representações matemáticas (vetores) e armazená-los estruturalmente em um banco de dados **PostgreSQL (pgvector)**.

## Contexto da Solução

Enquanto o modelo de Machine Learning (LinearSVC) foca em "etiquetar" e organizar o documento por macrocategorias (ex: normativo, técnico), este sistema foca em **preparar o conteúdo interno do arquivo** para buscas de alta precisão.

Atualmente, lidar com PDFs técnicos complexos (como manuais da FAA ou especificações MIL-STD) gera problemas de recuperação de dados em bancos tradicionais. 

Para resolver isso, utilizamos:
* **pymupdf4llm:** Para extrair o texto em formato Markdown, preservando a estrutura vital de tabelas e cabeçalhos.
* **Embeddings Locais:** Os textos são convertidos em matemática pelo modelo `nomic-embed-text` via **Ollama** e salvos no banco, garantindo que os dados da empresa permaneçam 100% locais e seguros.

## Estrutura do Banco de Dados

Para suportar o motor de IA sem duplicar arquivos, a modelagem foi construída como uma extensão da arquitetura existente no Django.

Foi criada uma entidade `DocumentoChunk` projetada para armazenar os blocos de texto fatiados. Ela se relaciona diretamente com a entidade base do sistema:
* **Relacionamento:** A tabela possui uma Chave Estrangeira que aponta para o ID da tabela de `Documento`.
* **Campos Vetoriais:** O campo principal armazena o `embedding` como um vetor de 768 dimensões.
* **Filtros (Pre-filtering):** A filtragem por setores será feita dinamicamente através do relacionamento já existente entre `Documento` e a tabela `EtiquetaDocumento`.

Opcionalmente, a tabela pode utilizar um índice **HNSW (Hierarchical Navigable Small World)** para permitir buscas ultrarrápidas em milhares de blocos.

## Funcionamento

O fluxo principal da Indexação Semântica é:
```text
Documento PDF
      ↓
Extração p/ Markdown (pymupdf4llm)
      ↓
Divisão em Chunks (LangChain)
      ↓
Embeddings (nomic-embed-text via Ollama)
      ↓
Salvo no PostgreSQL (pgvector)
```

## Resultado esperado

Ao executar o processo de indexação, o sistema fatia o documento de forma inteligente e popula o banco de dados. O resultado pode ser validado através de scripts de auditoria, comprovando a extração estruturada e a vetorização.

Exemplo de verificação do banco:
```text
📊 TOTAL DE CHUNKS NO BANCO: 142 blocos de texto.

📂 AMOSTRA DE DADOS:
------------------------------------------------------------
🆔 ID do Chunk : 1
📄 Documento   : AC-20-37E.pdf (Página 12)
📝 Texto       : # Capítulo 3. Requisitos de Manutenção...
🔢 Embedding   : 768 dimensões matemáticas geradas [0.012, -0.231, 0.054, ...]
```

Com os dados estruturados dessa forma, o banco de dados fica arquiteturalmente pronto para receber integrações futuras com motores de busca híbrida ou modelos de linguagem (LLMs).

## Estrutura no projeto

Os recursos de Busca Vetorial podem ser executados e auditados de forma independente. O ambiente contém:
```text
vectorial-database/
├── docker-compose.yml       # Orquestração do banco pgvector local
├── init.sql                 # Script de criação automatizada de tabelas
├── indexar.py               # Script de ingestão de PDFs, chunking e vetorização
└── verificar_banco.py       # Auditoria de blocos salvos e validação dos vetores no banco
```

## Repositório Oficial do Banco Vetorial

Todo o código-fonte executável desta Prova de Conceito, contendo os scripts Python, as rotinas do Docker e os artefatos de IA, está isolado no repositório de desenvolvimento da POC.

🔗 Acessar código-fonte e instruções de execução:
Repositório: Vectorial Database - POC
inteligencia_artificial_busca_semantica.md
Exibindo inteligencia_artificial_busca_semantica.md.