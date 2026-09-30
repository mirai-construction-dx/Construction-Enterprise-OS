"""Organization (tenant) isolation tests for the analytics service (Issue #114, ADR-0004)."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.auth import TokenData, get_current_user
from src.middleware.tenant import create_org, is_cross_org_admin, scope_org
from src.models import AnalyticsReport, DataPipeline, DataSource
from src.models.base import get_db

ORG_A = uuid.uuid4()
ORG_B = uuid.uuid4()
BASE = "/api/v1/analytics"


def _user(org: str | None = str(ORG_A), roles: list[str] | None = None) -> TokenData:
    return TokenData(
        sub=str(uuid.uuid4()),
        type="user",
        org=org,
        roles=roles if roles is not None else ["analyst"],
        scopes=[],
    )


def _admin(org: str | None = str(ORG_A)) -> TokenData:
    return _user(org=org, roles=["admin"])


class _Result:
    def __init__(self, value=None, items=None, total=0):
        self._value = value
        self._items = items or []
        self._total = total

    def scalar_one_or_none(self):
        return self._value

    def scalar(self):
        return self._total

    def scalars(self):
        mock = MagicMock()
        mock.all.return_value = self._items
        return mock


def _client(user: TokenData, *results, get_value=None):
    app = create_app()
    db = AsyncMock()
    if results:
        db.execute = AsyncMock(side_effect=list(results))
    else:
        db.execute = AsyncMock(return_value=_Result())
    db.get = AsyncMock(return_value=get_value)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    db.commit = AsyncMock()

    async def _refresh(obj):
        if obj.id is None:
            obj.id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        obj.created_at = obj.created_at or now
        obj.updated_at = obj.updated_at or now

    db.refresh = _refresh

    async def _db():
        yield db

    async def _current_user():
        return user

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _current_user
    return TestClient(app), db


def _params(db, index: int) -> list:
    """Bound parameter values (WHERE values) of the ``index``-th executed statement."""
    stmt = db.execute.await_args_list[index].args[0]
    return list(stmt.compile().params.values())


def _now():
    return datetime.now(timezone.utc)


def _datasource(org=ORG_A, **kw) -> DataSource:
    return DataSource(
        id=kw.pop("id", uuid.uuid4()),
        organization_id=org,
        name="ds",
        source_type="postgresql",
        connection_config={},
        status="active",
        created_at=_now(),
        updated_at=_now(),
        **kw,
    )


def _pipeline(org=ORG_A, **kw) -> DataPipeline:
    return DataPipeline(
        id=kw.pop("id", uuid.uuid4()),
        organization_id=org,
        name=kw.pop("name", "pipeline"),
        source_id=kw.pop("source_id", uuid.uuid4()),
        target_id=kw.pop("target_id", None),
        transform_logic={},
        status=kw.pop("status", "draft"),
        last_run=None,
        created_at=_now(),
        updated_at=_now(),
        **kw,
    )


def _report(org=ORG_A) -> AnalyticsReport:
    return AnalyticsReport(
        id=uuid.uuid4(),
        organization_id=org,
        name="report",
        report_type="table",
        query_config={},
        status="draft",
        created_at=_now(),
        updated_at=_now(),
    )


def _code(response) -> str:
    return response.json()["detail"]["code"]


# ── helper rules ─────────────────────────────────────────────


def test_scope_org_regular_user_is_pinned_to_token_org():
    assert scope_org(_user()) == ORG_A
    assert scope_org(_user(), ORG_A) == ORG_A


def test_scope_org_regular_user_other_org_is_forbidden():
    with pytest.raises(HTTPException) as exc:
        scope_org(_user(), ORG_B)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "ORG_FORBIDDEN"


def test_scope_org_admin_crosses_organizations():
    assert scope_org(_admin()) is None
    assert scope_org(_admin(), ORG_B) == ORG_B


def test_create_org_rules():
    assert create_org(_user(), ORG_A) == ORG_A
    assert create_org(_admin(), ORG_B) == ORG_B
    with pytest.raises(HTTPException) as exc:
        create_org(_user(), ORG_B)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "ORG_FORBIDDEN"


def test_roles_none_is_not_admin():
    user = TokenData(sub="u", type="user", org=str(ORG_A), roles=None)
    assert is_cross_org_admin(user) is False
    assert scope_org(user) == ORG_A


# ── fail-closed token org ────────────────────────────────────

LIST_PATHS = [f"{BASE}/datasources", f"{BASE}/pipelines", f"{BASE}/reports"]


@pytest.mark.parametrize("path", LIST_PATHS)
def test_token_without_org_is_rejected(path):
    client, db = _client(_user(org=None))
    response = client.get(path)
    assert response.status_code == 403
    assert _code(response) == "ORG_REQUIRED"
    db.execute.assert_not_called()


@pytest.mark.parametrize("path", LIST_PATHS)
def test_token_with_invalid_org_is_rejected(path):
    client, db = _client(_user(org="not-a-uuid"))
    response = client.get(path)
    assert response.status_code == 403
    assert _code(response) == "ORG_INVALID"
    db.execute.assert_not_called()


def test_token_without_org_cannot_fetch_by_id():
    client, db = _client(_user(org=None))
    response = client.get(f"{BASE}/datasources/{uuid.uuid4()}")
    assert response.status_code == 403
    assert _code(response) == "ORG_REQUIRED"
    db.execute.assert_not_called()
    db.get.assert_not_called()


# ── list / aggregate ─────────────────────────────────────────


@pytest.mark.parametrize("path", LIST_PATHS)
def test_list_other_org_is_forbidden(path):
    client, db = _client(_user())
    response = client.get(path, params={"organization_id": str(ORG_B)})
    assert response.status_code == 403
    assert _code(response) == "ORG_FORBIDDEN"
    db.execute.assert_not_called()


@pytest.mark.parametrize("path", LIST_PATHS)
@pytest.mark.parametrize("requested", [None, ORG_A])
def test_list_is_pinned_to_token_org(path, requested):
    client, db = _client(_user(), _Result(total=0), _Result(items=[]))
    params = {"organization_id": str(requested)} if requested else {}
    response = client.get(path, params=params)
    assert response.status_code == 200
    # Both the count (aggregate) query and the page query are filtered by the token org.
    assert ORG_A in _params(db, 0)
    assert ORG_A in _params(db, 1)


def test_list_pipelines_by_source_is_still_org_filtered():
    client, db = _client(_user(), _Result(total=0), _Result(items=[]))
    source_id = uuid.uuid4()
    response = client.get(f"{BASE}/pipelines", params={"source_id": str(source_id)})
    assert response.status_code == 200
    assert ORG_A in _params(db, 0)
    assert source_id in _params(db, 0)
    assert ORG_A in _params(db, 1)


# ── by-id: other org is 404 and nothing is written ───────────

BY_ID_CASES = [
    ("get", "datasources", None),
    ("put", "datasources", {"name": "renamed", "connection_config": {}}),
    ("delete", "datasources", None),
    ("post", "datasources/{id}/test", None),
    ("get", "pipelines", None),
    ("put", "pipelines", {"name": "renamed"}),
    ("delete", "pipelines", None),
    ("post", "pipelines/{id}/run", None),
    ("get", "reports", None),
    ("put", "reports", {"name": "renamed"}),
    ("delete", "reports", None),
    ("post", "reports/{id}/generate", None),
    ("post", "reports/{id}/export", None),
]


def _by_id_path(resource: str, record_id: uuid.UUID) -> str:
    if "{id}" in resource:
        return f"{BASE}/{resource.format(id=record_id)}"
    return f"{BASE}/{resource}/{record_id}"


@pytest.mark.parametrize("method,resource,body", BY_ID_CASES)
def test_by_id_other_org_is_not_found(method, resource, body):
    # The org-scoped lookup finds nothing for a record of another organization.
    client, db = _client(_user(), _Result(value=None))
    record_id = uuid.uuid4()
    kwargs = {"json": body} if body is not None else {}
    response = client.request(
        method.upper(), _by_id_path(resource, record_id), **kwargs
    )
    assert response.status_code == 404
    params = _params(db, 0)
    assert record_id in params
    assert ORG_A in params
    # Unscoped primary-key lookup is never used for a regular user, and nothing is written.
    db.get.assert_not_called()
    db.add.assert_not_called()
    db.delete.assert_not_called()
    db.flush.assert_not_called()
    db.commit.assert_not_called()


def test_get_own_datasource_is_scoped_and_found():
    ds = _datasource()
    client, db = _client(_user(), _Result(value=ds))
    response = client.get(f"{BASE}/datasources/{ds.id}")
    assert response.status_code == 200
    assert response.json()["id"] == str(ds.id)
    assert ORG_A in _params(db, 0)


def test_datasource_test_own_org_succeeds():
    ds = _datasource()
    client, db = _client(_user(), _Result(value=ds))
    response = client.post(f"{BASE}/datasources/{ds.id}/test")
    assert response.status_code == 200
    assert ORG_A in _params(db, 0)


# ── create ───────────────────────────────────────────────────

CREATE_CASES = [
    (
        "datasources",
        {"name": "ds", "source_type": "postgresql", "connection_config": {}},
    ),
    ("pipelines", {"name": "p"}),
    ("reports", {"name": "r", "report_type": "table"}),
]


@pytest.mark.parametrize("resource,body", CREATE_CASES)
def test_create_in_other_org_is_forbidden(resource, body):
    client, db = _client(_user())
    response = client.post(
        f"{BASE}/{resource}", json={**body, "organization_id": str(ORG_B)}
    )
    assert response.status_code == 403
    assert _code(response) == "ORG_FORBIDDEN"
    db.add.assert_not_called()


@pytest.mark.parametrize("resource,body", CREATE_CASES)
def test_create_without_token_org_is_rejected(resource, body):
    client, db = _client(_user(org=None))
    response = client.post(
        f"{BASE}/{resource}", json={**body, "organization_id": str(ORG_A)}
    )
    assert response.status_code == 403
    assert _code(response) == "ORG_REQUIRED"
    db.add.assert_not_called()


@pytest.mark.parametrize("resource,body", CREATE_CASES)
def test_create_in_own_org_succeeds(resource, body):
    client, db = _client(_user())
    response = client.post(
        f"{BASE}/{resource}", json={**body, "organization_id": str(ORG_A)}
    )
    assert response.status_code == 201
    assert db.add.call_args.args[0].organization_id == ORG_A


# ── pipeline → datasource references ─────────────────────────


@pytest.mark.parametrize("field", ["source_id", "target_id"])
def test_create_pipeline_with_other_org_datasource_is_not_found(field):
    ds_id = uuid.uuid4()
    client, db = _client(_user(), _Result(value=None))
    response = client.post(
        f"{BASE}/pipelines",
        json={"organization_id": str(ORG_A), "name": "p", field: str(ds_id)},
    )
    assert response.status_code == 404
    assert _code(response) == "DATASOURCE_NOT_FOUND"
    params = _params(db, 0)
    assert ds_id in params
    assert ORG_A in params
    db.get.assert_not_called()
    db.add.assert_not_called()


def test_create_pipeline_with_own_datasource_succeeds():
    ds = _datasource()
    client, db = _client(_user(), _Result(value=ds))
    response = client.post(
        f"{BASE}/pipelines",
        json={"organization_id": str(ORG_A), "name": "p", "source_id": str(ds.id)},
    )
    assert response.status_code == 201
    assert ORG_A in _params(db, 0)
    assert db.add.call_args.args[0].source_id == ds.id


@pytest.mark.parametrize("field", ["source_id", "target_id"])
def test_update_pipeline_with_other_org_datasource_is_not_found(field):
    pipeline = _pipeline()
    original_source, original_target = pipeline.source_id, pipeline.target_id
    new_ds = uuid.uuid4()
    client, db = _client(_user(), _Result(value=pipeline), _Result(value=None))
    response = client.put(
        f"{BASE}/pipelines/{pipeline.id}", json={"name": "renamed", field: str(new_ds)}
    )
    assert response.status_code == 404
    assert _code(response) == "DATASOURCE_NOT_FOUND"
    params = _params(db, 1)
    assert new_ds in params
    assert ORG_A in params
    # Nothing on the pipeline was mutated.
    assert pipeline.name == "pipeline"
    assert pipeline.source_id == original_source
    assert pipeline.target_id == original_target
    db.commit.assert_not_called()


def test_run_pipeline_referencing_other_org_datasource_is_not_found():
    # Legacy data: the pipeline points at a datasource that is not in its organization.
    pipeline = _pipeline()
    client, db = _client(_user(), _Result(value=pipeline), _Result(value=None))
    response = client.post(f"{BASE}/pipelines/{pipeline.id}/run")
    assert response.status_code == 404
    assert _code(response) == "DATASOURCE_NOT_FOUND"
    params = _params(db, 1)
    assert pipeline.source_id in params
    assert ORG_A in params
    assert pipeline.status == "draft"
    assert pipeline.last_run is None
    db.commit.assert_not_called()


def test_run_pipeline_with_own_datasources_succeeds():
    source, target = _datasource(), _datasource()
    pipeline = _pipeline(source_id=source.id, target_id=target.id)
    client, db = _client(
        _user(), _Result(value=pipeline), _Result(value=source), _Result(value=target)
    )
    response = client.post(f"{BASE}/pipelines/{pipeline.id}/run")
    assert response.status_code == 200
    assert pipeline.status == "running"
    assert ORG_A in _params(db, 1)
    assert ORG_A in _params(db, 2)


# ── admin crosses organizations ──────────────────────────────


@pytest.mark.parametrize("path", LIST_PATHS)
def test_admin_can_list_other_org(path):
    client, db = _client(_admin(), _Result(total=0), _Result(items=[]))
    response = client.get(path, params={"organization_id": str(ORG_B)})
    assert response.status_code == 200
    assert ORG_B in _params(db, 0)
    assert ORG_A not in _params(db, 0)


@pytest.mark.parametrize("path", LIST_PATHS)
def test_admin_list_without_filter_spans_orgs(path):
    client, db = _client(_admin(), _Result(total=0), _Result(items=[]))
    response = client.get(path)
    assert response.status_code == 200
    assert not any(isinstance(v, uuid.UUID) for v in _params(db, 0))


def test_admin_without_token_org_still_crosses():
    client, _db = _client(_admin(org=None), _Result(total=0), _Result(items=[]))
    response = client.get(f"{BASE}/reports")
    assert response.status_code == 200


def test_admin_can_get_other_org_record():
    report = _report(org=ORG_B)
    client, db = _client(_admin(), get_value=report)
    response = client.get(f"{BASE}/reports/{report.id}")
    assert response.status_code == 200
    assert response.json()["organization_id"] == str(ORG_B)
    db.execute.assert_not_called()


@pytest.mark.parametrize("resource,body", CREATE_CASES)
def test_admin_can_create_in_other_org(resource, body):
    client, db = _client(_admin())
    response = client.post(
        f"{BASE}/{resource}", json={**body, "organization_id": str(ORG_B)}
    )
    assert response.status_code == 201
    assert db.add.call_args.args[0].organization_id == ORG_B


def test_admin_create_pipeline_with_datasource_of_another_org_is_bad_request():
    ds = _datasource(org=ORG_A)
    client, db = _client(_admin(), get_value=ds)
    response = client.post(
        f"{BASE}/pipelines",
        json={"organization_id": str(ORG_B), "name": "p", "source_id": str(ds.id)},
    )
    assert response.status_code == 400
    assert _code(response) == "DATASOURCE_ORG_MISMATCH"
    db.add.assert_not_called()


def test_admin_create_pipeline_with_missing_datasource_is_not_found():
    client, db = _client(_admin(), get_value=None)
    response = client.post(
        f"{BASE}/pipelines",
        json={
            "organization_id": str(ORG_B),
            "name": "p",
            "target_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 404
    assert _code(response) == "DATASOURCE_NOT_FOUND"
    db.add.assert_not_called()


def test_admin_update_pipeline_with_datasource_of_another_org_is_bad_request():
    pipeline = _pipeline(org=ORG_B)
    original_source = pipeline.source_id
    ds = _datasource(org=ORG_A)

    async def _get(model, record_id):
        return pipeline if model is DataPipeline else ds

    client, db = _client(_admin())
    db.get = AsyncMock(side_effect=_get)
    response = client.put(
        f"{BASE}/pipelines/{pipeline.id}", json={"source_id": str(ds.id)}
    )
    assert response.status_code == 400
    assert _code(response) == "DATASOURCE_ORG_MISMATCH"
    assert pipeline.source_id == original_source
