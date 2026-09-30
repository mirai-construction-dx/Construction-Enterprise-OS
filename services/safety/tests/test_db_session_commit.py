"""Regression tests for get_db transaction handling (Issue #137)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models import base


def _fake_session_factory(session: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


def _session() -> MagicMock:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_get_db_commits_on_success():
    session = _session()
    with patch.object(base, "async_session", _fake_session_factory(session)):
        gen = base.get_db()
        assert await gen.__anext__() is session
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()
    session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_db_rolls_back_on_error():
    session = _session()
    with patch.object(base, "async_session", _fake_session_factory(session)):
        gen = base.get_db()
        await gen.__anext__()
        with pytest.raises(RuntimeError):
            await gen.athrow(RuntimeError("boom"))
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()
