# Production web server: builds the React app and serves it with Caddy,
# which also proxies /api/* to the backend and handles HTTPS automatically.
# Build context is the repo root:  docker build -f deploy/web.Dockerfile .

FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
# "/api" = same server as the page (Caddy forwards it to the backend)
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM caddy:2-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
