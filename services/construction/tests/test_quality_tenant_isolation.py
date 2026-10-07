"""品質テスト: テナント分離（Q2 データ分離 / Q1 権限境界）。

検証仮説:
  H1: GET /resources /schedules /methods は organization_id をクエリから受け、
      省略時は全テナントを返す（WBS の list_wbs はトークン由来で非対称）。
  H2: GET/PUT/DELETE /{resources,schedules,methods}/{id} は組織検査がない。
  H3: GET /projects/{project_id}/{resource-cost-summary,critical-path,gantt} は
      組織検査がない。
  H4: POST /{resources,schedules,methods} は body の organization_id を保存する。
  H7: /wbs/tree の子ノード取得は組織で絞られていない。

期待値は仕様（トークンの `org` クレームがテナントの唯一の根拠）に基づく。
欠陥が未修正の間は xfail(strict=True) とし、修正されると XPASS→FAIL になる。
"""

from unittest.mock import AsyncMock

import pytest

from tests.quality_helpers import (
    API,
    AUTH_HEADERS,
    ORG_A,
    ORG_B,
    PROJECT_A,
    MockScalarResult,
    client,  # noqa: F401  (pytest fixture)
    compile_sql,
    make_method,
    make_resource,
    make_schedule,
    make_wbs,
    mock_db,  # noqa: F401  (pytest fixture)
    record_execute,
    where_clause,
)

# ============================================
# H1: 一覧系の organization_id がクエリ由来
# ============================================
class TestH1ListTenantSource:
    @pytest.fixture(params=["resources", "schedules", "methods"])
    def list_case(self, request):
        return request.param

    def test_list_without_org_query_is_tenant_scoped(self, client, mock_db, list_case):
        captured = record_execute(
            mock_db, [MockScalarResult(total=0), MockScalarResult(items=[])]
        )
        response = client.get(f"{API}/{list_case}", headers=AUTH_HEADERS)
        assert response.status_code == 200
        # 一覧クエリ（count の次）に organization_id の WHERE が必須
        sql = where_clause(compile_sql(captured[-1]))
        assert "organization_id" in sql, (
            f"{list_case} の一覧がテナントで絞られていない: {sql!r}"
        )

    def test_list_honors_token_org_not_query_org(self, client, mock_db, list_case):
        captured = record_execute(
            mock_db, [MockScalarResult(total=0), MockScalarResult(items=[])]
        )
        response = client.get(
            f"{API}/{list_case}?organization_id={ORG_B}", headers=AUTH_HEADERS
        )
        assert response.status_code == 200
        sql = where_clause(compile_sql(captured[-1]))
        assert "organization_id" in sql
        # token(ORG_A) 以外の組織で絞ってはならない
        assert str(ORG_B) not in sql, (
            f"{list_case} の一覧がクエリ指定の他テナント {ORG_B} で絞られた: {sql!r}"
        )
        assert str(ORG_A) in sql, (
            f"{list_case} の一覧がトークン組織 {ORG_A} で絞られていない: {sql!r}"
        )

    def test_wbs_list_uses_token_org_ignoring_query(self, client, mock_db):
        """正の対照: WBS 一覧はトークン由来（同じサービス内で非対称）。"""
        captured = record_execute(
            mock_db, [MockScalarResult(total=0), MockScalarResult(items=[])]
        )
        response = client.get(f"{API}/wbs?organization_id={ORG_B}", headers=AUTH_HEADERS)
        assert response.status_code == 200
        sql = where_clause(compile_sql(captured[-1]))
        assert str(ORG_A) in sql
        assert str(ORG_B) not in sql


# ============================================
# H2: 個別取得/更新/削除のテナント境界
# ============================================
DETAIL_CASES = [
    ("resources", make_resource, {"planned_quantity": "99"}),
    ("schedules", make_schedule, {"name": "改ざん工程A"}),
    ("methods", make_method, {"title": "改ざん計画書A"}),
]
DETAIL_IDS = [c[0] for c in DETAIL_CASES]


class TestH2DetailTenantBoundary:
    @pytest.mark.parametrize("name,factory,_body", DETAIL_CASES, ids=DETAIL_IDS)
    def test_get_detail_rejects_other_tenant(self, client, mock_db, name, factory, _body):
        obj = factory(organization_id=ORG_B)
        mock_db.get = AsyncMock(return_value=obj)
        response = client.get(f"{API}/{name}/{obj.id}", headers=AUTH_HEADERS)
        assert response.status_code == 404, (
            f"{name} の個別GETが他テナント {ORG_B} を {response.status_code} で返した"
        )

    @pytest.mark.parametrize("name,factory,body", DETAIL_CASES, ids=DETAIL_IDS)
    def test_put_detail_rejects_other_tenant(self, client, mock_db, name, factory, body):
        obj = factory(organization_id=ORG_B)
        mock_db.get = AsyncMock(return_value=obj)
        response = client.put(
            f"{API}/{name}/{obj.id}", json=body, headers=AUTH_HEADERS
        )
        assert response.status_code == 404, (
            f"{name} のPUTが他テナント {ORG_B} を {response.status_code} で更新した"
        )

    @pytest.mark.parametrize("name,factory,_body", DETAIL_CASES, ids=DETAIL_IDS)
    def test_delete_detail_rejects_other_tenant(
        self, client, mock_db, name, factory, _body
    ):
        obj = factory(organization_id=ORG_B)
        mock_db.get = AsyncMock(return_value=obj)
        response = client.delete(f"{API}/{name}/{obj.id}", headers=AUTH_HEADERS)
        assert response.status_code == 404, (
            f"{name} のDELETEが他テナント {ORG_B} を {response.status_code} で削除した"
        )
        assert mock_db.delete.await_count == 0

    def test_wbs_detail_rejects_other_tenant(self, client, mock_db):
        """正の対照: WBS 個別GETは組織検査済み。"""
        other = make_wbs(organization_id=ORG_B, name="他組織のWBS")
        mock_db.get = AsyncMock(return_value=other)
        response = client.get(f"{API}/wbs/{other.id}", headers=AUTH_HEADERS)
        assert response.status_code == 404


# ============================================
# H3: プロジェクト集計系のテナント境界
# ============================================
class TestH3ProjectAggregateTenantBoundary:
    def test_resource_cost_summary_is_tenant_scoped(self, client, mock_db):
        captured = record_execute(mock_db, [MockScalarResult(items=[])])
        response = client.get(
            f"{API}/projects/{PROJECT_A}/resource-cost-summary", headers=AUTH_HEADERS
        )
        assert response.status_code == 200
        sql = where_clause(compile_sql(captured[-1]))
        assert "organization_id" in sql, (
            f"原価集計がテナントで絞られていない: {sql!r}"
        )

    def test_critical_path_is_tenant_scoped(self, client, mock_db):
        captured = record_execute(mock_db, [MockScalarResult(items=[])])
        response = client.get(
            f"{API}/projects/{PROJECT_A}/critical-path", headers=AUTH_HEADERS
        )
        assert response.status_code == 200
        sql = where_clause(compile_sql(captured[-1]))
        assert "organization_id" in sql, (
            f"クリティカルパスがテナントで絞られていない: {sql!r}"
        )

    def test_gantt_is_tenant_scoped(self, client, mock_db):
        captured = record_execute(mock_db, [MockScalarResult(items=[])])
        response = client.get(
            f"{API}/projects/{PROJECT_A}/gantt", headers=AUTH_HEADERS
        )
        assert response.status_code == 200
        sql = where_clause(compile_sql(captured[-1]))
        assert "organization_id" in sql, f"ガントがテナントで絞られていない: {sql!r}"


# ============================================
# H4: 作成時の organization_id がボディ由来
# ============================================
class TestH4CreateTenantSpoof:
    def test_create_resource_uses_token_org(self, client, mock_db):
        response = client.post(
            f"{API}/resources",
            json={
                "organization_id": str(ORG_B),
                "project_id": str(PROJECT_A),
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
        assert created.organization_id == ORG_A, (
            f"body の他テナント {ORG_B} が保存された: {created.organization_id}"
        )

    def test_create_schedule_uses_token_org(self, client, mock_db):
        response = client.post(
            f"{API}/schedules",
            json={
                "organization_id": str(ORG_B),
                "project_id": str(PROJECT_A),
                "name": "テスト工程A",
                "schedule_type": "master",
                "planned_start": "2026-05-01",
                "planned_end": "2026-06-30",
                "critical_path": True,
            },
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 201
        created = mock_db.add.call_args[0][0]
        assert created.organization_id == ORG_A, (
            f"body の他テナント {ORG_B} が保存された: {created.organization_id}"
        )

    def test_create_method_uses_token_org(self, client, mock_db):
        response = client.post(
            f"{API}/methods",
            json={
                "organization_id": str(ORG_B),
                "project_id": str(PROJECT_A),
                "title": "テスト施工計画書A",
                "document_type": "method_statement",
            },
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 201
        created = mock_db.add.call_args[0][0]
        assert created.organization_id == ORG_A, (
            f"body の他テナント {ORG_B} が保存された: {created.organization_id}"
        )

    def test_create_wbs_overrides_body_org_with_token(self, client, mock_db):
        """正の対照: WBS 作成は body をトークン組織で上書きする。"""
        response = client.post(
            f"{API}/wbs",
            json={
                "organization_id": str(ORG_B),
                "project_id": str(PROJECT_A),
                "wbs_code": "1",
                "name": "テスト工区A",
                "level": 1,
            },
            headers=AUTH_HEADERS,
        )
        assert response.status_code == 201
        created = mock_db.add.call_args[0][0]
        assert created.organization_id == ORG_A


# ============================================
# H7: WBS ツリー子ノードのテナント混入
# ============================================
class TestH7WbsTreeChildTenantLeak:
    def test_wbs_tree_children_query_is_tenant_scoped(self, client, mock_db):
        root = make_wbs(organization_id=ORG_A, wbs_code="1", name="テスト工区A")
        captured = record_execute(
            mock_db,
            [
                MockScalarResult(items=[root]),  # ルート（組織で絞られている）
                MockScalarResult(items=[]),  # 子
            ],
        )
        response = client.get(
            f"{API}/wbs/tree?project_id={PROJECT_A}", headers=AUTH_HEADERS
        )
        assert response.status_code == 200
        # captured[0]=ルート, captured[1]=子ノード
        root_sql = where_clause(compile_sql(captured[0]))
        child_sql = where_clause(compile_sql(captured[1]))
        assert "organization_id" in root_sql  # ルートは絞られている（対照）
        assert "organization_id" in child_sql, (
            f"子ノード取得がテナントで絞られていない: {child_sql!r}"
        )

    def test_wbs_tree_does_not_include_foreign_child(self, client, mock_db):
        root = make_wbs(organization_id=ORG_A, wbs_code="1", name="テスト工区A")
        foreign = make_wbs(
            organization_id=ORG_B,
            parent_id=root.id,
            wbs_code="1.9",
            name="他テナント子ノード",
            level=2,
        )
        record_execute(
            mock_db,
            [
                MockScalarResult(items=[root]),
                MockScalarResult(items=[foreign]),
                MockScalarResult(items=[]),
            ],
        )
        response = client.get(
            f"{API}/wbs/tree?project_id={PROJECT_A}", headers=AUTH_HEADERS
        )
        assert response.status_code == 200
        data = response.json()
        child_orgs = [c["organization_id"] for c in data[0]["children"]]
        assert str(ORG_B) not in child_orgs, (
            f"他テナント {ORG_B} の子ノードがツリーに混入: {child_orgs}"
        )

    def test_wbs_children_endpoint_excludes_foreign_child(self, client, mock_db):
        parent = make_wbs(organization_id=ORG_A, name="テスト工区A")
        foreign = make_wbs(
            organization_id=ORG_B,
            parent_id=parent.id,
            wbs_code="1.9",
            name="他テナント子ノード",
            level=2,
        )
        mock_db.get = AsyncMock(return_value=parent)
        record_execute(mock_db, [MockScalarResult(items=[foreign])])
        response = client.get(f"{API}/wbs/{parent.id}/children", headers=AUTH_HEADERS)
        assert response.status_code == 200
        orgs = [item["organization_id"] for item in response.json()]
        assert str(ORG_B) not in orgs, f"他テナント {ORG_B} の子ノードを返した: {orgs}"
