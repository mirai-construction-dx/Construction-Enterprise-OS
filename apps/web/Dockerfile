FROM node:24-slim AS builder
WORKDIR /app
COPY package.json ./
RUN npm install --no-audit --no-fund
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
# 2026-10-14: `output: "standalone"` では rewrites() が**ビルド時**に評価され、
# .next/standalone に焼き込まれる。runtime の API_GATEWAY は rewrite に効かないため、
# ビルド引数で渡す（未指定だと既定の http://localhost:9000 が焼き込まれ、
# コンテナ内から gateway へ到達できず /api/* が 500 になる）。
ARG API_GATEWAY=http://gateway:9000
ENV API_GATEWAY=${API_GATEWAY}
RUN npm run build

FROM node:24-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs --ingroup nodejs --no-create-home

COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3100
ENV PORT=3100
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
