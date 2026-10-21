"""cascade="all, delete-orphan" が他組織の子レコードを巻き込む問題の回帰テスト (Issue #149).

FK だけでは子の組織は保証されない（PR #148 以前に作られた不整合データが存在し得る）。
親 (agent / digital twin) の削除時、子 (task / simulation) に親と異なる
``organization_id`` の行があれば、cascade で他組織の行まで削除されてしまう。
削除は拒否し (409)、同一組織の子だけが消えることを固定する。
"""

import importlib
from unittest.mock import AsyncMock

import pytest

from src.services import autonomous_service as svc

from .tenant_support import (
    AUTH,
    BASE,
    ORG_A,
    admin,
    detail_code,
    make_client,
    make_db,
    record,
)

RID = "11111111-1111-1111-1111-111111111111"


# ── service layer ────────────────────────────────────────────


async def test_delete_agent_rejects_cross_org_tasks():
    agent = record("agent", org=ORG_A)
    db = make_db(agent, 1)  # 2nd query: 他組織のタスクが 1 件

    with pytest.raises(svc.CrossOrgChildrenError) as exc:
        await svc.delete_agent(db, agent.id, organization_id=ORG_A)

    assert exc.value.code == "AGENT_HAS_CROSS_ORG_TASKS"
    db.delete.assert_not_awaited()
    db.flush.assert_not_awaited()


async def test_delete_agent_cross_org_check_is_scoped_to_parent():
    agent = record("agent", org=ORG_A)
    db = make_db(agent, 1)

    with pytest.raises(svc.CrossOrgChildrenError):
        await svc.delete_agent(db, agent.id, organization_id=ORG_A)

    stmt = db.execute.await_args_list[1].args[0]
    sql = str(stmt)
    params = stmt.compile().params
    assert "autonomous_tasks" in sql
    assert "agent_id" in sql
    assert "organization_id !=" in sql
    assert agent.id in params.values()
    assert agent.organization_id in params.values()


async def test_delete_agent_without_cross_org_tasks_deletes():
    agent = record("agent", org=ORG_A)
    db = make_db(agent, 0)

    assert await svc.delete_agent(db, agent.id, organization_id=ORG_A) is True

    db.delete.assert_awaited_once_with(agent)
    db.flush.assert_awaited_once()


@pytest.mark.parametrize(
    ("task_mismatch", "sim_mismatch", "code"),
    [
        (1, 0, "TWIN_HAS_CROSS_ORG_TASKS"),
        (0, 1, "TWIN_HAS_CROSS_ORG_SIMULATIONS"),
        (1, 1, "TWIN_HAS_CROSS_ORG_TASKS"),
    ],
)
async def test_delete_twin_rejects_cross_org_children(task_mismatch, sim_mismatch, code):
    twin = record("twin", org=ORG_A)
    db = make_db(twin, task_mismatch, sim_mismatch)

    with pytest.raises(svc.CrossOrgChildrenError) as exc:
        await svc.delete_twin(db, twin.id, organization_id=ORG_A)

    assert exc.value.code == code
    db.delete.assert_not_awaited()
    db.flush.assert_not_awaited()


async def test_delete_twin_without_cross_org_children_deletes():
    twin = record("twin", org=ORG_A)
    db = make_db(twin, 0, 0)

    assert await svc.delete_twin(db, twin.id, organization_id=ORG_A) is True

    db.delete.assert_awaited_once_with(twin)
    db.flush.assert_awaited_once()


async def test_delete_agent_other_org_still_returns_false_without_child_queries():
    """他組織の親は従来どおり 404 (False)。子の検査クエリは発行しない。"""
    db = make_db(None)

    assert await svc.delete_agent(db, RID, organization_id=ORG_A) is False

    assert db.execute.await_count == 1
    db.delete.assert_not_awaited()


# ── API layer: 409 への変換 ──────────────────────────────────


def _spy(monkeypatch, module: str, fn: str, result) -> AsyncMock:
    spy = AsyncMock(return_value=result)
    monkeypatch.setattr(importlib.import_module(f"src.api.{module}"), fn, spy)
    return spy


@pytest.mark.parametrize(
    ("path", "module", "fn", "code"),
    [
        (
            f"/agents/{RID}",
            "agents",
            "delete_agent",
            "AGENT_HAS_CROSS_ORG_TASKS",
        ),
        (
            f"/digital-twins/{RID}",
            "digital_twins",
            "delete_twin",
            "TWIN_HAS_CROSS_ORG_SIMULATIONS",
        ),
    ],
)
def test_delete_with_cross_org_children_returns_409(
    monkeypatch, path, module, fn, code
):
    def _raise(*args, **kwargs):
        raise svc.CrossOrgChildrenError(code, "他組織の子レコードが存在します。")

    spy = AsyncMock(side_effect=_raise)
    monkeypatch.setattr(importlib.import_module(f"src.api.{module}"), fn, spy)
    client, _ = make_client(admin())

    resp = client.delete(f"{BASE}{path}", headers=AUTH)

    assert resp.status_code == 409
    assert detail_code(resp) == code


def test_delete_without_cross_org_children_still_succeeds(monkeypatch):
    spy = _spy(monkeypatch, "agents", "delete_agent", True)
    client, _ = make_client(admin())

    resp = client.delete(f"{BASE}/agents/{RID}", headers=AUTH)

    assert resp.status_code == 200, resp.text
    assert spy.await_args.kwargs["organization_id"] is None
