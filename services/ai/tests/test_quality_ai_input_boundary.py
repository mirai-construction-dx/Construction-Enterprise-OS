"""AI 入力境界・機密保護の品質テスト（Lead 所有 / 読み取り専用検証）。

根拠となる仕様:
- docs/みらい建設土木DX・AI統合基盤 全体構成 V3.5.html
  「極秘：モデルに送信しない」「Masking: 個人情報の検出とマスキング。社外秘はここを通してから送信」
- CLAUDE.md: AI は候補提示・説明まで。人の確認を通らない確定処理を合格にしない。

このファイルは「あるべき仕様」を assert する。
- SSTI テストは修正前 RED（＝テンプレートがコードとして評価される）→ 修正後 GREEN。
- マスキングテストは未実装のため RED。
- 組織スコープの回帰テストは現状 PASS（＝既存の正しい挙動の固定）。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from src.main import create_app
from src.models.base import get_db

ORG = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
USER = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
TEMPLATE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000c1")


class _Template:
    """PromptTemplate の代役（synthetic）。"""

    def __init__(self, user_prompt_template: str, system_prompt: str = "system"):
        self.id = TEMPLATE_ID
        self.organization_id = ORG
        self.user_prompt_template = user_prompt_template
        self.system_prompt = system_prompt
        self.model = "mock-model"
        self.temperature = 0.7
        self.max_tokens = 100


class _Result:
    rowcount = 0

    def __init__(self, value=None):
        self._value = value
        self.rowcount = 0

    def scalar_one_or_none(self):
        return self._value

    def scalar(self):
        return self._value if self._value is not None else 0

    def scalars(self):
        return self

    def all(self):
        return self._value if isinstance(self._value, list) else []


def _client_with(template: _Template | None, captured: dict | None = None):
    app = create_app()
    db = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()

    async def mock_execute(stmt, *args, **kwargs):
        if captured is not None:
            captured.setdefault("statements", []).append(stmt)
        return _Result(template)

    db.execute = mock_execute

    async def mock_get_db():
        yield db

    app.dependency_overrides[get_db] = mock_get_db
    return TestClient(app)


def _headers() -> dict[str, str]:
    import jwt

    from src.config import get_settings

    settings = get_settings()
    token = jwt.encode(
        {"sub": str(USER), "type": "user", "org": str(ORG), "roles": ["admin"]},
        settings.jwt_public_key,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# Critical: プロンプトテンプレートの SSTI（コードとして評価される）
# ============================================================
class TestPromptTemplateSSTI:
    def test_user_template_cannot_reach_python_objects(self, monkeypatch):
        """利用者が保存したテンプレートから Python のオブジェクト階層へ到達できないこと。

        `__class__.__mro__[...].__subclasses__()` は非サンドボックス Jinja2 で
        任意コード実行（RCE）に至る代表的な経路。サンドボックス化により 4xx で拒否される。
        """
        from src.services import llm_service

        sent: dict = {}

        async def fake_complete(self, messages, **kwargs):
            sent["messages"] = messages
            return "ok"

        monkeypatch.setattr(llm_service.MockLLMProvider, "complete", fake_complete)
        monkeypatch.setattr(llm_service.OpenAICompatibleProvider, "complete", fake_complete)

        client = _client_with(
            _Template("{{ ''.__class__.__mro__[1].__subclasses__() }}")
        )
        r = client.post(
            "/api/v1/ai/complete",
            json={"prompt_template_id": str(TEMPLATE_ID), "variables": {}},
            headers=_headers(),
        )
        assert r.status_code == 400, (
            f"危険なテンプレート式が拒否されていない: {r.status_code} {r.text[:200]}"
        )
        assert "subclasses" not in r.text
        assert "<class" not in r.text
        assert "messages" not in sent, "危険なテンプレートがモデルへ送信された"

    def test_legitimate_variable_substitution_still_works(self, monkeypatch):
        """正当な変数置換は引き続き機能すること（過剰な制限の回帰）。"""
        from src.services import llm_service

        sent: dict = {}

        async def fake_complete(self, messages, **kwargs):
            sent["messages"] = messages
            return "ok"

        monkeypatch.setattr(llm_service.MockLLMProvider, "complete", fake_complete)
        monkeypatch.setattr(llm_service.OpenAICompatibleProvider, "complete", fake_complete)

        client = _client_with(_Template("現場名: {{ site_name }}"))
        r = client.post(
            "/api/v1/ai/complete",
            json={
                "prompt_template_id": str(TEMPLATE_ID),
                "variables": {"site_name": "テスト現場A"},
            },
            headers=_headers(),
        )
        assert r.status_code == 200, r.text
        assert "テスト現場A" in sent["messages"][-1]["content"]

    def test_arithmetic_expression_is_still_evaluated_residual(self):
        """既知の残存挙動（Info）: サンドボックスは四則演算等の式評価は許容する。

        オブジェクト階層へは到達できないため RCE には至らないが、計算式が展開される。
        仕様上の扱い（許可/禁止）は未確認であり、人の確認が必要。
        """
        from src.services.prompt_service import render_user_template

        assert render_user_template("{{ 7*7 }}", {}) == "49"

    def test_template_lookup_is_organization_scoped(self):
        """テンプレート取得の SQL に organization_id 条件が含まれること（回帰）。"""
        captured: dict = {}
        client = _client_with(_Template("x"), captured)
        client.post(
            "/api/v1/ai/complete",
            json={"prompt_template_id": str(TEMPLATE_ID), "variables": {}},
            headers=_headers(),
        )
        sql = _compiled(captured)
        assert "organization_id" in sql, "テンプレート取得が組織スコープされていない"


# ============================================================
# Critical: 埋め込みの越境削除
# ============================================================
class TestEmbeddingTenantScope:
    def test_delete_embeddings_is_organization_scoped(self):
        """DELETE /ai/embeddings/{type}/{id} は自組織の埋め込みだけを消すこと。"""
        import asyncio

        from src.services.embedding_service import EmbeddingService

        captured: dict = {}
        db = AsyncMock()

        async def mock_execute(stmt, *args, **kwargs):
            captured["stmt"] = stmt
            return _Result()

        db.execute = mock_execute
        service = EmbeddingService(base_url="http://127.0.0.1:1", api_key="x")
        asyncio.run(
            service.delete_embeddings(
                db,
                "document",
                uuid.UUID("00000000-0000-0000-0000-0000000000d1"),
                organization_id=ORG,
            )
        )
        sql = str(
            captured["stmt"].compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        assert "organization_id" in sql, (
            f"埋め込み削除が組織スコープされていない（越境削除）: {sql}"
        )


# ============================================================
# High: 機密マスキング（仕様: 社外秘はマスキングを通してから送信）
# ============================================================
class TestMaskingBeforeModelSend:
    def test_pii_is_masked_before_sending_to_model(self, monkeypatch):
        """個人情報を含む入力はモデルへ送る前にマスキングされること（仕様 V3.5）。"""
        from src.services import llm_service

        sent: dict = {}

        async def fake_complete(self, messages, **kwargs):
            sent["messages"] = messages
            return "ok"

        monkeypatch.setattr(llm_service.MockLLMProvider, "complete", fake_complete)
        monkeypatch.setattr(llm_service.OpenAICompatibleProvider, "complete", fake_complete)

        client = _client_with(None)
        pii = "担当者テスト太郎の連絡先は test-taro@example.invalid / 090-0000-0000 です"
        r = client.post(
            "/api/v1/ai/chat",
            json={"messages": [{"role": "user", "content": pii}]},
            headers=_headers(),
        )
        assert r.status_code == 200, r.text
        payload = str(sent["messages"])
        assert "test-taro@example.invalid" not in payload, (
            "メールアドレスがマスキングされずにモデルへ送信されている"
        )
        assert "090-0000-0000" not in payload, (
            "電話番号がマスキングされずにモデルへ送信されている"
        )


def _compiled(captured: dict) -> str:
    stmts = captured.get("statements") or []
    return " ; ".join(
        str(
            s.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        for s in stmts
    )
