#!/usr/bin/env python3
"""Review gate for changes to static infrastructure dependency declarations.

This is not a proof of runtime non-consumption. document uses MinIO at startup
and in upload/download APIs; Kibana connects to Elasticsearch. Python imports,
requirements and Compose startup dependencies do not prove network behaviour.
Kafka's event-core adapter exists; calls through that adapter are inventoried
below, including currently uncalled auth helper bodies. Dynamic imports/calls,
non-Python clients and general transitive reachability are outside this gate.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CLIENTS = {"redis", "aio_pika", "pika", "aiormq", "aiokafka", "kafka",
           "elasticsearch", "opensearchpy", "minio", "boto3", "botocore"}
INFRA = {"redis", "rabbitmq", "kafka", "elasticsearch", "kibana", "minio"}
EXPECTED_IMPORTS = {
    ("packages/event-core/construction_enterprise_os_event_core/__init__.py", "construction_enterprise_os_event_core.publisher"),
    ("packages/event-core/construction_enterprise_os_event_core/__init__.py", "construction_enterprise_os_event_core.subscriber"),
    ("services/document/src/services/storage_service.py", "boto3"),
    ("services/document/src/services/storage_service.py", "botocore"),
    ("packages/event-core/construction_enterprise_os_event_core/publisher.py", "aiokafka"),
    ("packages/event-core/construction_enterprise_os_event_core/subscriber.py", "aiokafka"),
    ("services/auth/src/events.py", "construction_enterprise_os_event_core.publisher"),
}
EXPECTED_DEPS = {
    "kibana": {"elasticsearch"}, "gateway": {"redis"}, "auth": {"redis"},
    "notification": {"rabbitmq", "redis"}, "document": {"minio"},
    "iot": {"kafka"}, "ai": {"redis"}, "bim": {"minio"},
    "analytics": {"elasticsearch"}, "vision": {"minio"},
    "workflow": {"rabbitmq"}, "automation": {"rabbitmq"},
    "autonomous": {"kafka"}, "mcp": {"redis"},
}
# Calls in auth helper definitions are inventoried, not asserted to be reachable.
EVENT_SYMBOLS = {"EventPublisher", "EventSubscriber", "get_publisher", "get_subscriber", "get_event_publisher",
                 "publish_user_created", "publish_user_login",
                 "publish_user_role_changed", "publish_user_deactivated"}
EXPECTED_CALLS = {
    ("packages/event-core/construction_enterprise_os_event_core/__init__.py", "EventPublisher", 1),
    ("packages/event-core/construction_enterprise_os_event_core/__init__.py", "EventSubscriber", 1),
    ("services/auth/src/events.py", "EventPublisher", 1),
    ("services/auth/src/events.py", "get_event_publisher", 4),
}
EXPECTED_REQUIREMENTS = {
    ("services/document/requirements.txt", "boto3"),
    ("packages/event-core/requirements.txt", "aiokafka"),
}
SKIP = {".venv", "node_modules", "__pycache__", "tests", ".mypy_cache"}


def inspect_source(text: str) -> tuple[set[str], dict[str, int]]:
    """Recognize direct clients and event-core imports, including aliases/calls."""
    tree = ast.parse(text)
    imports: set[str] = set()
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                if module.split('.')[0] in CLIENTS or module.startswith('construction_enterprise_os_event_core'):
                    imports.add(module if module.startswith('construction_enterprise_os_event_core') else module.split('.')[0])
                aliases[alias.asname or module.split('.')[0]] = module
        elif isinstance(node, ast.ImportFrom) and node.module:
            module = node.module
            if not node.level and (module.split('.')[0] in CLIENTS or module.endswith('event_core.publisher') or module.endswith('event_core.subscriber')):
                imports.add(module if 'event_core' in module else module.split('.')[0])
            for alias in node.names:
                aliases[alias.asname or alias.name] = alias.name
    calls: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            name = aliases.get(node.func.id, node.func.id).split('.')[-1]
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        else:
            continue
        if name in EVENT_SYMBOLS:
            calls[name] = calls.get(name, 0) + 1
    return imports, calls


def difference(label: str, actual: set, expected: set) -> list[str]:
    return ([f"{label}: added {item}" for item in sorted(actual - expected)] +
            [f"{label}: missing {item}" for item in sorted(expected - actual)])


def check(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    imports: set = set()
    calls: set = set()
    bases = sorted((root / 'services').glob('*/src')) + [root / 'packages']
    if len(bases) < 2 or not (root / 'packages/event-core').is_dir():
        errors.append('source roots/event-core missing')
    for base in bases:
        for path in sorted(base.rglob('*.py')):
            rel = path.relative_to(root)
            if SKIP.intersection(rel.parts):
                continue
            try:
                modules, counts = inspect_source(path.read_text(encoding='utf-8'))
                imports.update((str(rel), mod) for mod in modules)
                calls.update((str(rel), name, count) for name, count in counts.items())
            except (OSError, UnicodeError, SyntaxError) as exc:
                errors.append(f'{rel}: cannot parse: {exc}')
    errors += difference('imports', imports, EXPECTED_IMPORTS)
    errors += difference('event adapter calls', calls, EXPECTED_CALLS)
    for filename in ('docker-compose.yml', 'docker-compose.stg.yml'):
        try:
            data = yaml.safe_load((root / filename).read_text())
            services = data['services']
            if not isinstance(services, dict) or not services:
                raise ValueError('services must be nonempty mapping')
            deps = {}
            for name, body in services.items():
                raw = body.get('depends_on', {})
                if not isinstance(raw, (dict, list)):
                    raise ValueError(f'{name}: invalid depends_on')
                hit = set(raw) & INFRA
                if hit:
                    deps[name] = hit
            actual = {(name, dep) for name, vals in deps.items() for dep in vals}
            expected = {(name, dep) for name, vals in EXPECTED_DEPS.items() for dep in vals}
            errors += difference(filename, actual, expected)
        except (OSError, UnicodeError, yaml.YAMLError, KeyError, TypeError, AttributeError, ValueError) as exc:
            errors.append(f'{filename}: invalid input: {exc}')
    requirements = set()
    files = sorted((root / 'services').glob('*/requirements.txt')) + sorted((root / 'packages').glob('*/requirements.txt'))
    for path in files:
        try:
            for line in path.read_text().splitlines():
                match = re.match(r'^\s*([A-Za-z0-9_-]+)\s*(?:[<>=~!;\[]|$)', line)
                if match and match[1].lower().replace('-', '_') in CLIENTS:
                    requirements.add((str(path.relative_to(root)), match[1].lower().replace('-', '_')))
        except (OSError, UnicodeError) as exc:
            errors.append(f'{path.name}: cannot read: {exc}')
    errors += difference('requirements.txt client declarations', requirements, EXPECTED_REQUIREMENTS)
    return errors


def main() -> int:
    errors = check()
    for error in errors:
        print(f'FAIL: {error}', file=sys.stderr)
    if errors:
        return 1
    print('OK: static dependency inventory matches reviewed baseline. '
          'document→MinIO and Kibana→Elasticsearch are real dependencies; '
          'runtime reachability/network non-consumption is NOT verified. '
          'Dependency scan covers requirements.txt, not arbitrary packaging metadata.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
