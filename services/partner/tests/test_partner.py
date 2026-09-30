"""Partner Service テスト"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from .conftest import (
    SAMPLE_UUID,
    TEST_USER_ID,
    make_mock_assignment,
    make_mock_contact,
    make_mock_contract,
    make_mock_evaluation,
    make_mock_partner,
)

pytestmark = pytest.mark.anyio


def _patch_partner_lookup(module: str):
    """Patch the org-scoped parent partner lookup added by ADR-0004 (Issue #114)."""
    return patch(
        f"src.api.{module}.partner_service.get_partner_by_id",
        new_callable=AsyncMock,
        return_value=make_mock_partner(),
    )


# ============================================
# 1. Health Check
# ============================================
async def test_health_check(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "partner-service"


# ============================================
# 2. Auth Required
# ============================================
async def test_auth_required_partners(client: AsyncClient):
    response = await client.get("/api/v1/partners")
    assert response.status_code == 401


async def test_auth_required_contracts(client: AsyncClient):
    response = await client.get("/api/v1/partners/contracts")
    assert response.status_code == 401


async def test_auth_required_evaluations(client: AsyncClient):
    response = await client.get("/api/v1/partners/evaluations")
    assert response.status_code == 401


# ============================================
# 3. Partner CRUD
# ============================================
async def test_create_partner(client: AsyncClient, auth_headers):
    mock_partner = make_mock_partner()

    with patch("src.api.partners.partner_service.create_partner", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_partner

        response = await client.post("/api/v1/partners", json={
            "name": "テスト建設株式会社",
            "company_type": "subcontractor",
            "email": "test@example.com",
        }, headers=auth_headers)

    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["data"]["name"] == "テスト建設株式会社"
    assert data["data"]["company_type"] == "subcontractor"


async def test_list_partners(client: AsyncClient, auth_headers):
    mock_partner = make_mock_partner()

    with patch("src.api.partners.partner_service.list_partners", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = ([mock_partner], 1)

        response = await client.get("/api/v1/partners", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["data"]) == 1
    assert data["meta"]["total"] == 1
    assert data["meta"]["page"] == 1


async def test_get_partner_detail(client: AsyncClient, auth_headers):
    mock_partner = make_mock_partner()
    mock_contract = make_mock_contract()

    with patch("src.api.partners.partner_service.get_partner_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_partner
        with patch("src.api.partners.contract_service.list_contracts_for_partner", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = ([mock_contract], 1)

            response = await client.get(f"/api/v1/partners/{SAMPLE_UUID}", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["data"]["name"] == "テスト建設株式会社"
    assert "contacts" in data["data"]
    assert "contracts_summary" in data["data"]
    assert len(data["data"]["contracts_summary"]) == 1


async def test_get_partner_not_found(client: AsyncClient, auth_headers):
    with patch("src.api.partners.partner_service.get_partner_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None

        response = await client.get(f"/api/v1/partners/{SAMPLE_UUID}", headers=auth_headers)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "PARTNER_NOT_FOUND"


async def test_update_partner(client: AsyncClient, auth_headers):
    mock_partner = make_mock_partner(name="更新された建設株式会社")

    with patch("src.api.partners.partner_service.update_partner", new_callable=AsyncMock) as mock_update:
        mock_update.return_value = mock_partner

        response = await client.put(f"/api/v1/partners/{SAMPLE_UUID}", json={
            "name": "更新された建設株式会社",
        }, headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["data"]["name"] == "更新された建設株式会社"


# ============================================
# 4. Partner Contacts
# ============================================
async def test_add_contact(client: AsyncClient, auth_headers):
    mock_partner = make_mock_partner()
    mock_contact = make_mock_contact()

    with patch("src.api.partners.partner_service.get_partner_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_partner
        with patch("src.api.partners.partner_service.add_contact", new_callable=AsyncMock) as mock_add:
            mock_add.return_value = mock_contact

            response = await client.post(
                f"/api/v1/partners/{SAMPLE_UUID}/contacts",
                json={
                    "name": "佐藤花子",
                    "title": "部長",
                    "department": "工事部",
                    "email": "sato@example.com",
                    "phone": "03-1234-5678",
                    "is_primary": True,
                },
                headers=auth_headers,
            )

    assert response.status_code == 201
    data = response.json()
    assert data["data"]["name"] == "佐藤花子"
    assert data["data"]["email"] == "sato@example.com"


async def test_list_contacts(client: AsyncClient, auth_headers):
    mock_partner = make_mock_partner()
    mock_contact = make_mock_contact()

    with patch("src.api.partners.partner_service.get_partner_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_partner
        with patch("src.api.partners.partner_service.list_contacts", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = [mock_contact]

            response = await client.get(f"/api/v1/partners/{SAMPLE_UUID}/contacts", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 1
    assert data["data"][0]["name"] == "佐藤花子"


# ============================================
# 5. Contract CRUD
# ============================================
async def test_create_contract(client: AsyncClient, auth_headers):
    mock_contract = make_mock_contract()

    with _patch_partner_lookup("contracts"), patch(
        "src.api.contracts.contract_service.create_contract", new_callable=AsyncMock
    ) as mock_create:
        mock_create.return_value = mock_contract

        response = await client.post("/api/v1/partners/contracts", json={
            "partner_id": str(SAMPLE_UUID),
            "title": "試験契約",
            "contract_type": "subcontract",
            "amount": 1000000.0,
            "start_date": "2026-05-01",
        }, headers=auth_headers)

    assert response.status_code == 201
    data = response.json()
    assert data["data"]["title"] == "試験契約"
    assert data["data"]["status"] == "active"


async def test_list_contracts(client: AsyncClient, auth_headers):
    mock_contract = make_mock_contract()

    with patch("src.api.contracts.contract_service.list_contracts", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = ([mock_contract], 1)

        response = await client.get("/api/v1/partners/contracts", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 1
    assert data["meta"]["total"] == 1


async def test_get_contract(client: AsyncClient, auth_headers):
    mock_contract = make_mock_contract()

    with patch("src.api.contracts.contract_service.get_contract_by_id", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_contract

        response = await client.get(f"/api/v1/partners/contracts/{SAMPLE_UUID}", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["data"]["id"] == str(SAMPLE_UUID)


async def test_sign_contract(client: AsyncClient, auth_headers):
    mock_contract = make_mock_contract()

    with patch("src.api.contracts.contract_service.sign_contract", new_callable=AsyncMock) as mock_sign:
        mock_sign.return_value = mock_contract

        response = await client.post(
            f"/api/v1/partners/contracts/{SAMPLE_UUID}/sign",
            json={
                "signed_by_our": str(uuid.UUID(TEST_USER_ID)),
                "signed_by_partner": "相手先代表者",
            },
            headers=auth_headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["data"]["status"] == "active"


# ============================================
# 6. Evaluation + Rating Auto-update
# ============================================
async def test_create_evaluation(client: AsyncClient, auth_headers):
    mock_evaluation = make_mock_evaluation()

    with _patch_partner_lookup("evaluations"), patch(
        "src.api.evaluations.evaluation_service.create_evaluation", new_callable=AsyncMock
    ) as mock_create:
        mock_create.return_value = mock_evaluation
        with patch("src.api.evaluations.evaluation_service.update_partner_rating", new_callable=AsyncMock) as mock_update:
            mock_update.return_value = None

            response = await client.post("/api/v1/partners/evaluations", json={
                "partner_id": str(SAMPLE_UUID),
                "overall_score": 4.5,
                "quality_score": 4.0,
                "safety_score": 5.0,
                "comment": "良い協力会社です",
            }, headers=auth_headers)

    assert response.status_code == 201
    data = response.json()
    assert data["data"]["overall_score"] == 4.5
    mock_update.assert_called_once()  # Rating auto-update called


async def test_get_partner_rating(client: AsyncClient, auth_headers):
    with _patch_partner_lookup("partners"), patch(
        "src.api.partners.evaluation_service.get_partner_rating", new_callable=AsyncMock
    ) as mock_rating:
        mock_rating.return_value = (4.5, 10)

        response = await client.get(f"/api/v1/partners/{SAMPLE_UUID}/rating", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["data"]["partner_id"] == str(SAMPLE_UUID)
    assert data["data"]["average_rating"] == 4.5
    assert data["data"]["evaluation_count"] == 10


# ============================================
# 7. Assignment Management
# ============================================
async def test_create_assignment(client: AsyncClient, auth_headers):
    mock_assignment = make_mock_assignment()

    with _patch_partner_lookup("assignments"), patch(
        "src.api.assignments.assignment_service.create_assignment", new_callable=AsyncMock
    ) as mock_create:
        mock_create.return_value = mock_assignment

        response = await client.post("/api/v1/partners/assignments", json={
            "partner_id": str(SAMPLE_UUID),
            "project_id": "44444444-4444-4444-4444-444444444444",
            "role": "元請け",
            "scope_of_work": "土木工事一式",
        }, headers=auth_headers)

    assert response.status_code == 201
    data = response.json()
    assert data["data"]["role"] == "元請け"
    assert data["data"]["status"] == "active"


async def test_list_assignments(client: AsyncClient, auth_headers):
    mock_assignment = make_mock_assignment()

    with patch("src.api.assignments.assignment_service.list_assignments", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = ([mock_assignment], 1)

        response = await client.get("/api/v1/partners/assignments", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 1


async def test_get_project_assignments(client: AsyncClient, auth_headers):
    mock_assignment = make_mock_assignment()
    project_id = "44444444-4444-4444-4444-444444444444"

    with patch("src.api.assignments.assignment_service.get_project_assignments", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = ([mock_assignment], 1)

        response = await client.get(f"/api/v1/projects/{project_id}/assignments", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 1
    assert data["data"][0]["project_id"] == project_id


# ============================================
# 8. Partner Contracts (nested route)
# ============================================
async def test_get_partner_contracts(client: AsyncClient, auth_headers):
    mock_contract = make_mock_contract()

    with _patch_partner_lookup("partners"), patch(
        "src.api.partners.contract_service.list_contracts_for_partner", new_callable=AsyncMock
    ) as mock_list:
        mock_list.return_value = ([mock_contract], 1)

        response = await client.get(f"/api/v1/partners/{SAMPLE_UUID}/contracts", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data["data"]) == 1
    assert data["data"][0]["partner_id"] == str(SAMPLE_UUID)
