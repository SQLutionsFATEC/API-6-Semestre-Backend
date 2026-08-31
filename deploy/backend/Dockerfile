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
RUN apt-get update && apt-get install -y pkg-config default-libmysqlclient-dev build-essential \
    && pip install --upgrade pip && pip install -r requirements.txt

# ==========================================
# EXECUÇÃO
# ==========================================
FROM python:3.12-slim

WORKDIR /app

# Copia a pasta do ambiente virtual do passo anterior
COPY --from=builder /opt/venv /opt/venv

# Ativa o venv na imagem final
ENV PATH="/opt/venv/bin:$PATH"

# Instala a biblioteca de runtime do MySQL
RUN apt-get update && apt-get install -y default-libmysqlclient-dev && rm -rf /var/lib/apt/lists/*

# Copia o código da sua aplicação
COPY . .

# ---> ADICIONE ESTA LINHA <---
# Garante que as pastas existam antes do Nginx tentar acessá-las
RUN mkdir -p /app/staticfiles /app/media

# Dá permissão de execução ao entrypoint
RUN chmod +x entrypoint.sh

EXPOSE 8000

# Script de inicialização
ENTRYPOINT ["/app/entrypoint.sh"]

# Executa o projeto 
CMD ["gunicorn", "api.wsgi:application", "--bind", "0.0.0.0:8000"]