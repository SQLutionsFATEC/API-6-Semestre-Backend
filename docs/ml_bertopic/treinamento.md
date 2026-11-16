# Treinamento do modelo de categorização dos documentos EverySpec

Este diretório contém um pipeline experimental para extrair o texto de manuais
 técnicos em PDF do EverySpec, descobrir categorias automaticamente e aplicar
essas categorias aos documentos. O método utilizado é **não supervisionado**:
não existe uma coluna de categorias previamente rotulada; os tópicos são
descobertos a partir da semelhança entre os textos.

## Visão geral do fluxo

```text
PDFs
  ↓
Extração de texto + OCR
  ↓
Limpeza, lematização e seleção de substantivos
  ↓
PostgreSQL (documentos_raw)
  ↓
Treinamento BERTopic em 75% dos documentos
  ↓
Modelo de tópicos + visualizações HTML
  ↓
Nomeação dos tópicos com Gemma via llama.cpp
  ↓
Etiquetagem dos documentos e consultas
```

## 1. Dependências e infraestrutura

As dependências estão listadas em [requirements.txt](./requirements.txt). O
pipeline utiliza principalmente:

- **PyMuPDF** (`fitz`) para abrir PDFs e extrair texto;
- **Tesseract/tesserocr** para páginas escaneadas;
- **spaCy**, com o modelo `en_core_web_sm`, para lematização e identificação
  gramatical;
- **PostgreSQL**, usado como armazenamento intermediário e de resultados;
- **BERTopic**, apoiado por Sentence Transformers, UMAP e HDBSCAN;
- **PyTorch**, com suporte a GPU AMD/ROCm quando disponível;
- **joblib** para persistir os modelos treinados;
- **llama.cpp**, opcionalmente, para gerar nomes legíveis para os tópicos.

Os scripts esperam um PostgreSQL local com os parâmetros definidos em
`DB_PARAMS` nos arquivos Python. A senha atualmente está configurada
diretamente nos scripts; em uma execução de produção, ela deve ser movida para
variáveis de ambiente ou outro mecanismo seguro de configuração.

## 2. Extração e preparação dos documentos

O processo é implementado principalmente em [extract.py](./extract.py).

### Leitura dos PDFs

1. O diretório `./ArquivosEveryspec` é percorrido recursivamente em busca de
   arquivos `.pdf`.
2. Cada página é lida com `pagina.get_text("text")`. (leitura via PyMuPDF)
3. Se a página tiver pouco texto, é renderizada em escala de cinza a 95 DPI e
   processada por OCR.
4. A extração padrão usa Tesseract através da biblioteca `tesserocr`.
5. Os documentos já registrados são ignorados, usando `file_path` como chave
   única. A extração é feita em paralelo com processos e os resultados são
   gravados em lotes no banco.

O script cria duas tabelas:

- `documentos_raw`: caminho do arquivo, texto processado, status e mensagem de
  erro;
- `documento_etiqueta`: relação entre documento, tópico e nome da etiqueta.

Somente documentos com `status = 'SUCESSO'` participam do treinamento.

### Limpeza do texto

A função `limpar_texto` é usada tanto na extração quanto na classificação
individual, para manter o mesmo pré-processamento nos dois momentos. Ela:

- converte o texto para minúsculas;
- remove caracteres nulos, quebras de linha e tabulações;
- remove URLs, e-mails e marcas comuns de download;
- elimina caracteres que não sejam letras, números, espaços ou hífen;
- processa textos muito longos em blocos de até 500.000 caracteres;
- mantém apenas tokens identificados pelo spaCy como substantivos;
- exige pelo menos três caracteres e usa o lema do token;
- remove palavras consideradas ruído, como `everyspec`, `downloaded`,
  `version`, `verify`, `information` e `operations`.

Se o texto ficar vazio, ou tiver menos de 50 caracteres após a extração, o
documento é marcado como erro e não é utilizado no treino.

## 3. Treinamento dos tópicos

O treinamento está em [train.py](./train.py).

### Seleção dos dados

O script consulta os documentos bem-sucedidos e seleciona aproximadamente 75% (essa quantidade foi escolhida por limitação de RAM (16GB). reduza-a caso o treinamento consuma mais memória RAM do que o disponível para o seu sistema.)
da base:

```sql
WHERE status = 'SUCESSO'
  AND conteudo IS NOT NULL
  AND conteudo != ''
ORDER BY md5(file_path)
LIMIT (SELECT GREATEST(count(*) * 0.75, 10) ...)
```

O `ORDER BY md5(file_path)` fornece uma ordem estável baseada no caminho do
arquivo. O mínimo de 10 documentos evita uma amostra vazia em bases pequenas.

### Reprodutibilidade

O valor `42` é aplicado como seed para:

- `random`;
- NumPy;
- PyTorch;
- CUDA, quando disponível;
- UMAP.

Também são ativadas as opções determinísticas do cuDNN. Isso reduz variações
entre execuções, embora diferenças de hardware, bibliotecas e versões ainda
possam produzir pequenas alterações.

### Representação dos documentos

Cada documento é convertido em embeddings pelo modelo
`all-MiniLM-L6-v2`, carregado pelo Sentence Transformers. Apesar de os nomes
das categorias serem gerados depois em inglês conforme o prompt,
o modelo de embeddings e o pipeline linguístico foram configurados para
textos em inglês, que é o idioma esperado nos manuais.

O `CountVectorizer` usa somente tokens ASCII com pelo menos três letras:

```python
token_pattern=r'(?u)\b[A-Za-z]{3,}\b'
```

### Descoberta dos tópicos com BERTopic

O BERTopic combina:

- **UMAP** para reduzir a dimensionalidade dos embeddings;
- **HDBSCAN** para agrupar documentos semanticamente próximos;
- `min_cluster_size=15`, evitando clusters muito pequenos;
- métrica euclidiana;
- método de seleção de clusters `eom`;
- `prediction_data=True`;
- `cluster_selection_epsilon=0.1`;
- `KeyBERTInspired` para produzir representações com palavras relevantes;
- probabilidades completas desativadas com
  `calculate_probabilities=False`.

O HDBSCAN também pode produzir o tópico `-1`, que representa documentos
considerados outliers. Esse tópico é ignorado ao gerar etiquetas.

## 4. Artefatos gerados pelo treinamento

Ao terminar, [train.py](./train.py) salva:

- `modelo_categorias_gpu.joblib`: modelo com o encoder ainda associado ao
  dispositivo (GPU) utilizado no treinamento;
- `modelo_categorias_cpu.joblib`: cópia preparada para uso em CPU;
- `mapa_topicos.html`: mapa interativo das distâncias entre tópicos;
- `barras_topicos.html`: palavras mais relevantes por tópico.

O modelo CPU é obtido movendo o `SentenceTransformer` para CPU antes de
salvá-lo. Isso permite executar a etapa de classificação em uma máquina sem
GPU.

## 5. Nomeação dos tópicos

O BERTopic inicialmente gera IDs e palavras representativas, mas não nomes
amigáveis. [nomear_topicos.py](./nomear_topicos.py) faz essa etapa:

1. carrega as versões GPU e CPU do modelo; (caso o seu sistema não tenha uma GPU, pode ser necessário remover o carregamento do modelo de GPU.)
2. coleta até sete palavras fortes de cada tópico válido;
3. envia os tópicos em lotes de 40 para um servidor local compatível com a API
   OpenAI, nesse caso o `llama.cpp` na porta `8080`;
4. pede ao modelo ([gemma-4-E4B-it-gguf](https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF)) nomes específicos de uma a três palavras, sem
   repetições;
5. interpreta a resposta como JSON;
6. injeta os nomes com `set_topic_labels`;
7. salva:
   - `modelo_categorias_gpu_named.joblib`;
   - `modelo_categorias_cpu_named.joblib`.

O nome `Outliers` é atribuído ao tópico `-1`. A classificação e os relatórios
preferem a coluna `CustomName`; se ela não existir, usam o nome padrão do
BERTopic.

Essa etapa depende de o servidor local do llama.cpp estar ativo e de retornar
JSON válido. Se um lote falhar, o script interrompe a nomeação para que a
resposta possa ser corrigida.

## 6. Inspeção e visualizações

[inspect_model.py](./inspect_model.py) carrega o modelo nomeado para GPU,
imprime as maiores categorias e gera:

- `relatorio_mapa.html`;
- `relatorio_barras.html`;
- `relatorio_hierarquia.html`.

[inspect_model_cpu.py](./inspect_model_cpu.py) faz a mesma inspeção forçando
os tensores para CPU, útil em uma sessão SSH ou em uma máquina sem GPU.

Os relatórios mostram quantidade de documentos por tópico, palavras
representativas, proximidade entre tópicos e uma hierarquia aproximada dos
clusters.

## 7. Aplicação das categorias

### Classificação da base inteira

[categorize.py](./categorize.py) carrega
`modelo_categorias_cpu_named.joblib` e percorre os documentos bem-sucedidos em
lotes de 1.000, usando um cursor do PostgreSQL para não carregar toda a base
na memória.

Para cada documento, `approximate_distribution` divide o texto em janelas:

- `window=50`;
- `stride=15`.

Isso é usado para evitar que documentos longos estourem o limite do modelo de
embeddings e para obter uma distribuição de tópicos baseada nas partes do
documento. Todo tópico com nota maior ou igual a `0.05` é salvo em
`documento_etiqueta`, exceto o tópico `-1`.

O script grava o ID do documento, o ID numérico do tópico e o nome oficial da
categoria. Como não há uma limpeza prévia da tabela de etiquetas nesse
script, novas execuções podem inserir relações duplicadas.

### Classificação de um único PDF

[categorize_one.py](./categorize_one.py) recebe o caminho de um PDF na linha de
comando, extrai e limpa o texto, calcula a distribuição com as mesmas janelas
`window=50` e `stride=15`, ordena os tópicos por confiança e imprime as
etiquetas com nota mínima de `0.01`.

Essa versão exibe todas as etiquetas acima do limite. A variante
[categorize_one_rapidocr.py](./categorize_one_rapidocr.py) usa RapidOCR e
limita a saída às três etiquetas mais fortes. Essa versão foi criada para servir como um comparativo para o `tesserocr`. Testes mostraram que o `tesserocr` com multithreading obteve melhor performance.

Exemplo:

```bash
python categorize_one.py /caminho/para/documento.pdf
python categorize_one_rapidocr.py /caminho/para/documento.pdf
```

## 8. Busca e exportação

[busca.py](./busca.py) fornece uma busca interativa. O termo digitado é
lematizado com spaCy e comparado com as etiquetas usando `ILIKE`. Os dez
documentos com maior quantidade de etiquetas correspondentes são exibidos.

[exportar_csv.py](./exportar_csv.py) agrupa as etiquetas por documento e gera
`relatorio_etiquetas_agrupado.csv`, contendo:

- nome da etiqueta;
- quantidade de PDFs associados;
- lista dos caminhos dos PDFs.

[assuntos.py](./assuntos.py) é um leitor simples desse CSV para imprimir a
etiqueta e sua quantidade de documentos.

## 9. Ordem recomendada de execução

Considerando uma base nova, a sequência esperada é:

```bash
# 1. Extrair e preparar os PDFs
python extract.py

# 2. Treinar e salvar os tópicos
python train.py

# 3. Nomear os tópicos com a LLM local
python nomear_topicos.py

# 4. Inspecionar o modelo e gerar relatórios
python inspect_model.py
# ou, sem GPU:
python inspect_model_cpu.py

# 5. Aplicar etiquetas à base completa
python categorize.py

# 6. Opcional: exportar e consultar resultados
python exportar_csv.py
python busca.py
```

O passo de nomeação requer o servidor `llama.cpp` configurado em
`http://127.0.0.1:8080/v1/chat/completions`. Se ele não for utilizado, ainda
é possível trabalhar com os nomes padrão gerados pelo BERTopic, ajustando o
nome do arquivo carregado pelos scripts de classificação e inspeção.

## 10. Limitações e cuidados

- O método descobre grupos por similaridade; ele não mede acurácia contra
  categorias humanas.
- A filtragem para substantivos pode remover termos técnicos que o spaCy
  classifique como outra classe gramatical.
- Os limiares de `0.01` e `0.05` têm objetivos diferentes: o primeiro é
  permissivo para inspeção individual; o segundo é usado para persistir
  etiquetas na base. Na aplicação em Django, utilizamos `0.01`.
- Alterar o modelo de embeddings, o pré-processamento, a amostra ou os
  parâmetros do UMAP/HDBSCAN muda os tópicos e exige um novo ciclo de
  nomeação.

## 11. Utilização.
- O modelo treinado `modelo_categorias_cpu_named` já está presente no repositório pelo Git LFS.

O Git LFS (Large File Storage) mantém arquivos grandes, como modelos
`.joblib`, fora do armazenamento normal do Git. O repositório continua
guardando uma referência para o arquivo, enquanto o conteúdo é baixado pelo
LFS.

### Linux (Ubuntu e Linux Mint)

No Ubuntu e no Mint, instale o pacote pelo `apt`:

```bash
sudo apt update
sudo apt install git-lfs
```

Ative o suporte do LFS para o seu usuário:

```bash
git lfs install
```
Então, basta executar: 

```bash
git lfs pull
```

Para adicionar um novo tipo de arquivo grande ao LFS:

```bash
git lfs track "*.joblib"
git add .gitattributes arquivo.joblib
git commit -m "Adiciona modelo ao Git LFS"
git push
```

### Windows

O Git LFS normalmente já vem incluído no
[Git for Windows](https://git-scm.com/download/win). Depois de instalar ou
atualizar o Git, abra o **Git Bash** ou o PowerShell e execute:

```bash
git lfs install
```

Também é possível instalar o Git LFS separadamente pelo `winget`:

```powershell
winget install GitHub.GitLFS
```

Clone ou atualize o repositório normalmente:

```bash
git clone URL_DO_REPOSITORIO
cd NOME_DO_REPOSITORIO
git lfs pull
```

Para conferir se os arquivos grandes estão disponíveis localmente:

```bash
git lfs ls-files
```

Se aparecer apenas um ponteiro de texto no lugar do modelo, execute
`git lfs pull` dentro da pasta do repositório. Para publicar novos modelos,
use `git lfs track`, `git add`, `git commit` e `git push` da mesma forma que no
Linux.