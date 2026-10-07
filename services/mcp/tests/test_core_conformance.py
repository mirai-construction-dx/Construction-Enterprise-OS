"""Mirai-Harness-Core 固定参照（v0.6.0 vendoring）への適合テスト

- vendored ファイルが lock（contracts/harness-core.lock.json）の SHA-256 と一致する（手編集検知）
- CEOS のハッシュ実装が Core の tool_def_hash.py と同一結果を返す（mcip の登録値も再現）
- CEOS の識別子（server_id / ツール名接頭辞）が Core のシステム台帳と一致する
- effect / tier が Core の承認階層・Allowlist スキーマ制約を満たす
"""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from src.tools import load_registry
from src.tools.contract import SERVER_ID, contract_document
from src.tools.registry import tool_contract_sha256

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCK_PATH = REPO_ROOT / "contracts" / "harness-core.lock.json"

# 固定する Core の版。更新時は lock と本定数の両方を変更する（意図しない差し替えの二重確認）。
EXPECTED_CORE_VERSION = "0.7.0"
EXPECTED_CORE_TAG = "v0.7.0"
EXPECTED_CORE_COMMIT = "0e5e3a4e74ceb98e5ee3746ac678fb0f6d8b0b1d"


def _lock() -> dict[str, Any]:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _vendor_dir() -> Path:
    return REPO_ROOT / _lock()["vendor_dir"]


def _load_yaml(relative: str) -> Any:
    return yaml.safe_load((_vendor_dir() / relative).read_text(encoding="utf-8"))


def _core_hash_module() -> ModuleType:
    path = _vendor_dir() / "tools" / "tool_def_hash.py"
    spec = importlib.util.spec_from_file_location("core_tool_def_hash", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # vendored ツリーに __pycache__ を作らない（lock の digest 検査対象を汚さない）
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def _ceos_tools() -> list[dict[str, Any]]:
    return contract_document(load_registry())["tools"]


def test_lock_pins_core_version_and_source():
    lock = _lock()
    assert lock["consumer"] == {"system_id": "ceos", "mcp_server_id": SERVER_ID}
    assert lock["core_version"] == EXPECTED_CORE_VERSION
    assert lock["source"]["tag"] == EXPECTED_CORE_TAG
    assert lock["source"]["commit"] == EXPECTED_CORE_COMMIT
    assert lock["vendor_dir"] == f"contracts/vendor/harness-core/{EXPECTED_CORE_TAG}"
    version = (_vendor_dir() / "VERSION").read_text(encoding="utf-8").strip()
    assert version == EXPECTED_CORE_VERSION
    # 由来の記載（VENDORED.md）も同じタグ・commit を指す
    vendored_md = (_vendor_dir() / "VENDORED.md").read_text(encoding="utf-8")
    assert EXPECTED_CORE_TAG in vendored_md
    assert EXPECTED_CORE_COMMIT in vendored_md


def test_vendored_files_match_lock_digests():
    lock = _lock()
    vendor = _vendor_dir()
    on_disk = {
        str(p.relative_to(vendor)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(vendor.rglob("*"))
        if p.is_file()
        and p.name != "VENDORED.md"
        and "__pycache__" not in p.relative_to(vendor).parts
    }
    # 追加・削除・改変のいずれも検知する
    assert on_disk == lock["files"]


def test_ceos_hash_matches_core_reference_implementation():
    core = _core_hash_module()
    for tool in _ceos_tools():
        assert tool_contract_sha256(tool) == core.tool_definition_sha256(tool), tool["name"]


def test_ceos_hash_reproduces_core_registered_mcip_hashes():
    """golden vector: Core に登録済みの mcip ツールのハッシュを CEOS 実装で再現する。"""
    mcip = json.loads(
        (_vendor_dir() / "contracts" / "mcp-tools" / "mcip.json").read_text(encoding="utf-8")
    )
    allowlist = _load_yaml("registries/mcp-allowlist.yaml")
    registered = {
        tool["name"]: tool["definition_sha256"]
        for server in allowlist["servers"]
        if server["server_id"] == "mcip"
        for tool in server["tools"]
    }
    computed = {tool["name"]: tool_contract_sha256(tool) for tool in mcip["tools"]}
    assert registered and computed == registered


def test_ceos_identity_matches_core_system_registry():
    systems = {s["id"]: s for s in _load_yaml("registries/systems.yaml")["systems"]}
    ceos = systems["ceos"]
    assert ceos["repo"] == "Construction-Enterprise-OS"
    assert ceos["mcp_server_id"] == SERVER_ID
    # Core VA-04: ツール名はサーバー ID で始まる
    for tool in _ceos_tools():
        assert tool["name"].startswith(SERVER_ID + "."), tool["name"]


@pytest.mark.parametrize("tool", _ceos_tools(), ids=lambda t: t["name"])
def test_effect_and_tier_satisfy_core_constraints(tool):
    tiers = _load_yaml("approval-tiers/tiers.yaml")
    tier_ids = {t["id"] for t in tiers["tiers"]}
    x_mirai = tool["x-mirai"]
    assert x_mirai["tier"] in tier_ids
    # Core mcp-allowlist.schema.json: effect=read なら tier は R0 のみ
    assert (x_mirai["effect"], x_mirai["tier"]) == ("read", "R0")
    # readOnlyHint は effect と矛盾しない（Core 基本設計の標準注釈規則）
    assert tool["annotations"]["readOnlyHint"] is True


def test_operation_is_not_guessed_until_core_defines_a_category():
    """x-mirai.operation は Core 承認階層表に CEOS 用カテゴリが定義されるまで付与しない。

    Core 側でカテゴリが追加されたら、本テストを「operation が tiers.operations に存在し、
    その階層が宣言 tier 以下である（VA-03-4）」検査へ置き換えること。
    """
    operations = _load_yaml("approval-tiers/tiers.yaml")["operations"]
    assert not any(op.startswith("ceos.") for op in operations)
    for tool in _ceos_tools():
        assert "operation" not in tool["x-mirai"]
