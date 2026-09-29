"""Mirai-Harness-Core 固定参照（v0.6.0 vendoring）への適合テスト

- vendored ファイルが lock（contracts/harness-core.lock.json）の SHA-256 と一致する（手編集検知）
- CEOS のハッシュ実装が Core の tool_def_hash.py と同一結果を返す（mcip の登録値も再現）
- CEOS の識別子（server_id / ツール名接頭辞）が Core のシステム台帳と一致する
- effect / tier が Core の承認階層・Allowlist スキーマ制約を満たす
- CEOS 契約から作る Allowlist 登録項目が Core の mcp-allowlist.schema.json（JSON Schema）に適合する
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
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from src.tools import load_registry
from src.tools.contract import SERVER_ID, contract_document
from src.tools.registry import tool_contract_sha256

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCK_PATH = REPO_ROOT / "contracts" / "harness-core.lock.json"

# 固定する Core の版。更新時は lock と本定数の両方を変更する（意図しない差し替えの二重確認）。
EXPECTED_CORE_VERSION = "0.6.0"
EXPECTED_CORE_TAG = "v0.6.0"
EXPECTED_CORE_COMMIT = "1fe396a8414a2bca6ffade879f837c69cccaf5cc"


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


ALLOWLIST_SCHEMA_ID = "https://schemas.core.mirai/registry/mcp-allowlist/1"
# Allowlist の 1 ツール分の登録項目（servers[].tools[]）を指すサブスキーマ
ALLOWLIST_TOOL_ITEM = f"{ALLOWLIST_SCHEMA_ID}#/properties/servers/items/properties/tools/items"


def _core_validator(ref: str) -> Draft202012Validator:
    """vendored の Core スキーマ群を $id で登録し、ref を検証するバリデータを返す。"""
    resources = []
    for path in sorted((_vendor_dir() / "schemas").rglob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Draft202012Validator({"$ref": ref}, registry=Registry().with_resources(resources))


def _allowlist_tool_entry(tool: dict[str, Any]) -> dict[str, Any]:
    """CEOS 契約から Core Allowlist のツール登録項目（必須キーのみ）を作る。

    trust・surfaces・scopes はサーバー単位の Core 判断事項（未決）のため作らない。
    """
    return {
        "name": tool["name"],
        "effect": tool["x-mirai"]["effect"],
        "tier": tool["x-mirai"]["tier"],
        "definition_sha256": tool_contract_sha256(tool),
    }


def _schema_errors(validator: Draft202012Validator, doc: Any) -> list[str]:
    return [
        f"{'/'.join(map(str, e.absolute_path))}: {e.message}"
        for e in validator.iter_errors(doc)
    ]


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


def test_vendored_core_allowlist_validates_against_its_schema():
    """検証器の構成確認: Core 自身の Allowlist（mcip 登録済み）が同スキーマで 0 件になる。"""
    validator = _core_validator(ALLOWLIST_SCHEMA_ID)
    assert _schema_errors(validator, _load_yaml("registries/mcp-allowlist.yaml")) == []


@pytest.mark.parametrize("tool", _ceos_tools(), ids=lambda t: t["name"])
def test_ceos_tool_entry_satisfies_core_allowlist_schema(tool):
    validator = _core_validator(ALLOWLIST_TOOL_ITEM)
    assert _schema_errors(validator, _allowlist_tool_entry(tool)) == []


def test_ceos_server_id_satisfies_core_system_id_rule():
    validator = _core_validator("https://schemas.core.mirai/common/defs/1#/$defs/systemId")
    assert _schema_errors(validator, SERVER_ID) == []


@pytest.mark.parametrize(
    ("mutation", "field"),
    [
        ({"tier": "R1"}, "tier"),  # effect=read は R0 のみ
        ({"effect": "delete"}, "effect"),  # Core の effect 列挙に無い
        ({"definition_sha256": "sha256:" + "0" * 64}, "definition_sha256"),  # 接頭辞付きは不可
        ({"name": "CEOS.cost.list"}, "name"),  # <サーバーID>.<領域>.<動作> の小文字規則
        ({"unexpected": True}, ""),  # additionalProperties=false
    ],
)
def test_core_allowlist_schema_rejects_contract_violations(mutation, field):
    """検証が形骸化していないこと（違反を注入すると該当箇所でエラーになる）。"""
    entry = {**_allowlist_tool_entry(_ceos_tools()[0]), **mutation}
    errors = _schema_errors(_core_validator(ALLOWLIST_TOOL_ITEM), entry)
    assert errors
    assert any(e.split(":", 1)[0] == field for e in errors), errors


def test_operation_is_not_guessed_until_core_defines_a_category():
    """x-mirai.operation は Core 承認階層表に CEOS 用カテゴリが定義されるまで付与しない。

    Core 側でカテゴリが追加されたら、本テストを「operation が tiers.operations に存在し、
    その階層が宣言 tier 以下である（VA-03-4）」検査へ置き換えること。
    """
    operations = _load_yaml("approval-tiers/tiers.yaml")["operations"]
    assert not any(op.startswith("ceos.") for op in operations)
    for tool in _ceos_tools():
        assert "operation" not in tool["x-mirai"]
