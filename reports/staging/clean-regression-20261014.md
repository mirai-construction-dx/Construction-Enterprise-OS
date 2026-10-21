# Clean service regression — 2026-10-14

## Result

**225 tests passed; all three test process exit codes were 0.** This is isolated unit/API regression evidence, not approval of the independent staging runtime apply.

| Service | Python venv creation | pinned pip install | pip freeze | pip check | redis presence check | pytest | Summary |
|---|---:|---:|---:|---:|---:|---:|---|
| auth | 0 | 0 | 0 | 0 | 0 | 0 | 108 passed, 3 warnings, 14.95 s |
| gateway | 0 | 0 | 0 | 0 | 0 | 0 | 91 passed, 1 warning, 3.12 s |
| notification | 0 | 0 | 0 | 0 | 0 | 0 | 26 passed, 1 warning, 4.12 s |

All three environments reported `redis importable: False`. Auth/gateway include the `types-redis` stub distribution, **not** the runtime Redis client. No package was added to mask a missing dependency.

## Isolation and reproducibility

- Interpreter: `/usr/bin/python3.12`, Python **3.12.3**, Linux. Three newly created venvs; no inherited system site packages.
- Dedicated scratch root: `/tmp/ceos-clean-regression-20261014-gypvhh`. Only service `src/`, `tests/`, pinned requirement lists and pytest configuration were copied. No credential files were read or copied; the source auth `.env` was deliberately excluded.
- CI inspected: [CI workflow](../../.github/workflows/ci.yml#L61-L77). Dependency command executed in each isolated service working directory: `venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt -r requirements-dev.txt`.
- Test processes received an allowlisted environment rather than inherited runtime variables: `ENVIRONMENT=test`, `DATABASE_URL=postgresql+asyncpg://synthetic:synthetic@127.0.0.1:1/synthetic`, `REDIS_URL=redis://127.0.0.1:1/0`, dedicated HOME/PATH/PYTHONPATH/COVERAGE_FILE, `PYTHONDONTWRITEBYTECODE=1` and `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`.
- Explicit plugins only: `pytest_asyncio.plugin`, `pytest_cov.plugin`, `anyio.pytest_plugin`, plus `pytest_mock` for notification. Flask disabled with `-p no:flask`.
- Equivalent pytest argument list: `tests/ --cov=src --cov-report=xml:coverage.xml -p no:flask`, with explicit plugin additions above. Coverage artifacts stayed in scratch, never in source directories.
- A temporary Python runner installed an audit hook rejecting `socket.connect`, `socket.getaddrinfo` and `socket.bind` before importing pytest. This prevented accidental live DB, upstream, SMTP or other socket access. Tests used their existing mocks/ASGI transports; no database/live-upstream checks were performed.
- Installs used the configured network policy path. No network denial occurred and no proxy bypass was attempted. Cached wheel artifacts were permitted; fresh environments do not mean empty download caches.
- Background jobs `bash-5012` (sequential install) and `bash-5014` (sequential tests) were collected, both outer process exit **0**; actual subprocess exit codes are shown above.

## CI/local-package limitation

The inspected CI installation step installs only the two requirement lists. Their comment mentions the shared auth middleware, but contains **no local-package requirement**. The local auth-core/event-core packages were therefore **not installed in this exact CI baseline**. Current tests pass without them, which does not validate the optional shared-auth startup branch or Kafka publisher integration. No local package sources, configuration, or Git state were modified. A supplemented local-package validation, if required, is a separate test variant rather than evidence that CI installed those packages.

## Warnings / scope limits

- All environments emit the unset `asyncio_default_fixture_loop_scope` deprecation warning before the pytest session summary.
- Starlette warns that its httpx TestClient use is deprecated in favor of httpx2.
- Auth also warns about Python crypt removal in 3.13 and an unawaited AsyncMock call in the transient DB retry test (`db.add(log)`). These warnings do not change pytest's exit 0, but should not be interpreted as resolved.
- Transitive versions are not fully pinned by the input files; the exact clean-environment resolutions are recorded below. No hashes/full dependency lock were asserted.
- This run covers the copied source snapshot at installation start, not subsequent concurrent changes. No Ruff/MyPy, migrations/DDL check, live integration, Docker build, staging apply, credential validation or production readiness claim is made.
- The filesystem MCP multi-read was initially refused because that server exposes only the DSH checkout. Lead confirmed using the authorized workspace read tool for the requested CEOS files; no protected credential path or network restriction was bypassed.

## Dependency evidence

The following pip-freeze outputs contain package names/versions only (no credentials or credential-bearing URLs). All pip-freeze and pip-check commands exited 0. Local package distributions are absent by design in the CI baseline.

### auth

```text
alembic==1.13.2
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.15.1
asgiref==3.12.1
asyncpg==0.29.0
bcrypt==3.2.2
certifi==2026.7.22
cffi==2.1.1
click==8.5.0
coverage==7.16.2
cryptography==50.0.2
Deprecated==3.0.0
dnspython==2.9.0
email_validator==2.2.0
factory_boy==3.3.1
Faker==30.1.0
fastapi==0.141.1
greenlet==3.5.6
h11==0.16.0
httpcore==1.0.9
httptools==0.9.0
httpx==0.27.2
idna==3.20
importlib_metadata==8.4.0
iniconfig==2.3.1
Mako==1.4.3
MarkupSafe==3.0.4
mypy==1.11.2
mypy_extensions==1.1.0
opentelemetry-api==1.27.0
opentelemetry-instrumentation==0.48b0
opentelemetry-instrumentation-asgi==0.48b0
opentelemetry-instrumentation-fastapi==0.48b0
opentelemetry-sdk==1.27.0
opentelemetry-semantic-conventions==0.48b0
opentelemetry-util-http==0.48b0
packaging==26.3
passlib==1.7.4
pluggy==1.6.0
pycparser==3.11
pydantic==2.9.2
pydantic-settings==2.5.2
pydantic_core==2.23.4
PyJWT==2.15.1
pyotp==2.9.0
pypng==0.20220715.0
pytest==8.3.3
pytest-asyncio==0.24.0
pytest-cov==5.0.0
python-dateutil==2.9.0.post0
python-dotenv==1.2.3
python-multipart==0.0.32
PyYAML==6.0.3
qrcode==7.4.2
ruff==0.6.9
setuptools==84.0.0
six==1.17.0
sniffio==1.3.1
SQLAlchemy==2.0.35
starlette==1.8.0
structlog==24.4.0
types-cffi==2.1.0.20260827
types-passlib==1.7.7.20240819
types-pyasn1==0.6.0.20260724
types-pyOpenSSL==24.1.0.20240722
types-python-jose==3.3.4.20240106
types-redis==4.6.0.20241004
types-setuptools==84.0.0.20261006
typing-inspection==0.4.4
typing_extensions==4.16.0
uvicorn==0.30.6
uvloop==0.23.0
watchfiles==1.3.0
websockets==17.2
wrapt==1.17.3
zipp==4.1.1
```

### gateway

```text
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.15.1
certifi==2026.7.22
cffi==2.1.1
click==8.5.0
coverage==7.16.2
cryptography==50.0.2
fastapi==0.141.1
h11==0.16.0
httpcore==1.0.9
httptools==0.9.0
httpx==0.27.2
idna==3.20
iniconfig==2.3.1
mypy==1.11.2
mypy_extensions==1.1.0
packaging==26.3
pluggy==1.6.0
pycparser==3.11
pydantic==2.9.2
pydantic-settings==2.5.2
pydantic_core==2.23.4
PyJWT==2.15.1
pytest==8.3.3
pytest-asyncio==0.24.0
pytest-cov==5.0.0
python-dotenv==1.2.3
PyYAML==6.0.3
ruff==0.6.9
sniffio==1.3.1
starlette==1.8.0
structlog==24.4.0
types-cffi==2.1.0.20260827
types-pyasn1==0.6.0.20260724
types-pyOpenSSL==24.1.0.20240722
types-python-jose==3.3.4.20240106
types-redis==4.6.0.20241004
types-setuptools==84.0.0.20261006
typing-inspection==0.4.4
typing_extensions==4.16.0
uvicorn==0.30.6
uvloop==0.23.0
watchfiles==1.3.0
websockets==17.2
```

### notification

```text
aiosmtplib==5.1.2
alembic==1.13.2
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.15.1
asyncpg==0.29.0
certifi==2026.7.22
cffi==2.1.1
click==8.5.0
coverage==7.16.2
cryptography==50.0.2
fastapi==0.141.1
greenlet==3.5.6
h11==0.16.0
httpcore==1.0.9
httptools==0.9.0
httpx==0.27.2
idna==3.20
iniconfig==2.3.1
Jinja2==3.1.6
Mako==1.4.3
MarkupSafe==3.0.4
mypy==1.11.2
mypy_extensions==1.1.0
packaging==26.3
pluggy==1.6.0
pycparser==3.11
pydantic==2.9.2
pydantic-settings==2.5.2
pydantic_core==2.23.4
PyJWT==2.15.1
pytest==8.3.4
pytest-asyncio==0.24.0
pytest-cov==5.0.0
pytest-mock==3.14.0
python-dotenv==1.2.3
PyYAML==6.0.3
ruff==0.6.9
sniffio==1.3.1
SQLAlchemy==2.0.35
starlette==1.8.0
typing-inspection==0.4.4
typing_extensions==4.16.0
uvicorn==0.30.6
uvloop==0.23.0
watchfiles==1.3.0
websockets==17.2
```
