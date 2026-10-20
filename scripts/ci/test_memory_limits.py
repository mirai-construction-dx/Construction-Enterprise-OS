#!/usr/bin/env python3
"""Offline regressions for static resource guards; no Docker/DB/network calls."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

CI = Path(__file__).resolve().parent
sys.path.insert(0, str(CI))
import check_memory_limits as limits

spec = importlib.util.spec_from_file_location(
    "resource_staging_guards", CI.parent / "stg" / "check_staging_guards.py"
)
guards = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guards)


def service(memory="768M", cpus="1.0"):
    return {"deploy": {"resources": {"limits": {"memory": memory, "cpus": cpus}}}}


class ResourceLimitsTests(unittest.TestCase):
    def test_memory_bytes_and_units(self):
        for raw, expected in ((1048576, 1), ("1048576", 1), ("1048576b", 1),
                              ("1024kb", 1), ("1M", 1), ("1GB", 1024),
                              ("${LIMIT:-768M}", 768)):
            with self.subTest(raw=raw):
                self.assertEqual(limits.parse_memory(raw), expected)

    def test_reject_invalid_memory(self):
        for raw in (0, "0M", -1, "-1M", float("nan"), float("inf"),
                    "NaN", "inf", True, None, [], {}, "1TB", "${LIMIT}",
                    "9" * 400 + "G"):
            with self.subTest(raw=raw):
                self.assertIsNone(limits.parse_memory(raw))

    def test_reject_invalid_cpu(self):
        for raw in (0, "0", -1, "-0.5", "nan", "NaN", "inf", "-inf",
                    float("nan"), float("inf"), True, None, [], {}, "1e999"):
            with self.subTest(raw=raw):
                self.assertIsNone(limits.parse_cpus(raw))
        self.assertEqual(limits.parse_cpus("${CPU:-0.5}"), 0.5)

    def test_valid_policy_and_boundaries(self):
        self.assertEqual(limits.check_compose(limits.BASE, "test", {"s": service("4G", 4)}), [])
        self.assertEqual(limits.check_compose(limits.BASE, "test", {"s": service(1048576, 0.5)}), [])
        self.assertTrue(limits.check_compose(limits.BASE, "test", {"s": service("4097M", 4.1)}))

    def test_both_forms_supported_but_deploy_is_policy(self):
        failures = limits.check_compose(limits.BASE, "test", {"s": {"mem_limit": "768M", "cpus": 1}})
        self.assertTrue(failures)
        self.assertIn("サポート", failures[0])
        self.assertNotIn("実行時に反映されない", failures[0])
        body = service()
        body.update(mem_limit="768M", cpus=1)
        self.assertEqual(limits.check_compose(limits.BASE, "test", {"s": body}), [])
        body["mem_limit"] = "1G"
        self.assertTrue(limits.check_compose(limits.BASE, "test", {"s": body}))

    def test_empty_and_invalid_structures_fail_without_crashing(self):
        for services in (None, [], "services", {}, {"s": None}, {"s": []},
                         {1: service()}, {"s": {"deploy": []}},
                         {"s": {"deploy": None}},
                         {"s": {"deploy": {"resources": "bad"}}},
                         {"s": {"deploy": {"resources": {"limits": [1]}}}}):
            with self.subTest(services=services):
                self.assertTrue(limits.check_compose(limits.BASE, "test", services))
        self.assertTrue(limits.negative_control({}))
        self.assertEqual(limits.negative_control({"s": service()}), [])

    def test_zero_and_nonfinite_fail_checks(self):
        for memory, cpu in (("0M", 1), ("1M", 0), ("1M", "nan"), ("1M", "inf")):
            with self.subTest(memory=memory, cpu=cpu):
                self.assertTrue(limits.check_compose(limits.BASE, "test", {"s": service(memory, cpu)}))

    def test_main_handles_malformed_or_empty_documents(self):
        for text in ("", "[]", "services: {}", "services: []", "services: ["):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as directory:
                base, stg = Path(directory) / "base.yml", Path(directory) / "stg.yml"
                base.write_text(text)
                stg.write_text(yaml.safe_dump({"services": {"s": service()}}))
                with patch.object(limits, "BASE", base), patch.object(limits, "STG", stg), \
                        contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(limits.main(), 1)

    def test_main_detects_staging_mismatch_and_empty_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            base, stg = Path(directory) / "base.yml", Path(directory) / "stg.yml"
            base.write_text(yaml.safe_dump({"services": {"s": service()}}))
            for doc in ({"services": {"s": service("1G")}}, {"services": {}}):
                stg.write_text(yaml.safe_dump(doc))
                with patch.object(limits, "BASE", base), patch.object(limits, "STG", stg), \
                        contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(limits.main(), 1)

    def test_g14_reuses_value_and_structure_validation(self):
        for doc, status in (({"services": {"s": service()}}, "PASS"),
                            ({"services": {"s": service(cpus="nan")}}, "FAIL"),
                            ({"services": {"s": {"deploy": []}}}, "FAIL"),
                            ({"services": {}}, "FAIL"), ([], "FAIL")):
            with self.subTest(doc=doc):
                guards.results.clear()
                guards.check_resource_limits(doc)
                self.assertEqual(guards.results[0][1], status)

    def test_staging_main_calls_g14(self):
        # All other checks are mocked: this tests wiring only, never DB/network.
        names = ("check_compose_in_sync", "check_loopback_only", "check_environment",
                 "check_no_dev_secrets", "check_database_target", "check_replaced_services_absent",
                 "check_service_guards", "check_no_mutable_tags", "check_restart_policy",
                 "check_static_ip_and_hosts", "check_drill_records", "check_api_tunnel_consistency",
                 "check_dev_not_polluted")
        with contextlib.ExitStack() as stack:
            for name in names:
                stack.enter_context(patch.object(guards, name))
            stack.enter_context(patch.object(guards, "load_stg", return_value={"services": {"s": service()}}))
            called = stack.enter_context(patch.object(guards, "check_resource_limits", wraps=guards.check_resource_limits))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            self.assertEqual(guards.main(), 0)
            called.assert_called_once()
            self.assertTrue(any(check.startswith("G-14") for check, _, _ in guards.results))


if __name__ == "__main__":
    unittest.main()
