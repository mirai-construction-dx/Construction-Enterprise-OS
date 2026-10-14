"""AI 入力の機密マスキング（仕様 V3.5: 社外秘はマスキングを通してから送信）。

個人情報（メールアドレス・電話番号など）を、モデルへ送信する前にプレースホルダへ置換する。
これは「検出して隠す」防御であり、完全な匿名化ではない。検出パターンは拡張可能。
"""

from __future__ import annotations

import re

# メールアドレス（標準的な local@domain.tld）
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# 電話番号（ハイフン区切りの国内固定/携帯、および国番号付き）
_PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[ -]?)?\d{1,4}-\d{1,4}-\d{1,4}\b")

_EMAIL_PLACEHOLDER = "<EMAIL>"
_PHONE_PLACEHOLDER = "<PHONE>"


def mask_pii(text: str) -> str:
    """個人情報を含むテキストをマスキングして返す（非破壊）。"""
    if not text:
        return text
    masked = _EMAIL_RE.sub(_EMAIL_PLACEHOLDER, text)
    masked = _PHONE_RE.sub(_PHONE_PLACEHOLDER, masked)
    return masked


def mask_messages(messages: list[dict]) -> list[dict]:
    """メッセージ列の content をマスキングした新しいリストを返す。"""
    return [
        {"role": m.get("role"), "content": mask_pii(m.get("content") or "")}
        for m in messages
    ]
