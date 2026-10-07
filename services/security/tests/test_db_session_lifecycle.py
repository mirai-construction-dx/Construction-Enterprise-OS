"""get_db のトランザクション確定を守る回帰テスト。

症状:
    `get_db` に `commit()` が無いと、サービス層で `flush()` 済みの書き込みが
    `session.close()` 時に暗黙ロールバックされ、API は 201/200 を返すのに
    データが永続化されない（サイレントなデータ消失）。
期待:
    正常終了時は commit、例外時は rollback してから close されること。
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from src.models import base


class _FakeSession:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def commit(self) -> None:
        self._log.append("commit")

    async def rollback(self) -> None:
        self._log.append("rollback")

    async def close(self) -> None:
        self._log.append("close")


def _install(monkeypatch, log: list[str]):
    session = _FakeSession(log)

    @asynccontextmanager
    async def fake_session_factory():
        yield session

    monkeypatch.setattr(base, "async_session", fake_session_factory)
    return session


async def test_get_db_commits_on_success(monkeypatch):
    log: list[str] = []
    session = _install(monkeypatch, log)

    gen = base.get_db()
    assert await gen.__anext__() is session
    try:
        await gen.__anext__()
    except StopAsyncIteration:
        pass
    else:  # pragma: no cover - 生成器が終了しない異常
        raise AssertionError("get_db が終了しなかった")

    assert log == ["commit", "close"], f"正常終了時に commit されていない: {log}"


async def test_get_db_rolls_back_on_error(monkeypatch):
    log: list[str] = []
    _install(monkeypatch, log)

    gen = base.get_db()
    await gen.__anext__()
    try:
        await gen.athrow(RuntimeError("boom"))
    except RuntimeError:
        pass
    else:  # pragma: no cover - 例外が握り潰された異常
        raise AssertionError("例外が伝播しなかった")

    assert log == ["rollback", "close"], f"例外時に rollback されていない: {log}"
