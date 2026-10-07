"""日付入力の不備が 500 にならないことを守る回帰テスト。

症状:
    POST /api/v1/security/policies または PUT /api/v1/security/policies/{id} に
    不正な日付文字列（例 "2024/01/01"）を渡すと 500 を返す。

原因:
    `src/schemas/__init__.py` の `PolicyCreate` / `PolicyUpdate` が
    `effective_date` / `review_date` を `str` で受けるため pydantic の形式検証が入らず、
    `src/services/policy_service.py` が `date.fromisoformat()` を未保護で実行する。
    例外はグローバル例外ハンドラに到達して 500 に変換される。

期待:
    形式不正は 4xx（422）で返し、500 にしない。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.models import SecurityPolicy
from src.models.base import get_db

BASE = "/api/v1/security/policies"
ORG_ID = UUID("00000000-0000-0000-0000-0000000000aa")
USER_ID = UUID("00000000-0000-0000-0000-0000000000a1")


class _ScalarResult:
    def __init__(self, items=None, value=None):
        self._items = items or []
        self._value = value

    def scalars(self):
        return self

    def all(self):
        return self._items

    def first(self):
        return self._items[0] if self._items else None

    def scalar_one_or_none(self):
        return self._items[0] if self._items else self._value

    def scalar(self):
        return self._value if self._value is not None else 0


def _make_policy() -> SecurityPolicy:
    return SecurityPolicy(
        id=uuid4(),
        organization_id=ORG_ID,
        name="テストポリシー",
        category="access_control",
        content="synthetic content",
        status="active",
    )


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarResult([_make_policy()]))
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()

    async def mock_get_db():
        yield db

    app.dependency_overrides[get_db] = mock_get_db
    # 500 を「例外」ではなく「応答」として観測する
    return TestClient(app, raise_server_exceptions=False)


def _auth_headers() -> dict[str, str]:
    import jwt

    from src.config import get_settings

    settings = get_settings()
    token = jwt.encode(
        {
            "sub": str(USER_ID),
            "type": "user",
            "org": str(ORG_ID),
            "roles": ["security_admin"],
            "scopes": [],
        },
        settings.jwt_public_key,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def _create_payload(**overrides) -> dict:
    payload = {
        "organization_id": str(ORG_ID),
        "name": "テストポリシー",
        "category": "access_control",
        "content": "synthetic content",
    }
    payload.update(overrides)
    return payload


INVALID_DATES = ["not-a-date", "2024/01/01", "2024-13-45"]


class TestCreatePolicyDateValidation:
    @pytest.mark.parametrize("bad", INVALID_DATES)
    def test_malformed_effective_date_returns_4xx_not_500(self, client, bad):
        response = client.post(
            BASE,
            json=_create_payload(effective_date=bad),
            headers=_auth_headers(),
        )
        assert response.status_code == 422, (
            f"不正な effective_date({bad!r}) が 500 になった: "
            f"{response.status_code} {response.text[:200]}"
        )
        assert response.status_code != 500

    @pytest.mark.parametrize("bad", INVALID_DATES)
    def test_malformed_review_date_returns_4xx_not_500(self, client, bad):
        response = client.post(
            BASE,
            json=_create_payload(review_date=bad),
            headers=_auth_headers(),
        )
        assert response.status_code == 422, (
            f"不正な review_date({bad!r}) が 500 になった: "
            f"{response.status_code} {response.text[:200]}"
        )

    def test_iso_dates_are_accepted(self, client):
        """正しい ISO 日付は従来どおり受理される（過剰な拒否をしない）。"""
        response = client.post(
            BASE,
            json=_create_payload(
                effective_date="2024-01-01", review_date="2025-01-01"
            ),
            headers=_auth_headers(),
        )
        assert response.status_code == 201, response.text

    def test_omitted_dates_are_accepted(self, client):
        response = client.post(BASE, json=_create_payload(), headers=_auth_headers())
        assert response.status_code == 201, response.text


class TestUpdatePolicyDateValidation:
    @pytest.mark.parametrize("bad", INVALID_DATES)
    def test_malformed_effective_date_returns_4xx_not_500(self, client, bad):
        response = client.put(
            f"{BASE}/{uuid4()}",
            json={"effective_date": bad},
            headers=_auth_headers(),
        )
        assert response.status_code == 422, (
            f"不正な effective_date({bad!r}) が 500 になった: "
            f"{response.status_code} {response.text[:200]}"
        )

    @pytest.mark.parametrize("bad", INVALID_DATES)
    def test_malformed_review_date_returns_4xx_not_500(self, client, bad):
        response = client.put(
            f"{BASE}/{uuid4()}",
            json={"review_date": bad},
            headers=_auth_headers(),
        )
        assert response.status_code == 422, (
            f"不正な review_date({bad!r}) が 500 になった: "
            f"{response.status_code} {response.text[:200]}"
        )

    def test_iso_dates_are_accepted(self, client):
        response = client.put(
            f"{BASE}/{uuid4()}",
            json={"effective_date": "2024-01-01"},
            headers=_auth_headers(),
        )
        assert response.status_code == 200, response.text
