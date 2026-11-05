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

# Instala Tesseract e o cliente do Docker (para o restore.sh)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-por \
    ca-certificates \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Adiciona o repositório oficial da Docker e instala o CLI + Compose plugin
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copia a pasta do ambiente virtual do passo anterior
COPY --from=builder /opt/venv /opt/venv

# Ativa o venv na imagem final
ENV PATH="/opt/venv/bin:$PATH"

# Copia o código da sua aplicação
COPY . .

# Garante que as pastas existam
RUN mkdir -p /app/staticfiles /app/media

# Copia o entrypoint
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/entrypoint.sh && chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8000

# Script de inicialização
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Executa o projeto 
CMD ["gunicorn", "api.wsgi:application", "--bind", "0.0.0.0:8000"]