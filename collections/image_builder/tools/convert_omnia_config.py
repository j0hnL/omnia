#!/usr/bin/env python3
"""Convert Omnia software_config.json to standalone image_builder vars.

Reads Omnia's software_config.json and the per-bundle package JSON files
to generate a standalone YAML vars file for omnia.image_builder.

Usage:
    python3 tools/convert_omnia_config.py /opt/omnia/input
    python3 tools/convert_omnia_config.py /opt/omnia/input -o my_cluster.yml
    python3 tools/convert_omnia_config.py /opt/omnia/input --arch aarch64
"""

import argparse
import json
import os
import sys
import yaml


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def extract_rpm_packages(items):
    """Extract RPM package names from a list of package dicts."""
    if not isinstance(items, list):
        return []
    return [
        item["package"]
        for item in items
        if isinstance(item, dict) and item.get("type") == "rpm" and item.get("package")
    ]


def collect_base_packages(input_dir, sw_config):
    """Collect base image packages from default_packages.json and friends."""
    config_dir = os.path.join(input_dir, "config")
    packages = []

    # default_packages.json
    default_path = os.path.join(config_dir, "default_packages.json")
    if os.path.isfile(default_path):
        data = load_json(default_path)
        packages.extend(extract_rpm_packages(data.get("cluster", [])))

    # additional_packages.json (if enabled in software_config)
    softwares = sw_config.get("softwares", [])
    has_additional = any(s.get("name") == "additional_packages" for s in softwares)
    if has_additional:
        additional_path = os.path.join(config_dir, "additional_packages.json")
        if os.path.isfile(additional_path):
            data = load_json(additional_path)
            packages.extend(extract_rpm_packages(data.get("cluster", [])))

    # admin_debug_packages.json (if enabled in software_config)
    has_debug = any(s.get("name") == "admin_debug_packages" for s in softwares)
    if has_debug:
        debug_path = os.path.join(config_dir, "admin_debug_packages.json")
        if os.path.isfile(debug_path):
            data = load_json(debug_path)
            packages.extend(extract_rpm_packages(data.get("cluster", [])))

    return list(dict.fromkeys(packages))


def collect_compute_images(input_dir, sw_config, arch):
    """Collect per-role compute image package lists."""
    config_dir = os.path.join(input_dir, "config")
    compute_images = {}

    # Known bundle keys that map to compute roles
    bundle_keys = {
        "slurm_custom": ["slurm_node", "slurm_control_node", "login_node", "login_compiler_node"],
        "service_k8s": ["service_kube_node", "service_kube_control"],
        "compute_k8s": ["compute_kube_node"],
    }

    softwares = sw_config.get("softwares", [])
    enabled_bundles = {s["name"] for s in softwares if s.get("name")}

    for bundle_name, roles in bundle_keys.items():
        if bundle_name not in enabled_bundles:
            continue

        # Check if this bundle supports the target arch
        bundle_sw = next((s for s in softwares if s.get("name") == bundle_name), {})
        bundle_archs = bundle_sw.get("arch", ["x86_64"])
        if arch not in bundle_archs:
            continue

        # Get roles defined in the bundle
        bundle_roles = sw_config.get(bundle_name, [])
        role_names = [r["name"] for r in bundle_roles if isinstance(r, dict) and r.get("name")]

        for role_name in role_names:
            if role_name not in roles:
                continue

            fg_name = f"{role_name}_{arch}"
            packages = []

            # Load role-specific packages from config/<bundle>/<role>.json
            role_json = os.path.join(config_dir, bundle_name, f"{role_name}.json")
            if os.path.isfile(role_json):
                data = load_json(role_json)
                packages.extend(extract_rpm_packages(data.get("cluster", [])))

            # Also check additional_packages.json for role-specific entries
            additional_path = os.path.join(config_dir, "additional_packages.json")
            if os.path.isfile(additional_path):
                data = load_json(additional_path)
                if role_name in data:
                    role_data = data[role_name]
                    packages.extend(extract_rpm_packages(role_data.get("cluster", [])))

            if packages:
                compute_images[fg_name] = {
                    "functional_group": fg_name,
                    "packages": list(dict.fromkeys(packages)),
                }

    return compute_images


def main():
    parser = argparse.ArgumentParser(
        description="Convert Omnia software_config.json to standalone image_builder vars"
    )
    parser.add_argument(
        "input_dir",
        help="Path to Omnia input directory (contains software_config.json and config/)",
    )
    parser.add_argument(
        "-o", "--output",
        default="image_builder_vars.yml",
        help="Output YAML file (default: image_builder_vars.yml)",
    )
    parser.add_argument(
        "--arch",
        default="x86_64",
        choices=["x86_64", "aarch64"],
        help="Target architecture (default: x86_64)",
    )
    args = parser.parse_args()

    # Load software_config.json
    sw_config_path = os.path.join(args.input_dir, "software_config.json")
    if not os.path.isfile(sw_config_path):
        print(f"Error: {sw_config_path} not found", file=sys.stderr)
        sys.exit(1)

    sw_config = load_json(sw_config_path)

    # Extract OS info
    os_type = sw_config.get("cluster_os_type", "rhel")
    os_version = sw_config.get("cluster_os_version", "10.0")

    # Map Omnia os type to os_family
    os_family_map = {
        "rhel": "rhel",
        "rocky": "rocky",
        "almalinux": "almalinux",
        "fedora": "fedora",
    }
    os_family = os_family_map.get(os_type, "rhel")

    # Collect packages
    base_packages = collect_base_packages(args.input_dir, sw_config)
    compute_images = collect_compute_images(args.input_dir, sw_config, args.arch)

    # Build output vars
    vars_data = {
        "os_family": os_family,
        "os_version": str(os_version),
        "target_arch": args.arch,
    }

    if base_packages:
        vars_data["base_image_packages"] = base_packages

    if compute_images:
        vars_data["compute_images_dict"] = compute_images

    # Write YAML
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(f"# Generated from {sw_config_path}\n")
        f.write(f"# Architecture: {args.arch}\n")
        f.write("# Add your repos below:\n")
        f.write("# repos:\n")
        f.write("#   - name: baseos\n")
        f.write("#     base_url: https://your-mirror/BaseOS/x86_64/os\n")
        f.write("#     gpg: \"\"\n")
        f.write("---\n\n")
        yaml.dump(vars_data, f, default_flow_style=False, sort_keys=False)

    # Summary
    print(f"Converted: {sw_config_path}")
    print(f"OS: {os_family} {os_version} ({args.arch})")
    print(f"Base packages: {len(base_packages)}")
    print(f"Compute roles: {len(compute_images)}")
    for name, data in compute_images.items():
        print(f"  {name}: {len(data['packages'])} packages")
    print(f"Output: {args.output}")
    print()
    print("Next steps:")
    print(f"  1. Edit {args.output} and add your repos")
    print(f"  2. ansible-playbook omnia.image_builder.build_{args.arch} -e @{args.output}")


if __name__ == "__main__":
    main()
