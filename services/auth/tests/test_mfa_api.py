"""MFA 有効化・バックアップコードの挙動テスト"""

import time
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pyotp
import pytest
from fastapi.testclient import TestClient

from src.api.auth import _create_mfa_session_token, _decode_mfa_session_token
from src.main import create_app
from src.middleware.auth_middleware import get_current_user
from src.models import MfaSessionUse
from src.models.base import get_db
from src.schemas import TokenData
from src.services.auth_service import hash_backup_code

SECRET = "JBSWY3DPEHPK3PXP"
# pyotp の既定タイムステップ（= settings.MFA_TOKEN_VALIDITY_SECONDS の既定値 30）
TOTP_INTERVAL_SECONDS = 30


def fresh_totp_code(secret: str = SECRET, margin: float = 5.0) -> str:
    """時刻窓の境界をまたいで検証に失敗しない TOTP コードを返す。

    #166: 実時刻から生成したコードは、生成と検証の間（CI では数〜数十 ms）に
    30 秒のタイムステップが切り替わると `verify_mfa_code` が False になる。
    残り時間が margin 秒未満なら次の窓まで待ってから生成する。
    """
    remaining = TOTP_INTERVAL_SECONDS - (time.time() % TOTP_INTERVAL_SECONDS)
    if remaining < margin:
        time.sleep(remaining + 0.05)
    return pyotp.TOTP(secret).now()


class FakeUser:
    def __init__(self, **overrides):
        self.id = overrides.get("id", uuid.uuid4())
        self.email = overrides.get("email", "user@example.com")
        self.organization_id = overrides.get("organization_id", uuid.uuid4())
        self.status = overrides.get("status", "active")
        self.hashed_password = overrides.get("hashed_password", "pw")
        self.mfa_secret = overrides.get("mfa_secret")
        self.mfa_enabled = overrides.get("mfa_enabled", False)
        self.mfa_backup_codes = overrides.get("mfa_backup_codes")
        self.login_attempts = overrides.get("login_attempts", 0)
        self.locked_until = overrides.get("locked_until")


@pytest.fixture(autouse=True)
def _stub_password_check(monkeypatch):
    monkeypatch.setattr(
        "src.api.auth.verify_password", lambda plain, hashed: plain == hashed
    )


class _Result:
    def __init__(self, user):
        self._user = user

    def scalar_one_or_none(self):
        return self._user

    def scalar(self):
        return 0

    def scalars(self):
        return self

    def all(self):
        return []

    def first(self):
        return None


def _client(user):
    app = create_app()
    db = AsyncMock()

    async def mock_execute(*args, **kwargs):
        return _Result(user)

    db.execute = mock_execute
    db.get = AsyncMock(return_value=None)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.close = AsyncMock()

    async def mock_get_db():
        yield db

    async def mock_get_current_user():
        return TokenData(sub=str(user.id), type="user", roles=["admin"])

    app.dependency_overrides[get_db] = mock_get_db
    app.dependency_overrides[get_current_user] = mock_get_current_user
    return TestClient(app), db


def test_mfa_activate_requires_auth():
    app = create_app()
    db = AsyncMock()

    async def mock_get_db():
        yield db

    app.dependency_overrides[get_db] = mock_get_db
    client = TestClient(app)
    res = client.post("/api/v1/auth/mfa/activate", json={"code": "123456"})
    assert res.status_code == 401


def test_mfa_activate_enables_mfa():
    user = FakeUser(mfa_secret=SECRET, mfa_enabled=False)
    client, _ = _client(user)

    code = fresh_totp_code()
    res = client.post("/api/v1/auth/mfa/activate", json={"code": code})

    assert res.status_code == 200
    assert res.json()["data"]["message"] == "MFAを有効化しました。"
    assert user.mfa_enabled is True


def test_mfa_activate_rejects_invalid_code():
    user = FakeUser(mfa_secret=SECRET, mfa_enabled=False)
    client, _ = _client(user)

    res = client.post("/api/v1/auth/mfa/activate", json={"code": "000000"})

    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "INVALID_MFA_CODE"
    assert user.mfa_enabled is False


def test_mfa_activate_requires_prior_setup():
    user = FakeUser(mfa_secret=None, mfa_enabled=False)
    client, _ = _client(user)

    res = client.post("/api/v1/auth/mfa/activate", json={"code": "123456"})

    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "MFA_NOT_SETUP"


def test_mfa_setup_rejected_when_already_enabled():
    user = FakeUser(mfa_secret=SECRET, mfa_enabled=True)
    client, _ = _client(user)

    res = client.post("/api/v1/auth/mfa/setup", json={"password": "pw"})

    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "MFA_ALREADY_ENABLED"


def test_mfa_setup_rejects_wrong_password():
    user = FakeUser(mfa_secret=None, mfa_enabled=False)
    client, _ = _client(user)

    res = client.post("/api/v1/auth/mfa/setup", json={"password": "wrong"})

    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "WRONG_PASSWORD"


def test_mfa_setup_persists_hashed_backup_codes():
    user = FakeUser(mfa_secret=None, mfa_enabled=False)
    client, _ = _client(user)

    res = client.post("/api/v1/auth/mfa/setup", json={"password": "pw"})

    assert res.status_code == 200
    plain_codes = res.json()["data"]["backup_codes"]
    assert len(plain_codes) == 10
    assert all(len(code) == 16 for code in plain_codes)
    assert user.mfa_backup_codes is not None
    assert len(user.mfa_backup_codes) == 10
    assert all(code not in user.mfa_backup_codes for code in plain_codes)
    assert user.mfa_backup_codes == [hash_backup_code(c) for c in plain_codes]


def _session_token(user):
    return _create_mfa_session_token(str(user.id), user.email)


def test_mfa_verify_refuses_when_not_enabled():
    user = FakeUser(mfa_secret=SECRET, mfa_enabled=False)
    client, _ = _client(user)

    res = client.post(
        "/api/v1/auth/mfa/verify",
        json={"session_token": _session_token(user), "code": "123456"},
    )

    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "MFA_UNAVAILABLE"


def test_mfa_verify_consumes_backup_code():
    code = "a1b2c3d4e5f60708"
    user = FakeUser(
        mfa_secret=SECRET, mfa_enabled=True, mfa_backup_codes=[hash_backup_code(code)]
    )
    client, _ = _client(user)

    res = client.post(
        "/api/v1/auth/mfa/verify",
        json={"session_token": _session_token(user), "code": code},
    )

    assert res.status_code == 200
    assert res.json()["success"] is True
    assert user.mfa_backup_codes == []


def test_mfa_verify_rejects_replayed_backup_code():
    code = "0011223344556677"
    user = FakeUser(
        mfa_secret=SECRET, mfa_enabled=True, mfa_backup_codes=[hash_backup_code(code)]
    )
    client, _ = _client(user)

    first = client.post(
        "/api/v1/auth/mfa/verify",
        json={"session_token": _session_token(user), "code": code},
    )
    second = client.post(
        "/api/v1/auth/mfa/verify",
        json={"session_token": _session_token(user), "code": code},
    )

    assert first.json()["success"] is True
    assert second.status_code == 200
    assert second.json()["success"] is False


def test_mfa_verify_locked_account_is_rejected():
    user = FakeUser(
        mfa_secret=SECRET,
        mfa_enabled=True,
        locked_until=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    client, _ = _client(user)

    res = client.post(
        "/api/v1/auth/mfa/verify",
        json={"session_token": _session_token(user), "code": "123456"},
    )

    assert res.status_code == 429
    assert res.json()["detail"]["code"] == "ACCOUNT_LOCKED"


def test_mfa_verify_counts_failed_attempts():
    user = FakeUser(mfa_secret=SECRET, mfa_enabled=True, mfa_backup_codes=[])
    client, _ = _client(user)

    res = client.post(
        "/api/v1/auth/mfa/verify",
        json={"session_token": _session_token(user), "code": "000000"},
    )

    assert res.status_code == 200
    assert res.json()["success"] is False
    assert user.login_attempts == 1


@pytest.fixture
def consumed_session(monkeypatch):
    """消費済み MFA セッションの状態をテスト内で明示的に組み立てる。

    #166: 以前は実時刻の TOTP コードに依存していたため、30 秒の時刻窓をまたぐ
    （生成直後にタイムステップが切り替わる）と `verify_mfa_code` が False になり、
    期待する 400 MFA_SESSION_USED ではなく 200 INVALID_MFA_CODE が返るフレークがあった。
    このテストの関心は「消費済み jti の拒否」だけなので、コード検証は成功に固定し、
    消費済み状態は db.get の戻り値として明示的に与える（他テストとの共有状態は使わない）。
    """
    monkeypatch.setattr("src.api.auth.verify_mfa_code", lambda secret, code: True)
    user = FakeUser(mfa_secret=SECRET, mfa_enabled=True)
    client, db = _client(user)
    db.get = AsyncMock(return_value=object())
    return SimpleNamespace(client=client, db=db, user=user, token=_session_token(user))


def test_mfa_verify_rejects_consumed_session_token(consumed_session):
    session = consumed_session

    res = session.client.post(
        "/api/v1/auth/mfa/verify",
        json={"session_token": session.token, "code": "123456"},
    )

    assert res.status_code == 400
    assert res.json()["detail"]["code"] == "MFA_SESSION_USED"

    # 消費済み判定は、トークンに埋め込まれた jti を MfaSessionUse から引いて行われる
    payload = _decode_mfa_session_token(session.token)
    assert payload is not None
    session.db.get.assert_awaited_once()
    model, jti = session.db.get.await_args.args
    assert model is MfaSessionUse
    assert jti == payload["jti"]
