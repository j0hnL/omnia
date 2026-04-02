"""
Configuration Registry for Omnia MCP Server.

Maintains the mapping between config file names, their filesystem paths,
associated JSON schemas, validation tags, and cross-file references.
This mirrors the structure defined in:
  common/library/module_utils/input_validation/common_utils/config.py
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ConfigEntry:
    """Metadata for a single Omnia configuration file."""

    key: str                          # e.g. "omnia_config"
    filename: str                     # e.g. "omnia_config.yml"
    description: str
    schema_filename: str | None       # e.g. "omnia_config.json"
    tags: list[str] = field(default_factory=list)


# The canonical set of Omnia config files, mirroring config.py `files` dict.
CONFIG_ENTRIES: list[ConfigEntry] = [
    ConfigEntry(
        key="omnia_config",
        filename="omnia_config.yml",
        description="Slurm and Kubernetes cluster parameters (cluster names, CNI, CIDRs, NFS, CSI drivers)",
        schema_filename="omnia_config.json",
        tags=["scheduler", "slurm", "service_k8s", "all"],
    ),
    ConfigEntry(
        key="network_spec",
        filename="network_spec.yml",
        description="Admin and InfiniBand network definitions (NICs, IPs, DNS, NTP)",
        schema_filename="network_spec.json",
        tags=["provision", "prepare_oim", "all"],
    ),
    ConfigEntry(
        key="software_config",
        filename="software_config.json",
        description="OS type/version, repo policy, and list of software packages to deploy",
        schema_filename="software_config.json",
        tags=["software_config", "scheduler", "provision", "local_repo", "prepare_oim", "all"],
    ),
    ConfigEntry(
        key="provision_config",
        filename="provision_config.yml",
        description="PXE mapping file path, language, DHCP lease time for OS provisioning",
        schema_filename="provision_config.json",
        tags=["build_image", "provision", "all"],
    ),
    ConfigEntry(
        key="storage_config",
        filename="storage_config.yml",
        description="NFS client mounts and PowerVault iSCSI configuration",
        schema_filename="storage_config.json",
        tags=["slurm", "service_k8s", "storage", "all"],
    ),
    ConfigEntry(
        key="high_availability_config",
        filename="high_availability_config.yml",
        description="Kubernetes HA and virtual IP settings for service clusters",
        schema_filename="high_availability_config.json",
        tags=["service_k8s", "all"],
    ),
    ConfigEntry(
        key="security_config",
        filename="security_config.yml",
        description="LDAP connection type (TLS/SSL) for OpenLDAP",
        schema_filename="security_config.json",
        tags=["security", "all"],
    ),
    ConfigEntry(
        key="telemetry_config",
        filename="telemetry_config.yml",
        description="iDRAC telemetry, VictoriaMetrics, Kafka, LDMS settings",
        schema_filename="telemetry_config.json",
        tags=["telemetry", "all"],
    ),
    ConfigEntry(
        key="local_repo_config",
        filename="local_repo_config.yml",
        description="User repo URLs, RHEL OS repo URLs for x86_64 and aarch64",
        schema_filename="local_repo_config.json",
        tags=["local_repo", "all"],
    ),
    ConfigEntry(
        key="build_stream_config",
        filename="build_stream_config.yml",
        description="Build stream configuration for OIM image builds",
        schema_filename="build_stream_config.json",
        tags=["build_stream", "prepare_oim", "gitlab", "all"],
    ),
    ConfigEntry(
        key="gitlab_config",
        filename="gitlab_config.yml",
        description="GitLab integration configuration for CI/CD pipelines",
        schema_filename="gitlab_config.json",
        tags=["gitlab", "all"],
    ),
]


# Cross-file reference rules: (source_file, source_key) must match (target_file, target_key)
# These encode the consistency constraints scattered across Omnia's docs.
CROSS_FILE_REFS: list[dict[str, str]] = [
    {
        "description": "service_k8s nfs_storage_name must match an nfs_name in storage_config",
        "source_file": "omnia_config.yml",
        "source_path": "service_k8s_cluster[*].nfs_storage_name",
        "target_file": "storage_config.yml",
        "target_path": "nfs_client_params[*].nfs_name",
    },
    {
        "description": "slurm nfs_storage_name must match an nfs_name in storage_config",
        "source_file": "omnia_config.yml",
        "source_path": "slurm_cluster[*].nfs_storage_name",
        "target_file": "storage_config.yml",
        "target_path": "nfs_client_params[*].nfs_name",
    },
    {
        "description": "HA cluster_name must match a service_k8s_cluster entry with deployment=true",
        "source_file": "high_availability_config.yml",
        "source_path": "service_k8s_cluster_ha[*].cluster_name",
        "target_file": "omnia_config.yml",
        "target_path": "service_k8s_cluster[*].cluster_name",
    },
    {
        "description": "Software names in software_config.json must align with available validation tags",
        "source_file": "software_config.json",
        "source_path": "softwares[*].name",
        "target_file": "omnia_config.yml",
        "target_path": "(informational: service_k8s_cluster and slurm_cluster must exist if referenced)",
    },
]

# Expected software versions from config.py — used for documentation
EXPECTED_VERSIONS: dict[str, str] = {
    "amdgpu": "6.3.1",
    "cuda": "12.9.1",
    "ofed": "24.10-1.1.4.0",
    "beegfs": "7.4.5",
    "intel_benchmarks": "2024.1.0",
    "ucx": "1.19.0",
    "openmpi": "5.0.8",
    "csi_driver_powerscale": "v2.15.0",
    "rocm": "6.3.1",
    "service_k8s": "1.34.1",
}

# Password fields that should never be exposed in plain text
PASSWORDS_SET: set[str] = {
    "slurm_db_password",
    "directory_manager_password",
    "kerberos_admin_password",
    "openldap_db_password",
    "openldap_config_password",
    "openldap_monitor_password",
    "timescaledb_password",
    "idrac_password",
    "mysqldb_password",
    "mysqldb_root_password",
    "grafana_password",
    "provision_password",
    "postgres_password",
    "bmc_password",
    "switch_snmp3_password",
    "docker_password",
}

# Supported OS versions
OS_VERSION_RANGES: dict[str, list[str]] = {
    "rhel": ["10.0", "10.1"],
}


# ---------------------------------------------------------------------------
# Registry class
# ---------------------------------------------------------------------------

class ConfigRegistry:
    """
    Discovers and indexes Omnia config files, JSON schemas, and their
    relationships within a given project input directory.
    """

    def __init__(self, omnia_root: str | Path):
        self.omnia_root = Path(omnia_root)
        self.input_dir = self.omnia_root / "input"
        self.schema_dir = (
            self.omnia_root
            / "common"
            / "library"
            / "module_utils"
            / "input_validation"
            / "schema"
        )
        self._entries: dict[str, ConfigEntry] = {e.key: e for e in CONFIG_ENTRIES}

    # -- Lookup helpers -----------------------------------------------------

    @property
    def entries(self) -> dict[str, ConfigEntry]:
        return dict(self._entries)

    def entry_by_filename(self, filename: str) -> ConfigEntry | None:
        for e in self._entries.values():
            if e.filename == filename:
                return e
        return None

    def entry_by_key(self, key: str) -> ConfigEntry | None:
        return self._entries.get(key)

    # -- Path resolution ----------------------------------------------------

    def config_path(self, key: str) -> Path | None:
        """Absolute path to an input config file, or None if not found."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        p = self.input_dir / entry.filename
        return p if p.exists() else None

    def schema_path(self, key: str) -> Path | None:
        """Absolute path to the JSON schema for a config file."""
        entry = self._entries.get(key)
        if entry is None or entry.schema_filename is None:
            return None
        p = self.schema_dir / entry.schema_filename
        return p if p.exists() else None

    # -- I/O ----------------------------------------------------------------

    def read_config(self, key: str) -> dict[str, Any] | list | None:
        """Read and parse a config file (YAML or JSON)."""
        path = self.config_path(key)
        if path is None:
            return None
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            return json.loads(text)
        return yaml.safe_load(text)

    def read_config_raw(self, key: str) -> str | None:
        """Read a config file as raw text (preserving comments)."""
        path = self.config_path(key)
        if path is None:
            return None
        return path.read_text(encoding="utf-8")

    def read_schema(self, key: str) -> dict[str, Any] | None:
        """Read and parse the JSON schema for a config file."""
        path = self.schema_path(key)
        if path is None:
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    # -- Listing ------------------------------------------------------------

    def list_config_keys(self) -> list[str]:
        return list(self._entries.keys())

    def list_available_configs(self) -> list[dict[str, str]]:
        """Return metadata for all config files that exist on disk."""
        results = []
        for key, entry in self._entries.items():
            path = self.config_path(key)
            results.append({
                "key": key,
                "filename": entry.filename,
                "description": entry.description,
                "exists": path is not None,
                "path": str(path) if path else str(self.input_dir / entry.filename),
                "has_schema": self.schema_path(key) is not None,
                "tags": entry.tags,
            })
        return results

    # -- Cross-file references ----------------------------------------------

    def get_cross_refs(self) -> list[dict[str, str]]:
        return list(CROSS_FILE_REFS)

    # -- Metadata -----------------------------------------------------------

    def get_expected_versions(self) -> dict[str, str]:
        return dict(EXPECTED_VERSIONS)

    def get_os_version_ranges(self) -> dict[str, list[str]]:
        return dict(OS_VERSION_RANGES)
