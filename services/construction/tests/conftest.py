"""テスト共通設定"""

import pytest

# quality_helpers のフィクスチャを pytest へ登録する。
# テストモジュール側で import して引数に使うと F811（再定義）になるため、
# conftest 経由で自動検出させる。
from tests.quality_helpers import (  # noqa: F401
    app,
    client,
    client_no_auth,
    mock_db,
)


def pytest_configure(config):
    for plugin in ["pytest_flask"]:
        try:
            config.pluginmanager.set_blocked(plugin)
        except Exception:
            pass

    config.addinivalue_line("markers", "asyncio: mark test as async")


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"
