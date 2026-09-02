#!/usr/bin/env python3
# Copyright 2026 Dell Inc. or its subsidiaries. All Rights Reserved.
# Licensed under the Apache License, Version 2.0
#
# Diff two package manifests (packages.json) produced by omnia.open_image_builder.
# Shows added, removed, upgraded, and downgraded packages between two image builds.
#
# Usage:
#   python3 tools/diff_manifests.py previous/packages.json current/packages.json
#   python3 tools/diff_manifests.py --json previous/packages.json current/packages.json

import argparse
import json
import sys
from collections import OrderedDict


def load_manifest(path):
    with open(path) as f:
        return json.load(f)


def packages_by_name(manifest):
    pkgs = {}
    for p in manifest.get("packages", []):
        name = p.get("name", "")
        if name:
            pkgs[name] = p
    return pkgs


def version_string(pkg):
    parts = []
    if pkg.get("version"):
        parts.append(pkg["version"])
    if pkg.get("release"):
        parts.append(pkg["release"])
    return "-".join(parts) if parts else "(unknown)"


def diff_manifests(old_manifest, new_manifest):
    old_pkgs = packages_by_name(old_manifest)
    new_pkgs = packages_by_name(new_manifest)

    old_names = set(old_pkgs.keys())
    new_names = set(new_pkgs.keys())

    added = sorted(new_names - old_names)
    removed = sorted(old_names - new_names)
    common = sorted(old_names & new_names)

    upgraded = []
    downgraded = []
    for name in common:
        old_ver = version_string(old_pkgs[name])
        new_ver = version_string(new_pkgs[name])
        if old_ver != new_ver:
            upgraded.append({
                "name": name,
                "old_version": old_ver,
                "new_version": new_ver,
            })

    unchanged = len(common) - len(upgraded) - len(downgraded)

    return {
        "old_image": old_manifest.get("image", "unknown"),
        "new_image": new_manifest.get("image", "unknown"),
        "old_date": old_manifest.get("build_date", "unknown"),
        "new_date": new_manifest.get("build_date", "unknown"),
        "old_count": old_manifest.get("package_count", len(old_pkgs)),
        "new_count": new_manifest.get("package_count", len(new_pkgs)),
        "added": [{"name": n, "version": version_string(new_pkgs[n])} for n in added],
        "removed": [{"name": n, "version": version_string(old_pkgs[n])} for n in removed],
        "upgraded": upgraded,
        "unchanged": unchanged,
    }


def print_diff(diff):
    print(f"Image diff: {diff['new_image']}")
    print(f"  Previous: {diff['old_date']} ({diff['old_count']} packages)")
    print(f"  Current:  {diff['new_date']} ({diff['new_count']} packages)")
    print()

    if diff["upgraded"]:
        print(f"  Upgraded ({len(diff['upgraded'])}):")
        for p in diff["upgraded"]:
            name_pad = p["name"].ljust(30)
            print(f"    {name_pad} {p['old_version']} -> {p['new_version']}")
        print()

    if diff["added"]:
        print(f"  Added ({len(diff['added'])}):")
        for p in diff["added"]:
            print(f"    {p['name']}-{p['version']}")
        print()

    if diff["removed"]:
        print(f"  Removed ({len(diff['removed'])}):")
        for p in diff["removed"]:
            print(f"    {p['name']}-{p['version']}")
        print()

    print(f"  Unchanged: {diff['unchanged']}")

    total_changes = len(diff["upgraded"]) + len(diff["added"]) + len(diff["removed"])
    if total_changes == 0:
        print("\n  No changes detected.")
    else:
        print(f"\n  Total changes: {total_changes}")


def main():
    parser = argparse.ArgumentParser(
        description="Diff two package manifests from omnia.open_image_builder"
    )
    parser.add_argument("old", help="Previous packages.json")
    parser.add_argument("new", help="Current packages.json")
    parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Output as JSON instead of human-readable text"
    )
    args = parser.parse_args()

    old_manifest = load_manifest(args.old)
    new_manifest = load_manifest(args.new)
    diff = diff_manifests(old_manifest, new_manifest)

    if args.json_output:
        json.dump(diff, sys.stdout, indent=2)
        print()
    else:
        print_diff(diff)


if __name__ == "__main__":
    main()
