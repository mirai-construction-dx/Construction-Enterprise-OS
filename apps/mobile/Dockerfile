# ==============================================================================
# Construction-Enterprise-OS — mobile (PWA)
#
# 2026-10-14 改定:
#   旧版は「Static export mode」と書きながら `npm run dev`（Next の開発サーバ）で
#   配信していた。開発サーバは本番ビルドと挙動・性能が異なるため、staging が
#   本番の実行形態を練習していないことになる（docs/operations/staging.md §9 D-1）。
#   `output: 'export'` の生成物（out/）を静的配信する 2 ステージ構成へ変更した。
#   開発時のホットリロードは従来どおり手元の `pnpm dev` を使う。
# ==============================================================================

# --- ステージ 1: 静的エクスポートを生成する -----------------------------------
FROM node:24-alpine AS builder

WORKDIR /app

COPY package.json ./
RUN npm install --no-audit --no-fund

COPY . .

ENV NEXT_TELEMETRY_DISABLED=1
# output: 'export' のため生成物は out/ に出る（.dockerignore でホスト側の out/ は除外済み）。
RUN npm run build

# --- ステージ 2: 生成物を静的配信する（開発サーバを使わない） -------------------
FROM node:24-alpine AS runner

WORKDIR /app

RUN addgroup -S -g 1001 app && adduser -S -u 1001 -G app app

COPY --from=builder --chown=app:app /app/out ./out
COPY --chown=app:app serve.mjs ./serve.mjs

USER app

ENV PORT=3101
ENV NEXT_TELEMETRY_DISABLED=1
EXPOSE 3101

# 依存を増やさないため、静的配信は Node 標準モジュールのみの serve.mjs が担う。
CMD ["node", "serve.mjs", "out", "3101"]
