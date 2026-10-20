#!/usr/bin/env python3
"""秘密配置の限定的・決定的なヒューリスティック検査 (ADR-0005)。

S-1: 追跡された通常ファイルの PEM header + payload、資格情報候補の追跡。
S-2: 固定対象 compose の environment にある秘密らしい名前の直書き。
S-3: 代表的な env パスの Git ignore 意味検査（網羅性の証明ではない）。
S-4: ホスト ~/.config/ceos と stg.env の種別・権限を stat のみで検査。
S-5: 合成入力による検出器の対照。資格情報候補の内容は読み取らない。

未読・不正・欠落入力は FAIL。ホスト不在のみ NOT_CHECKED として扱う。
秘密の不存在、履歴、実行時展開、任意の資格情報形式の安全を証明しない。
"""
from __future__ import annotations

import re
import stat
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSES = (ROOT / "docker-compose.yml", ROOT / "docker-compose.stg.yml")
CONFIG_DIR = Path.home() / ".config" / "ceos"
CONFIG_FILE = CONFIG_DIR / "stg.env"

# Require actual separate header/payload lines, not quoted source/doc examples.
PEM_PATTERN = re.compile(
    r"^-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----\r?\n[A-Za-z0-9+/=]{4,}\r?$",
    re.MULTILINE,
)
SECRET_NAME = re.compile(
    r"(SECRET|PASSWORD|PASSWD|TOKEN|_KEY$|^JWT_|API_KEY|CLIENT_SECRET|ACCESS_KEY|ROOT_PASSWORD)",
    re.IGNORECASE,
)
ALLOWED_VALUE = re.compile(
    r"(?:\$\{[A-Za-z_][A-Za-z0-9_]*(?:(?::?[-+?=])[^{}\r\n]*)?\}|__[A-Z_]+__|change-me|)",
    re.IGNORECASE,
)
IGNORE_PROBES = tuple(
    prefix + name
    for prefix in ("", "services/example/")
    for name in (".env", "stg.env", ".env.stg", ".env.production", ".env.local")
)


class InputError(Exception):
    """Unavailable or invalid inspection input (never a clean result)."""


class UniqueLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys instead of silently hiding earlier values."""


def _unique_mapping(loader: UniqueLoader, node: yaml.MappingNode) -> dict:
    # Explicit duplicates are invalid; YAML << merge overrides are legitimate.
    explicit = set()
    for key_node, _ in node.value:
        if key_node.tag == "tag:yaml.org,2002:merge":
            continue
        key = loader.construct_object(key_node)
        if not isinstance(key, (str, int, float, bool, type(None))) or key in explicit:
            raise InputError("YAML mapping に不正または重複したキー")
        explicit.add(key)
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, (str, int, float, bool, type(None))):
            raise InputError("YAML mapping に不正なキー")
        result[key] = loader.construct_object(value_node)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _git(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", str(ROOT), *args], capture_output=True, text=True,
            check=False, **kwargs,
        )
    except (OSError, UnicodeError) as exc:
        raise InputError("Git 入力を取得できない") from exc


def tracked_files() -> list[str]:
    out = _git(["ls-files", "-z"])
    if out.returncode != 0 or not out.stdout or not out.stdout.endswith("\0"):
        raise InputError("git ls-files が失敗/空/不正（追跡対象を未確認）")
    paths = out.stdout[:-1].split("\0")
    if any(not p or Path(p).is_absolute() or ".." in Path(p).parts for p in paths):
        raise InputError("git ls-files に不正なパス")
    return paths


def credential_candidate(rel: str) -> bool:
    name = Path(rel).name.lower()
    if name.endswith(".example"):
        return False
    return (
        name == ".env" or name.startswith(".env.") or name.endswith(".env")
        or ".env.bak" in name or name in ("id_rsa", "id_ed25519", "id_dsa", "id_ecdsa")
        or Path(name).suffix in (".pem", ".key", ".p12", ".pfx", ".keystore")
    )


def check_pem(tracked: list[str] | None = None) -> list[str]:
    failures = []
    try:
        paths = tracked_files() if tracked is None else tracked
    except InputError as exc:
        return [f"S-1: {exc}"]
    for rel in paths:
        if credential_candidate(rel):
            failures.append(f"S-1: 資格情報候補が追跡されている（内容未読）: {rel}")
            continue
        try:
            path = ROOT / rel
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise InputError("通常ファイルでない（リンク/ディレクトリ等は内容未読）")
            text = path.read_text(encoding="utf-8", errors="replace")
        except (OSError, InputError):
            failures.append(f"S-1: 読めない/不正な追跡ファイル: {rel}")
            continue
        if PEM_PATTERN.search(text):
            failures.append(f"S-1: PEM 秘密鍵らしい header/payload: {rel}")
    return failures


def _environment(env: object) -> list[tuple[str, object]]:
    if isinstance(env, dict):
        pairs = list(env.items())
    elif isinstance(env, list):
        pairs = []
        for item in env:
            if not isinstance(item, str):
                raise InputError("environment list は文字列のみ")
            key, sep, value = item.partition("=")
            pairs.append((key, value if sep else None))
    else:
        raise InputError("environment は mapping/list である必要がある")
    names = set()
    for key, value in pairs:
        if not isinstance(key, str) or not key or "=" in key or "\0" in key or any(c.isspace() for c in key):
            raise InputError("environment に不正な名前")
        if key in names or (value is not None and not isinstance(value, (str, int, float, bool))):
            raise InputError("environment に重複名/不正な値型")
        names.add(key)
    return pairs


def check_compose_values() -> list[str]:
    failures = []
    for compose in COMPOSES:
        try:
            if not stat.S_ISREG(compose.lstat().st_mode):
                raise InputError("通常ファイルでない")
            data = yaml.load(compose.read_text(encoding="utf-8"), Loader=UniqueLoader)
            if not isinstance(data, dict) or not isinstance(data.get("services"), dict) or not data["services"]:
                raise InputError("services は空でない mapping が必要")
            for svc, body in data["services"].items():
                if not isinstance(svc, str) or not svc or not isinstance(body, dict):
                    raise InputError("service は名前と mapping が必要")
                if "environment" not in body:
                    continue
                for key, value in _environment(body["environment"]):
                    if SECRET_NAME.search(key):
                        text = "" if value is None else str(value)
                        if not ALLOWED_VALUE.fullmatch(text):
                            failures.append(f"S-2: {compose.name}:{svc} の {key} に実値らしい値（値は非表示）")
        except (OSError, UnicodeError, yaml.YAMLError, InputError):
            # Parser errors can embed source lines and hence credentials: never echo them.
            failures.append(f"S-2: {compose.name} の入力欠落/読取失敗/不正な YAML または environment")
    return failures


def check_gitignore(tracked: list[str] | None = None) -> list[str]:
    failures = []
    try:
        if not stat.S_ISREG((ROOT / ".gitignore").lstat().st_mode):
            raise InputError(".gitignore が通常ファイルでない")
        out = _git(["check-ignore", "--no-index", "--verbose", "-z", "--stdin"], input="\0".join(IGNORE_PROBES) + "\0")
        if out.returncode not in (0, 1) or (out.stdout and not out.stdout.endswith("\0")):
            raise InputError("git check-ignore が失敗/不正")
        fields = out.stdout[:-1].split("\0") if out.stdout else []
        if len(fields) % 4 or (out.returncode == 1 and fields):
            raise InputError("git check-ignore の応答が不正")
        ignored = set()
        for source, line, pattern, rel in zip(fields[::4], fields[1::4], fields[2::4], fields[3::4]):
            if rel not in IGNORE_PROBES or not line.isdigit():
                raise InputError("git check-ignore の応答が不正")
            # Ignore local/global exclusions: only committed-project rule paths count.
            if source == ".gitignore" and pattern and not pattern.startswith("!"):
                ignored.add(rel)
        for rel in IGNORE_PROBES:
            if rel not in ignored:
                failures.append(f"S-3: env 代表パスが Git ignore 対象でない: {rel}")
        paths = tracked_files() if tracked is None else tracked
        for rel in paths:
            if credential_candidate(rel):
                failures.append(f"S-3: 資格情報候補が追跡されている（内容未読）: {rel}")
    except (OSError, InputError) as exc:
        failures.append(f"S-3: {exc}" if isinstance(exc, InputError) else "S-3: .gitignore の入力欠落/読取失敗")
    return failures


def check_permissions() -> tuple[list[str], list[str]]:
    """Inspect metadata only; no credential file content is opened."""
    failures, notes = [], []
    for path, expected_mode, expected_type in (
        (CONFIG_DIR, 0o700, stat.S_ISDIR), (CONFIG_FILE, 0o600, stat.S_ISREG),
    ):
        try:
            info = path.lstat()
        except FileNotFoundError:
            notes.append(f"S-4: NOT_CHECKED（{path} が無い）")
            continue
        except OSError:
            failures.append(f"S-4: {path} のメタデータを取得できない")
            continue
        mode = stat.S_IMODE(info.st_mode)
        if not expected_type(info.st_mode) or mode != expected_mode:
            failures.append(f"S-4: {path} の種別/権限が期待値 {oct(expected_mode)} と異なる")
        else:
            notes.append(f"S-4: CHECKED {path} の種別/権限 {oct(mode)}（内容未読）")
    return failures, notes


def negative_control() -> list[str]:
    # Join the synthetic marker so the scanner does not match its own source.
    marker = "-----BEGIN " + "RSA PRIVATE KEY-----"
    if not PEM_PATTERN.search(marker + "\nMIIE\n"):
        return ["S-5: 合成 PEM 検出が動いていない"]
    if ALLOWED_VALUE.fullmatch("synthetic-literal") or not ALLOWED_VALUE.fullmatch("${STG_JWT_SECRET_KEY}"):
        return ["S-5: 合成 environment 対照が失敗"]
    return []


def main() -> int:
    failures = []
    try:
        tracked = tracked_files()
    except InputError as exc:
        tracked = []
        failures.append(str(exc))
    failures += check_pem(tracked)
    failures += check_compose_values()
    failures += check_gitignore(tracked)
    perm_failures, notes = check_permissions()
    failures += perm_failures + negative_control()
    for note in notes:
        print(f"  - {note}")
    print("SCOPE: 決定的ヒューリスティックのみ。秘密の不存在・履歴・実行時値・全形式の安全は未証明。")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        print(f"NG: 限定検査で {len(failures)} 件の問題/未検査入力。", file=sys.stderr)
        return 1
    print("PASS: S-1/S-2/S-3/S-5 の限定検査で検出なし。S-4 は上記個別状態を参照（NOT_CHECKED は合格ではない）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
