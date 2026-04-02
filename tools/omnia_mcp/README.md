# Omnia MCP Server — Configuration Assistant

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server that exposes Dell Omnia's configuration files as resources and provides tools for AI-assisted cluster configuration management.

## Overview

Omnia requires coordinating 11+ interrelated YAML/JSON configuration files to provision and manage HPC/AI clusters. This MCP server lets any MCP-compatible AI agent (Claude, Copilot, Windsurf, etc.) read, validate, explain, update, and generate these configurations with full schema awareness and cross-file consistency checking.

## Architecture

```
┌──────────────────────┐
│   MCP Client (LLM)   │  Claude Desktop / Windsurf / any MCP client
└──────────┬───────────┘
           │ MCP Protocol (stdio or SSE)
           ▼
┌──────────────────────┐
│  omnia_mcp/server.py │  Resources + Tools
├──────────────────────┤
│  config_registry.py  │  File discovery, schema loading, cross-ref maps
│  schema_docs.py      │  Documentation extraction (JSON Schema + YAML comments)
│  validators.py       │  L1 schema + L2 cross-file + password exposure checks
│  config_mutator.py   │  Safe mutation with backup/rollback, generation from intent
└──────────┬───────────┘
           │ reads/writes
           ▼
┌──────────────────────┐
│  input/*.yml / .json │  Omnia configuration files
│  common/.../schema/  │  JSON Schema definitions
└──────────────────────┘
```

## Resources (Read-Only)

| URI | Description |
|-----|-------------|
| `omnia://inventory` | List of all config files with metadata |
| `omnia://config/{key}` | Raw config file contents (YAML/JSON) |
| `omnia://config/{key}/parsed` | Parsed config as structured JSON |
| `omnia://schema/{key}` | JSON Schema for a config file |

**Config keys**: `omnia_config`, `network_spec`, `software_config`, `provision_config`, `storage_config`, `high_availability_config`, `security_config`, `telemetry_config`, `local_repo_config`, `build_stream_config`, `gitlab_config`

## Tools

### `validate_config`
Run L1 JSON Schema validation and L2 cross-file consistency checks.

```json
{"config_key": "omnia_config"}
{"tags": ["service_k8s"]}
{"use_ansible": true}
```

### `update_config`
Safely mutate a config value with automatic backup, post-write validation, and rollback on failure.

```json
{
  "config_key": "omnia_config",
  "key_path": "service_k8s_cluster.0.k8s_cni",
  "value": "flannel",
  "dry_run": true
}
```

### `explain_config`
Get documentation for a parameter or entire config file, combining JSON Schema metadata with YAML comment descriptions.

```json
{"config_key": "omnia_config", "parameter": "k8s_cni"}
{"config_key": "network_spec"}
```

### `generate_config`
Generate consistent config fragments from high-level intent.

```json
{
  "cluster_name": "my_cluster",
  "pod_external_ip_range": "10.11.0.100-10.11.0.150",
  "nfs_server_ip": "172.16.107.121",
  "nfs_share_path": "/mnt/share/omnia_k8s",
  "enable_ha": true,
  "virtual_ip": "172.16.107.1",
  "admin_ip": "172.16.107.254"
}
```

### `list_configs`
List all available configuration files with paths, tags, and schema availability.

### `get_cross_refs`
Show cross-file dependency rules (e.g., `nfs_storage_name` in omnia_config must match `nfs_name` in storage_config).

## Installation

```bash
cd tools/omnia_mcp
pip install -r requirements.txt
```

## Usage

### stdio transport (default — for Claude Desktop, Windsurf, etc.)

```bash
# Set OMNIA_ROOT if not running from the omnia project directory
export OMNIA_ROOT=/path/to/omnia

python -m omnia_mcp
```

### SSE transport (for HTTP-based MCP clients)

```bash
pip install 'mcp[sse]' starlette uvicorn
python -m omnia_mcp --sse --port 8080
```

## MCP Client Configuration

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "omnia": {
      "command": "python",
      "args": ["-m", "omnia_mcp"],
      "env": {
        "OMNIA_ROOT": "/path/to/omnia"
      }
    }
  }
}
```

### Windsurf / Codeium

Add to your MCP server configuration:

```json
{
  "omnia": {
    "command": "python",
    "args": ["-m", "omnia_mcp"],
    "cwd": "/path/to/omnia/tools/omnia_mcp"
  }
}
```

## Validation Tags

Tags control which config files are validated together:

| Tag | Files |
|-----|-------|
| `scheduler` | software_config, omnia_config |
| `provision` | provision_config, network_spec, software_config |
| `security` | security_config |
| `telemetry` | telemetry_config |
| `local_repo` | local_repo_config, software_config |
| `slurm` | omnia_config, storage_config |
| `service_k8s` | omnia_config, storage_config, high_availability_config |
| `storage` | storage_config |
| `prepare_oim` | network_spec, software_config, build_stream_config |
| `build_stream` | build_stream_config |
| `gitlab` | gitlab_config, build_stream_config |
| `all` | All config files |

## Cross-File Consistency Rules

The server enforces these cross-file constraints:

1. **`service_k8s_cluster[*].nfs_storage_name`** in `omnia_config.yml` must match an `nfs_client_params[*].nfs_name` in `storage_config.yml`
2. **`slurm_cluster[*].nfs_storage_name`** in `omnia_config.yml` must match an `nfs_client_params[*].nfs_name` in `storage_config.yml`
3. **`service_k8s_cluster_ha[*].cluster_name`** in `high_availability_config.yml` must match a `service_k8s_cluster[*].cluster_name` in `omnia_config.yml`

## Development

```bash
# Run with debug logging
python -m omnia_mcp --log-level DEBUG

# Run tests
python tools/omnia_mcp/tests/test_all.py
```
