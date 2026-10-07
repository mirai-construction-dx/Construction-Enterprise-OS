"""Q1(権限境界) / Q2(データ分離) 協力会社サービスのテナント分離テスト。

対象仮説:
  ① org 欠落トークン時のフォールバック先が ADMIN_ORG_ID
     (00000000-0000-0000-0000-000000000001 = 本社組織) になっていないか
  ⑤ 個別取得・更新・一覧・削除が organization_id で絞られているか

方針:
  既存 tests/ と同じく create_app() + dependency_overrides + httpx ASGITransport。
  実 DB / 外部サービスへは接続しない(session は AsyncMock、service は patch)。
  synthetic fixture のみ。実在企業名・実在個人名は使わない。

注: `@pytest.mark.xfail(strict=True)` は「未修正の欠陥」の証跡であり成功ではない。
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.config import get_settings
from src.main import create_app
from src.models.base import get_db
from src.services import (
    assignment_service,
    contract_service,
    evaluation_service,
    partner_service,
)

pytestmark = pytest.mark.anyio

UTC = timezone.utc
NOW = datetime(2026, 5, 24, tzinfo=UTC)

# 本社組織(ADMIN_ORG_ID) — ここへ到達してはならない
ADMIN_ORG_ID = UUID("00000000-0000-0000-0000-000000000001")
ORG_A = UUID("22222222-2222-2222-2222-222222222222")
ORG_B = UUID("55555555-5555-5555-5555-555555555555")
USER_A = UUID("11111111-1111-1111-1111-111111111111")
PARTNER_ID = UUID("33333333-3333-3333-3333-333333333333")
PROJECT_ID = UUID("44444444-4444-4444-4444-444444444444")


def _token(
    sub: UUID | str = USER_A,
    org: UUID | str | None = ORG_A,
    roles: tuple[str, ...] = ("admin",),
    include_sub: bool = True,
) -> dict:
    """テスト用の実署名 JWT を生成する(dev 鍵。実在の資格情報は使わない)。"""
    settings = get_settings()
    payload: dict = {"type": "user", "roles": list(roles), "scopes": []}
    if include_sub:
        payload["sub"] = str(sub)
    if org is not None:
        payload["org"] = str(org)
    token = jwt.encode(payload, settings.jwt_public_key, algorithm=settings.JWT_ALGORITHM)
    return {"Authorization": f"Bearer {token}"}


def _empty_result():
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    result.scalar.return_value = None
    result.one_or_none.return_value = None
    scalars = MagicMock()
    scalars.all.return_value = []
    result.scalars.return_value = scalars
    return result


@pytest_asyncio.fixture
async def api():
    app_ = create_app()
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock(return_value=_empty_result())

    async def override_get_db():
        yield session

    app_.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app_, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield SimpleNamespace(client=ac, session=session, app=app_)
    app_.dependency_overrides.clear()


PARTNER_PAYLOAD = {
    "name": "テスト建設株式会社",
    "company_type": "subcontractor",
}
CONTRACT_PAYLOAD = {
    "partner_id": str(PARTNER_ID),
    "title": "試験契約",
    "contract_type": "subcontract",
    "amount": 1000000.0,
    "start_date": "2026-05-01",
}
EVALUATION_PAYLOAD = {"partner_id": str(PARTNER_ID), "overall_score": 4.5}
ASSIGNMENT_PAYLOAD = {
    "partner_id": str(PARTNER_ID),
    "project_id": str(PROJECT_ID),
    "role": "元請け",
}

CREATE_CASES = [
    ("/api/v1/partners", PARTNER_PAYLOAD),
    ("/api/v1/partners/contracts", CONTRACT_PAYLOAD),
    ("/api/v1/partners/evaluations", EVALUATION_PAYLOAD),
    ("/api/v1/partners/assignments", ASSIGNMENT_PAYLOAD),
]


# ——— ① org 欠落トークンのフォールバック ———


class TestOrgMissingFallback:
    @pytest.mark.parametrize("path,payload", CREATE_CASES)
    async def test_org_missing_token_is_rejected(self, api, path, payload):
        """org クレームが無いトークンは 403。本社組織へフォールバックしない。"""
        response = await api.client.post(
            path, json=payload, headers=_token(org=None)
        )
        assert response.status_code == 403, (
            f"{path}: org 欠落トークンが {response.status_code} で通った"
        )

    @pytest.mark.parametrize("path,payload", CREATE_CASES)
    async def test_org_missing_token_never_uses_admin_org(self, api, path, payload):
        """org 欠落トークンで ADMIN_ORG_ID が service へ渡らないこと。"""
        calls: list = []

        def _spy(name):
            async def _f(*args, **kwargs):
                calls.append((name, args, kwargs))
                raise AssertionError("service が呼ばれてはならない")

            return _f

        with (
            patch.object(partner_service, "create_partner", _spy("partner")),
            patch.object(contract_service, "create_contract", _spy("contract")),
            patch.object(evaluation_service, "create_evaluation", _spy("evaluation")),
            patch.object(assignment_service, "create_assignment", _spy("assignment")),
        ):
            response = await api.client.post(
                path, json=payload, headers=_token(org=None)
            )

        assert response.status_code == 403
        for name, args, kwargs in calls:
            values = list(args) + list(kwargs.values())
            assert ADMIN_ORG_ID not in values, f"{name} に ADMIN_ORG_ID が渡された"

    @pytest.mark.parametrize("path,payload", CREATE_CASES)
    async def test_malformed_org_token_is_rejected_not_500(self, api, path, payload):
        """org が UUID でないトークンは 500 ではなく 4xx で拒否する。"""
        response = await api.client.post(
            path, json=payload, headers=_token(org="not-a-uuid")
        )
        assert response.status_code in (401, 403), (
            f"{path}: 不正 org が {response.status_code} になった"
        )

    async def test_token_without_subject_is_rejected_not_500(self, api):
        """sub クレーム欠落トークンは 500 ではなく 401。"""
        response = await api.client.post(
            "/api/v1/partners/evaluations",
            json=EVALUATION_PAYLOAD,
            headers=_token(include_sub=False),
        )
        assert response.status_code == 401, (
            f"sub 欠落が {response.status_code} になった"
        )

    async def test_non_uuid_subject_is_rejected_not_500(self, api):
        """sub が UUID でないトークンは 500 ではなく 401。"""
        response = await api.client.post(
            "/api/v1/partners/evaluations",
            json=EVALUATION_PAYLOAD,
            headers=_token(sub="not-a-uuid"),
        )
        assert response.status_code == 401, (
            f"不正 sub が {response.status_code} になった"
        )

    def test_admin_org_id_is_not_a_fallback_constant_in_api_sources(self):
        """API 層に ADMIN_ORG_ID へのフォールバック定数が残っていないこと。"""
        from pathlib import Path

        src = Path(__file__).resolve().parents[1] / "src" / "api"
        offenders = []
        for path in src.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "00000000-0000-0000-0000-000000000001" in text:
                offenders.append(path.name)
        assert offenders == [], f"本社組織フォールバックが残存: {offenders}"


# ——— ⑤ 一覧・個別取得のテナント境界(service 層の SQL) ———


class TestServiceScoping:
    """service 層のクエリが organization_id で絞られているかを SQL で確認する。"""

    @staticmethod
    async def _capture(call):
        """実行された SELECT の WHERE 句のみを連結して返す。

        SELECT の列リストには organization_id が常に現れるため、
        列リストではなく WHERE 句で絞り込みの有無を判定する。
        """
        captured: list = []
        db = AsyncMock()
        db.add = MagicMock()

        async def fake_execute(stmt):
            captured.append(stmt)
            return _empty_result()

        db.execute = fake_execute
        await call(db)
        wheres = []
        for stmt in captured:
            parts = str(stmt).split("WHERE", 1)
            wheres.append(parts[1] if len(parts) > 1 else "")
        return " | ".join(wheres)

    @pytest.mark.xfail(strict=True, reason="DEFECT-P-1: 協力会社の取得が org で絞られていない")
    async def test_defect_get_partner_by_id_not_scoped(self):
        sql = await self._capture(
            lambda db: partner_service.get_partner_by_id(db, PARTNER_ID)
        )
        assert "organization_id" in sql

    @pytest.mark.xfail(strict=True, reason="DEFECT-P-1: 協力会社一覧が org で絞られていない")
    async def test_defect_list_partners_not_scoped(self):
        sql = await self._capture(lambda db: partner_service.list_partners(db))
        assert "organization_id" in sql

    @pytest.mark.xfail(strict=True, reason="DEFECT-P-1: 契約の取得が org で絞られていない")
    async def test_defect_get_contract_by_id_not_scoped(self):
        sql = await self._capture(
            lambda db: contract_service.get_contract_by_id(db, PARTNER_ID)
        )
        assert "organization_id" in sql

    @pytest.mark.xfail(strict=True, reason="DEFECT-P-1: 契約一覧が org で絞られていない")
    async def test_defect_list_contracts_not_scoped(self):
        sql = await self._capture(lambda db: contract_service.list_contracts(db))
        assert "organization_id" in sql

    @pytest.mark.xfail(strict=True, reason="DEFECT-P-1: 評価一覧が org で絞られていない")
    async def test_defect_list_evaluations_not_scoped(self):
        sql = await self._capture(lambda db: evaluation_service.list_evaluations(db))
        assert "organization_id" in sql

    @pytest.mark.xfail(strict=True, reason="DEFECT-P-1: 配置一覧が org で絞られていない")
    async def test_defect_list_assignments_not_scoped(self):
        sql = await self._capture(lambda db: assignment_service.list_assignments(db))
        assert "organization_id" in sql

    @pytest.mark.xfail(strict=True, reason="DEFECT-P-1: 評価集計が org で絞られていない")
    async def test_defect_get_partner_rating_not_scoped(self):
        sql = await self._capture(
            lambda db: evaluation_service.get_partner_rating(db, PARTNER_ID)
        )
        assert "organization_id" in sql


# ——— ⑤ API 層がトークン org を service へ渡しているか ———


class TestApiPassesTokenOrg:
    @staticmethod
    async def _assert_passed(api, path, service_name, patch_target):
        captured = {}

        async def _f(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return ([], 0)

        with patch.object(patch_target, service_name, _f):
            await api.client.get(path, headers=_token(org=ORG_A))

        values = list(captured.get("args", ())) + list(
            captured.get("kwargs", {}).values()
        )
        return values

    async def test_defect_list_partners_passes_token_org(self, api):
        values = await self._assert_passed(
            api, "/api/v1/partners", "list_partners", partner_service
        )
        assert ORG_A in values

    async def test_defect_list_contracts_passes_token_org(self, api):
        values = await self._assert_passed(
            api, "/api/v1/partners/contracts", "list_contracts", contract_service
        )
        assert ORG_A in values

    async def test_defect_list_evaluations_passes_token_org(self, api):
        values = await self._assert_passed(
            api, "/api/v1/partners/evaluations", "list_evaluations", evaluation_service
        )
        assert ORG_A in values

    async def test_defect_list_assignments_passes_token_org(self, api):
        values = await self._assert_passed(
            api, "/api/v1/partners/assignments", "list_assignments", assignment_service
        )
        assert ORG_A in values

    async def test_defect_get_partner_passes_token_org(self, api):
        captured = {}

        partner = MagicMock()
        partner.id = PARTNER_ID
        partner.contacts = []

        async def _get(db, partner_id, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return partner

        with (
            patch.object(partner_service, "get_partner_by_id", _get),
            patch.object(contract_service, "list_contracts_for_partner", AsyncMock(return_value=([], 0))),
        ):
            await api.client.get(
                f"/api/v1/partners/{PARTNER_ID}", headers=_token(org=ORG_A)
            )

        values = list(captured.get("args", ())) + list(
            captured.get("kwargs", {}).values()
        )
        assert ORG_A in values


# ——— 認証必須(回帰) ———


class TestAuthRequired:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("GET", "/api/v1/partners"),
            ("POST", "/api/v1/partners"),
            ("GET", f"/api/v1/partners/{PARTNER_ID}"),
            ("PUT", f"/api/v1/partners/{PARTNER_ID}"),
            ("GET", "/api/v1/partners/contracts"),
            ("POST", "/api/v1/partners/contracts"),
            ("GET", f"/api/v1/partners/contracts/{PARTNER_ID}"),
            ("GET", "/api/v1/partners/evaluations"),
            ("POST", "/api/v1/partners/evaluations"),
            ("GET", "/api/v1/partners/assignments"),
            ("POST", "/api/v1/partners/assignments"),
        ],
    )
    async def test_endpoints_require_auth(self, api, method, path):
        response = await api.client.request(method, path, json={})
        assert response.status_code == 401, f"{method} {path}"


# ——— 正常系の回帰(org 付きトークンでは従来どおり動く) ———


class TestRegression:
    async def test_create_partner_uses_token_org(self, api):
        created = MagicMock()
        created.id = PARTNER_ID
        created.organization_id = ORG_A
        created.name = "テスト建設株式会社"
        created.name_kana = None
        created.company_type = "subcontractor"
        created.tax_id = None
        created.address = None
        created.phone = None
        created.email = None
        created.website = None
        created.representative_name = None
        created.employee_count = None
        created.established_year = None
        created.specializations = None
        created.license_info = None
        created.insurance_info = None
        created.status = "active"
        created.rating = None
        created.registered_at = NOW
        created.updated_at = NOW

        with patch.object(
            partner_service, "create_partner", AsyncMock(return_value=created)
        ) as create:
            response = await api.client.post(
                "/api/v1/partners", json=PARTNER_PAYLOAD, headers=_token(org=ORG_A)
            )

        assert response.status_code == 201
        assert create.call_args.args[1] == ORG_A

    async def test_list_partners_returns_pagination_meta(self, api):
        with patch.object(
            partner_service, "list_partners", AsyncMock(return_value=([], 0))
        ):
            response = await api.client.get(
                "/api/v1/partners", headers=_token(org=ORG_A)
            )
        assert response.status_code == 200
        assert response.json()["meta"]["total"] == 0
        assert response.json()["meta"]["total_pages"] == 0
