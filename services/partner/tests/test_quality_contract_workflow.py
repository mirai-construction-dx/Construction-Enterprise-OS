"""Q6(承認・証跡) / Q3(計算再現性) 契約締結・評価フローの品質テスト。

対象仮説:
  ② 契約 sign の署名者同定がトークン由来か(ボディ・クエリ由来でないか)
  ③ 一度署名済みの契約への再署名(重複・再実行・状態遷移)
  ④ 契約金額・評点・評価集計の丸めと再現性(0 件時の平均)
  ⑥ 評価の重複登録

方針:
  既存 tests/ と同じく create_app() + dependency_overrides + httpx ASGITransport。
  実 DB / 外部サービスへは接続しない。synthetic fixture のみ。

注: `@pytest.mark.xfail(strict=True)` は「未修正の欠陥」の証跡であり成功ではない。
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import UniqueConstraint

from src.api.evaluations import _evaluation_to_response
from src.config import get_settings
from src.main import create_app
from src.models import Evaluation
from src.models.base import get_db
from src.schemas import EvaluationCreate
from src.services import contract_service, evaluation_service, partner_service
from src.services.contract_service import ContractStateError

pytestmark = pytest.mark.anyio

UTC = timezone.utc
NOW = datetime(2026, 5, 24, tzinfo=UTC)

ORG_A = UUID("22222222-2222-2222-2222-222222222222")
ORG_B = UUID("55555555-5555-5555-5555-555555555555")
USER_A = UUID("11111111-1111-1111-1111-111111111111")
USER_B = UUID("66666666-6666-6666-6666-666666666666")
PARTNER_ID = UUID("33333333-3333-3333-3333-333333333333")
CONTRACT_ID = UUID("77777777-7777-7777-7777-777777777777")


def _token(sub: UUID = USER_A, org: UUID = ORG_A, roles: tuple[str, ...] = ("admin",)) -> dict:
    settings = get_settings()
    payload = {
        "sub": str(sub),
        "type": "user",
        "org": str(org),
        "roles": list(roles),
        "scopes": [],
    }
    token = jwt.encode(payload, settings.jwt_public_key, algorithm=settings.JWT_ALGORITHM)
    return {"Authorization": f"Bearer {token}"}


def _result_one(obj):
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    result.scalar.return_value = obj
    result.one_or_none.return_value = obj
    scalars = MagicMock()
    scalars.all.return_value = [] if obj is None else [obj]
    result.scalars.return_value = scalars
    return result


def _contract(**overrides) -> MagicMock:
    defaults = {
        "id": CONTRACT_ID,
        "organization_id": ORG_A,
        "partner_id": PARTNER_ID,
        "project_id": None,
        "contract_number": "CNT-2026-001",
        "title": "試験契約",
        "contract_type": "subcontract",
        "amount": Decimal("1000000.00"),
        "currency": "JPY",
        "start_date": date(2026, 5, 1),
        "end_date": date(2027, 3, 31),
        "status": "draft",
        "terms": None,
        "signed_by_our": None,
        "signed_by_partner": None,
        "signed_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    defaults.update(overrides)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _evaluation(**overrides) -> MagicMock:
    defaults = {
        "id": UUID("88888888-8888-8888-8888-888888888888"),
        "organization_id": ORG_A,
        "partner_id": PARTNER_ID,
        "project_id": None,
        "evaluator_id": USER_A,
        "overall_score": Decimal("4.5"),
        "quality_score": Decimal("4.0"),
        "safety_score": Decimal("5.0"),
        "schedule_score": Decimal("4.0"),
        "cost_score": Decimal("4.5"),
        "communication_score": Decimal("4.5"),
        "comment": "良い",
        "evaluation_period_start": date(2026, 1, 1),
        "evaluation_period_end": date(2026, 3, 31),
        "created_at": NOW,
    }
    defaults.update(overrides)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


@pytest_asyncio.fixture
async def api():
    app_ = create_app()
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.execute = AsyncMock(return_value=_result_one(None))

    async def override_get_db():
        yield session

    app_.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app_, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield SimpleNamespace(client=ac, session=session, app=app_)
    app_.dependency_overrides.clear()


SIGN_BODY = {"signed_by_our": str(USER_B), "signed_by_partner": "テスト商事株式会社"}


# ——— ② 署名者の同定 ———


class TestSignerIdentity:
    async def test_defect_sign_identity_is_not_token_derived(self, api):
        """署名者 signed_by_our は操作者(トークン sub)でなければならない。"""
        captured = {}

        async def _sign(db, contract_id, signed_by_our, signed_by_partner, organization_id=None):
            captured["signed_by_our"] = signed_by_our
            return _contract(
                status="active",
                signed_by_our=signed_by_our,
                signed_by_partner=signed_by_partner,
                signed_at=NOW,
            )

        with patch.object(contract_service, "sign_contract", _sign):
            response = await api.client.post(
                f"/api/v1/partners/contracts/{CONTRACT_ID}/sign",
                json=SIGN_BODY,
                headers=_token(sub=USER_A),
            )

        assert response.status_code == 200
        assert captured["signed_by_our"] == USER_A, (
            "ボディの signed_by_our がそのまま署名者として記録された"
        )

    async def test_sign_endpoint_requires_auth(self, api):
        response = await api.client.post(
            f"/api/v1/partners/contracts/{CONTRACT_ID}/sign", json=SIGN_BODY
        )
        assert response.status_code == 401


# ——— ③ 再署名・状態遷移 ———


class TestSignatureStateTransition:
    async def test_sign_sets_signature_and_timestamp(self):
        """未署名契約への署名は成功し、署名者・時刻が記録される(正常系の回帰)。"""
        contract = _contract(status="pending_approval")
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result_one(contract))

        result = await contract_service.sign_contract(
            db, CONTRACT_ID, USER_A, "テスト商事株式会社"
        )

        assert result.status == "active"
        assert result.signed_by_our == USER_A
        assert result.signed_by_partner == "テスト商事株式会社"
        assert result.signed_at is not None

    async def test_defect_resign_overwrites_previous_signature(self):
        """一度署名した契約は再署名できず、先行する署名証跡が保持されること。"""
        previous_signer = USER_B
        previous_signed_at = datetime(2026, 4, 1, tzinfo=UTC)
        contract = _contract(
            status="active",
            signed_by_our=previous_signer,
            signed_by_partner="先行商事",
            signed_at=previous_signed_at,
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result_one(contract))

        with pytest.raises(ContractStateError):
            await contract_service.sign_contract(db, CONTRACT_ID, USER_A, "後行商事")

        # 先行署名の証跡は保持される（否認不能性）
        assert contract.signed_by_our == previous_signer, "先行署名者が上書きされた"
        assert contract.signed_at == previous_signed_at, "先行署名時刻が上書きされた"

    async def test_defect_terminated_contract_can_be_signed(self):
        """終了済み(terminated)契約が署名で active に戻ってはならない。"""
        contract = _contract(status="terminated", signed_at=datetime(2026, 1, 1, tzinfo=UTC))
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result_one(contract))

        with pytest.raises(ContractStateError):
            await contract_service.sign_contract(db, CONTRACT_ID, USER_A, "テスト商事")

        # 拒否された契約は変更されない（終端状態のまま）
        assert contract.status == "terminated", "terminated 契約が active へ遷移した"

    async def test_defect_update_status_bypasses_signing(self, api):
        """署名を経ずに PUT で status=active にできないこと。"""
        contract = _contract(status="draft", signed_at=None)
        api.session.execute = AsyncMock(return_value=_result_one(contract))

        response = await api.client.put(
            f"/api/v1/partners/contracts/{CONTRACT_ID}",
            json={"status": "active"},
            headers=_token(),
        )

        assert response.status_code >= 400, (
            "署名なしで契約を active にできてしまう(status 迂回)"
        )


# ——— ④ 契約金額・評点の計算再現性 ———


class TestAmountValidation:
    async def test_create_contract_rejects_non_positive_amount(self, api):
        for amount in (0, -1, -1000000):
            response = await api.client.post(
                "/api/v1/partners/contracts",
                json={**SIGN_BODY, "partner_id": str(PARTNER_ID), "title": "x",
                      "contract_type": "subcontract", "amount": amount,
                      "start_date": "2026-05-01"},
                headers=_token(),
            )
            assert response.status_code == 422, f"amount={amount} が受理された"

    async def test_update_rejects_non_positive_amount(self, api):
        """[修正済 DEFECT-P-6] 契約金額は更新時も正値のみ許可される。"""
        contract = _contract(status="draft")
        api.session.execute = AsyncMock(return_value=_result_one(contract))

        for amount in (0, -1000000):
            response = await api.client.put(
                f"/api/v1/partners/contracts/{CONTRACT_ID}",
                json={"amount": amount},
                headers=_token(),
            )
            assert response.status_code == 422, f"amount={amount} が受理された"


class TestRatingAggregation:
    async def test_rating_rounds_deterministically_to_one_decimal(self):
        """同一入力は同一出力(決定性)。丸めは Python round(銀行丸め)である。"""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result_one((Decimal("4.25"), 2)))

        first = await evaluation_service.get_partner_rating(db, PARTNER_ID)
        second = await evaluation_service.get_partner_rating(db, PARTNER_ID)

        assert first == second
        # round(4.25, 1) は銀行丸めで 4.2。JIS の四捨五入なら 4.3 になる。
        assert first == (4.2, 2)

    async def test_rating_with_no_evaluations_returns_zero_and_count(self):
        db = AsyncMock()
        result = MagicMock()
        result.one_or_none.return_value = (None, 0)
        db.execute = AsyncMock(return_value=result)

        rating, count = await evaluation_service.get_partner_rating(db, PARTNER_ID)

        assert rating == 0.0
        assert count == 0

    async def test_rating_average_is_computed_over_all_rows(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_result_one((Decimal("3.75"), 4)))

        rating, count = await evaluation_service.get_partner_rating(db, PARTNER_ID)

        assert rating == 3.8  # round(3.75, 1) = 3.8 (銀行丸め)
        assert count == 4

    def test_zero_subscore_is_preserved_as_zero(self):
        """[修正済 DEFECT-P-7] 0 点は 0.0 として返る(null に潰さない)。

        API の EvaluationCreate は ge=1.0 のため通常は到達しないが、
        DB 直投入・移行データ・将来の下限変更で 0 点は起こりうる。
        """
        evaluation = _evaluation(quality_score=Decimal("0.0"))

        response = _evaluation_to_response(evaluation)

        assert response.quality_score == 0.0, "0 点が null に化けた"

    async def test_defect_rating_helpers_inconsistent_on_zero_average(self):
        """同じ「平均 0.0」に対し 2 つのヘルパが None / 0.0 を返し不一致。"""
        db = AsyncMock()
        result = MagicMock()
        result.scalar.return_value = 0.0
        result.one_or_none.return_value = (0.0, 3)
        db.execute = AsyncMock(return_value=result)

        partner_service_value = await partner_service.calculate_partner_rating(
            db, PARTNER_ID
        )
        evaluation_service_value, _ = await evaluation_service.get_partner_rating(
            db, PARTNER_ID
        )

        assert partner_service_value == evaluation_service_value


# ——— ⑥ 評価の重複登録 ———


class TestDuplicateEvaluation:
    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-P-9: evaluations に (partner_id, project_id, evaluator_id) の一意制約が無い",
    )
    def test_defect_evaluation_has_unique_constraint(self):
        """同一評価者・同一対象・同一案件の重複登録を DB で防ぐ制約が必要。"""
        unique_sets = [
            tuple(c.name for c in constraint.columns)
            for constraint in Evaluation.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        ]
        assert any(
            set(columns) >= {"partner_id", "evaluator_id"} for columns in unique_sets
        ), f"評価の一意制約が無い (existing unique sets: {unique_sets})"

    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-P-9: 同一内容の評価を重複登録でき、評点集計が汚染される",
    )
    async def test_defect_duplicate_evaluation_can_be_registered(self, api):
        """同一評価者・同一対象・同一期間の 2 回目の登録は拒否されるべき。"""
        payload = {
            "partner_id": str(PARTNER_ID),
            "overall_score": 4.5,
            "evaluation_period_start": "2026-01-01",
            "evaluation_period_end": "2026-03-31",
        }
        created = _evaluation()

        with (
            patch.object(
                evaluation_service, "create_evaluation", AsyncMock(return_value=created)
            ),
            patch.object(
                evaluation_service, "update_partner_rating", AsyncMock(return_value=None)
            ),
        ):
            first = await api.client.post(
                "/api/v1/partners/evaluations", json=payload, headers=_token()
            )
            second = await api.client.post(
                "/api/v1/partners/evaluations", json=payload, headers=_token()
            )

        assert first.status_code == 201
        assert second.status_code >= 400, "同一評価が重複登録できてしまう"

    def test_evaluation_scores_are_bounded_by_schema(self):
        """スキーマ側のスコア範囲(1.0-5.0)は正常に機能していること(回帰)。"""
        for bad in (0.0, 0.9, 5.1, 100.0, -1.0):
            with pytest.raises(ValueError):
                EvaluationCreate(partner_id=PARTNER_ID, overall_score=bad)
        ok = EvaluationCreate(partner_id=PARTNER_ID, overall_score=5.0)
        assert ok.overall_score == 5.0


# ——— マスタ値の検証 ———


class TestMasterValueValidation:
    @pytest.mark.xfail(
        strict=True,
        reason="DEFECT-P-10: company_type / status が許可リストで検証されない",
    )
    async def test_defect_company_type_and_status_not_validated(self, api):
        """company_type / status は定義済み許可リストに制限されるべき。"""
        created = MagicMock()
        created.id = PARTNER_ID
        created.organization_id = ORG_A
        created.name = "テスト建設株式会社"
        created.name_kana = None
        created.company_type = "__arbitrary__"
        created.tax_id = None
        created.address = None
        created.phone = None
        created.email = None
        created.website = None
        created.representative_name = None
        created.employee_count = None
        created.established_year = None
        created.specializations = None
        created.license_info = None
        created.insurance_info = None
        created.status = "__arbitrary__"
        created.rating = None
        created.registered_at = NOW
        created.updated_at = NOW

        with patch.object(
            partner_service, "create_partner", AsyncMock(return_value=created)
        ):
            response = await api.client.post(
                "/api/v1/partners",
                json={
                    "name": "テスト建設株式会社",
                    "company_type": "__arbitrary__",
                    "status": "__arbitrary__",
                },
                headers=_token(),
            )

        assert response.status_code == 422, "未定義の company_type/status が受理された"
