# ==========================================
# BUILD
# ==========================================
FROM python:3.12-slim AS builder

WORKDIR /app

# Cria o ambiente virtual na pasta /opt/venv
RUN python -m venv /opt/venv

# Ativa o venv (garante que os próximos comandos pip usem ele)
ENV PATH="/opt/venv/bin:$PATH"

# Copia e instala as dependências puramente no venv
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ==========================================
# EXECUÇÃO
# ==========================================
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-por \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia a pasta do ambiente virtual do passo anterior
COPY --from=builder /opt/venv /opt/venv

# Ativa o venv na imagem final
ENV PATH="/opt/venv/bin:$PATH"

# Copia o código da sua aplicação
COPY . .

# ---> ADICIONE ESTA LINHA <---
# Garante que as pastas existam antes do Nginx tentar acessá-las
RUN mkdir -p /app/staticfiles /app/media

# Copia o entrypoint para fora de /app e ajusta CRLF/permissões
# (evita que o volume montado - ../django:/app sobrescreva com quebras de linha do Windows)
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8000

# Script de inicialização
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Executa o projeto 
CMD ["gunicorn", "api.wsgi:application", "--bind", "0.0.0.0:8000"]