# Contexto de build = raiz do repo (precisa de docs/help).
FROM node:22-alpine AS deps
WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web/ ./
RUN npm run build

FROM node:22-alpine AS run
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HELP_DIR=/app/help PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /app
RUN addgroup -S app && adduser -S -u 10001 -G app app
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY docs/help /app/help
USER 10001
EXPOSE 3000
CMD ["node", "server.js"]
