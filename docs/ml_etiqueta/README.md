# Machine Learning — Categorização Automática de Documentos

Este diretório contém o treinamento de Machine Learning utilizada para classificar documentos automaticamente de acordo com uma etiqueta.

O objetivo é receber um documento PDF, extrair seu conteúdo textual, transformar esse conteúdo em dados numéricos com **TF-IDF** e utilizar um modelo **LinearSVC** para identificar a categoria mais provável.

## Notebook no Google Colab

O treinamento e os testes do modelo também podem ser visualizados e executados diretamente pelo Google Colab:

[🔗 Acessar notebook no Google Colab](https://colab.research.google.com/drive/1EoCxbNxJdR929Mhgri_bFASGlKQZe3UZ?usp=sharing)

## Contexto do Treinamento

Nesta etapa do projeto ainda não possuímos uma base real de documentos separados pelas categorias finais da aplicação.

Por isso, foram utilizados documentos de diferentes organizações como forma de **simular as categorias que serão utilizadas futuramente**.

A relação utilizada atualmente é:

```text
DOCS_API/
├── tecnico/
│   └── documentos AIAA
│
├── qualitativo/
│   └── documentos ESA
│
├── juridico/
│   └── documentos FAA
│
└── normativo/
    └── documentos NASA
```

Ou seja:

```text
AIAA → simula documentos técnicos

ESA → simula documentos qualitativos

FAA → simula documentos jurídicos

NASA → simula documentos normativos
```

Essa relação existe apenas para validar o funcionamento do Treinamento.

O modelo não entende que um documento da FAA é necessariamente jurídico ou que um documento da NASA é necessariamente normativo. Ele apenas aprende os padrões presentes nos documentos utilizados em cada pasta.

Quando a base real estiver disponível, os documentos utilizados na simulação poderão ser substituídos pelos arquivos reais de cada categoria e o modelo poderá ser treinado novamente.

## Estrutura do dataset

Os documentos devem ser organizados em pastas.

O nome da pasta representa a etiqueta que o modelo deverá aprender.

Exemplo:

```text
DOCS_API/
├── tecnico/
├── qualitativo/
├── juridico/
└── normativo/
```

Cada pasta contém os documentos utilizados como exemplos daquela categoria.

Por exemplo:

```text
DOCS_API/
│
├── tecnico/
│   ├── documento_aiaa_1.pdf
│   ├── documento_aiaa_2.pdf
│   └── ...
│
├── qualitativo/
│   ├── documento_esa_1.pdf
│   ├── documento_esa_2.pdf
│   └── ...
│
├── juridico/
│   ├── documento_faa_1.pdf
│   ├── documento_faa_2.pdf
│   └── ...
│
└── normativo/
    ├── documento_nasa_1.pdf
    ├── documento_nasa_2.pdf
    └── ...
```

Durante a montagem do dataset, o nome da pasta é utilizado automaticamente como etiqueta do documento.

Exemplo:

```text
DOCS_API/tecnico/documento_aiaa.pdf
```

é interpretado como:

```text
arquivo: documento_aiaa.pdf
etiqueta: tecnico
```

## Funcionamento

O fluxo principal do Treinamento é:

```text
Documento PDF
      ↓
Extração do texto
      ↓
PyMuPDF ou OCR
      ↓
Limpeza do texto
      ↓
TF-IDF
      ↓
LinearSVC
      ↓
Etiqueta classificada
```

A extração dos documentos funciona de forma híbrida.

Primeiro é utilizado **PyMuPDF** para tentar obter o texto diretamente do PDF.

Caso uma página seja escaneada ou possua pouco conteúdo textual extraível, é utilizado **Tesseract OCR** para recuperar o texto da imagem.

Depois da extração, o conteúdo passa por uma etapa de limpeza e é transformado em valores numéricos pelo **TF-IDF**.

Esses valores são enviados ao **LinearSVC**, responsável por classificar o documento entre as etiquetas conhecidas.

## Resultado esperado

Ao receber um novo documento, o modelo retorna a etiqueta identificada.

Exemplo:

```json
{
  "etiqueta_classificada": "tecnico"
}
```

Caso o documento não possua evidência suficiente para pertencer a uma das categorias aprendidas, o resultado pode ser:

```json
{
  "etiqueta_classificada": "NÃO CLASSIFICADO"
}
```

## Estrutura no projeto

Os recursos de Machine Learning podem ser organizados da seguinte forma:

```text
ml/
├── notebooks/
│   └── treinamento_etiquetas.ipynb
│
├── artifacts/
│   └── modelo_categorizacao_tags.joblib
│
└── README.md
```

- `notebooks/`: contém o processo de treinamento e avaliação do modelo.
- `artifacts/`: contém o modelo treinado utilizado posteriormente pelo backend.
- `README.md`: documenta o funcionamento e a estrutura do Treinamento.

O notebook é responsável pelo treinamento, enquanto o backend deverá apenas carregar o modelo já treinado e utilizá-lo para classificar novos documentos.