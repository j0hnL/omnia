"""
Omnia MCP Server — Configuration Assistant.

Exposes Omnia's input configuration files as MCP resources and provides
tools for validation, mutation, documentation, and generation of cluster
configurations.

Resources (read-only):
  omnia://config/{key}          Raw config file contents
  omnia://config/{key}/parsed   Parsed YAML/JSON as structured data
  omnia://schema/{key}          JSON Schema for a config file
  omnia://inventory             List of all config files and metadata

Tools:
  validate_config     Run L1 schema + L2 cross-file validation
  update_config       Safely mutate a config value with backup + validation
  explain_config      Get documentation for a parameter or entire file
  generate_config     Generate config fragments from high-level intent
  list_configs        List all available configuration files
  get_cross_refs      Show cross-file dependency rules
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    TextContent,
    Tool,
)

from omnia_mcp.config_mutator import generate_config_fragment, update_config_value
from omnia_mcp.config_registry import ConfigRegistry
from omnia_mcp.schema_docs import (
    explain_all_parameters,
    explain_parameter,
)
from omnia_mcp.validators import validate_config, validate_via_ansible

logger = logging.getLogger("omnia_mcp")

# ---------------------------------------------------------------------------
# Resolve the Omnia project root
# ---------------------------------------------------------------------------

def _find_omnia_root() -> Path:
    """
    Determine the Omnia project root directory.

    Resolution order:
      1. OMNIA_ROOT environment variable
      2. Walk up from this file looking for 'input/omnia_config.yml'
      3. Default: /opt/omnia (standard OIM container path)
    """
    env_root = os.environ.get("OMNIA_ROOT")
    if env_root:
        p = Path(env_root)
        if (p / "input" / "omnia_config.yml").exists():
            return p

    # Walk up from this file's directory (tools/omnia_mcp -> tools -> repo root)
    current = Path(__file__).resolve().parent
    for _ in range(6):
        if (current / "input" / "omnia_config.yml").exists():
            return current
        current = current.parent

    # Fallback
    return Path("/opt/omnia")


# ---------------------------------------------------------------------------
# Server factory
# ---------------------------------------------------------------------------

def create_server() -> tuple[Server, ConfigRegistry]:
    """Create and configure the MCP server and its config registry."""

    omnia_root = _find_omnia_root()
    registry = ConfigRegistry(omnia_root)

    server = Server("omnia-config-assistant")

    # -----------------------------------------------------------------------
    # Resources
    # -----------------------------------------------------------------------

    @server.list_resources()
    async def list_resources() -> list[Resource]:
        resources: list[Resource] = []

        # Inventory resource
        resources.append(Resource(
            uri="omnia://inventory",
            name="Config Inventory",
            description="List of all Omnia configuration files with metadata",
            mimeType="application/json",
        ))

        for info in registry.list_available_configs():
            key = info["key"]

            # Raw config resource
            mime = "application/json" if info["filename"].endswith(".json") else "text/yaml"
            resources.append(Resource(
                uri=f"omnia://config/{key}",
                name=info["filename"],
                description=info["description"],
                mimeType=mime,
            ))

            # Parsed config resource
            resources.append(Resource(
                uri=f"omnia://config/{key}/parsed",
                name=f"{info['filename']} (parsed)",
                description=f"Parsed contents of {info['filename']}",
                mimeType="application/json",
            ))

            # Schema resource
            if info["has_schema"]:
                resources.append(Resource(
                    uri=f"omnia://schema/{key}",
                    name=f"{info['filename']} schema",
                    description=f"JSON Schema for {info['filename']}",
                    mimeType="application/json",
                ))

        return resources

    @server.read_resource()
    async def read_resource(uri: str) -> str:
        # Parse URI
        if uri == "omnia://inventory":
            return json.dumps(registry.list_available_configs(), indent=2)

        parts = uri.replace("omnia://", "").split("/")

        if len(parts) >= 2 and parts[0] == "config":
            key = parts[1]
            if len(parts) == 3 and parts[2] == "parsed":
                data = registry.read_config(key)
                if data is None:
                    return json.dumps({"error": f"Config not found: {key}"})
                return json.dumps(data, indent=2, default=str)
            else:
                raw = registry.read_config_raw(key)
                if raw is None:
                    return f"# Config not found: {key}"
                return raw

        if len(parts) >= 2 and parts[0] == "schema":
            key = parts[1]
            schema = registry.read_schema(key)
            if schema is None:
                return json.dumps({"error": f"Schema not found: {key}"})
            return json.dumps(schema, indent=2)

        return json.dumps({"error": f"Unknown resource URI: {uri}"})

    # -----------------------------------------------------------------------
    # Tools
    # -----------------------------------------------------------------------

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="validate_config",
                description=(
                    "Validate Omnia configuration files. Runs L1 JSON Schema "
                    "validation and L2 cross-file consistency checks. "
                    "Can validate a single file, files matching specific tags, "
                    "or all files at once."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "config_key": {
                            "type": "string",
                            "description": (
                                "Specific config to validate (e.g. 'omnia_config', "
                                "'network_spec'). Omit to validate all."
                            ),
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Validation tags to filter which files to check. "
                                "Options: scheduler, provision, security, telemetry, "
                                "local_repo, slurm, service_k8s, storage, prepare_oim, "
                                "build_stream, gitlab, all"
                            ),
                        },
                        "use_ansible": {
                            "type": "boolean",
                            "description": (
                                "If true, invoke the full Ansible validation playbook "
                                "(requires Ansible on the host). Default: false"
                            ),
                            "default": False,
                        },
                    },
                },
            ),
            Tool(
                name="update_config",
                description=(
                    "Update a value in an Omnia configuration file. Creates a "
                    "backup, applies the change, and runs validation. Supports "
                    "dry_run mode to preview changes without writing. "
                    "Automatically rolls back if validation fails."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "config_key": {
                            "type": "string",
                            "description": "Config file to update (e.g. 'omnia_config')",
                        },
                        "key_path": {
                            "type": "string",
                            "description": (
                                "Dot-notation path to the value. Use array indices "
                                "for list items. E.g. 'service_k8s_cluster.0.k8s_cni'"
                            ),
                        },
                        "value": {
                            "description": "New value to set (any JSON type)",
                        },
                        "dry_run": {
                            "type": "boolean",
                            "description": "Preview changes without writing. Default: true",
                            "default": True,
                        },
                    },
                    "required": ["config_key", "key_path", "value"],
                },
            ),
            Tool(
                name="explain_config",
                description=(
                    "Get documentation for a configuration parameter or an entire "
                    "config file. Combines JSON Schema metadata, YAML comment "
                    "descriptions, and cross-file reference information."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "config_key": {
                            "type": "string",
                            "description": "Config file to explain (e.g. 'omnia_config')",
                        },
                        "parameter": {
                            "type": "string",
                            "description": (
                                "Specific parameter name to explain. "
                                "Omit to get docs for the entire file."
                            ),
                        },
                    },
                    "required": ["config_key"],
                },
            ),
            Tool(
                name="generate_config",
                description=(
                    "Generate Omnia configuration fragments from a high-level "
                    "intent description. Produces consistent, cross-referenced "
                    "config snippets for omnia_config, storage_config, HA config, "
                    "network_spec, and software_config."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "cluster_name": {
                            "type": "string",
                            "description": "Name for the K8s service cluster",
                            "default": "service_cluster",
                        },
                        "pod_external_ip_range": {
                            "type": "string",
                            "description": "IP range for LoadBalancer external IPs (e.g. '10.11.0.100-10.11.0.150')",
                        },
                        "nfs_server_ip": {
                            "type": "string",
                            "description": "IP address of the NFS server",
                        },
                        "nfs_share_path": {
                            "type": "string",
                            "description": "NFS export path on the server",
                        },
                        "enable_ha": {
                            "type": "boolean",
                            "description": "Enable Kubernetes HA with virtual IP",
                            "default": False,
                        },
                        "virtual_ip": {
                            "type": "string",
                            "description": "Virtual IP for K8s HA (required if enable_ha is true)",
                        },
                        "admin_ip": {
                            "type": "string",
                            "description": "OIM admin IP address",
                        },
                        "admin_nic": {
                            "type": "string",
                            "description": "OIM NIC name for admin network",
                            "default": "eno1",
                        },
                        "os_type": {
                            "type": "string",
                            "enum": ["rhel"],
                            "default": "rhel",
                        },
                        "os_version": {
                            "type": "string",
                            "default": "10.0",
                        },
                    },
                },
            ),
            Tool(
                name="list_configs",
                description="List all available Omnia configuration files with their metadata, tags, and paths.",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="get_cross_refs",
                description=(
                    "Show cross-file dependency rules. These define which values "
                    "in one config file must match values in another."
                ),
                inputSchema={"type": "object", "properties": {}},
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            result = _dispatch_tool(name, arguments, registry)
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2, default=str),
            )]
        except Exception as e:
            logger.exception("Tool execution failed: %s", name)
            return [TextContent(
                type="text",
                text=json.dumps({"error": str(e)}, indent=2),
            )]

    return server, registry


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

def _dispatch_tool(
    name: str,
    arguments: dict[str, Any],
    registry: ConfigRegistry,
) -> dict[str, Any]:
    """Route a tool call to the appropriate handler."""

    if name == "validate_config":
        if arguments.get("use_ansible"):
            return validate_via_ansible(registry, tags=arguments.get("tags"))
        return validate_config(
            registry,
            config_key=arguments.get("config_key"),
            tags=arguments.get("tags"),
        )

    elif name == "update_config":
        return update_config_value(
            registry,
            config_key=arguments["config_key"],
            key_path=arguments["key_path"],
            value=arguments["value"],
            dry_run=arguments.get("dry_run", True),
        )

    elif name == "explain_config":
        config_key = arguments["config_key"]
        parameter = arguments.get("parameter")
        if parameter:
            return explain_parameter(registry, config_key, parameter)
        return explain_all_parameters(registry, config_key)

    elif name == "generate_config":
        return generate_config_fragment(arguments)

    elif name == "list_configs":
        return {
            "configs": registry.list_available_configs(),
            "omnia_root": str(registry.omnia_root),
        }

    elif name == "get_cross_refs":
        return {"cross_references": registry.get_cross_refs()}

    else:
        return {"error": f"Unknown tool: {name}"}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def main():
    """Run the MCP server over stdio."""
    server, registry = create_server()

    logger.info(
        "Omnia MCP Config Assistant starting — root=%s, configs=%d",
        registry.omnia_root,
        len(registry.list_config_keys()),
    )

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
