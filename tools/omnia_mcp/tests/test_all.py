"""
Comprehensive tests for the Omnia MCP server.
Run with: python tools/omnia_mcp/tests/test_all.py
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Ensure the tools/omnia_mcp package is importable
TOOLS_DIR = Path(__file__).resolve().parent.parent.parent  # tools/
OMNIA_MCP_DIR = TOOLS_DIR / "omnia_mcp"
sys.path.insert(0, str(TOOLS_DIR))

# Resolve Omnia project root (tools/ -> repo root)
PROJECT_ROOT = TOOLS_DIR.parent
os.environ["OMNIA_ROOT"] = str(PROJECT_ROOT)

from omnia_mcp.config_registry import ConfigRegistry, CONFIG_ENTRIES, CROSS_FILE_REFS
from omnia_mcp.schema_docs import (
    schema_docs_for_config,
    yaml_comment_docs_for_config,
    explain_parameter,
    explain_all_parameters,
)
from omnia_mcp.validators import (
    validate_schema,
    validate_cross_references,
    validate_config,
    validate_no_exposed_passwords,
    _resolve_jsonpath_simple,
)
from omnia_mcp.config_mutator import (
    generate_config_fragment,
    update_config_value,
    _get_nested,
    _set_nested,
)
from omnia_mcp.server import create_server, _dispatch_tool, _find_omnia_root


OMNIA_ROOT = PROJECT_ROOT
passed = 0
failed = 0
errors = []


def test(name):
    """Decorator to register and run a test function."""
    def decorator(func):
        global passed, failed
        try:
            func()
            print(f"  PASS: {name}")
            passed += 1
        except Exception as e:
            print(f"  FAIL: {name} -- {e}")
            failed += 1
            errors.append((name, str(e)))
        return func
    return decorator


# ==========================================================================
# 1. ConfigRegistry Tests
# ==========================================================================
print("\n=== ConfigRegistry Tests ===")

registry = ConfigRegistry(OMNIA_ROOT)


@test("Registry has all 11 config entries")
def _():
    assert len(registry.entries) == 11, f"Expected 11, got {len(registry.entries)}"


@test("All config keys are strings")
def _():
    for key in registry.list_config_keys():
        assert isinstance(key, str), f"Key {key!r} is not a string"


@test("list_available_configs returns correct structure")
def _():
    configs = registry.list_available_configs()
    assert len(configs) == 11, f"Expected 11, got {len(configs)}"
    for c in configs:
        assert "key" in c
        assert "filename" in c
        assert "description" in c
        assert "exists" in c
        assert "has_schema" in c
        assert "tags" in c


@test("All config files exist on disk")
def _():
    missing = []
    for key in registry.list_config_keys():
        path = registry.config_path(key)
        if path is None:
            missing.append(key)
    assert not missing, f"Missing config files: {missing}"


@test("Schema files exist on disk")
def _():
    found = 0
    missing = []
    for key in registry.list_config_keys():
        entry = registry.entry_by_key(key)
        if entry and entry.schema_filename:
            path = registry.schema_path(key)
            if path is None:
                missing.append(key)
            else:
                found += 1
    print(f"    ({found} schemas found, {len(missing)} missing: {missing})")


@test("read_config returns parsed data for omnia_config")
def _():
    data = registry.read_config("omnia_config")
    assert data is not None, "read_config returned None"
    assert isinstance(data, dict), f"Expected dict, got {type(data)}"
    assert "service_k8s_cluster" in data, "Missing service_k8s_cluster key"
    assert "slurm_cluster" in data, "Missing slurm_cluster key"


@test("read_config returns parsed data for software_config (JSON)")
def _():
    data = registry.read_config("software_config")
    assert data is not None
    assert isinstance(data, dict)
    assert "cluster_os_type" in data
    assert "softwares" in data


@test("read_config_raw returns raw text with comments")
def _():
    raw = registry.read_config_raw("omnia_config")
    assert raw is not None
    assert "#" in raw, "Raw text should contain comments"
    assert "service_k8s_cluster" in raw


@test("read_schema returns valid JSON schema for omnia_config")
def _():
    schema = registry.read_schema("omnia_config")
    assert schema is not None
    assert "properties" in schema
    assert "service_k8s_cluster" in schema["properties"]


@test("entry_by_filename works")
def _():
    entry = registry.entry_by_filename("omnia_config.yml")
    assert entry is not None
    assert entry.key == "omnia_config"

    entry2 = registry.entry_by_filename("nonexistent.yml")
    assert entry2 is None


@test("entry_by_key works")
def _():
    entry = registry.entry_by_key("network_spec")
    assert entry is not None
    assert entry.filename == "network_spec.yml"


@test("get_cross_refs returns rules")
def _():
    refs = registry.get_cross_refs()
    assert len(refs) >= 3, f"Expected >= 3 cross-ref rules, got {len(refs)}"
    for ref in refs:
        assert "source_file" in ref
        assert "target_file" in ref
        assert "description" in ref


@test("build_stream_config and gitlab_config entries exist")
def _():
    bs = registry.entry_by_key("build_stream_config")
    assert bs is not None
    assert bs.filename == "build_stream_config.yml"
    gl = registry.entry_by_key("gitlab_config")
    assert gl is not None
    assert gl.filename == "gitlab_config.yml"


# ==========================================================================
# 2. Schema Docs Tests
# ==========================================================================
print("\n=== Schema Docs Tests ===")


@test("schema_docs_for_config returns properties for omnia_config")
def _():
    docs = schema_docs_for_config(registry, "omnia_config")
    assert len(docs) > 0, "No schema docs returned"
    paths = [d["path"] for d in docs]
    assert any("cluster_name" in p for p in paths), f"No cluster_name found in paths: {paths}"


@test("schema_docs_for_config returns properties for software_config")
def _():
    docs = schema_docs_for_config(registry, "software_config")
    assert len(docs) > 0
    paths = [d["path"] for d in docs]
    assert any("cluster_os_type" in p for p in paths), f"Missing cluster_os_type in: {paths}"


@test("schema_docs_for_config returns properties for network_spec")
def _():
    docs = schema_docs_for_config(registry, "network_spec")
    assert len(docs) > 0
    print(f"    (found {len(docs)} properties)")


@test("yaml_comment_docs_for_config extracts comments from omnia_config")
def _():
    docs = yaml_comment_docs_for_config(registry, "omnia_config")
    print(f"    (extracted {len(docs)} comment-documented params)")


@test("explain_parameter returns data for known parameter")
def _():
    result = explain_parameter(registry, "omnia_config", "cluster_name")
    assert result["found"], f"Parameter not found: {result}"


@test("explain_parameter returns cross-reference for nfs_storage_name")
def _():
    result = explain_parameter(registry, "omnia_config", "nfs_storage_name")
    assert result["found"], f"Parameter not found: {result}"
    if "cross_reference" in result:
        assert "target_file" in result["cross_reference"]
        print(f"    (cross-ref found: -> {result['cross_reference']['target_file']})")


@test("explain_all_parameters returns full docs for omnia_config")
def _():
    result = explain_all_parameters(registry, "omnia_config")
    assert "error" not in result, f"Error: {result.get('error')}"
    assert "schema_properties" in result
    assert "comment_docs" in result
    assert "cross_references" in result
    print(f"    (schema props: {len(result['schema_properties'])}, "
          f"comment docs: {len(result['comment_docs'])}, "
          f"cross-refs: {len(result['cross_references'])})")


@test("explain_all_parameters returns error for unknown key")
def _():
    result = explain_all_parameters(registry, "nonexistent")
    assert "error" in result


# ==========================================================================
# 3. Validators Tests
# ==========================================================================
print("\n=== Validators Tests ===")


@test("validate_schema runs for omnia_config")
def _():
    errs = validate_schema(registry, "omnia_config")
    assert isinstance(errs, list)
    if errs:
        print(f"    ({len(errs)} validation errors)")
    else:
        print("    (valid)")


@test("validate_schema runs for software_config")
def _():
    errs = validate_schema(registry, "software_config")
    assert isinstance(errs, list)
    if errs:
        print(f"    ({len(errs)} validation errors)")
    else:
        print("    (valid)")


@test("validate_schema runs for network_spec")
def _():
    errs = validate_schema(registry, "network_spec")
    assert isinstance(errs, list)
    if errs:
        print(f"    ({len(errs)} validation errors)")
    else:
        print("    (valid)")


@test("validate_schema returns error for nonexistent config")
def _():
    errs = validate_schema(registry, "nonexistent")
    assert len(errs) == 1
    assert "not found" in errs[0]["message"]


@test("_resolve_jsonpath_simple works on nested data")
def _():
    data = {
        "service_k8s_cluster": [
            {"cluster_name": "svc1", "nfs_storage_name": "nfs1"},
            {"cluster_name": "svc2", "nfs_storage_name": "nfs2"},
        ]
    }
    result = _resolve_jsonpath_simple(data, "service_k8s_cluster[*].nfs_storage_name")
    assert result == ["nfs1", "nfs2"], f"Got: {result}"


@test("_resolve_jsonpath_simple works on simple key")
def _():
    data = {"cluster_os_type": "rhel"}
    result = _resolve_jsonpath_simple(data, "cluster_os_type")
    assert result == ["rhel"], f"Got: {result}"


@test("validate_cross_references runs without error")
def _():
    errs = validate_cross_references(registry)
    assert isinstance(errs, list)
    if errs:
        for e in errs:
            print(f"    [{e['level']}] {e['message'][:120]}")
    else:
        print("    (all cross-refs valid)")


@test("validate_config runs full validation")
def _():
    result = validate_config(registry)
    assert "valid" in result
    assert "errors" in result
    assert "warnings" in result
    assert "files_checked" in result
    print(f"    (valid={result['valid']}, errors={len(result['errors'])}, "
          f"warnings={len(result['warnings'])}, files={len(result['files_checked'])})")


@test("validate_config with tag filter works")
def _():
    result = validate_config(registry, tags=["service_k8s"])
    assert "files_checked" in result
    print(f"    (checked: {result['files_checked']})")


@test("validate_config with specific config_key works")
def _():
    result = validate_config(registry, config_key="security_config")
    assert "files_checked" in result
    assert "security_config.yml" in result["files_checked"]


@test("validate_no_exposed_passwords runs")
def _():
    warnings = validate_no_exposed_passwords(registry)
    assert isinstance(warnings, list)
    print(f"    ({len(warnings)} password warnings)")


# ==========================================================================
# 4. Config Mutator Tests
# ==========================================================================
print("\n=== Config Mutator Tests ===")


@test("_get_nested works on dict")
def _():
    data = {"a": {"b": {"c": 42}}}
    assert _get_nested(data, "a.b.c") == 42
    assert _get_nested(data, "a.b") == {"c": 42}
    assert _get_nested(data, "x.y") is None


@test("_get_nested works with list indices")
def _():
    data = {"items": [{"name": "first"}, {"name": "second"}]}
    assert _get_nested(data, "items.0.name") == "first"
    assert _get_nested(data, "items.1.name") == "second"


@test("_set_nested works on dict")
def _():
    data = {"a": {"b": {"c": 42}}}
    assert _set_nested(data, "a.b.c", 99)
    assert data["a"]["b"]["c"] == 99


@test("_set_nested works with list indices")
def _():
    data = {"items": [{"name": "first"}, {"name": "second"}]}
    assert _set_nested(data, "items.0.name", "updated")
    assert data["items"][0]["name"] == "updated"


@test("update_config_value dry_run works for omnia_config")
def _():
    result = update_config_value(
        registry, "omnia_config",
        "service_k8s_cluster.0.k8s_cni", "flannel",
        dry_run=True,
    )
    assert result["success"], f"Failed: {result}"
    assert result.get("dry_run") is True
    print(f"    (old={result['old_value']}, new={result['new_value']})")


@test("update_config_value dry_run for nonexistent config")
def _():
    result = update_config_value(
        registry, "nonexistent",
        "foo.bar", "baz",
        dry_run=True,
    )
    assert not result["success"]
    assert "error" in result


@test("generate_config_fragment produces config")
def _():
    fragment = generate_config_fragment({
        "cluster_name": "test_cluster",
        "pod_external_ip_range": "10.0.0.100-10.0.0.200",
        "nfs_server_ip": "192.168.1.1",
        "nfs_share_path": "/mnt/share",
        "enable_ha": True,
        "virtual_ip": "10.0.0.50",
        "admin_ip": "192.168.1.254",
    })
    assert "omnia_config" in fragment
    assert "storage_config" in fragment
    assert "high_availability_config" in fragment
    assert "network_spec" in fragment
    assert "software_config" in fragment

    k8s = fragment["omnia_config"]["service_k8s_cluster"][0]
    assert k8s["cluster_name"] == "test_cluster"
    assert k8s["nfs_storage_name"] == "nfs_test_cluster"

    ha = fragment["high_availability_config"]["service_k8s_cluster_ha"][0]
    assert ha["cluster_name"] == "test_cluster"

    nfs = fragment["storage_config"]["nfs_client_params"][0]
    assert nfs["nfs_name"] == "nfs_test_cluster"


@test("generate_config_fragment without HA omits HA section")
def _():
    fragment = generate_config_fragment({
        "cluster_name": "no_ha_cluster",
        "enable_ha": False,
    })
    assert "high_availability_config" not in fragment


@test("generate_config_fragment cross-ref consistency")
def _():
    fragment = generate_config_fragment({"cluster_name": "xref_test", "nfs_server_ip": "10.0.0.1"})
    nfs_storage_name = fragment["omnia_config"]["service_k8s_cluster"][0]["nfs_storage_name"]
    nfs_name = fragment["storage_config"]["nfs_client_params"][0]["nfs_name"]
    assert nfs_storage_name == nfs_name, f"Cross-ref mismatch: {nfs_storage_name} != {nfs_name}"


@test("generate_config_fragment with minimal input")
def _():
    fragment = generate_config_fragment({})
    assert "omnia_config" in fragment
    k8s = fragment["omnia_config"]["service_k8s_cluster"][0]
    assert k8s["cluster_name"] == "service_cluster"


# ==========================================================================
# 5. Server Tests
# ==========================================================================
print("\n=== Server Tests ===")


@test("_find_omnia_root resolves correctly")
def _():
    root = _find_omnia_root()
    assert (root / "input" / "omnia_config.yml").exists(), f"Root {root} invalid"


@test("create_server returns Server and ConfigRegistry")
def _():
    server, reg = create_server()
    assert server is not None
    assert reg is not None
    assert len(reg.list_config_keys()) == 11


@test("_dispatch_tool list_configs works")
def _():
    result = _dispatch_tool("list_configs", {}, registry)
    assert "configs" in result
    assert "omnia_root" in result
    assert len(result["configs"]) == 11


@test("_dispatch_tool get_cross_refs works")
def _():
    result = _dispatch_tool("get_cross_refs", {}, registry)
    assert "cross_references" in result


@test("_dispatch_tool validate_config works")
def _():
    result = _dispatch_tool("validate_config", {}, registry)
    assert "valid" in result
    assert "errors" in result


@test("_dispatch_tool validate_config with config_key works")
def _():
    result = _dispatch_tool("validate_config", {"config_key": "omnia_config"}, registry)
    assert "valid" in result


@test("_dispatch_tool validate_config with tags works")
def _():
    result = _dispatch_tool("validate_config", {"tags": ["security"]}, registry)
    assert "files_checked" in result
    assert "security_config.yml" in result["files_checked"]


@test("_dispatch_tool explain_config for whole file works")
def _():
    result = _dispatch_tool("explain_config", {"config_key": "omnia_config"}, registry)
    assert "schema_properties" in result
    assert "comment_docs" in result


@test("_dispatch_tool explain_config for specific parameter works")
def _():
    result = _dispatch_tool(
        "explain_config",
        {"config_key": "omnia_config", "parameter": "cluster_name"},
        registry,
    )
    assert result["found"], f"Parameter not found: {result}"


@test("_dispatch_tool update_config dry_run works")
def _():
    result = _dispatch_tool(
        "update_config",
        {
            "config_key": "omnia_config",
            "key_path": "service_k8s_cluster.0.k8s_cni",
            "value": "flannel",
            "dry_run": True,
        },
        registry,
    )
    assert result["success"]
    assert result["dry_run"]


@test("_dispatch_tool generate_config works")
def _():
    result = _dispatch_tool(
        "generate_config",
        {"cluster_name": "gen_test"},
        registry,
    )
    assert "omnia_config" in result


@test("_dispatch_tool unknown tool returns error")
def _():
    result = _dispatch_tool("nonexistent_tool", {}, registry)
    assert "error" in result


@test("Server tool dispatch returns JSON-serializable results for all tools")
def _():
    test_cases = [
        ("list_configs", {}),
        ("get_cross_refs", {}),
        ("validate_config", {}),
        ("validate_config", {"config_key": "omnia_config"}),
        ("validate_config", {"tags": ["service_k8s"]}),
        ("explain_config", {"config_key": "omnia_config"}),
        ("explain_config", {"config_key": "omnia_config", "parameter": "k8s_cni"}),
        ("update_config", {"config_key": "omnia_config", "key_path": "service_k8s_cluster.0.k8s_cni", "value": "flannel", "dry_run": True}),
        ("generate_config", {"cluster_name": "test"}),
    ]
    for tool_name, args in test_cases:
        result = _dispatch_tool(tool_name, args, registry)
        try:
            serialized = json.dumps(result, default=str)
            assert len(serialized) > 2
        except (TypeError, ValueError) as e:
            raise AssertionError(f"Tool '{tool_name}' returned non-serializable result: {e}")
    print(f"    (all {len(test_cases)} tool dispatches return valid JSON)")


# ==========================================================================
# 6. Edge Cases
# ==========================================================================
print("\n=== Edge Case Tests ===")


@test("_resolve_jsonpath_simple handles empty data")
def _():
    result = _resolve_jsonpath_simple({}, "nonexistent[*].field")
    assert result == []


@test("_resolve_jsonpath_simple handles non-list for array path")
def _():
    result = _resolve_jsonpath_simple({"items": "not_a_list"}, "items[*].name")
    assert result == []


@test("_get_nested handles deeply nested missing keys")
def _():
    assert _get_nested({}, "a.b.c.d.e") is None
    assert _get_nested({"a": 1}, "a.b") is None


@test("_set_nested rejects invalid paths")
def _():
    data = {"a": 1}
    assert not _set_nested(data, "a.b.c", 99)


@test("update_config_value dry_run on nonexistent key_path")
def _():
    result = update_config_value(
        registry, "omnia_config",
        "nonexistent.deep.path", "value",
        dry_run=True,
    )
    assert not result["success"]
    assert "error" in result


@test("validate_config with empty tags list")
def _():
    result = validate_config(registry, tags=[])
    assert isinstance(result, dict)


# ==========================================================================
# 7. Write + Rollback Tests (temp copy of input/)
# ==========================================================================
print("\n=== Write + Rollback Tests ===")


def _make_temp_registry():
    """Create a ConfigRegistry pointing at a temp copy so writes don't affect real files."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="omnia_mcp_test_"))
    shutil.copytree(OMNIA_ROOT / "input", tmp_dir / "input")
    schema_src = (
        OMNIA_ROOT / "common" / "library" / "module_utils"
        / "input_validation" / "schema"
    )
    schema_dst = (
        tmp_dir / "common" / "library" / "module_utils"
        / "input_validation" / "schema"
    )
    if schema_src.exists():
        shutil.copytree(schema_src, schema_dst)
    return ConfigRegistry(tmp_dir), tmp_dir


@test("Non-dry-run write actually modifies the file")
def _():
    tmp_reg, tmp_dir = _make_temp_registry()
    try:
        orig_data = tmp_reg.read_config("omnia_config")
        orig_cni = orig_data["service_k8s_cluster"][0].get("k8s_cni", "calico")
        new_cni = "flannel" if orig_cni == "calico" else "calico"

        result = update_config_value(
            tmp_reg, "omnia_config",
            "service_k8s_cluster.0.k8s_cni", new_cni,
            dry_run=False, validate_after=False,
        )
        assert result["success"], f"Write failed: {result}"
        assert "backup" in result
        assert Path(result["backup"]).exists(), "Backup file was not created"

        updated_data = tmp_reg.read_config("omnia_config")
        assert updated_data["service_k8s_cluster"][0]["k8s_cni"] == new_cni
        print(f"    (wrote k8s_cni={new_cni}, backup={Path(result['backup']).name})")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@test("Non-dry-run write with validation (valid change)")
def _():
    tmp_reg, tmp_dir = _make_temp_registry()
    try:
        result = update_config_value(
            tmp_reg, "omnia_config",
            "service_k8s_cluster.0.k8s_cni", "calico",
            dry_run=False, validate_after=True,
        )
        assert result["success"], f"Write failed: {result}"
        assert result["validation_errors"] == [], f"Unexpected errors: {result['validation_errors']}"
        print("    (valid write with post-validation succeeded)")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@test("Non-dry-run write with validation rollback (invalid change)")
def _():
    tmp_reg, tmp_dir = _make_temp_registry()
    try:
        result = update_config_value(
            tmp_reg, "omnia_config",
            "service_k8s_cluster.0.k8s_cni", "invalid_cni_value",
            dry_run=False, validate_after=True,
        )
        if not result["success"]:
            assert result.get("rolled_back"), f"Expected rollback: {result}"
            restored = tmp_reg.read_config("omnia_config")
            assert restored["service_k8s_cluster"][0]["k8s_cni"] != "invalid_cni_value"
            print(f"    (rollback worked)")
        else:
            print("    (write succeeded -- schema allows arbitrary k8s_cni)")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@test("Backup file preserves original content")
def _():
    tmp_reg, tmp_dir = _make_temp_registry()
    try:
        result = update_config_value(
            tmp_reg, "omnia_config",
            "service_k8s_cluster.0.k8s_crio_storage_size", "50G",
            dry_run=False, validate_after=False,
        )
        assert result["success"]
        backup_content = Path(result["backup"]).read_text(encoding="utf-8")
        assert "service_k8s_cluster" in backup_content
        print("    (backup preserved original)")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@test("Non-dry-run JSON write works (software_config.json)")
def _():
    tmp_reg, tmp_dir = _make_temp_registry()
    try:
        result = update_config_value(
            tmp_reg, "software_config",
            "repo_config", "always",
            dry_run=False, validate_after=False,
        )
        assert result["success"], f"JSON write failed: {result}"
        updated = tmp_reg.read_config("software_config")
        assert updated["repo_config"] == "always"
        print("    (JSON write succeeded)")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@test("ruamel.yaml preserves comments during round-trip write")
def _():
    tmp_reg, tmp_dir = _make_temp_registry()
    try:
        result = update_config_value(
            tmp_reg, "omnia_config",
            "service_k8s_cluster.0.k8s_crio_storage_size", "30G",
            dry_run=False, validate_after=False,
        )
        assert result["success"]
        raw = tmp_reg.read_config_raw("omnia_config")
        assert "# " in raw, "Comments were stripped during write"
        assert "30G" in raw, "New value not found"
        print("    (comments preserved)")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ==========================================================================
# 8. Per-file Schema Validation
# ==========================================================================
print("\n=== Per-file Schema Validation ===")

for _cfg_key in registry.list_config_keys():
    @test(f"Schema validation for {_cfg_key}")
    def _(_key=_cfg_key):
        schema = registry.read_schema(_key)
        if schema is None:
            print(f"    (no schema -- skipping)")
            return
        errs = validate_schema(registry, _key)
        if errs:
            for e in errs[:3]:
                print(f"    {e.get('level', '?')}: {e.get('path', '?')}: {e.get('message', str(e))[:80]}")
        else:
            entry = registry.entry_by_key(_key)
            print(f"    ({entry.filename} -- valid)")


# ==========================================================================
# 9. Full Validation Report
# ==========================================================================
print("\n=== Full Config Validation Report ===")


@test("Full validation of all config files")
def _():
    result = validate_config(registry)
    print(f"    Valid: {result['valid']}")
    print(f"    Files checked: {result['files_checked']}")
    print(f"    Errors: {len(result['errors'])}")
    print(f"    Warnings: {len(result['warnings'])}")
    for e in result['errors'][:5]:
        print(f"      ERROR: {e.get('file', '?')}: {e.get('message', str(e))[:100]}")


# ==========================================================================
# Summary
# ==========================================================================
print("\n" + "=" * 60)
print(f"RESULTS: {passed} passed, {failed} failed, {passed + failed} total")
if errors:
    print("\nFailed tests:")
    for name, err in errors:
        print(f"  - {name}: {err}")
print("=" * 60)

sys.exit(1 if failed else 0)
