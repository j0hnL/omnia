"""
Validation engine for Omnia MCP Server.

Provides two validation layers that mirror the existing Ansible-based pipeline:
  L1 - JSON Schema validation (using jsonschema library directly)
  L2 - Cross-file logical consistency checks (pure Python, no Ansible dependency)

Additionally supports invoking the full Ansible validation playbook when
running on the OIM container where Ansible is available.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import jsonschema

from omnia_mcp.config_registry import CROSS_FILE_REFS, PASSWORDS_SET, ConfigRegistry


# ---------------------------------------------------------------------------
# L1: JSON Schema Validation
# ---------------------------------------------------------------------------

def validate_schema(
    registry: ConfigRegistry,
    config_key: str,
) -> list[dict[str, Any]]:
    """
    Validate a config file against its JSON schema.
    Returns a list of error dicts; empty list means valid.
    """
    data = registry.read_config(config_key)
    schema = registry.read_schema(config_key)

    if data is None:
        return [{"level": "error", "message": f"Config file not found: {config_key}"}]
    if schema is None:
        return [{"level": "warning", "message": f"No schema found for: {config_key}"}]

    errors: list[dict[str, Any]] = []
    validator = jsonschema.Draft7Validator(schema)
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        errors.append({
            "level": "error",
            "path": ".".join(str(p) for p in error.absolute_path) or "(root)",
            "message": error.message,
            "schema_path": ".".join(str(p) for p in error.schema_path),
            "validator": error.validator,
        })

    return errors


# ---------------------------------------------------------------------------
# L2: Cross-file logical consistency
# ---------------------------------------------------------------------------

def _resolve_jsonpath_simple(data: Any, path: str) -> list[Any]:
    """
    Minimal JSONPath-like resolver.
    Supports: key, key[*].subkey, nested.key
    """
    parts = re.split(r"\[\*\]\.", path, maxsplit=1)

    if len(parts) == 2:
        # Array wildcard: e.g. "service_k8s_cluster[*].nfs_storage_name"
        array_key = parts[0]
        rest = parts[1]
        collection = data.get(array_key, [])
        if not isinstance(collection, list):
            return []
        results = []
        for item in collection:
            results.extend(_resolve_jsonpath_simple(item, rest))
        return results

    # Simple dotted path
    keys = path.split(".")
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list):
            try:
                current = current[int(key)]
            except (ValueError, IndexError):
                return []
        else:
            return []
        if current is None:
            return []

    if isinstance(current, list):
        return current
    return [current]


def validate_cross_references(registry: ConfigRegistry) -> list[dict[str, Any]]:
    """
    Check all cross-file reference constraints.
    Returns a list of error dicts; empty means all consistent.
    """
    errors: list[dict[str, Any]] = []

    # Cache loaded configs
    config_cache: dict[str, Any] = {}

    def _load(filename: str) -> Any:
        if filename not in config_cache:
            entry = registry.entry_by_filename(filename)
            if entry:
                config_cache[filename] = registry.read_config(entry.key)
            else:
                config_cache[filename] = None
        return config_cache[filename]

    for ref in CROSS_FILE_REFS:
        # Skip informational-only references
        if ref["target_path"].startswith("(informational"):
            continue

        source_data = _load(ref["source_file"])
        target_data = _load(ref["target_file"])

        if source_data is None:
            errors.append({
                "level": "warning",
                "message": f"Cannot check cross-ref: {ref['source_file']} not found",
                "rule": ref["description"],
            })
            continue
        if target_data is None:
            errors.append({
                "level": "warning",
                "message": f"Cannot check cross-ref: {ref['target_file']} not found",
                "rule": ref["description"],
            })
            continue

        source_values = _resolve_jsonpath_simple(source_data, ref["source_path"])
        target_values = _resolve_jsonpath_simple(target_data, ref["target_path"])

        target_set = set(str(v) for v in target_values if v)

        for sv in source_values:
            if sv and str(sv) not in target_set:
                errors.append({
                    "level": "error",
                    "message": (
                        f"Value '{sv}' in {ref['source_file']} "
                        f"({ref['source_path']}) not found among "
                        f"allowed values {sorted(target_set)} in "
                        f"{ref['target_file']} ({ref['target_path']})"
                    ),
                    "rule": ref["description"],
                })

    return errors


# ---------------------------------------------------------------------------
# L2: Password exposure check
# ---------------------------------------------------------------------------

def validate_no_exposed_passwords(
    registry: ConfigRegistry,
) -> list[dict[str, Any]]:
    """
    Scan all config files for password fields that contain non-empty values.
    These should be encrypted with ansible-vault, not stored in plain text.
    """
    warnings: list[dict[str, Any]] = []

    for key in registry.list_config_keys():
        data = registry.read_config(key)
        if data is None or not isinstance(data, dict):
            continue
        _check_passwords_recursive(data, key, "", warnings)

    return warnings


def _check_passwords_recursive(
    data: Any, config_key: str, prefix: str, warnings: list[dict[str, Any]]
) -> None:
    """Recursively check for exposed password fields."""
    if isinstance(data, dict):
        for k, v in data.items():
            full_path = f"{prefix}.{k}" if prefix else k
            if k in PASSWORDS_SET and v and str(v).strip():
                warnings.append({
                    "level": "warning",
                    "message": (
                        f"Password field '{full_path}' in {config_key} contains a "
                        f"non-empty value. Consider encrypting with ansible-vault."
                    ),
                    "file": config_key,
                    "path": full_path,
                })
            elif isinstance(v, (dict, list)):
                _check_passwords_recursive(v, config_key, full_path, warnings)
    elif isinstance(data, list):
        for i, item in enumerate(data):
            _check_passwords_recursive(item, config_key, f"{prefix}[{i}]", warnings)


# ---------------------------------------------------------------------------
# Combined validation
# ---------------------------------------------------------------------------

def validate_config(
    registry: ConfigRegistry,
    config_key: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """
    Run L1 schema + L2 cross-ref validation.

    Args:
        config_key: Validate a specific config, or None for all.
        tags: If specified, only validate configs matching these tags.

    Returns:
        { "valid": bool, "errors": [...], "warnings": [...], "files_checked": [...] }
    """
    keys_to_check: list[str] = []

    if config_key:
        keys_to_check = [config_key]
    elif tags:
        for key, entry in registry.entries.items():
            if any(t in entry.tags for t in tags):
                keys_to_check.append(key)
    else:
        keys_to_check = registry.list_config_keys()

    all_errors: list[dict[str, Any]] = []
    all_warnings: list[dict[str, Any]] = []
    files_checked: list[str] = []

    for key in keys_to_check:
        entry = registry.entry_by_key(key)
        if entry is None:
            continue
        files_checked.append(entry.filename)

        results = validate_schema(registry, key)
        for r in results:
            if r.get("level") == "warning":
                all_warnings.append({**r, "file": entry.filename})
            else:
                all_errors.append({**r, "file": entry.filename})

    # Cross-file checks (always run when checking multiple files)
    if len(keys_to_check) > 1 or config_key is None:
        xref_results = validate_cross_references(registry)
        for r in xref_results:
            if r.get("level") == "warning":
                all_warnings.append(r)
            else:
                all_errors.append(r)

    # Password exposure checks
    pwd_warnings = validate_no_exposed_passwords(registry)
    all_warnings.extend(pwd_warnings)

    return {
        "valid": len(all_errors) == 0,
        "errors": all_errors,
        "warnings": all_warnings,
        "files_checked": files_checked,
    }


# ---------------------------------------------------------------------------
# Ansible playbook invocation (optional, for full L1+L2 on the OIM host)
# ---------------------------------------------------------------------------

def validate_via_ansible(
    registry: ConfigRegistry,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """
    Invoke the full Ansible validation playbook.
    Only works when running on the OIM container with Ansible installed.

    Returns parsed output from the ansible-playbook run.
    """
    playbook = registry.omnia_root / "input_validation" / "validate_config.yml"
    if not playbook.exists():
        return {"error": f"Playbook not found: {playbook}"}

    cmd = [
        "ansible-playbook",
        str(playbook),
        "-e", f"omnia_base_dir={registry.omnia_root / 'input'}",
    ]
    if tags:
        cmd.extend(["--tags", ",".join(tags)])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(registry.omnia_root),
        )
        return {
            "return_code": result.returncode,
            "stdout": result.stdout[-4000:] if len(result.stdout) > 4000 else result.stdout,
            "stderr": result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr,
            "success": result.returncode == 0,
        }
    except FileNotFoundError:
        return {"error": "ansible-playbook not found. Ansible validation requires the OIM container environment."}
    except subprocess.TimeoutExpired:
        return {"error": "Ansible validation timed out after 120 seconds."}
