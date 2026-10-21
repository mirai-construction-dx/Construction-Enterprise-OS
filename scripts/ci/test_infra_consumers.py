"""Offline regression tests for static dependency review gate."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('inventory', Path(__file__).with_name('check_infra_consumers.py'))
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class InventoryTests(unittest.TestCase):
    def test_baseline(self):
        self.assertEqual(module.check(), [])

    def test_direct_import(self):
        imports, _ = module.inspect_source('import redis.asyncio as r\n')
        self.assertEqual(imports, {'redis'})

    def test_event_alias_call(self):
        imports, calls = module.inspect_source('from construction_enterprise_os_event_core.publisher import EventPublisher as P\np = P()\n')
        self.assertIn('construction_enterprise_os_event_core.publisher', imports)
        self.assertEqual(calls, {'EventPublisher': 1})

    def test_helper_alias_call(self):
        _, calls = module.inspect_source('from .events import publish_user_login as login\nlogin()\n')
        self.assertEqual(calls, {'publish_user_login': 1})

    def test_module_attribute_call(self):
        _, calls = module.inspect_source('import events\nevents.publish_user_created()\n')
        self.assertEqual(calls, {'publish_user_created': 1})

    def test_lazy_factory(self):
        _, calls = module.inspect_source('import construction_enterprise_os_event_core as ec\nec.get_publisher()\n')
        self.assertEqual(calls, {'get_publisher': 1})

    def test_added_removed_inventory(self):
        self.assertTrue(module.difference('test', {'new'}, {'old'}))

    def test_missing_roots_fail(self):
        with tempfile.TemporaryDirectory() as path:
            self.assertTrue(module.check(Path(path)))

    def test_invalid_source_fails(self):
        with self.assertRaises(SyntaxError):
            module.inspect_source('import (')


if __name__ == '__main__':
    unittest.main()
