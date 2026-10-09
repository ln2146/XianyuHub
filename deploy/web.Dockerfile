# 前端构建 + Caddy 网关（静态资源、反向代理 /api、WebSocket）
FROM node:22-alpine AS build
WORKDIR /src
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM caddy:2-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/dist /srv
