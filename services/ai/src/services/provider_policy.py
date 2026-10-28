"""LLM Provider の経路判定（ADR-0008 是正: 本番相当の環境では直接呼び出しを無効にする）。

/chat・/rag・/embeddings の全経路が、外部 Provider を直接呼ぶかどうかをこの 1 つの関数で決める。

判定（fail closed）:

- ``LLM_API_KEY`` が空 → ``mock``（外部送信なし。従来どおり）
- キーあり・開発系の環境（``DIRECT_LLM_ALLOWED_ENVIRONMENTS``）→ ``direct``
- キーあり・それ以外の環境（production・staging・未知の値を含む）
  - ``ALLOW_DIRECT_LLM_IN_NONDEV`` が真 → ``direct``（明示した場合だけ）
  - それ以外 → 503（モックへ黙って切り替えない）

``ALLOW_DIRECT_LLM_IN_NONDEV`` は既定 False。stg・本番の定義には入れない。
"""

from __future__ import annotations

import logging
from enum import Enum

from fastapi import HTTPException, status

from ..config import Settings, get_settings

logger = logging.getLogger(__name__)

# 直接呼び出しを既定で許す環境。ここに無い値（production / staging / 綴りの違い・未知の値）は
# すべて本番相当として扱う（許可リスト方式。fail closed）。
DIRECT_LLM_ALLOWED_ENVIRONMENTS = frozenset({"development", "test", "docker"})


class LLMMode(str, Enum):
    DIRECT = "direct"
    MOCK = "mock"


def is_direct_allowed_environment(environment: str) -> bool:
    return environment.strip().lower() in DIRECT_LLM_ALLOWED_ENVIRONMENTS


def resolve_llm_mode(settings: Settings | None = None) -> LLMMode:
    """外部 Provider を直接呼ぶか、モックで応答するかを決める。

    本番相当の環境でキーが設定されている（明示フラグなし）場合は 503 を送出する。
    """
    s = settings if settings is not None else get_settings()
    if not s.LLM_API_KEY:
        return LLMMode.MOCK
    if is_direct_allowed_environment(s.ENVIRONMENT) or s.ALLOW_DIRECT_LLM_IN_NONDEV:
        return LLMMode.DIRECT
    # キーの値・送信内容は記録しない
    logger.warning(
        "LLM の直接呼び出しを拒否しました（ENVIRONMENT=%s。ADR-0008）",
        s.ENVIRONMENT,
    )
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "AI_PROVIDER_DISABLED",
            "message": "この環境では AI Provider の直接呼び出しは無効です。",
        },
    )
