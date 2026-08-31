FROM node:20-alpine

# Instala o git para podermos clonar o repositório externo
RUN apk add --no-cache git

WORKDIR /app

# Recebe os argumentos passados pelo docker-compose
ARG REPO_URL
ARG FRONTEND_BRANCH=main

# Clona o repositório na branch especificada
RUN git clone -b ${FRONTEND_BRANCH} ${REPO_URL} .

# Instala as dependências (permissivo)
RUN npm install

EXPOSE 3000

# Executa o servidor de desenvolvimento (Vai funcionar para Next.js, Vite, Create React App, etc.)
CMD ["npm", "run", "dev"]