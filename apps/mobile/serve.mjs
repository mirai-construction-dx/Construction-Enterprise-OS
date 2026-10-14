/**
 * `next build`（`output: 'export'`）が生成した `out/` を配信する最小の静的サーバ。
 *
 * なぜ必要か:
 *   `apps/mobile/Dockerfile` は「Static export mode」と書きながら `next dev` で配信していた
 *   （2026-10-14 実測）。開発サーバは本番ビルドと挙動・性能が異なるため、
 *   **staging が本番の実行形態を練習していない**ことになる（docs/operations/staging.md §9 D-1）。
 *
 * 依存を増やさないため、Node 標準モジュールだけで書く。
 * `serve` 等の追加パッケージはビルド時にネットワークを要し、
 * MCDX-ADR-0002（イメージを digest で固定する）とも相性が悪い。
 *
 * 挙動:
 *   - 実在するファイルはそのまま返す（拡張子から Content-Type を決める）
 *   - 拡張子のないパスは `index.html` を返す（クライアントルーティング用のフォールバック）
 *   - 拡張子つきで見つからないものは 404（存在しないアセットを index.html で隠さない）
 *
 * 使い方:
 *   node serve.mjs [dir] [port]
 */
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize, resolve, sep } from "node:path";

const ROOT = resolve(process.argv[2] ?? "out");
const PORT = Number(process.argv[3] ?? process.env.PORT ?? 3101);

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".webmanifest": "application/manifest+json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8",
};

/** パストラバーサルを防ぐ。ROOT の外を指すパスは null。 */
function safeJoin(pathname) {
  const decoded = decodeURIComponent(pathname.split("?")[0]);
  const candidate = resolve(join(ROOT, normalize(decoded)));
  if (candidate !== ROOT && !candidate.startsWith(ROOT + sep)) return null;
  return candidate;
}

async function tryFile(path) {
  try {
    const info = await stat(path);
    if (info.isFile()) return path;
    if (info.isDirectory()) {
      const index = join(path, "index.html");
      if ((await stat(index)).isFile()) return index;
    }
  } catch {
    /* 無ければ null */
  }
  return null;
}

const server = createServer(async (req, res) => {
  const url = req.url ?? "/";
  const pathname = url.split("?")[0];
  const target = safeJoin(pathname);
  if (!target) {
    res.writeHead(400).end("bad request");
    return;
  }

  let file = await tryFile(target);
  if (!file && !extname(pathname)) {
    // 拡張子なし＝クライアント側ルート。index.html へフォールバックする。
    file = await tryFile(join(ROOT, "index.html"));
  }
  if (!file) {
    res.writeHead(404, { "content-type": "text/plain; charset=utf-8" }).end("not found");
    return;
  }

  const body = await readFile(file);
  const type = TYPES[extname(file).toLowerCase()] ?? "application/octet-stream";
  const immutable = file.includes(`${sep}_next${sep}static${sep}`);
  res.writeHead(200, {
    "content-type": type,
    "content-length": body.length,
    "cache-control": immutable ? "public, max-age=31536000, immutable" : "no-cache",
    // 開発サーバではなく静的配信であることを外から判別できるようにする。
    "x-ceos-static-export": "1",
  });
  res.end(body);
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(`mobile static export serving ${ROOT} on http://0.0.0.0:${PORT}`);
});
