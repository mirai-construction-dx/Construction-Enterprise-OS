"""品質テスト: 資源原価計算（Q3）と施工計画書承認（Q6）／権限境界（Q1）。

検証仮説:
  H5: POST /methods/{id}/approve は approved_by をボディから受け取り、ロール検査もない。
  H6: `_calculate_resource_total_cost` は actual_quantity == 0 のとき planned に
      フォールバックする。また `create_resource` は total_cost を計算しない。

期待値は仕様（承認者はトークン `sub` で同定する／承認は review 状態のみ）に基づく。
未修正の欠陥は xfail(strict=True)（修正されれば XPASS→FAIL で気付ける）。
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from src.services.construction_service import _calculate_resource_total_cost
from tests.quality_helpers import (
    API,
    AUTH_HEADERS,
    ORG_A,
    ORG_B,
    USER_A,
    USER_B,
    build_client,
    client,  # noqa: F401  (pytest fixture)
    client_no_auth,  # noqa: F401  (pytest fixture)
    make_method,
    make_resource,
    make_wbs,
    mock_db,  # noqa: F401  (pytest fixture)
)

METHOD_BODY = {
    "organization_id": str(ORG_B),
    "project_id": "00000000-0000-0000-0000-0000000000dd",
    "title": "テスト施工計画書A",
    "document_type": "method_statement",
}


# ============================================
# H6: 資源原価の計算再現性
# ============================================
class TestH6ResourceCostCalculation:
    def test_total_cost_uses_actual_quantity_when_present(self):
        r = make_resource(
            planned_quantity=Decimal("30"),
            actual_quantity=Decimal("10"),
            unit_cost=Decimal("100"),
        )
        _calculate_resource_total_cost(r)
        assert r.total_cost == Decimal("1000")

    def test_total_cost_falls_back_to_planned_when_actual_is_none(self):
        """actual 未入力なら planned を使う（意図された挙動の記録）。"""
        r = make_resource(
            planned_quantity=Decimal("30"),
            actual_quantity=None,
            unit_cost=Decimal("100"),
        )
        _calculate_resource_total_cost(r)
        assert r.total_cost == Decimal("3000")

    @pytest.mark.xfail(
        strict=True,
        reason="DEF-06a: actual_quantity=0 が偽値として planned にフォールバックする",
    )
    def test_total_cost_zero_actual_is_not_replaced_by_planned(self):
        """実績数量 0（=未消化）は 0 円であるべきで、計画値で水増ししてはならない。"""
        r = make_resource(
            planned_quantity=Decimal("30"),
            actual_quantity=Decimal("0"),
            unit_cost=Decimal("100"),
        )
        _calculate_resource_total_cost(r)
        assert r.total_cost == Decimal("0"), (
            f"actual=0 で planned=30 にフォールバックした: total_cost={r.total_cost}"
        )

    def test_total_cost_zero_actual_and_no_planned_is_zero(self):
        r = make_resource(
            planned_quantity=None,
            actual_quantity=Decimal("0"),
            unit_cost=Decimal("100"),
        )
        _calculate_resource_total_cost(r)
        assert r.total_cost == Decimal("0")

    def test_total_cost_none_unit_cost_is_zero(self):
        r = make_resource(
            planned_quantity=Decimal("30"),
            actual_quantity=None,
            unit_cost=None,
        )
        _calculate_resource_total_cost(r)
        assert r.total_cost == Decimal("0")

    def test_total_cost_is_deterministic(self):
        def calc():
            r = make_resource(
                planned_quantity=Decimal("12.5"),
                actual_quantity=Decimal("7.25"),
                unit_cost=Decimal("3333.33"),
            )
            _calculate_resource_total_cost(r)
            return r.total_cost

        assert calc() == calc()

    @pytest.mark.xfail(
        strict=True,
        reason="DEF-06b: create_resource が total_cost を計算せず None のまま保存する",
    )
    def test_create_resource_computes_total_cost(self, client, mock_db):
        response = client.post(
            f"{API}/resources",
            json={
                "organization_id": str(ORG_A),
                "project_id": "00000000-0000-0000-0000-0000000000dd",
                "resource_type": "labor",
                "name": "テスト資源A",
                "unit": "人日",
                "planned_quantity": "30",
                "unit_cost": "25000",
            },
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 201
        created = mock_db.add.call_args[0][0]
        assert created.total_cost is not None, "作成時に total_cost が未計算（None）"
        assert created.total_cost == Decimal("750000")

    def test_update_resource_recomputes_total_cost(self, client, mock_db):
        """正の対照: 更新時は total_cost が再計算される（作成時との非対称）。"""
        from unittest.mock import AsyncMock

        resource = make_resource(
            planned_quantity=Decimal("30"),
            actual_quantity=None,
            unit_cost=Decimal("25000"),
        )
        mock_db.get = AsyncMock(return_value=resource)
        response = client.put(
            f"{API}/resources/{resource.id}",
            json={"planned_quantity": "40"},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200
        assert resource.total_cost == Decimal("1000000")


# ============================================
# H5: 承認者アイデンティティとロール
# ============================================
class TestH5ApprovalIdentity:
    def test_approve_uses_token_identity_not_body(self, client, mock_db):
        from unittest.mock import AsyncMock

        method = make_method(status="review", organization_id=ORG_A)
        mock_db.get = AsyncMock(return_value=method)

        response = client.post(
            f"{API}/methods/{method.id}/approve",
            json={"approved_by": str(USER_B)},  # 偽装を試みる
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 200
        assert method.status == "approved"
        assert method.approved_by == USER_A, (
            f"ボディ指定の別人 {USER_B} が承認者として記録された: {method.approved_by}"
        )
        assert method.approved_at is not None

    def test_approve_without_body_uses_token_identity(self, client, mock_db):
        from unittest.mock import AsyncMock

        method = make_method(status="review", organization_id=ORG_A)
        mock_db.get = AsyncMock(return_value=method)

        response = client.post(
            f"{API}/methods/{method.id}/approve", headers=AUTH_HEADERS
        )
        assert response.status_code == 200, (
            f"ボディなしの承認が {response.status_code} になった"
        )
        assert method.approved_by == USER_A

    @pytest.mark.xfail(
        strict=True,
        reason="DEF-05b: 承認にロール検査がない（roles 未使用。必要ロール名は仕様未定義→人の確認要）",
    )
    def test_approve_requires_explicit_role(self, mock_db):
        from unittest.mock import AsyncMock

        method = make_method(status="review", organization_id=ORG_A)
        mock_db.get = AsyncMock(return_value=method)
        _app, viewer = build_client(mock_db, org=ORG_A, sub=USER_A, roles=())

        response = viewer.post(
            f"{API}/methods/{method.id}/approve",
            json={"approved_by": str(USER_A)},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 403, (
            f"ロールを持たない利用者が承認できた: {response.status_code}"
        )

    @pytest.mark.xfail(
        strict=True,
        reason="DEF-05c: 他テナントの施工計画書を承認できてしまう（組織検査なし）",
    )
    def test_approve_other_tenant_method_rejected(self, client, mock_db):
        from unittest.mock import AsyncMock

        method = make_method(status="review", organization_id=ORG_B)
        mock_db.get = AsyncMock(return_value=method)

        response = client.post(
            f"{API}/methods/{method.id}/approve",
            json={"approved_by": str(USER_A)},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 404, (
            f"他テナント {ORG_B} の計画書を {response.status_code} で承認した"
        )
        assert method.status == "review"  # 状態が変わっていないこと

    @pytest.mark.xfail(
        strict=True,
        reason="DEF-05d: created_by がボディ由来で作成者を偽装できる（証跡の信頼性）",
    )
    def test_create_method_created_by_is_token_derived(self, client, mock_db):
        response = client.post(
            f"{API}/methods",
            json={**METHOD_BODY, "created_by": str(USER_B)},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 201
        created = mock_db.add.call_args[0][0]
        assert created.created_by == USER_A, (
            f"ボディ指定の別人 {USER_B} が作成者として記録された: {created.created_by}"
        )


# ============================================
# 承認ステートマシン（Q6/Q8・現状 PASS）
# ============================================
class TestApprovalStateMachine:
    def _review_method(self, mock_db, status):
        from unittest.mock import AsyncMock

        method = make_method(status=status, organization_id=ORG_A)
        mock_db.get = AsyncMock(return_value=method)
        return method

    def test_approve_requires_review_status(self, client, mock_db):
        method = self._review_method(mock_db, "draft")
        response = client.post(
            f"{API}/methods/{method.id}/approve",
            json={"approved_by": str(USER_A)},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 400
        assert method.status == "draft"

    def test_double_approve_is_rejected(self, client, mock_db):
        method = self._review_method(mock_db, "review")
        first = client.post(
            f"{API}/methods/{method.id}/approve",
            json={"approved_by": str(USER_A)},
            headers=AUTH_HEADERS,
        )
        assert first.status_code == 200
        second = client.post(
            f"{API}/methods/{method.id}/approve",
            json={"approved_by": str(USER_A)},
            headers=AUTH_HEADERS,
        )
        assert second.status_code == 400
        assert method.status == "approved"

    def test_reject_requires_review_status(self, client, mock_db):
        method = self._review_method(mock_db, "draft")
        response = client.post(
            f"{API}/methods/{method.id}/reject", headers=AUTH_HEADERS
        )
        assert response.status_code == 400
        assert method.status == "draft"

    def test_submit_requires_draft_status(self, client, mock_db):
        method = self._review_method(mock_db, "approved")
        response = client.post(
            f"{API}/methods/{method.id}/submit", headers=AUTH_HEADERS
        )
        assert response.status_code == 400
        assert method.status == "approved"

    def test_submit_twice_is_rejected(self, client, mock_db):
        method = self._review_method(mock_db, "draft")
        first = client.post(f"{API}/methods/{method.id}/submit", headers=AUTH_HEADERS)
        assert first.status_code == 200
        assert method.status == "review"
        second = client.post(f"{API}/methods/{method.id}/submit", headers=AUTH_HEADERS)
        assert second.status_code == 400


# ============================================
# 未認証アクセス（Q1）
# ============================================
class TestAuthRequiredQuality:
    @pytest.mark.parametrize(
        "method,path",
        [
            ("get", f"{API}/resources"),
            ("get", f"{API}/schedules"),
            ("get", f"{API}/methods"),
            ("get", f"{API}/projects/00000000-0000-0000-0000-0000000000dd/gantt"),
            ("get", f"{API}/projects/00000000-0000-0000-0000-0000000000dd/critical-path"),
        ],
    )
    def test_reads_require_auth(self, client_no_auth, method, path):
        response = getattr(client_no_auth, method)(path)
        assert response.status_code == 401

    def test_approve_requires_auth(self, client_no_auth):
        response = client_no_auth.post(
            f"{API}/methods/00000000-0000-0000-0000-0000000000ab/approve",
            json={"approved_by": str(USER_A)},
        )
        assert response.status_code == 401


# ============================================
# 境界値（Q8）: 進捗率の範囲検証
# ============================================
class TestBoundaryValidationQ8:
    @pytest.mark.parametrize("value", ["150", "-5"])
    @pytest.mark.xfail(
        strict=True,
        reason="DEF-08a: PUT /wbs/{id} は進捗率の0-100制約を検証しない（PATCHとは非対称）",
    )
    def test_wbs_put_rejects_out_of_range_progress(self, client, mock_db, value):
        from unittest.mock import AsyncMock

        wbs = make_wbs(organization_id=ORG_A)
        mock_db.get = AsyncMock(return_value=wbs)
        response = client.put(
            f"{API}/wbs/{wbs.id}",
            json={"progress_percent": value},
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 422, (
            f"範囲外の進捗率 {value} が {response.status_code} で受理された"
        )
