#!/usr/bin/env python3
"""リクエストスキーマが「実行者」を本文から受け付けていないか検査する。

なぜ必要か（#139）:
    作成者・報告者・承認者・発行者をリクエスト本文から受け取ると、呼び出し元が
    他人になりすませる。API 側でトークンの `sub` を使って上書きしていても、
    スキーマにフィールドが残っていると「本文で送れる」と誤解され、
    将来の実装でそのまま保存される回帰を招く。

検査する内容:
    `services/*/src/schemas/*.py` のリクエストモデル（名前に Create / Update /
    Request / Approve を含むクラス）が、次の actor フィールドを持たないこと。

        created_by / reported_by / performed_by / approved_by / uploaded_by /
        issued_by / requested_by / updated_by / assigned_by

    応答モデル（Response 等）は対象外（返すのは正当）。
    どうしても必要な場合は `ALLOWED` に「サービス:クラス.フィールド」と理由を書く
    （推測で許容しない。理由を実測で説明できるものだけ）。

使い方:
    python3 scripts/ci/check_identity_fields.py
    python3 scripts/ci/check_identity_fields.py --root /tmp/fixture
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ACTOR_FIELDS = frozenset(
    {
        "created_by",
        "reported_by",
        "performed_by",
        "approved_by",
        "uploaded_by",
        "issued_by",
        "requested_by",
        "updated_by",
        "assigned_by",
    }
)

REQUEST_MARKERS = ("Create", "Update", "Request", "Approve")

# 例外は「サービス:クラス.フィールド」→ 理由。空であることが望ましい。
ALLOWED: dict[str, str] = {}


def is_request_model(name: str) -> bool:
    return any(marker in name for marker in REQUEST_MARKERS)


def scan(root: Path) -> list[str]:
    violations: list[str] = []
    services = root / "services"
    if not services.is_dir():
        return [f"services ディレクトリが無い: {services}"]
    for path in sorted(services.glob("*/src/schemas/*.py")):
        service = path.parents[2].name
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            violations.append(f"{service}: スキーマを解析できない（{path.name}: {exc}）")
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or not is_request_model(node.name):
                continue
            for stmt in node.body:
                if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
                    continue
                field = stmt.target.id
                if field not in ACTOR_FIELDS:
                    continue
                key = f"{service}:{node.name}.{field}"
                if key in ALLOWED:
                    continue
                violations.append(f"{key}（リクエスト本文で実行者を指定できる）")
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="リポジトリ根（テスト用。既定はこのスクリプトの 2 つ上）",
    )
    args = parser.parse_args(argv)

    violations = scan(args.root)
    if violations:
        print("NG: リクエストスキーマが actor フィールドを受け付けている", file=sys.stderr)
        for item in violations:
            print(f"  - {item}", file=sys.stderr)
        print(
            "対処: スキーマから削除し、API でトークンの `sub` から設定する。"
            " どうしても必要なら ALLOWED に理由つきで宣言する。",
            file=sys.stderr,
        )
        return 1
    checked = len(list((args.root / "services").glob("*/src/schemas/*.py")))
    print(f"OK: {checked} スキーマファイルに actor フィールドの受け付けは無い（#139）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
