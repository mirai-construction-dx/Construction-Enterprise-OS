#!/usr/bin/env python3
"""Restore prior Docker limits from the apply record; default is dry-run.

Only exact container IDs, names and ceos-stg project labels are accepted.
Never recreate containers or read secrets. A replaced container must be handled
through its Compose declaration instead. Zero-valued unlimited baselines cannot
be safely restored with docker update here; those require reviewed Compose
recreation. Dry-run checks identities only, not restoration feasibility.
"""
import argparse
import json
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('record', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    record = json.loads(args.record.read_text())
    if record.get('mode') != 'apply':
        raise SystemExit('Only an apply record can be restored')
    plan = record['plan']
    if not isinstance(plan, list) or not plan:
        raise SystemExit('Invalid/empty restoration plan')
    names = [item['name'] for item in plan]
    attempted = record.get('attempted', record.get('applied', []))
    if len(set(names)) != len(names) or not set(attempted).issubset(names):
        raise SystemExit('Duplicate/unknown restoration targets')
    validated = []
    for item in plan:
        if item['name'] not in attempted:
            continue
        data = json.loads(subprocess.check_output(['docker', 'inspect', item['id']], text=True))[0]
        if (data['Name'].lstrip('/') != item['name'] or
                data['Config']['Labels'].get('com.docker.compose.project') != 'ceos-stg' or
                data['Config']['Labels'].get('com.docker.compose.service') != item['service'] or
                data['Config']['Labels'].get('com.docker.compose.project.working_dir') != str(Path(__file__).resolve().parents[2]) or
                item['name'] != f"ceos-stg-{item['service']}"):
            raise SystemExit('Container identity mismatch')
        host = data['HostConfig']
        expected = {'Memory': item['memory'], 'NanoCpus': int(item['cpus'] * 1e9), 'MemorySwap': 2 * item['memory']}
        if any(host[key] != expected[key] for key in expected):
            raise SystemExit(f"Runtime drift for {item['name']}; refuse to overwrite later changes")
        validated.append(item)
    if args.apply and any(item['old']['Memory'] == 0 or item['old']['NanoCpus'] == 0 or item['old']['MemorySwap'] == 0 for item in validated):
        raise SystemExit('Unlimited/zero baseline restoration via update is unverified. No changes made. Use reviewed staging Compose recreation; do not bypass credential gates.')
    for item in validated:
        old = item['old']
        command = ['docker', 'update', '--memory', str(old['Memory']),
                   '--memory-swap', str(old['MemorySwap']),
                   '--cpus', str(old['NanoCpus'] / 1e9), item['id']]
        print(f"Restore {item['name']}: {old}")
        if args.apply:
            subprocess.run(command, check=True)
            current = json.loads(subprocess.check_output(['docker', 'inspect', item['id']], text=True))[0]['HostConfig']
            if any(current[key] != old[key] for key in ('Memory', 'NanoCpus', 'MemorySwap')):
                raise SystemExit(f"Restoration mismatch for {item['name']}; inspect limits and use reviewed staging Compose recreation")
    print(f"{'Restored' if args.apply else 'Validated restoration for'} {len(validated)} staging containers")


if __name__ == '__main__':
    main()
