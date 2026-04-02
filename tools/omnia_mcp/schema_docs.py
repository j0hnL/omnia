"""
Schema & Documentation Extractor for Omnia MCP Server.

Provides two complementary documentation sources:
  1. Structured docs from JSON Schema files (property types, enums, patterns, descriptions)
  2. Human-readable docs extracted from YAML comment blocks in input files

Together these let the explain_config tool return rich parameter documentation.
"""

from __future__ import annotations

import re
from typing import Any

from omnia_mcp.config_registry import CROSS_FILE_REFS, ConfigRegistry


# ---------------------------------------------------------------------------
# JSON Schema documentation extraction
# ---------------------------------------------------------------------------

def _flatten_schema_properties(
    schema: dict[str, Any],
    prefix: str = "",
) -> list[dict[str, Any]]:
    """
    Recursively walk a JSON Schema and yield one dict per leaf property with:
      path, type, description, enum, pattern, required, default

    Handles nested objects, arrays, and oneOf/anyOf/allOf branches.
    """
    results: list[dict[str, Any]] = []
    properties = schema.get("properties", {})
    required_keys = set(schema.get("required", []))

    for prop_name, prop_schema in properties.items():
        full_path = f"{prefix}.{prop_name}" if prefix else prop_name
        prop_type = prop_schema.get("type", "")

        if prop_type == "object" and "properties" in prop_schema:
            results.extend(_flatten_schema_properties(prop_schema, full_path))
        elif prop_type == "array" and "items" in prop_schema:
            items = prop_schema["items"]
            if isinstance(items, dict):
                if items.get("type") == "object" and "properties" in items:
                    results.extend(
                        _flatten_schema_properties(items, f"{full_path}[]")
                    )
                elif items.get("type") == "object":
                    # items is an object but properties are inside oneOf/anyOf/allOf
                    found_branch = False
                    for branch_key in ("oneOf", "anyOf", "allOf"):
                        for branch in items.get(branch_key, []):
                            if isinstance(branch, dict) and "properties" in branch:
                                results.extend(
                                    _flatten_schema_properties(branch, f"{full_path}[]")
                                )
                                found_branch = True
                    if not found_branch:
                        results.append(_make_prop_doc(
                            full_path, prop_schema, prop_name in required_keys
                        ))
                else:
                    results.append(_make_prop_doc(
                        full_path, prop_schema, prop_name in required_keys
                    ))
            else:
                results.append(_make_prop_doc(
                    full_path, prop_schema, prop_name in required_keys
                ))
        else:
            # Also walk into oneOf/anyOf/allOf at the property level
            walked_branch = False
            if prop_type == "object" or prop_type == "":
                for branch_key in ("oneOf", "anyOf", "allOf"):
                    for branch in prop_schema.get(branch_key, []):
                        if isinstance(branch, dict) and "properties" in branch:
                            results.extend(
                                _flatten_schema_properties(branch, full_path)
                            )
                            walked_branch = True
            if not walked_branch:
                results.append(_make_prop_doc(
                    full_path, prop_schema, prop_name in required_keys
                ))

    return results


def _make_prop_doc(
    path: str,
    schema: dict[str, Any],
    required: bool,
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "path": path,
        "type": schema.get("type", "unknown"),
        "required": required,
    }
    if "description" in schema:
        doc["description"] = schema["description"]
    if "enum" in schema:
        doc["allowed_values"] = schema["enum"]
    if "pattern" in schema:
        doc["pattern"] = schema["pattern"]
    if "default" in schema:
        doc["default"] = schema["default"]
    if "minLength" in schema:
        doc["min_length"] = schema["minLength"]
    if "minItems" in schema:
        doc["min_items"] = schema["minItems"]
    if "maxLength" in schema:
        doc["max_length"] = schema["maxLength"]
    if "minimum" in schema:
        doc["minimum"] = schema["minimum"]
    if "maximum" in schema:
        doc["maximum"] = schema["maximum"]
    return doc


def schema_docs_for_config(
    registry: ConfigRegistry, config_key: str
) -> list[dict[str, Any]]:
    """
    Return structured property documentation derived from the JSON schema
    for the given config key.
    """
    schema = registry.read_schema(config_key)
    if schema is None:
        return []
    return _flatten_schema_properties(schema)


# ---------------------------------------------------------------------------
# YAML comment documentation extraction
# ---------------------------------------------------------------------------

# Matches lines like:  # param_name: description text
_PARAM_COMMENT_RE = re.compile(
    r"^#\s*[-]?\s*(\w[\w.]*)\s*[:]\s*(.+)$"
)

# Matches section headers like:  # ------- SECTION NAME -------
_SECTION_RE = re.compile(
    r"^#\s*[-=]{3,}\s*(.+?)\s*[-=]{3,}\s*$"
)


def _extract_yaml_comment_docs(text: str) -> list[dict[str, str]]:
    """
    Parse comment blocks from a YAML file and return a list of documentation
    entries with keys: section, parameter, description.
    """
    results: list[dict[str, str]] = []
    current_section = ""

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue

        section_match = _SECTION_RE.match(stripped)
        if section_match:
            current_section = section_match.group(1).strip()
            continue

        param_match = _PARAM_COMMENT_RE.match(stripped)
        if param_match:
            results.append({
                "section": current_section,
                "parameter": param_match.group(1),
                "description": param_match.group(2).strip(),
            })

    return results


def yaml_comment_docs_for_config(
    registry: ConfigRegistry, config_key: str
) -> list[dict[str, str]]:
    """
    Return documentation extracted from YAML comment blocks for a config file.
    """
    raw = registry.read_config_raw(config_key)
    if raw is None:
        return []
    return _extract_yaml_comment_docs(raw)


# ---------------------------------------------------------------------------
# Unified documentation
# ---------------------------------------------------------------------------

def explain_parameter(
    registry: ConfigRegistry,
    config_key: str,
    parameter_name: str,
) -> dict[str, Any]:
    """
    Return combined documentation for a specific parameter, merging
    JSON Schema metadata with YAML comment descriptions.
    """
    result: dict[str, Any] = {
        "config_file": config_key,
        "parameter": parameter_name,
        "found": False,
    }

    # Search schema docs
    for doc in schema_docs_for_config(registry, config_key):
        path_tail = doc["path"].rsplit(".", 1)[-1] if "." in doc["path"] else doc["path"]
        # Also strip [] suffix from array paths
        path_tail = path_tail.rstrip("[]")
        if path_tail == parameter_name or doc["path"] == parameter_name:
            result.update(doc)
            result["found"] = True
            break

    # Enrich with YAML comment docs
    for doc in yaml_comment_docs_for_config(registry, config_key):
        if doc["parameter"] == parameter_name:
            result["comment_description"] = doc["description"]
            result["section"] = doc.get("section", "")
            result["found"] = True
            break

    # Check cross-file references
    entry = registry.entry_by_key(config_key)
    if entry:
        for ref in CROSS_FILE_REFS:
            if (
                entry.filename == ref["source_file"]
                and parameter_name in ref["source_path"]
            ):
                result["cross_reference"] = {
                    "description": ref["description"],
                    "target_file": ref["target_file"],
                    "target_path": ref["target_path"],
                }

    return result


def explain_all_parameters(
    registry: ConfigRegistry, config_key: str
) -> dict[str, Any]:
    """
    Return full documentation for every parameter in a config file.
    """
    entry = registry.entry_by_key(config_key)
    if entry is None:
        return {"error": f"Unknown config key: {config_key}"}

    return {
        "config_key": config_key,
        "filename": entry.filename,
        "description": entry.description,
        "tags": entry.tags,
        "schema_properties": schema_docs_for_config(registry, config_key),
        "comment_docs": yaml_comment_docs_for_config(registry, config_key),
        "cross_references": [
            ref for ref in CROSS_FILE_REFS
            if entry.filename in (ref["source_file"], ref["target_file"])
        ],
    }
