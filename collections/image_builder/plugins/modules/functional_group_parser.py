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

"""Ansible module to parse functional_groups_config.yml into a flat list of group names."""

import yaml
from ansible.module_utils.basic import AnsibleModule


DOCUMENTATION = r"""
---
module: functional_group_parser
short_description: Parse functional group configuration file
description:
  - Reads a YAML file containing functional group definitions and returns
    a flat list of group name strings.
options:
  functional_groups_file:
    description: Path to the functional_groups_config.yml file
    required: true
    type: str
author:
  - Dell Omnia Team
"""

RETURN = r"""
functional_groups:
  description: Flat list of functional group name strings
  type: list
  returned: always
"""


def normalize_functional_groups(data):
    """
    Accepts either a dict with key 'functional_groups', or a list of
    strings/dicts, and returns a flat list of functional group names.
    """
    if data is None:
        return []

    if isinstance(data, str):
        try:
            data = yaml.safe_load(data)
        except Exception:
            return []

    if isinstance(data, dict):
        functional_groups = data.get("functional_groups", [])
    else:
        functional_groups = data

    if not isinstance(functional_groups, list):
        return []

    names = []
    for fg in functional_groups:
        if isinstance(fg, str):
            names.append(fg)
        elif isinstance(fg, dict) and "name" in fg:
            names.append(fg["name"])
    return names


def get_functional_groups(config_path):
    with open(config_path, "r") as f:
        data = yaml.safe_load(f)
    return normalize_functional_groups(data)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            functional_groups_file=dict(type="str", required=True)
        ),
        supports_check_mode=True,
    )

    config_path = module.params["functional_groups_file"]

    try:
        fg_list = get_functional_groups(config_path)
        module.exit_json(changed=False, functional_groups=fg_list)
    except Exception as e:
        module.fail_json(msg=str(e))


if __name__ == "__main__":
    main()
