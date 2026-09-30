"""固定データを返す一覧エンドポイントのページング / 絞り込みテスト (Issue #101)。

対象: drone-flights / error-logs / rpa-tasks / twin-sensors。
現在の実装はページング情報を `meta` ではなく `data.total` と
`data.items` のスライスで返す（`meta` は null）。その挙動を固定する。
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.middleware.auth import get_current_user

BASE = "/api/v1/autonomous"
AUTH = {"Authorization": "Bearer mock-user-token"}


async def _mock_get_current_user():
    user = MagicMock()
    user.sub = "00000000-0000-0000-0000-000000000001"
    user.type = "user"
    user.org = "00000000-0000-0000-0000-000000000001"
    user.roles = ["admin"]
    user.scopes = []
    return user


@pytest.fixture
def api_client():
    # pytest-django の `client` と衝突しないよう別名にする
    app = create_app()
    app.dependency_overrides[get_current_user] = _mock_get_current_user
    return TestClient(app)


def _get(api_client, path: str) -> dict:
    response = api_client.get(f"{BASE}{path}", headers=AUTH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    return body


def _ids(body: dict) -> list[str]:
    return [item["id"] for item in body["data"]["items"]]


# ============================================
# 共通: ページング
# ============================================
@pytest.mark.parametrize(
    ("resource", "total"),
    [
        ("drone-flights", 6),
        ("error-logs", 5),
        ("rpa-tasks", 6),
        ("twin-sensors", 8),
    ],
)
def test_default_paging_returns_all_items_without_meta(api_client, resource, total):
    body = _get(api_client, f"/{resource}")
    assert body["data"]["total"] == total
    assert len(body["data"]["items"]) == total
    assert body["meta"] is None


@pytest.mark.parametrize(
    "resource", ["drone-flights", "error-logs", "rpa-tasks", "twin-sensors"]
)
@pytest.mark.parametrize("query", ["page=0", "per_page=0", "per_page=101"])
def test_out_of_range_paging_is_rejected(api_client, resource, query):
    response = api_client.get(f"{BASE}/{resource}?{query}", headers=AUTH)
    assert response.status_code == 422


# ============================================
# drone-flights
# ============================================
def test_drone_flights_second_page(api_client):
    body = _get(api_client, "/drone-flights?page=2&per_page=2")
    assert _ids(body) == ["df3", "df4"]
    assert body["data"]["total"] == 6


def test_drone_flights_page_past_end_is_empty(api_client):
    body = _get(api_client, "/drone-flights?page=4&per_page=2")
    assert _ids(body) == []
    assert body["data"]["total"] == 6


def test_drone_flights_status_filter(api_client):
    body = _get(api_client, "/drone-flights?status=planned")
    assert _ids(body) == ["df6"]
    assert body["data"]["total"] == 1


def test_drone_flights_status_filter_with_paging(api_client):
    body = _get(api_client, "/drone-flights?status=completed&page=2&per_page=3")
    assert _ids(body) == ["df4"]
    assert body["data"]["total"] == 4


def test_drone_flights_unknown_status_is_empty(api_client):
    body = _get(api_client, "/drone-flights?status=unknown")
    assert _ids(body) == []
    assert body["data"]["total"] == 0


# ============================================
# error-logs
# ============================================
def test_error_logs_severity_and_status_filters(api_client):
    body = _get(api_client, "/error-logs?severity=warning&status=open")
    assert _ids(body) == ["err1", "err4"]
    assert body["data"]["total"] == 2


def test_error_logs_severity_filter(api_client):
    body = _get(api_client, "/error-logs?severity=critical")
    assert _ids(body) == ["err2"]
    assert body["data"]["total"] == 1


def test_error_logs_machine_no_filter(api_client):
    body = _get(api_client, "/error-logs?machine_no=CB-001")
    assert _ids(body) == ["err2"]
    assert body["data"]["total"] == 1


def test_error_logs_status_filter_with_paging(api_client):
    body = _get(api_client, "/error-logs?status=resolved&page=2&per_page=2")
    assert _ids(body) == ["err5"]
    assert body["data"]["total"] == 3


# ============================================
# rpa-tasks
# ============================================
def test_rpa_tasks_is_active_false_filter(api_client):
    body = _get(api_client, "/rpa-tasks?is_active=false")
    assert _ids(body) == ["rpa6"]
    assert body["data"]["total"] == 1


def test_rpa_tasks_is_active_true_filter(api_client):
    body = _get(api_client, "/rpa-tasks?is_active=true")
    assert _ids(body) == ["rpa1", "rpa2", "rpa3", "rpa4", "rpa5"]
    assert body["data"]["total"] == 5


def test_rpa_tasks_paging(api_client):
    body = _get(api_client, "/rpa-tasks?page=3&per_page=2")
    assert _ids(body) == ["rpa5", "rpa6"]
    assert body["data"]["total"] == 6


# ============================================
# twin-sensors
# ============================================
def test_twin_sensors_twin_id_and_sensor_type_filters(api_client):
    body = _get(api_client, "/twin-sensors?twin_id=twin-002&sensor_type=pressure")
    assert _ids(body) == ["sen4"]
    assert body["data"]["total"] == 1


def test_twin_sensors_status_filter(api_client):
    body = _get(api_client, "/twin-sensors?status=warning")
    assert _ids(body) == ["sen3", "sen5", "sen7"]
    assert body["data"]["total"] == 3


def test_twin_sensors_sensor_type_filter_with_paging(api_client):
    body = _get(api_client, "/twin-sensors?sensor_type=temperature&page=2&per_page=1")
    assert _ids(body) == ["sen5"]
    assert body["data"]["total"] == 2
