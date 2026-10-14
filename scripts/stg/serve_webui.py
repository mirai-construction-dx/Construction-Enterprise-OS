#!/usr/bin/env python3
"""WebUI 成果物を Cloudflare Pages と同じ挙動でローカル配信する。

`python3 -m http.server` は未知のパスに 404 を返すため、
「SPA フォールバックで直接 URL でも起動する」という Pages の挙動を再現できず、
`e2e/mvp.spec.ts` の該当テストが**成果物の欠陥ではない理由で失敗する**（2026-10-14 実測）。

このサーバーは次を再現する。
  - 実在するファイルはそのまま返す
  - 未知のパス（拡張子なし / .html 以外）は `index.html` を 200 で返す（SPA フォールバック）
  - `/api/*` は 501 を返す（Pages Functions は wrangler の Workers ランタイムが担うため
    ローカルでは再現しない。**再現したふりをしない**）

使い方:
    python3 scripts/stg/serve_webui.py <dir> <port>
"""

from __future__ import annotations

import functools
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class PagesLikeHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str, **kwargs) -> None:
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/"):
            # Pages Functions のプロキシは Workers ランタイムで動く。ここでは再現しない。
            self.send_error(501, "API proxy (Pages Functions) is not available in the local harness")
            return
        target = Path(self.directory) / path.lstrip("/")
        if path == "/" or target.is_dir() or target.exists():
            super().do_GET()
            return
        # SPA フォールバック: 未知のパスは index.html を 200 で返す（Pages と同じ）。
        self.path = "/index.html"
        super().do_GET()

    def log_message(self, fmt: str, *args) -> None:  # 出力を静かにする
        return


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    directory, port = sys.argv[1], int(sys.argv[2])
    handler = functools.partial(PagesLikeHandler, directory=directory)
    with ThreadingHTTPServer(("127.0.0.1", port), handler) as httpd:
        httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
