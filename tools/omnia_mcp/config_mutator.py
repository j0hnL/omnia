"""
Configuration Mutator for Omnia MCP Server.

Provides safe, schema-aware mutation of Omnia config files:
  - Single-key updates with type coercion and validation
  - Cross-file propagation (e.g. renaming a cluster propagates to HA config)
  - Full config generation from high-level intent
  - Backup before write, rollback on validation failure

Uses ruamel.yaml to preserve comments and formatting in YAML files.
"""

from __future__ import annotations

import copy
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from omnia_mcp.config_registry import CROSS_FILE_REFS, ConfigRegistry
from omnia_mcp.validators import validate_schema


# ---------------------------------------------------------------------------
# YAML round-trip loader (preserves comments)
# ---------------------------------------------------------------------------

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.default_flow_style = False


def _load_yaml_roundtrip(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return _yaml.load(f)


def _dump_yaml_roundtrip(data: Any, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        _yaml.dump(data, f)


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

def _backup(path: Path) -> Path:
    """Create a timestamped backup of a file before mutating it."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = path.with_suffix(f".{ts}.bak")
    shutil.copy2(path, backup_path)
    return backup_path


# ---------------------------------------------------------------------------
# Key-path resolution and mutation
# ---------------------------------------------------------------------------

def _set_nested(data: Any, key_path: str, value: Any) -> bool:
    """
    Set a value in a nested dict/list structure using dot-notation with
    optional array indexing: e.g. "service_k8s_cluster.0.engine"

    Returns True if the key was set successfully.
    """
    parts = key_path.split(".")
    current = data

    for i, part in enumerate(parts[:-1]):
        if isinstance(current, dict):
            if part not in current:
                return False
            current = current[part]
        elif isinstance(current, (list, tuple)):
            try:
                idx = int(part)
                current = current[idx]
            except (ValueError, IndexError):
                return False
        else:
            return False

    final_key = parts[-1]
    if isinstance(current, dict):
        current[final_key] = value
        return True
    elif isinstance(current, (list, tuple)):
        try:
            idx = int(final_key)
            current[idx] = value
            return True
        except (ValueError, IndexError):
            return False
    return False


def _get_nested(data: Any, key_path: str) -> Any:
    """Get a value from a nested dict/list using dot-notation."""
    parts = key_path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, (list, tuple)):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if current is None:
            return None
    return current


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def update_config_value(
    registry: ConfigRegistry,
    config_key: str,
    key_path: str,
    value: Any,
    *,
    validate_after: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Update a single value in a config file.

    Args:
        config_key: Registry key (e.g. "omnia_config")
        key_path: Dot-notation path (e.g. "service_k8s_cluster.0.k8s_cni")
        value: New value to set
        validate_after: Run schema validation after mutation
        dry_run: If True, return what would change without writing

    Returns:
        { "success": bool, "backup": str|None, "old_value": ...,
          "new_value": ..., "validation_errors": [...], "error": str|None }
    """
    path = registry.config_path(config_key)
    entry = registry.entry_by_key(config_key)

    if path is None or entry is None:
        return {"success": False, "error": f"Config not found: {config_key}"}

    # Load with round-trip to preserve comments
    if entry.filename.endswith(".json"):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = _load_yaml_roundtrip(path)

    old_value = _get_nested(data, key_path)
    if old_value is None and "." in key_path:
        return {
            "success": False,
            "error": f"Key path '{key_path}' not found in {entry.filename}",
        }

    if dry_run:
        result: dict[str, Any] = {
            "success": True,
            "dry_run": True,
            "old_value": _serialize(old_value),
            "new_value": _serialize(value),
            "file": entry.filename,
            "key_path": key_path,
        }
        # Check if cross-file propagation would be needed
        propagations = _find_propagations(entry.filename, key_path, value)
        if propagations:
            result["propagations"] = propagations
        return result

    # Mutate in-memory
    if not _set_nested(data, key_path, value):
        return {"success": False, "error": f"Failed to set '{key_path}' in {entry.filename}"}

    # Backup the original file before writing
    backup_path = _backup(path)

    # Write the mutated data
    if entry.filename.endswith(".json"):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    else:
        _dump_yaml_roundtrip(data, path)

    # Post-write validation
    validation_errors: list[dict[str, Any]] = []
    if validate_after:
        validation_errors = validate_schema(registry, config_key)
        if validation_errors:
            # Rollback: restore from backup since the new value broke validation
            shutil.copy2(backup_path, path)
            return {
                "success": False,
                "file": entry.filename,
                "key_path": key_path,
                "old_value": _serialize(old_value),
                "new_value": _serialize(value),
                "backup": str(backup_path),
                "rolled_back": True,
                "error": "Validation failed after write — rolled back to backup",
                "validation_errors": validation_errors,
            }

    # Check if cross-file propagation is needed
    propagations = _find_propagations(entry.filename, key_path, value)

    return {
        "success": True,
        "file": entry.filename,
        "key_path": key_path,
        "old_value": _serialize(old_value),
        "new_value": _serialize(value),
        "backup": str(backup_path),
        "validation_errors": validation_errors,
        "propagations": propagations if propagations else [],
    }


def _serialize(val: Any) -> Any:
    """Ensure a value is JSON-serializable."""
    if hasattr(val, "items"):
        return dict(val)
    if isinstance(val, (list, tuple)):
        return [_serialize(v) for v in val]
    return val


def _find_propagations(
    source_filename: str, key_path: str, new_value: Any
) -> list[dict[str, str]]:
    """
    Check if changing a value in one file requires updates in other files
    based on cross-file reference rules.
    """
    propagations = []
    for ref in CROSS_FILE_REFS:
        # Skip informational-only references
        if ref["target_path"].startswith("(informational"):
            continue
        # Check if the key being changed is the source of a cross-ref
        if ref["source_file"] == source_filename:
            field_name = ref["source_path"].rsplit(".", 1)[-1] if "." in ref["source_path"] else ref["source_path"]
            if field_name in key_path:
                propagations.append({
                    "target_file": ref["target_file"],
                    "target_path": ref["target_path"],
                    "reason": ref["description"],
                    "action": f"Ensure '{new_value}' exists in {ref['target_file']} at {ref['target_path']}",
                })
        # Also check if the key is the target of a cross-ref
        if ref["target_file"] == source_filename:
            field_name = ref["target_path"].rsplit(".", 1)[-1] if "." in ref["target_path"] else ref["target_path"]
            if field_name in key_path:
                propagations.append({
                    "source_file": ref["source_file"],
                    "source_path": ref["source_path"],
                    "reason": ref["description"],
                    "action": f"Values in {ref['source_file']} at {ref['source_path']} reference this field",
                })

    return propagations


# ---------------------------------------------------------------------------
# Config generation from high-level intent
# ---------------------------------------------------------------------------

# Template fragments for common cluster configurations
_K8S_DEFAULTS = {
    "k8s_cni": "calico",
    "k8s_service_addresses": "10.233.0.0/18",
    "k8s_pod_network_cidr": "10.233.64.0/18",
    "k8s_crio_storage_size": "20G",
    "csi_powerscale_driver_secret_file_path": "",
    "csi_powerscale_driver_values_file_path": "",
}


def generate_config_fragment(
    intent: dict[str, Any],
) -> dict[str, Any]:
    """
    Generate config fragments from a high-level intent dict.

    Supported intent keys:
      - cluster_name: str
      - pod_external_ip_range: str (CIDR or range)
      - nfs_server_ip: str
      - nfs_share_path: str
      - enable_ha: bool
      - virtual_ip: str
      - admin_ip: str
      - admin_nic: str
      - os_type: str
      - os_version: str

    Returns a dict with keys for each config file that needs content.
    """
    cluster_name = intent.get("cluster_name", "service_cluster")
    nfs_name = f"nfs_{cluster_name}"

    fragments: dict[str, Any] = {}

    # -- omnia_config.yml fragment --
    k8s_defaults = copy.deepcopy(_K8S_DEFAULTS)
    k8s_entry = {
        "cluster_name": cluster_name,
        **k8s_defaults,
        "deployment": True,
        "pod_external_ip_range": intent.get("pod_external_ip_range", ""),
        "nfs_storage_name": nfs_name,
    }
    fragments["omnia_config"] = {
        "service_k8s_cluster": [k8s_entry],
        "slurm_cluster": [
            {
                "cluster_name": "slurm_cluster",
                "nfs_storage_name": "nfs_slurm",
            }
        ],
    }

    # -- storage_config.yml fragment --
    nfs_ip = intent.get("nfs_server_ip", "")
    nfs_path = intent.get("nfs_share_path", "/mnt/share/omnia_k8s")
    fragments["storage_config"] = {
        "nfs_client_params": [
            {
                "server_ip": nfs_ip,
                "server_share_path": nfs_path,
                "client_share_path": f"/share_{cluster_name}",
                "client_mount_options": "nosuid,rw,sync,hard,intr",
                "nfs_name": nfs_name,
            }
        ]
    }

    # -- high_availability_config.yml fragment --
    if intent.get("enable_ha", False):
        fragments["high_availability_config"] = {
            "service_k8s_cluster_ha": [
                {
                    "cluster_name": cluster_name,
                    "enable_k8s_ha": True,
                    "virtual_ip_address": intent.get("virtual_ip", ""),
                }
            ]
        }

    # -- network_spec.yml fragment --
    if intent.get("admin_ip"):
        fragments["network_spec"] = {
            "Networks": [
                {
                    "admin_network": {
                        "oim_nic_name": intent.get("admin_nic", "eno1"),
                        "netmask_bits": intent.get("netmask_bits", "24"),
                        "primary_oim_admin_ip": intent["admin_ip"],
                        "primary_oim_bmc_ip": "",
                        "dynamic_range": intent.get("dynamic_range", ""),
                        "dns": intent.get("dns", []),
                        "ntp_servers": intent.get("ntp_servers", []),
                    }
                },
                {
                    "ib_network": {
                        "subnet": intent.get("ib_subnet", "192.168.0.0"),
                        "netmask_bits": intent.get("netmask_bits", "24"),
                    }
                },
            ]
        }

    # -- software_config.json fragment --
    fragments["software_config"] = {
        "cluster_os_type": intent.get("os_type", "rhel"),
        "cluster_os_version": intent.get("os_version", "10.0"),
        "repo_config": intent.get("repo_config", "partial"),
        "softwares": [
            {"name": "default_packages", "arch": ["x86_64", "aarch64"]},
            {"name": "service_k8s", "version": "1.34.1", "arch": ["x86_64"]},
        ],
        "service_k8s": [
            {"name": "service_kube_control_plane_first"},
            {"name": "service_kube_control_plane"},
            {"name": "service_kube_node"},
        ],
    }

    return fragments
