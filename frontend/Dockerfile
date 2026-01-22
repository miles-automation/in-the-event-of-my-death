FROM node:current-alpine AS build

WORKDIR /app

# Build-time environment variables for Vite
ARG VITE_BTCPAY_POS_URL
ARG VITE_BASE_URL=https://ieomd.com

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM caddy:2-alpine

COPY --from=build /app/dist /srv
COPY deploy/Caddyfile /etc/caddy/Caddyfile

