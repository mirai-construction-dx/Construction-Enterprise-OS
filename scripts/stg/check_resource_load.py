#!/usr/bin/env python3
"""Bounded read-only staging health load; not business/ML capacity acceptance.

Uses Docker labels and loopback port declarations only, never credentials.
Samples kernel cgroup values via docker exec cat (no credentials/environment).
429 responses are load shedding, not successful health responses.
"""
import concurrent.futures
import json
import subprocess
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def probe(url):
    started = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            response.read()
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    except (OSError, TimeoutError):
        status = 'transport-error'
    return status, time.monotonic() - started


def main():
    ids = subprocess.check_output(['docker', 'ps', '-q', '--no-trunc', '--filter', 'label=com.docker.compose.project=ceos-stg'], text=True).split()
    if len(ids) != 32:
        raise SystemExit('Expected exactly 32 staging containers')
    report = {'scope': '20 requests per Python service /health at concurrency4; no authenticated business/ML validation', 'services': [], 'containers': []}
    failures = []
    for cid in ids:
        data = json.loads(subprocess.check_output(['docker', 'inspect', cid], text=True))[0]
        service = data['Config']['Labels']['com.docker.compose.service']
        if data['Name'] != f'/ceos-stg-{service}':
            raise SystemExit('Container name mismatch')
        cgroup = {}
        for key in ('memory.max', 'memory.swap.max', 'cpu.max'):
            result = subprocess.run(['docker', 'exec', cid, 'cat', f'/sys/fs/cgroup/{key}'], capture_output=True, text=True)
            cgroup[key] = result.stdout.strip() if result.returncode == 0 else 'NOT_CHECKED'
        expected = data['HostConfig']
        if cgroup['memory.max'] != str(expected['Memory']):
            failures.append(f'{service}: kernel memory limit mismatch/unreadable')
        if cgroup['memory.swap.max'] != str(expected['MemorySwap'] - expected['Memory']):
            failures.append(f'{service}: kernel swap limit mismatch/unreadable')
        cpu = cgroup['cpu.max'].split()
        if len(cpu) != 2 or cpu[0] == 'max' or abs(int(cpu[0]) / int(cpu[1]) - expected['NanoCpus'] / 1e9) > 0.001:
            failures.append(f'{service}: kernel CPU limit mismatch/unreadable')
        report['containers'].append({'service': service, 'cgroup': cgroup, 'health': data['State'].get('Health', {}).get('Status'), 'oom': data['State']['OOMKilled'], 'restart_count': data['RestartCount']})
        ports = data['NetworkSettings']['Ports'] or {}
        # Python services listen on 8000, gateway on 9000. Other protocols are not probed.
        exposed = ports.get('8000/tcp') or (ports.get('9000/tcp') if service == 'gateway' else None)
        if not exposed:
            continue
        if len(exposed) != 1 or exposed[0]['HostIp'] != '127.0.0.1':
            raise SystemExit('Refuse non-loopback/ambiguous binding')
        url = f"http://127.0.0.1:{exposed[0]['HostPort']}/health"
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(probe, [url] * 20))
        durations = sorted(value[1] for value in results)
        counts = Counter(str(value[0]) for value in results)
        report['services'].append({'service': service, 'statuses': dict(counts), 'p95_seconds': durations[18], 'max_seconds': durations[-1]})
        if counts.get('200') != 20:
            failures.append(f'{service}: not all 20 health requests succeeded')
    # Post-load readiness; do not assume initial inspect proves final health.
    for cid in ids:
        data = json.loads(subprocess.check_output(['docker', 'inspect', cid], text=True))[0]
        if data['State'].get('Health', {}).get('Status') != 'healthy' or data['State']['OOMKilled']:
            failures.append(f"{data['Name']}: unhealthy/OOM after load")
    report['failures'] = failures
    destination = ROOT / 'reports/staging/resource-service-load-20261014.json'
    if destination.exists():
        raise SystemExit('Refusing to overwrite previous load evidence')
    destination.write_text(json.dumps(report, indent=2) + '\n')
    print(f"services={len(report['services'])} requests={20 * len(report['services'])} containers={len(ids)} failures={len(failures)}")
    for failure in failures:
        print(f'FAIL: {failure}')
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
