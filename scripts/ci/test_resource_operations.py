"""Offline safety regressions: no Docker daemon or credentials accessed."""
import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f'scripts/stg/{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


apply = load('apply_resource_limits')
restore = load('restore_resource_limits')


def container(root, memory=0, cpus=0, swap=0):
    return {'Name': '/ceos-stg-auth', 'Config': {'Labels': {
        'com.docker.compose.project': 'ceos-stg', 'com.docker.compose.service': 'auth',
        'com.docker.compose.project.working_dir': str(root)}},
        'HostConfig': {'Memory': memory, 'NanoCpus': cpus, 'MemorySwap': swap}}


class OperationsTests(unittest.TestCase):
    def run_apply(self, root, docker, target):
        with patch.object(apply, 'ROOT', root), patch.object(apply, 'docker', side_effect=docker), patch('sys.argv', ['apply', '--apply', '--record', str(target)]), contextlib.redirect_stdout(io.StringIO()):
            apply.main()

    def test_attempt_recorded_before_update_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'docker-compose.stg.yml').write_text('services:\n  auth:\n    deploy:\n      resources:\n        limits:\n          memory: 768M\n          cpus: 1\n')
            target = root / 'record.json'
            def docker(*args):
                if args[0] == 'ps':
                    return 'synthetic-id\n'
                if args[0] == 'inspect':
                    return json.dumps([container(root)])
                self.assertEqual(json.loads(target.read_text())['attempted'], ['ceos-stg-auth'])
                raise subprocess.CalledProcessError(1, 'synthetic update')
            with self.assertRaises(subprocess.CalledProcessError):
                self.run_apply(root, docker, target)
            record = json.loads(target.read_text())
            self.assertEqual(record['applied'], [])
            self.assertEqual(record['attempted'], ['ceos-stg-auth'])

    def test_wrong_workdir_never_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'docker-compose.stg.yml').write_text('services:\n  auth:\n    deploy:\n      resources:\n        limits:\n          memory: 768M\n          cpus: 1\n')
            calls = []
            def docker(*args):
                calls.append(args[0])
                return 'synthetic-id' if args[0] == 'ps' else json.dumps([container('/another-repo')])
            with self.assertRaises(SystemExit):
                self.run_apply(root, docker, root / 'record.json')
            self.assertNotIn('update', calls)

    def test_atomic_write_failure_preserves_previous_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'record.json'
            path.write_text('{"baseline": true}')
            with patch.object(apply.os, 'replace', side_effect=OSError('synthetic full disk')):
                with self.assertRaises(OSError):
                    apply.save_record(path, {'baseline': False})
            self.assertTrue(json.loads(path.read_text())['baseline'])

    def run_restore(self, old, drift=False):
        memory = 805306368
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'record.json'
            path.write_text(json.dumps({'mode': 'apply', 'applied': [], 'attempted': ['ceos-stg-auth'], 'plan': [{'id': 'synthetic-id', 'name': 'ceos-stg-auth', 'service': 'auth', 'old': old, 'memory': memory, 'cpus': 1}]}))
            data = container(ROOT, memory + int(drift), 1000000000, memory * 2)
            with patch.object(restore.subprocess, 'check_output', return_value=json.dumps([data])), patch.object(restore.subprocess, 'run') as update, patch('sys.argv', ['restore', str(path), '--apply']), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    restore.main()
                update.assert_not_called()

    def test_zero_baseline_refused_before_mutation(self):
        self.run_restore({'Memory': 0, 'NanoCpus': 0, 'MemorySwap': 0})

    def test_drift_refused_before_mutation(self):
        self.run_restore({'Memory': 268435456, 'NanoCpus': 500000000, 'MemorySwap': 536870912}, drift=True)


if __name__ == '__main__':
    unittest.main()
