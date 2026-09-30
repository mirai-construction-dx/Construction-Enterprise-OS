"""Organization (tenant) isolation tests for the AI service (Issue #114, ADR-0004)."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.config import get_settings
from src.main import create_app
from src.middleware.auth import TokenData
from src.middleware.tenant import create_org, scope_org, token_org
from src.models import Embedding, PromptTemplate
from src.models.base import get_db

ORG_A = uuid4()
ORG_B = uuid4()
TEMPLATE_ID = uuid4()
SOURCE_ID = uuid4()

_UNSET = object()


def _headers(org: object = _UNSET, roles: list[str] | None = None) -> dict:
    settings = get_settings()
    payload = {
        "sub": str(uuid4()),
        "type": "user",
        "roles": roles if roles is not None else ["member"],
        "scopes": ["ai:read", "ai:write"],
    }
    if org is not _UNSET:
        payload["org"] = org
    else:
        payload["org"] = str(ORG_A)
    token = jwt.encode(
        payload, settings.jwt_public_key, algorithm=settings.JWT_ALGORITHM
    )
    return {"Authorization": f"Bearer {token}"}


USER_A = _headers()
NO_ORG = _headers(org=None)
EMPTY_ORG = _headers(org="")
INVALID_ORG = _headers(org="not-a-uuid")
ADMIN = _headers(org=str(ORG_B), roles=["admin"])
ADMIN_NO_ORG = _headers(org=None, roles=["admin"])


class _Result:
    def __init__(self, value=None):
        self._value = value
        self.rowcount = 0

    def scalar_one_or_none(self):
        return self._value

    def scalar(self):
        return 0

    def scalars(self):
        return self

    def all(self):
        return [] if self._value is None else [self._value]

    def fetchall(self):
        return []


class _RecordingDB:
    """AsyncSession stand-in that records executed statements."""

    def __init__(self, lookup_value=None):
        self.statements: list = []
        self.params: list = []
        self.lookup_value = lookup_value
        self.add = MagicMock()
        self.flush = AsyncMock()
        self.delete = AsyncMock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.close = AsyncMock()

    async def execute(self, stmt, params=None):
        self.statements.append(stmt)
        self.params.append(params)
        return _Result(self.lookup_value)

    def assert_no_db_access(self):
        assert self.statements == []
        self.add.assert_not_called()
        self.flush.assert_not_called()
        self.delete.assert_not_called()
        self.commit.assert_not_called()


def _template(org: UUID = ORG_B) -> SimpleNamespace:
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=TEMPLATE_ID,
        organization_id=org,
        name="t",
        description=None,
        category="general",
        system_prompt="sys",
        user_prompt_template="{{ q }}",
        model="gpt-4",
        temperature=0.5,
        max_tokens=100,
        is_active=True,
        created_by=None,
        created_at=now,
        updated_at=now,
    )


def _make_client(db: _RecordingDB) -> TestClient:
    app = create_app()

    async def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    return TestClient(app)


@pytest.fixture
def db():
    return _RecordingDB()


@pytest.fixture
def client(db):
    return _make_client(db)


def _org_filter_value(stmt, params) -> object:
    """Return the organization value a statement filters on, or None if unfiltered."""
    if params is not None:  # raw text() SQL (vector search)
        if "organization_id = :org_id" in str(stmt):
            return params["org_id"]
        return None
    # Covers the outer WHERE and subqueries (e.g. the list count query);
    # "organization_id = :" never matches the SELECT column list.
    compiled = stmt.compile()
    if "organization_id = :" not in str(compiled):
        return None
    for value in compiled.params.values():
        if isinstance(value, UUID) and value in (ORG_A, ORG_B):
            return value
    raise AssertionError("organization filter without a known org value")


PROMPT_BODY = {
    "name": "T",
    "category": "general",
    "system_prompt": "s",
    "user_prompt_template": "u",
}

# All endpoints whose behaviour changed (method, path, json body)
CHANGED_ENDPOINTS = [
    ("POST", "/api/v1/ai/prompts", PROMPT_BODY),
    ("GET", "/api/v1/ai/prompts", None),
    ("GET", f"/api/v1/ai/prompts/{TEMPLATE_ID}", None),
    ("PUT", f"/api/v1/ai/prompts/{TEMPLATE_ID}", {"name": "x"}),
    ("DELETE", f"/api/v1/ai/prompts/{TEMPLATE_ID}", None),
    ("POST", "/api/v1/ai/chat", {"messages": [{"role": "user", "content": "hi"}]}),
    (
        "POST",
        "/api/v1/ai/chat/stream",
        {"messages": [{"role": "user", "content": "hi"}]},
    ),
    ("POST", "/api/v1/ai/complete", {"prompt_template_id": str(TEMPLATE_ID)}),
    ("POST", "/api/v1/ai/rag/search", {"query": "q"}),
    ("POST", "/api/v1/ai/rag/generate", {"query": "q"}),
    (
        "POST",
        "/api/v1/ai/embeddings",
        {"source_type": "document", "source_id": str(SOURCE_ID), "content": "text"},
    ),
    ("POST", "/api/v1/ai/embeddings/search", {"query": "q"}),
    ("DELETE", f"/api/v1/ai/embeddings/document/{SOURCE_ID}", None),
]


def _call(client: TestClient, method: str, path: str, body, headers):
    return client.request(method, path, json=body, headers=headers)


# ============================================
# 1. Fail-closed: token without / with invalid org
# ============================================


@pytest.mark.parametrize("method,path,body", CHANGED_ENDPOINTS)
@pytest.mark.parametrize("headers", [NO_ORG, EMPTY_ORG], ids=["null", "empty"])
def test_no_org_token_is_rejected(client, db, method, path, body, headers):
    response = _call(client, method, path, body, headers)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ORG_REQUIRED"
    db.assert_no_db_access()


@pytest.mark.parametrize("method,path,body", CHANGED_ENDPOINTS)
def test_invalid_org_token_is_rejected(client, db, method, path, body):
    response = _call(client, method, path, body, INVALID_ORG)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ORG_INVALID"
    db.assert_no_db_access()


def test_chat_without_template_still_requires_org(client, db):
    """The org check must not be swallowed by the template try/except."""
    response = client.post(
        "/api/v1/ai/chat",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "prompt_template_id": str(TEMPLATE_ID),
        },
        headers=NO_ORG,
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ORG_REQUIRED"
    db.assert_no_db_access()


# ============================================
# 2. Prompt templates
# ============================================


def test_create_prompt_uses_token_org(client, db):
    response = client.post("/api/v1/ai/prompts", json=PROMPT_BODY, headers=USER_A)
    assert response.status_code == 200
    created = db.add.call_args.args[0]
    assert isinstance(created, PromptTemplate)
    assert created.organization_id == ORG_A
    assert response.json()["data"]["organization_id"] == str(ORG_A)


def test_create_prompt_ignores_body_organization(client, db):
    body = {**PROMPT_BODY, "organization_id": str(ORG_B)}
    response = client.post("/api/v1/ai/prompts", json=body, headers=USER_A)
    assert response.status_code == 200
    assert db.add.call_args.args[0].organization_id == ORG_A


def test_admin_without_org_cannot_create_prompt(client, db):
    response = client.post("/api/v1/ai/prompts", json=PROMPT_BODY, headers=ADMIN_NO_ORG)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ORG_REQUIRED"
    db.assert_no_db_access()


def test_list_prompts_filtered_by_token_org(client, db):
    response = client.get("/api/v1/ai/prompts", headers=USER_A)
    assert response.status_code == 200
    assert db.statements, "list query was not executed"
    for stmt, params in zip(db.statements, db.params):
        assert _org_filter_value(stmt, params) == ORG_A


def test_admin_list_prompts_crosses_orgs(client, db):
    response = client.get("/api/v1/ai/prompts", headers=ADMIN)
    assert response.status_code == 200
    assert db.statements
    for stmt, params in zip(db.statements, db.params):
        assert _org_filter_value(stmt, params) is None


def test_get_other_org_prompt_is_404(client, db):
    response = client.get(f"/api/v1/ai/prompts/{TEMPLATE_ID}", headers=USER_A)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"
    assert _org_filter_value(db.statements[0], db.params[0]) == ORG_A


def test_update_other_org_prompt_is_404_without_write(client, db):
    response = client.put(
        f"/api/v1/ai/prompts/{TEMPLATE_ID}", json={"name": "hijack"}, headers=USER_A
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"
    assert _org_filter_value(db.statements[0], db.params[0]) == ORG_A
    db.flush.assert_not_called()
    db.commit.assert_not_called()


def test_delete_other_org_prompt_is_404_without_write(client, db):
    response = client.delete(f"/api/v1/ai/prompts/{TEMPLATE_ID}", headers=USER_A)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"
    assert _org_filter_value(db.statements[0], db.params[0]) == ORG_A
    db.delete.assert_not_called()
    db.flush.assert_not_called()
    db.commit.assert_not_called()


def test_admin_gets_and_updates_other_org_prompt():
    template = _template(org=ORG_A)
    db = _RecordingDB(lookup_value=template)
    client = _make_client(db)

    response = client.get(f"/api/v1/ai/prompts/{TEMPLATE_ID}", headers=ADMIN)
    assert response.status_code == 200
    assert response.json()["data"]["organization_id"] == str(ORG_A)
    assert _org_filter_value(db.statements[0], db.params[0]) is None

    response = client.put(
        f"/api/v1/ai/prompts/{TEMPLATE_ID}", json={"name": "renamed"}, headers=ADMIN
    )
    assert response.status_code == 200
    assert template.name == "renamed"
    db.flush.assert_awaited()


# ============================================
# 3. LLM chat / completion (template lookup)
# ============================================


def test_complete_with_other_org_template_is_404(client, db):
    response = client.post(
        "/api/v1/ai/complete",
        json={"prompt_template_id": str(TEMPLATE_ID)},
        headers=USER_A,
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"
    assert _org_filter_value(db.statements[0], db.params[0]) == ORG_A


@pytest.mark.parametrize("path", ["/api/v1/ai/chat", "/api/v1/ai/chat/stream"])
def test_chat_template_lookup_is_org_scoped(client, db, path):
    response = client.post(
        path,
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "prompt_template_id": str(TEMPLATE_ID),
        },
        headers=USER_A,
    )
    assert response.status_code == 200
    assert len(db.statements) == 1
    assert _org_filter_value(db.statements[0], db.params[0]) == ORG_A


def test_admin_complete_uses_any_org_template():
    db = _RecordingDB(lookup_value=_template(org=ORG_A))
    client = _make_client(db)
    response = client.post(
        "/api/v1/ai/complete",
        json={"prompt_template_id": str(TEMPLATE_ID), "variables": {"q": "x"}},
        headers=ADMIN,
    )
    assert response.status_code == 200
    assert _org_filter_value(db.statements[0], db.params[0]) is None


# ============================================
# 4. Embeddings / RAG retrieval
# ============================================


def test_create_embeddings_stored_in_token_org(client, db):
    response = client.post(
        "/api/v1/ai/embeddings",
        json={
            "source_type": "document",
            "source_id": str(SOURCE_ID),
            "content": "text",
        },
        headers=USER_A,
    )
    assert response.status_code == 200
    stored = [c.args[0] for c in db.add.call_args_list]
    assert stored
    assert all(isinstance(e, Embedding) and e.organization_id == ORG_A for e in stored)


@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/v1/ai/embeddings/search", {"query": "q"}),
        ("/api/v1/ai/rag/search", {"query": "q"}),
        ("/api/v1/ai/rag/generate", {"query": "q"}),
    ],
)
def test_vector_search_restricted_to_token_org(client, db, path, body):
    response = client.post(path, json=body, headers=USER_A)
    assert response.status_code == 200
    assert _org_filter_value(db.statements[0], db.params[0]) == ORG_A


@pytest.mark.parametrize(
    "path", ["/api/v1/ai/embeddings/search", "/api/v1/ai/rag/search"]
)
def test_admin_vector_search_crosses_orgs(client, db, path):
    response = client.post(path, json={"query": "q"}, headers=ADMIN)
    assert response.status_code == 200
    assert _org_filter_value(db.statements[0], db.params[0]) is None


def test_rag_generate_template_lookup_is_org_scoped(client, db):
    response = client.post(
        "/api/v1/ai/rag/generate",
        json={"query": "q", "prompt_template_id": str(TEMPLATE_ID)},
        headers=USER_A,
    )
    assert response.status_code == 200
    # [0] vector search, [1] prompt template lookup
    assert len(db.statements) == 2
    assert _org_filter_value(db.statements[0], db.params[0]) == ORG_A
    assert _org_filter_value(db.statements[1], db.params[1]) == ORG_A


def test_delete_embeddings_restricted_to_token_org(client, db):
    response = client.delete(
        f"/api/v1/ai/embeddings/document/{SOURCE_ID}", headers=USER_A
    )
    assert response.status_code == 200
    assert response.json()["data"]["deleted"] == 0
    assert len(db.statements) == 1
    assert _org_filter_value(db.statements[0], db.params[0]) == ORG_A


def test_admin_delete_embeddings_crosses_orgs(client, db):
    response = client.delete(
        f"/api/v1/ai/embeddings/document/{SOURCE_ID}", headers=ADMIN
    )
    assert response.status_code == 200
    assert _org_filter_value(db.statements[0], db.params[0]) is None


# ============================================
# 5. Unchanged endpoints (fixed mock data, no org-owned records)
# ============================================


@pytest.mark.parametrize("path", ["/api/v1/ai/models", "/api/v1/ai/ocr"])
def test_mock_endpoints_unchanged(client, path):
    response = client.get(path, headers=NO_ORG)
    assert response.status_code == 200


# ============================================
# 6. Helper unit tests
# ============================================


def _user(org: str | None, roles: list[str] | None) -> TokenData:
    return TokenData(sub=str(uuid4()), type="user", org=org, roles=roles)


def test_scope_org_rejects_other_org_request():
    with pytest.raises(HTTPException) as exc:
        scope_org(_user(str(ORG_A), ["member"]), ORG_B)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "ORG_FORBIDDEN"


def test_scope_org_handles_none_roles():
    assert scope_org(_user(str(ORG_A), None)) == ORG_A


def test_scope_org_admin_crosses():
    admin = _user(str(ORG_A), ["admin"])
    assert scope_org(admin) is None
    assert scope_org(admin, ORG_B) == ORG_B


def test_create_org_rules():
    with pytest.raises(HTTPException) as exc:
        create_org(_user(str(ORG_A), ["member"]), ORG_B)
    assert exc.value.detail["code"] == "ORG_FORBIDDEN"
    assert create_org(_user(str(ORG_A), ["member"]), ORG_A) == ORG_A
    assert create_org(_user(None, ["admin"]), ORG_B) == ORG_B


@pytest.mark.parametrize(
    "org,code", [(None, "ORG_REQUIRED"), ("", "ORG_REQUIRED"), ("bad", "ORG_INVALID")]
)
def test_token_org_fail_closed(org, code):
    with pytest.raises(HTTPException) as exc:
        token_org(_user(org, ["member"]))
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == code
