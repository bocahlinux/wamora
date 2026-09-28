FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .

# Phase 14 (Production deployment) Blocker B1 — Vite bakes
# `import.meta.env.VITE_*` in at BUILD time (frontend/src/lib/config.ts is
# the only reader: VITE_BFF_BASE_URL/VITE_DJANGO_BASE_URL/VITE_WAHA_SESSION_NAME).
# `.dockerignore` deliberately excludes `.env` from this build context (it
# must never bake in secrets), so these three — none of which is a secret,
# just base URLs and a session name — must arrive as build ARGs instead.
# Passed via `infrastructure/tencent/docker-compose.yml`'s `build.args:`.
ARG VITE_BFF_BASE_URL
ARG VITE_DJANGO_BASE_URL
ARG VITE_WAHA_SESSION_NAME
ENV VITE_BFF_BASE_URL=${VITE_BFF_BASE_URL} \
    VITE_DJANGO_BASE_URL=${VITE_DJANGO_BASE_URL} \
    VITE_WAHA_SESSION_NAME=${VITE_WAHA_SESSION_NAME}

RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# Phase 14 MISSING item M5 — replaces the stock default.conf with an
# SPA-fallback-aware config (see nginx.conf's own comment for why this
# is needed: react-router-dom's BrowserRouter, direct navigation/refresh
# on a client-side route otherwise 404s).
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
