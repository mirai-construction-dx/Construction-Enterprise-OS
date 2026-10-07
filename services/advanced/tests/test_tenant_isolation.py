"""Organization (tenant) isolation tests for the Advanced service (Issue #114, ADR-0004)."""

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import src.api.design_review as design_review_api
import src.api.inspections_ai as inspections_api
import src.api.marine as marine_api
import src.api.predictive as predictive_api
from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.middleware.tenant import create_org, scope_org
from src.models import (
    DesignReview,
    InspectionRecord,
    MarineConstruction,
    PredictiveModel,
)
from src.models.base import get_db
from src.services import advanced_service

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
BASE = "/api/v1/advanced"


@pytest.fixture(autouse=True)
def _real_service_functions(monkeypatch):
    """Route through the real service layer.

    test_advanced.py replaces router-module attributes with mocks without restoring them;
    re-bind the real functions so these tests exercise the actual organization predicates.
    """
    for module in (design_review_api, inspections_api, marine_api, predictive_api):
        for name in dir(module):
            real = getattr(advanced_service, name, None)
            if real is not None and callable(real) and not name.startswith("_"):
                if name in ("select", "func"):
                    continue
                monkeypatch.setattr(module, name, real)


def _user(org: str | None = str(ORG_A), roles: list[str] | None = None) -> TokenData:
    return TokenData(
        sub=str(uuid.uuid4()),
        type="user",
        org=org,
        roles=roles if roles is not None else ["engineer"],
    )


ADMIN = _user(org=str(ORG_A), roles=["admin"])


class _Result:
    def __init__(self, value=None, items=None, total=0):
        self._value = value
        self._items = items or []
        self._total = total

    def scalar(self):
        return self._total

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._items


def _client(*results, user: TokenData | None = None):
    """App whose DB returns ``results`` for successive ``execute`` calls."""
    app = create_app()
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=list(results))
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()

    async def _flush():
        # emulate server defaults for records passed to ``add`` so the response validates
        now = datetime.now(timezone.utc)
        for call in db.add.call_args_list:
            obj = call.args[0]
            obj.id = obj.id or uuid.uuid4()
            for attr, default in {
                "created_at": now,
                "updated_at": now,
                "status": "pending",
                "requires_action": False,
            }.items():
                if hasattr(obj, attr) and getattr(obj, attr) is None:
                    setattr(obj, attr, default)

    db.flush = AsyncMock(side_effect=_flush)

    async def _db():
        yield db

    async def _current_user():
        return user or _user()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _current_user
    return TestClient(app), db


def _compiled(db, index: int):
    stmt = db.execute.await_args_list[index].args[0]
    return str(stmt), stmt.compile().params


def _assert_scoped_to(db, index: int, org: uuid.UUID):
    sql, params = _compiled(db, index)
    assert ".organization_id = :" in sql  # a WHERE predicate, not just the column list
    assert org in params.values()


def _assert_unscoped(db, index: int):
    sql, _ = _compiled(db, index)
    assert ".organization_id = :" not in sql


def _assert_no_write(db):
    db.add.assert_not_called()
    db.flush.assert_not_awaited()
    db.delete.assert_not_awaited()
    db.commit.assert_not_awaited()


def _error_code(resp) -> str:
    return resp.json()["detail"]["code"]


# ---------------------------------------------------------------------------
# Records of ORG_B (the "other" organization)
# ---------------------------------------------------------------------------
def _marine(org=ORG_B) -> MarineConstruction:
    now = datetime.now(timezone.utc)
    return MarineConstruction(
        id=uuid.uuid4(),
        organization_id=org,
        name="Breakwater",
        construction_type="breakwater",
        status="planning",
        created_at=now,
        updated_at=now,
    )


def _inspection(org=ORG_B) -> InspectionRecord:
    return InspectionRecord(
        id=uuid.uuid4(),
        organization_id=org,
        asset_name="Bridge A",
        asset_type="bridge",
        severity="moderate",
        defect_type="crack",
        confidence=0.9,
        inspection_date=date.today(),
        requires_action=True,
        created_at=datetime.now(timezone.utc),
    )


def _review(org=ORG_B) -> DesignReview:
    return DesignReview(
        id=uuid.uuid4(),
        organization_id=org,
        review_type="structural",
        status="pending",
        ai_suggestions=[],
        compliance_checks={},
        created_at=datetime.now(timezone.utc),
    )


def _model(org=ORG_B) -> PredictiveModel:
    now = datetime.now(timezone.utc)
    return PredictiveModel(
        id=uuid.uuid4(),
        organization_id=org,
        asset_name="Crane 1",
        asset_type="crane",
        model_type="failure",
        status="training",
        recommendations=[],
        input_metrics={},
        created_at=now,
        updated_at=now,
    )


RESOURCES = {
    "marine": {
        "path": f"{BASE}/marine",
        "factory": _marine,
        "create": {"name": "Breakwater", "construction_type": "breakwater"},
        "update": {"name": "renamed"},
    },
    "inspections": {
        "path": f"{BASE}/inspections",
        "factory": _inspection,
        "create": {
            "asset_name": "Bridge A",
            "asset_type": "bridge",
            "inspection_date": date.today().isoformat(),
        },
        "update": {"severity": "critical"},
    },
    "design-review": {
        "path": f"{BASE}/design-reviews",
        "factory": _review,
        "create": {"review_type": "structural"},
        "update": {"status": "completed"},
    },
    "predictive": {
        "path": f"{BASE}/predictive",
        "factory": _model,
        "create": {
            "asset_name": "Crane 1",
            "asset_type": "crane",
            "model_type": "failure",
        },
        "update": {"status": "active"},
    },
}
KINDS = list(RESOURCES)

# (method, path suffix, json body) for every by-id operation incl. actions
BY_ID_OPS = [
    ("marine", "get", "", None),
    ("marine", "put", "", {"name": "renamed"}),
    ("marine", "delete", "", None),
    ("marine", "patch", "/progress", {"progress_percent": 50}),
    ("inspections", "get", "", None),
    ("inspections", "put", "", {"severity": "critical"}),
    ("inspections", "delete", "", None),
    ("design-review", "get", "", None),
    ("design-review", "put", "", {"status": "completed"}),
    ("design-review", "delete", "", None),
    ("design-review", "get", "/compliance-report", None),
    ("predictive", "get", "", None),
    ("predictive", "put", "", {"status": "active"}),
    ("predictive", "delete", "", None),
    ("predictive", "get", "/prediction", None),
]
BY_ID_IDS = [f"{k}-{m}{s}" for k, m, s, _ in BY_ID_OPS]


def _request(client, method, url, body):
    if body is None:
        return getattr(client, method)(url)
    return getattr(client, method)(url, json=body)


# ---------------------------------------------------------------------------
# Tenant helper unit tests
# ---------------------------------------------------------------------------
def test_scope_org_regular_user_gets_own_org():
    assert scope_org(_user()) == ORG_A
    assert scope_org(_user(), ORG_A) == ORG_A


def test_scope_org_other_org_forbidden():
    with pytest.raises(HTTPException) as exc:
        scope_org(_user(), ORG_B)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "ORG_FORBIDDEN"


@pytest.mark.parametrize(
    ("org", "code"),
    [(None, "ORG_REQUIRED"), ("", "ORG_REQUIRED"), ("not-a-uuid", "ORG_INVALID")],
)
def test_scope_org_fail_closed(org, code):
    with pytest.raises(HTTPException) as exc:
        scope_org(_user(org=org))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == code


def test_scope_org_admin_crosses():
    assert scope_org(ADMIN) is None
    assert scope_org(ADMIN, ORG_B) == ORG_B


def test_create_org_rules():
    assert create_org(_user(), ORG_A) == ORG_A
    assert create_org(ADMIN, ORG_B) == ORG_B
    with pytest.raises(HTTPException) as exc:
        create_org(_user(), ORG_B)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "ORG_FORBIDDEN"


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind", KINDS)
def test_list_defaults_to_token_org(kind):
    client, db = _client(_Result(total=0), _Result(items=[]))
    resp = client.get(RESOURCES[kind]["path"])
    assert resp.status_code == 200
    _assert_scoped_to(db, 0, ORG_A)  # count query
    _assert_scoped_to(db, 1, ORG_A)  # page query


@pytest.mark.parametrize("kind", KINDS)
def test_list_other_org_forbidden(kind):
    client, db = _client()
    resp = client.get(RESOURCES[kind]["path"], params={"organization_id": str(ORG_B)})
    assert resp.status_code == 403
    assert _error_code(resp) == "ORG_FORBIDDEN"
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("bad", "ORG_INVALID")]
)
def test_list_without_valid_org_rejected(kind, org, code):
    client, db = _client(user=_user(org=org))
    resp = client.get(RESOURCES[kind]["path"])
    assert resp.status_code == 403
    assert _error_code(resp) == code
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("kind", KINDS)
def test_admin_list_crosses_orgs(kind):
    factory = RESOURCES[kind]["factory"]
    client, db = _client(_Result(total=1), _Result(items=[factory(ORG_B)]), user=ADMIN)
    resp = client.get(RESOURCES[kind]["path"])
    assert resp.status_code == 200
    assert resp.json()["data"]["records"][0]["organization_id"] == str(ORG_B)
    _assert_unscoped(db, 0)
    _assert_unscoped(db, 1)


@pytest.mark.parametrize("kind", KINDS)
def test_admin_list_may_filter_other_org(kind):
    client, db = _client(_Result(total=0), _Result(items=[]), user=ADMIN)
    resp = client.get(RESOURCES[kind]["path"], params={"organization_id": str(ORG_B)})
    assert resp.status_code == 200
    _assert_scoped_to(db, 0, ORG_B)
    _assert_scoped_to(db, 1, ORG_B)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind", KINDS)
def test_create_in_other_org_forbidden(kind):
    client, db = _client()
    body = {**RESOURCES[kind]["create"], "organization_id": str(ORG_B)}
    resp = client.post(RESOURCES[kind]["path"], json=body)
    assert resp.status_code == 403
    assert _error_code(resp) == "ORG_FORBIDDEN"
    _assert_no_write(db)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("bad", "ORG_INVALID")]
)
def test_create_without_valid_org_rejected(kind, org, code):
    client, db = _client(user=_user(org=org))
    body = {**RESOURCES[kind]["create"], "organization_id": str(ORG_A)}
    resp = client.post(RESOURCES[kind]["path"], json=body)
    assert resp.status_code == 403
    assert _error_code(resp) == code
    _assert_no_write(db)


@pytest.mark.parametrize("kind", KINDS)
def test_create_in_own_org(kind):
    client, db = _client()
    body = {**RESOURCES[kind]["create"], "organization_id": str(ORG_A)}
    resp = client.post(RESOURCES[kind]["path"], json=body)
    assert resp.status_code == 201
    assert db.add.call_args.args[0].organization_id == ORG_A
    assert resp.json()["data"]["organization_id"] == str(ORG_A)


@pytest.mark.parametrize("kind", KINDS)
def test_admin_creates_in_body_org(kind):
    client, db = _client(user=ADMIN)
    body = {**RESOURCES[kind]["create"], "organization_id": str(ORG_B)}
    resp = client.post(RESOURCES[kind]["path"], json=body)
    assert resp.status_code == 201
    assert db.add.call_args.args[0].organization_id == ORG_B


# ---------------------------------------------------------------------------
# By-id operations (get / update / delete / actions)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("kind", "method", "suffix", "body"), BY_ID_OPS, ids=BY_ID_IDS)
def test_by_id_other_org_is_not_found_and_not_written(kind, method, suffix, body):
    # The org-scoped lookup does not match another organization's record -> None.
    # DELETE additionally requires a management role, so use site_manager (regular org-scoped
    # manager) to reach the org-scoped 404 rather than the RBAC 403.
    client, db = _client(_Result(value=None), user=_user(roles=["site_manager"]))
    url = f"{RESOURCES[kind]['path']}/{uuid.uuid4()}{suffix}"
    resp = _request(client, method, url, body)
    assert resp.status_code == 404
    assert _error_code(resp) == "NOT_FOUND"
    assert db.execute.await_count == 1
    _assert_scoped_to(db, 0, ORG_A)
    _assert_no_write(db)


@pytest.mark.parametrize("kind", KINDS)
def test_delete_requires_management_role(kind):
    client, db = _client(user=_user(roles=["engineer"]))
    resp = client.delete(f"{RESOURCES[kind]['path']}/{uuid.uuid4()}")
    assert resp.status_code == 403
    assert _error_code(resp) == "FORBIDDEN"
    _assert_no_write(db)


@pytest.mark.parametrize(("kind", "method", "suffix", "body"), BY_ID_OPS, ids=BY_ID_IDS)
@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("bad", "ORG_INVALID")]
)
def test_by_id_without_valid_org_rejected(kind, method, suffix, body, org, code):
    client, db = _client(user=_user(org=org))
    url = f"{RESOURCES[kind]['path']}/{uuid.uuid4()}{suffix}"
    resp = _request(client, method, url, body)
    assert resp.status_code == 403
    assert _error_code(resp) == code
    db.execute.assert_not_awaited()
    _assert_no_write(db)


@pytest.mark.parametrize(("kind", "method", "suffix", "body"), BY_ID_OPS, ids=BY_ID_IDS)
def test_admin_by_id_crosses_orgs(kind, method, suffix, body):
    record = RESOURCES[kind]["factory"](ORG_B)
    client, db = _client(_Result(value=record), user=ADMIN)
    url = f"{RESOURCES[kind]['path']}/{record.id}{suffix}"
    resp = _request(client, method, url, body)
    assert resp.status_code == 200
    _assert_unscoped(db, 0)


@pytest.mark.parametrize("kind", KINDS)
def test_own_org_record_is_returned(kind):
    record = RESOURCES[kind]["factory"](ORG_A)
    client, db = _client(_Result(value=record))
    resp = client.get(f"{RESOURCES[kind]['path']}/{record.id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == str(record.id)
    _assert_scoped_to(db, 0, ORG_A)


# ---------------------------------------------------------------------------
# Defect summary (aggregate) — previously accepted any organization_id
# ---------------------------------------------------------------------------
SUMMARY = f"{BASE}/inspections/defect-summary"


def test_defect_summary_defaults_to_token_org():
    client, db = _client(_Result(items=[_inspection(ORG_A)]))
    resp = client.get(SUMMARY)
    assert resp.status_code == 200
    assert resp.json()["data"]["total_inspections"] == 1
    _assert_scoped_to(db, 0, ORG_A)


def test_defect_summary_own_org_param_allowed():
    client, db = _client(_Result(items=[]))
    resp = client.get(SUMMARY, params={"organization_id": str(ORG_A)})
    assert resp.status_code == 200
    _assert_scoped_to(db, 0, ORG_A)


def test_defect_summary_other_org_forbidden():
    client, db = _client()
    resp = client.get(SUMMARY, params={"organization_id": str(ORG_B)})
    assert resp.status_code == 403
    assert _error_code(resp) == "ORG_FORBIDDEN"
    db.execute.assert_not_awaited()


@pytest.mark.parametrize(
    ("org", "code"), [(None, "ORG_REQUIRED"), ("bad", "ORG_INVALID")]
)
def test_defect_summary_without_valid_org_rejected(org, code):
    client, db = _client(user=_user(org=org))
    resp = client.get(SUMMARY, params={"organization_id": str(ORG_A)})
    assert resp.status_code == 403
    assert _error_code(resp) == code
    db.execute.assert_not_awaited()


def test_admin_defect_summary_crosses_orgs():
    client, db = _client(
        _Result(items=[_inspection(ORG_A), _inspection(ORG_B)]), user=ADMIN
    )
    resp = client.get(SUMMARY)
    assert resp.status_code == 200
    assert resp.json()["data"]["total_inspections"] == 2
    _assert_unscoped(db, 0)


def test_admin_defect_summary_other_org():
    client, db = _client(_Result(items=[]), user=ADMIN)
    resp = client.get(SUMMARY, params={"organization_id": str(ORG_B)})
    assert resp.status_code == 200
    _assert_scoped_to(db, 0, ORG_B)
