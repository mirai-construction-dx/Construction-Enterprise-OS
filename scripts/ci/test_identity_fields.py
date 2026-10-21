"""`scripts/ci/check_identity_fields.py` のオフライン回帰テスト。

検出器が「空回りして緑」にならないことを、合成スキーマで確認する。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("check_identity_fields.py")


def run_checker(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )


class IdentityFieldGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.schemas = self.root / "services" / "demo" / "src" / "schemas"
        self.schemas.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_schema(self, body: str) -> None:
        (self.schemas / "models.py").write_text(textwrap.dedent(body), encoding="utf-8")

    def test_clean_request_model_passes(self) -> None:
        self.write_schema(
            """
            class WidgetCreate:
                name: str
            """
        )
        result = run_checker(self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK:", result.stdout)

    def test_created_by_in_request_model_fails(self) -> None:
        self.write_schema(
            """
            class WidgetCreate:
                name: str
                created_by: str | None = None
            """
        )
        result = run_checker(self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("demo:WidgetCreate.created_by", result.stderr)

    def test_issued_by_in_request_model_fails(self) -> None:
        self.write_schema(
            """
            class CommandSendRequest:
                command: str
                issued_by: str
            """
        )
        result = run_checker(self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("demo:CommandSendRequest.issued_by", result.stderr)

    def test_response_model_is_not_flagged(self) -> None:
        self.write_schema(
            """
            class WidgetResponse:
                created_by: str
                issued_by: str
            """
        )
        result = run_checker(self.root)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_services_directory_fails(self) -> None:
        empty = self.root / "empty"
        empty.mkdir()
        result = run_checker(empty)
        self.assertEqual(result.returncode, 1)
        self.assertIn("services ディレクトリが無い", result.stderr)


if __name__ == "__main__":
    unittest.main()
