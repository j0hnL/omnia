#!/bin/bash
# Copyright 2026 Dell Inc. or its subsidiaries. All Rights Reserved.
# Licensed under the Apache License, Version 2.0
#
# Extract installed package list from a squashfs image and save as packages.json.
# Usage: extract_packages.sh <squashfs> <output.json> <name> <channel> <date> <os_family> <os_ver> <arch>

set -euo pipefail

SQ="$1"
OUTPUT="$2"
IMG_NAME="$3"
CHANNEL="${4:-dev}"
BUILD_DATE="${5:-unknown}"
OS_FAMILY="${6:-rhel}"
OS_VERSION="${7:-}"
ARCH="${8:-x86_64}"

if [ ! -f "$SQ" ]; then
    echo "No squashfs at $SQ, skipping package manifest"
    exit 0
fi

WORKDIR=$(mktemp -d)
SQROOT=$(mktemp -d)
trap "rm -rf '$WORKDIR'; rm -rf '$SQROOT' 2>/dev/null || true" EXIT

# Extract only RPM database from squashfs
unsquashfs -f -d "$SQROOT" "$SQ" 'var/lib/rpm/*' 2>/dev/null || true

# Get kernel version from lib/modules directory names
unsquashfs -l "$SQ" 2>/dev/null | grep -oP 'lib/modules/\K[^/]+' | sort -Vu > "$WORKDIR/kvers.txt" 2>/dev/null || true

# Try to query the RPM database
RPMDB="$SQROOT/var/lib/rpm"
PKGLIST="$WORKDIR/pkglist.tsv"
touch "$PKGLIST"

if [ -d "$RPMDB" ]; then
    rpm --dbpath "$RPMDB" -qa --queryformat '%{NAME}\t%{VERSION}\t%{RELEASE}\t%{ARCH}\n' 2>/dev/null | \
        sort > "$PKGLIST" || true
fi

# Get kernel version
KVER=$(ls "$SQROOT/lib/modules/" 2>/dev/null | sort -V | tail -1 || \
    tail -1 "$WORKDIR/kvers.txt" 2>/dev/null || echo "unknown")

# Generate packages.json
export PKGLIST OUTPUT IMG_NAME CHANNEL BUILD_DATE OS_FAMILY OS_VERSION ARCH KVER
python3 << 'PYEOF'
import json, os

pkglist_path = os.environ.get("PKGLIST", "")
packages = []
if os.path.isfile(pkglist_path):
    with open(pkglist_path) as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 1 and parts[0]:
                pkg = {"name": parts[0]}
                if len(parts) >= 2 and parts[1]: pkg["version"] = parts[1]
                if len(parts) >= 3 and parts[2]: pkg["release"] = parts[2]
                if len(parts) >= 4 and parts[3]: pkg["arch"] = parts[3]
                packages.append(pkg)

manifest = {
    "image": os.environ.get("IMG_NAME", "unknown"),
    "channel": os.environ.get("CHANNEL", "dev"),
    "build_date": os.environ.get("BUILD_DATE", "unknown"),
    "os_family": os.environ.get("OS_FAMILY", "rhel"),
    "os_version": os.environ.get("OS_VERSION", ""),
    "arch": os.environ.get("ARCH", "x86_64"),
    "kernel_version": os.environ.get("KVER", "unknown"),
    "package_count": len(packages),
    "packages": packages
}

output_path = os.environ.get("OUTPUT", "/dev/stdout")
with open(output_path, "w") as f:
    json.dump(manifest, f, indent=2)

print(f"Package manifest: {len(packages)} packages, kernel {manifest['kernel_version']}")
PYEOF
