"""上流呼び出し用のトークン交換クライアント（ADR-0003）

aud=MCP_AUDIENCE のトークンは上流（construction / erp）で無効なため、auth の
トークン交換（RFC 8693）でクライアント認証のうえ上流用トークンへ交換する。
aud を持たない従来トークンはそのまま転送する（Phase 0/1 の互換）。

交換に失敗した場合・資格情報が未設定の場合は上流を呼ばない（fail-closed）。
トークン・クライアント秘密はログに出さない。
"""

import logging

import httpx

from ..config import Settings, get_settings
from ..middleware.auth import authenticate_bearer

logger = logging.getLogger(__name__)

GRANT_TYPE_TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
TOKEN_TYPE_ACCESS_TOKEN = "urn:ietf:params:oauth:token-type:access_token"


class UpstreamAuthError(RuntimeError):
    """上流用の資格情報を用意できない（交換失敗・未設定）。"""


class TokenExchanger:
    """呼び出し元トークンから上流用 Authorization ヘッダーを解決する。"""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport  # テスト用（None なら実ネットワーク）

    @property
    def settings(self) -> Settings:
        return self._settings or get_settings()

    async def upstream_authorization(self, authorization: str | None) -> str | None:
        token_data = authenticate_bearer(authorization)
        if token_data is None:
            raise UpstreamAuthError("呼び出し元トークンが無効です。")
        if not token_data.audience_bound:
            return authorization

        settings = self.settings
        if not settings.token_exchange_configured:
            raise UpstreamAuthError("上流用トークン交換が設定されていません。")

        subject_token = (authorization or "").partition(" ")[2].strip()
        try:
            async with httpx.AsyncClient(
                timeout=settings.TOKEN_EXCHANGE_TIMEOUT_SECONDS,
                transport=self._transport,
            ) as client:
                response = await client.post(
                    f"{settings.AUTH_SERVICE_URL.rstrip('/')}/api/v1/auth/token",
                    data={
                        "grant_type": GRANT_TYPE_TOKEN_EXCHANGE,
                        "subject_token": subject_token,
                        "subject_token_type": TOKEN_TYPE_ACCESS_TOKEN,
                        "audience": settings.UPSTREAM_EXCHANGE_AUDIENCE,
                    },
                    auth=(
                        settings.MCP_EXCHANGE_CLIENT_ID,
                        settings.MCP_EXCHANGE_CLIENT_SECRET.get_secret_value(),
                    ),
                )
        except httpx.HTTPError as exc:
            raise UpstreamAuthError("トークン交換に到達できません。") from exc

        if response.status_code != 200:
            error = ""
            try:
                error = str(response.json().get("error", ""))
            except ValueError:
                pass
            logger.warning(
                "token exchange failed: status=%s error=%s", response.status_code, error
            )
            raise UpstreamAuthError("トークン交換に失敗しました。")

        try:
            access_token = response.json()["access_token"]
        except (ValueError, KeyError, TypeError) as exc:
            raise UpstreamAuthError("トークン交換の応答が不正です。") from exc
        if not isinstance(access_token, str) or not access_token:
            raise UpstreamAuthError("トークン交換の応答が不正です。")
        return f"Bearer {access_token}"


_exchanger: TokenExchanger | None = None


def get_token_exchanger() -> TokenExchanger:
    global _exchanger
    if _exchanger is None:
        _exchanger = TokenExchanger()
    return _exchanger


def set_token_exchanger(exchanger: TokenExchanger | None) -> None:
    """テスト用に差し替える（None で既定へ戻す）。"""
    global _exchanger
    _exchanger = exchanger
