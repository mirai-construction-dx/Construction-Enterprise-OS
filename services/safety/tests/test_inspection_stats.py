"""GET /api/v1/safety/inspections/stats のテスト (Issue #101)。

現在の実装の挙動（集計の形と未認証時の応答）を固定する。
"""

import base64
import json
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from src.main import create_app
from src.models.base import get_db

STATS_URL = "/api/v1/safety/inspections/stats"

VALID_TOKEN_PAYLOAD = {
    "sub": str(uuid.uuid4()),
    "type": "user",
    "org": str(uuid.uuid4()),
    "roles": ["safety_admin"],
    "scopes": [],
}


def _make_auth_header() -> dict:
    payload_b64 = base64.urlsafe_b64encode(
        json.dumps(VALID_TOKEN_PAYLOAD).encode()
    ).decode().rstrip("=")
    header_b64 = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).decode().rstrip("=")
    return {"Authorization": f"Bearer {header_b64}.{payload_b64}.fake_signature"}


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


def _client_with_results(*values) -> tuple[TestClient, AsyncMock]:
    app = create_app()
    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(side_effect=[_ScalarResult(v) for v in values])
    db_mock.add = MagicMock()
    db_mock.commit = AsyncMock()
    db_mock.rollback = AsyncMock()
    db_mock.close = AsyncMock()

    async def get_mock_db():
        yield db_mock

    app.dependency_overrides[get_db] = get_mock_db
    return TestClient(app), db_mock


@patch("src.middleware.auth.jwt")
def test_inspection_stats_returns_aggregates(mock_jwt):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD
    # total, passed, failed, avg(score) の順に 4 回 execute される
    client, db_mock = _client_with_results(10, 6, 2, Decimal("87.456"))

    response = client.get(STATS_URL, headers=_make_auth_header())

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"] == {
        "total": 10,
        "passed": 6,
        "failed": 2,
        "average_score": 87.46,
    }
    assert db_mock.execute.await_count == 4


@patch("src.middleware.auth.jwt")
def test_inspection_stats_counts_passed_and_failed_by_status(mock_jwt):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD
    client, db_mock = _client_with_results(3, 1, 1, 70.0)

    response = client.get(STATS_URL, headers=_make_auth_header())

    assert response.status_code == 200
    stmts = [str(call.args[0]) for call in db_mock.execute.await_args_list]
    # Tenant filtering is intentionally not asserted either way (see Issue #106).
    assert "status = :status_1" in stmts[1]
    assert "status = :status_1" in stmts[2]
    assert "avg(" in stmts[3]
    passed_param = db_mock.execute.await_args_list[1].args[0].compile().params
    failed_param = db_mock.execute.await_args_list[2].args[0].compile().params
    assert passed_param["status_1"] == "passed"
    assert failed_param["status_1"] == "failed"


@patch("src.middleware.auth.jwt")
def test_inspection_stats_with_no_rows(mock_jwt):
    mock_jwt.decode.return_value = VALID_TOKEN_PAYLOAD
    client, _ = _client_with_results(None, None, None, None)

    response = client.get(STATS_URL, headers=_make_auth_header())

    assert response.status_code == 200
    assert response.json()["data"] == {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "average_score": None,
    }


def test_inspection_stats_requires_auth():
    client, db_mock = _client_with_results()

    response = client.get(STATS_URL)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_REQUIRED"
    db_mock.execute.assert_not_awaited()


@patch("src.middleware.auth.jwt")
def test_inspection_stats_rejects_client_token(mock_jwt):
    mock_jwt.decode.return_value = {**VALID_TOKEN_PAYLOAD, "type": "client"}
    client, db_mock = _client_with_results()

    response = client.get(STATS_URL, headers=_make_auth_header())

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "FORBIDDEN"
    db_mock.execute.assert_not_awaited()
