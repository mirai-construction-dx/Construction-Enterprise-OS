"""Isolated synthetic fixtures; no real home, credentials, Git, network or DB."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Patch home before import so even module constants never consult the real home.
with patch.object(Path, "home", return_value=Path("/synthetic-unused-home")):
    spec = importlib.util.spec_from_file_location("secrets_hygiene", Path(__file__).with_name("check_secrets_hygiene.py"))
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)


def response(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout, "synthetic diagnostic")


def ignore_response(pattern="*.env", source=".gitignore", paths=None):
    paths = guard.IGNORE_PROBES if paths is None else paths
    return response("".join(f"{source}\0{1}\0{pattern}\0{p}\0" for p in paths))


class HygieneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.compose = self.root / "compose.yml"
        self.compose.write_text("services:\n  app:\n    environment:\n      API_TOKEN: '${TOKEN}'\n")
        (self.root / ".gitignore").write_text("*.env\n.env.*\n")
        self.home = self.root / "synthetic-home"
        self.config = self.home / ".config" / "ceos"
        for name, value in (
            ("ROOT", self.root), ("COMPOSES", (self.compose,)),
            ("CONFIG_DIR", self.config), ("CONFIG_FILE", self.config / "stg.env"),
        ):
            p = patch.object(guard, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(guard.subprocess, "run", side_effect=AssertionError("unmocked subprocess prohibited"))
        self.runner = p.start()
        self.addCleanup(p.stop)

    def test_git_failure_empty_and_malformed_fail_closed(self):
        for out in (response(code=128), response(), response("file.py"), response("../escape\0"), response("\0")):
            with self.subTest(out=out), patch.object(guard.subprocess, "run", return_value=out):
                with self.assertRaises(guard.InputError):
                    guard.tracked_files()
        with patch.object(guard.subprocess, "run", side_effect=OSError("synthetic")):
            with self.assertRaises(guard.InputError):
                guard.tracked_files()

    def test_tracked_names_use_nul(self):
        with patch.object(guard.subprocess, "run", return_value=response("with\nnewline.py\0")):
            self.assertEqual(guard.tracked_files(), ["with\nnewline.py"])

    def test_pem_marker_and_doc_examples(self):
        marker = "-----BEGIN " + "RSA PRIVATE KEY-----"
        (self.root / "bad.txt").write_text(marker + "\nMIIE\n")
        (self.root / "docs.md").write_text(f"Example `{marker}`; not a block\n")
        self.assertEqual(len(guard.check_pem(["bad.txt"])), 1)
        self.assertEqual(guard.check_pem(["docs.md"]), [])
        own_source = Path(__file__).with_name("check_secrets_hygiene.py").read_text()
        self.assertIsNone(guard.PEM_PATTERN.search(own_source))
        self.assertEqual(guard.negative_control(), [])

    def test_full_pem_in_docs_is_not_exempted(self):
        marker = "-----BEGIN " + "PRIVATE KEY-----"
        (self.root / "docs.md").write_text("```\n" + marker + "\nMIIE\n```\n")
        self.assertTrue(guard.check_pem(["docs.md"]))

    def test_credential_candidates_not_opened(self):
        for rel in (".env", ".env.stg", "stg.env", "backup.env.bak", "private.pem", "id_ed25519"):
            with self.subTest(rel=rel), patch.object(Path, "read_text", side_effect=AssertionError("credential opened")):
                self.assertTrue(guard.check_pem([rel]))

    def test_unreadable_missing_and_nonregular_tracked_fail(self):
        self.assertTrue(guard.check_pem(["missing.txt"]))
        (self.root / "directory").mkdir()
        (self.root / "link").symlink_to(self.compose)
        for rel in ("directory", "link"):
            self.assertTrue(guard.check_pem([rel]))
        with patch.object(Path, "read_text", side_effect=PermissionError("synthetic")):
            self.assertTrue(guard.check_pem(["compose.yml"]))

    def test_compose_environment_list_checked(self):
        self.compose.write_text("services:\n  app:\n    environment:\n      - API_TOKEN=synthetic-literal\n      - PASSWORD\n")
        failures = guard.check_compose_values()
        self.assertEqual(len(failures), 1)
        self.assertNotIn("synthetic-literal", failures[0])

    def test_allowed_references_and_placeholder_are_limited(self):
        for value in ("${TOKEN}", "${TOKEN:?required}", "${TOKEN:-default}", "${TOKEN-default}", "__TOKEN__", "change-me", ""):
            self.assertIsNotNone(guard.ALLOWED_VALUE.fullmatch(value))
        for value in ("${anything broken}", "${TOKEN}literal", "${}", "literal", "${TOKEN}\n"):
            self.assertIsNone(guard.ALLOWED_VALUE.fullmatch(value))

    def test_malformed_compose_shapes_fail(self):
        fixtures = (
            "", "[]", "services: null", "services: []", "services: {}",
            "services: {app: null}", "services: {app: []}",
            "services: {app: {environment: null}}", "services: {app: {environment: true}}",
            "services: {app: {environment: 42}}", "services: {app: {environment: [42]}}",
            "services: {app: {environment: [{TOKEN: synthetic}]}}",
            "services: {app: {environment: {TOKEN: []}}}",
            "services: {app: {environment: {TOKEN: {nested: synthetic}}}}",
            "services: {app: {environment: {42: synthetic}}}",
            "services: {app: {environment: ['TOKEN=a', 'TOKEN=b']}}",
            "services: {app: {environment: {TOKEN: synthetic, TOKEN: '${TOKEN}'}}}",
            "services: {app: {environment: ['=synthetic']}}", "services: [",
        )
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                self.compose.write_text(fixture)
                self.assertTrue(guard.check_compose_values())

    def test_yaml_merge_overrides_and_dotted_environment_names(self):
        self.compose.write_text(
            "x-base: &base\n  environment:\n    API_TOKEN: '${TOKEN}'\n"
            "services:\n  app:\n    <<: *base\n    environment:\n      xpack.security.enabled: 'false'\n      API_TOKEN: '${TOKEN:?required}'\n"
        )
        self.assertEqual(guard.check_compose_values(), [])

    def test_missing_and_unreadable_compose_fail_without_echoing_content(self):
        with patch.object(guard, "COMPOSES", (self.root / "missing.yml",)):
            self.assertTrue(guard.check_compose_values())
        with patch.object(Path, "read_text", side_effect=PermissionError("synthetic-private-value")):
            failures = guard.check_compose_values()
            self.assertTrue(failures)
            self.assertNotIn("synthetic-private-value", str(failures))

    def test_ignore_uses_semantics_not_comment_substrings(self):
        (self.root / ".gitignore").write_text("# .env *.env .env.*\n")
        with patch.object(guard.subprocess, "run", return_value=response(code=1)) as run:
            self.assertEqual(len(guard.check_gitignore([])), len(guard.IGNORE_PROBES))
            self.assertIn("--no-index", run.call_args.args[0])
            self.assertIn("--verbose", run.call_args.args[0])
        with patch.object(guard.subprocess, "run", return_value=ignore_response()):
            self.assertEqual(guard.check_gitignore([]), [])

    def test_ignore_negation_and_global_rules_do_not_pass(self):
        for result in (ignore_response(pattern="!.env"), ignore_response(source="/synthetic/global-ignore"), ignore_response(source=".git/info/exclude")):
            with patch.object(guard.subprocess, "run", return_value=result):
                self.assertTrue(guard.check_gitignore([]))

    def test_ignore_git_failure_missing_input_and_bad_output(self):
        for result in (response(code=128), response("bad\0"), response("bad")):
            with patch.object(guard.subprocess, "run", return_value=result):
                self.assertTrue(guard.check_gitignore([]))
        with patch.object(guard, "ROOT", self.root / "missing"):
            self.assertTrue(guard.check_gitignore([]))

    def test_permissions_absent_is_not_checked(self):
        failures, notes = guard.check_permissions()
        self.assertEqual(failures, [])
        self.assertEqual(len(notes), 2)
        self.assertTrue(all("NOT_CHECKED" in n for n in notes))

    def test_permissions_stat_only_and_bad_modes(self):
        self.config.mkdir(parents=True, mode=0o700)
        target = self.config / "stg.env"
        target.touch(mode=0o600)
        with patch.object(Path, "read_text", side_effect=AssertionError("credential read")):
            failures, notes = guard.check_permissions()
            self.assertEqual(failures, [])
            self.assertTrue(all("CHECKED" in n for n in notes))
            target.chmod(0o644)
            self.assertTrue(guard.check_permissions()[0])
            target.chmod(0o4600)
            self.assertTrue(guard.check_permissions()[0])

    def test_permissions_symlinks_and_stat_failure(self):
        self.config.mkdir(parents=True, mode=0o700)
        (self.config / "stg.env").symlink_to(self.compose)
        self.assertTrue(guard.check_permissions()[0])
        with patch.object(Path, "lstat", side_effect=PermissionError("synthetic")):
            self.assertTrue(guard.check_permissions()[0])

    def test_main_absent_host_has_no_blanket_safety_claim(self):
        with patch.object(guard, "tracked_files", return_value=["compose.yml"]), patch.object(guard.subprocess, "run", return_value=ignore_response()):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(guard.main(), 0)
            output = stdout.getvalue()
            self.assertIn("NOT_CHECKED", output)
            self.assertIn("限定検査", output)
            self.assertNotIn("秘密はリポジトリ外にあり", output)

    def test_main_git_failure_is_nonzero(self):
        with patch.object(guard.subprocess, "run", return_value=response(code=128)):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(guard.main(), 1)


if __name__ == "__main__":
    unittest.main()
