#!/usr/bin/python
# Copyright 2026 Dell Inc. or its subsidiaries. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Ansible module to collect RPM packages from default_packages.json, additional_packages.json,
and admin_debug_packages.json. Returns a flat list of package names for base image building."""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.omnia.open_image_builder.plugins.module_utils.build_image.common_functions import (
    load_json_file,
    is_additional_packages_enabled,
    is_admin_debug_enabled,
    extract_rpm_package_names,
    deduplicate_list
)


DOCUMENTATION = r"""
---
module: base_image_package_collector
short_description: Collect RPM packages for base image building
description:
  - Reads default_packages.json, additional_packages.json, and admin_debug_packages.json
    to produce a flat, deduplicated list of RPM package names for the base OS image.
options:
  default_json_path:
    description: Path to default_packages.json
    required: true
    type: str
  additional_json_path:
    description: Path to additional_packages.json
    required: false
    type: str
    default: ""
  admin_debug_json_path:
    description: Path to admin_debug_packages.json
    required: false
    type: str
    default: ""
  software_config_path:
    description: Path to software_config.json
    required: true
    type: str
author:
  - Dell Omnia Team
"""

RETURN = r"""
base_image_packages:
  description: Combined deduplicated list of RPM package names
  type: list
  returned: always
"""


def collect_default_packages(json_path, module):
    """Collect RPM package names from default_packages.json."""
    data = load_json_file(json_path, module)
    if not data:
        return []
    default_packages = data.get('default_packages', {})
    cluster_items = default_packages.get('cluster', [])
    return extract_rpm_package_names(cluster_items)


def collect_additional_global_packages(json_path, module):
    """Collect ONLY global RPM package names from additional_packages.json."""
    data = load_json_file(json_path, module)
    if not data:
        return []
    additional_packages = data.get('additional_packages', {})
    global_cluster = additional_packages.get('cluster', [])
    return extract_rpm_package_names(global_cluster)


def collect_admin_debug_packages(json_path, module):
    """Collect RPM package names from admin_debug_packages.json."""
    data = load_json_file(json_path, module)
    if not data:
        return []
    admin_debug_packages = data.get('admin_debug_packages', {})
    cluster_items = admin_debug_packages.get('cluster', [])
    return extract_rpm_package_names(cluster_items)


def run_module():
    """Run the Ansible module."""
    module_args = dict(
        default_json_path=dict(type="str", required=True),
        additional_json_path=dict(type="str", required=False, default=""),
        admin_debug_json_path=dict(type="str", required=False, default=""),
        software_config_path=dict(type="str", required=True),
    )

    result = dict(
        changed=False,
        base_image_packages=[],
        default_packages=[],
        additional_packages=[],
        admin_debug_packages=[]
    )

    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)

    default_json_path = module.params["default_json_path"]
    additional_json_path = module.params["additional_json_path"]
    admin_debug_json_path = module.params["admin_debug_json_path"]
    software_config_path = module.params["software_config_path"]

    software_config = load_json_file(software_config_path, module)

    default_pkgs = collect_default_packages(default_json_path, module)
    result["default_packages"] = default_pkgs

    additional_pkgs = []
    if additional_json_path and is_additional_packages_enabled(software_config):
        additional_pkgs = collect_additional_global_packages(additional_json_path, module)
    result["additional_packages"] = additional_pkgs

    admin_debug_pkgs = []
    if admin_debug_json_path and is_admin_debug_enabled(software_config):
        admin_debug_pkgs = collect_admin_debug_packages(admin_debug_json_path, module)
    result["admin_debug_packages"] = admin_debug_pkgs

    combined = default_pkgs + additional_pkgs + admin_debug_pkgs
    result["base_image_packages"] = deduplicate_list(combined)
    module.exit_json(**result)


def main():
    """Main entry point."""
    run_module()


if __name__ == "__main__":
    main()
