#!/usr/bin/env python3
"""Apply candidate limits ONLY to existing ceos-stg labelled containers.

Default dry-run; --apply uses docker update without recreating containers or
reading credentials. Records prior limits for restoration. This does not change
Compose environment or rebuild images. Runtime overrides are lost if Compose
configuration changes. Acceptance is a bounded staging smoke, not capacity proof.
"""
import argparse
import importlib.util
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('limits', ROOT / 'scripts/ci/check_memory_limits.py')
limits = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(limits)


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True)


def save_record(path, record):
    # Keep previous complete JSON intact if a write is interrupted.
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w') as stream:
        json.dump(record, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--record', type=Path, required=True)
    args = parser.parse_args()
    if args.record.exists():
        raise SystemExit('Refusing to overwrite existing record')
    config = yaml.safe_load((ROOT / 'docker-compose.stg.yml').read_text())['services']
    errors = limits.check_compose(ROOT / 'docker-compose.stg.yml', 'stg', config)
    if errors:
        raise SystemExit('\n'.join(errors))
    ids = docker('ps', '-q', '--no-trunc', '--filter', 'label=com.docker.compose.project=ceos-stg').split()
    if len(ids) != len(config):
        raise SystemExit(f'Expected {len(config)} running containers, found {len(ids)}')
    plan = []
    for cid in ids:
        data = json.loads(docker('inspect', cid))[0]
        name = data['Name'].lstrip('/')
        labels = data['Config']['Labels']
        service = labels.get('com.docker.compose.service')
        if service not in config or name != f'ceos-stg-{service}':
            raise SystemExit(f'Identity mismatch: {name}')
        if labels.get('com.docker.compose.project.working_dir') != str(ROOT):
            raise SystemExit(f'Working directory mismatch: {name}')
        declared = limits.limits_of(config[service])
        memory = int(limits.parse_memory(declared['memory']) * 1024 * 1024)
        cpus = limits.parse_cpus(declared['cpus'])
        host = data['HostConfig']
        plan.append({'id': cid, 'name': name, 'service': service,
                     'old': {key: host[key] for key in ('Memory', 'NanoCpus', 'MemorySwap')},
                     'memory': memory, 'cpus': cpus})
    if len({p['service'] for p in plan}) != len(config):
        raise SystemExit('Duplicate/missing service identity')
    record = {'timestamp': datetime.now(timezone.utc).isoformat(), 'mode': 'apply' if args.apply else 'dry-run', 'scope': 'declared defaults; environment overrides not resolved', 'plan': plan, 'attempted': [], 'applied': []}
    args.record.parent.mkdir(parents=True, exist_ok=True)
    save_record(args.record, record)
    for entry in plan:
        print(f"{entry['name']}: memory={entry['memory']} cpus={entry['cpus']}")
        if args.apply:
            # Record attempted updates before changing state, including failures.
            record['attempted'].append(entry['name'])
            save_record(args.record, record)
            # Bound swap to twice RAM; no restart/secret access required.
            docker('update', '--memory', str(entry['memory']), '--memory-swap', str(2 * entry['memory']), '--cpus', str(entry['cpus']), entry['id'])
            now = json.loads(docker('inspect', entry['id']))[0]
            host = now['HostConfig']
            if host['Memory'] != entry['memory'] or host['NanoCpus'] != int(entry['cpus'] * 1e9) or host['MemorySwap'] != 2 * entry['memory']:
                raise SystemExit(f"Limits did not apply: {entry['name']}; use saved prior limits for restoration")
            record['applied'].append(entry['name'])
            save_record(args.record, record)
    print(f"{'Applied' if args.apply else 'Planned'} {len(plan)} staging containers; record={args.record}")


if __name__ == '__main__':
    main()
