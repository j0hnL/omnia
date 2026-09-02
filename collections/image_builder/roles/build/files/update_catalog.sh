#!/bin/bash
# Copyright 2026 Dell Inc. or its subsidiaries. All Rights Reserved.
# Licensed under the Apache License, Version 2.0
#
# Update image catalog (catalog.json) after a build.
# Usage: update_catalog.sh <catalog_path> <img_name> <packages_json> <squashfs> <channel> <date> <os_family> <os_ver> <arch>

set -euo pipefail

CATALOG="$1"
IMG_NAME="$2"
PACKAGES_JSON="$3"
SQUASHFS="$4"
CHANNEL="${5:-dev}"
BUILD_DATE="${6:-unknown}"
OS_FAMILY="${7:-rhel}"
OS_VERSION="${8:-}"
ARCH="${9:-x86_64}"

# Read package count and kernel version from packages.json
PKG_COUNT=0
KVER="unknown"
if [ -f "$PACKAGES_JSON" ]; then
    PKG_COUNT=$(python3 -c "import json; print(json.load(open('$PACKAGES_JSON')).get('package_count', 0))" 2>/dev/null || echo 0)
    KVER=$(python3 -c "import json; print(json.load(open('$PACKAGES_JSON')).get('kernel_version', 'unknown'))" 2>/dev/null || echo "unknown")
fi

# Get squashfs checksum and size
SQ_SHA=""
SQ_SIZE=0
if [ -f "$SQUASHFS" ]; then
    SQ_SHA=$(sha256sum "$SQUASHFS" | awk '{print $1}')
    SQ_SIZE=$(( $(stat -c%s "$SQUASHFS" 2>/dev/null || echo 0) / 1048576 ))
fi

export CATALOG IMG_NAME CHANNEL BUILD_DATE OS_FAMILY OS_VERSION ARCH KVER PKG_COUNT SQ_SIZE SQ_SHA

python3 << 'PYEOF'
import json, os
from datetime import datetime, timezone

catalog_path = os.environ["CATALOG"]
catalog = {"last_updated": "", "images": []}

if os.path.isfile(catalog_path):
    try:
        with open(catalog_path) as f:
            catalog = json.load(f)
    except Exception:
        pass

entry = {
    "name": os.environ["IMG_NAME"],
    "channel": os.environ["CHANNEL"],
    "build_date": os.environ["BUILD_DATE"],
    "os_family": os.environ["OS_FAMILY"],
    "os_version": os.environ["OS_VERSION"],
    "arch": os.environ["ARCH"],
    "kernel_version": os.environ["KVER"],
    "package_count": int(os.environ.get("PKG_COUNT", "0") or "0"),
    "squashfs_size_mb": int(os.environ.get("SQ_SIZE", "0") or "0"),
    "squashfs_sha256": os.environ.get("SQ_SHA", ""),
}

images = catalog.get("images", [])
updated = False
for i, img in enumerate(images):
    if img.get("name") == entry["name"] and img.get("channel") == entry["channel"]:
        images[i] = entry
        updated = True
        break
if not updated:
    images.append(entry)

catalog["images"] = images
catalog["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

with open(catalog_path, "w") as f:
    json.dump(catalog, f, indent=2)

print(f"Catalog updated: {entry['name']} ({entry['channel']}) - {entry['package_count']} pkgs, {entry['squashfs_size_mb']} MB, kernel {entry['kernel_version']}")
PYEOF
