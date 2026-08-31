#!/bin/bash
# Setup script for testing image_builder on remote system
set -euo pipefail

echo "=== Installing pip ==="
python3 -m ensurepip --user 2>/dev/null || true

echo "=== Installing ansible, pytest, pyyaml ==="
python3 -m pip install --user ansible-core pytest pyyaml

echo "=== Verify installations ==="
~/.local/bin/ansible --version
~/.local/bin/pytest --version
python3 -c "import yaml; print('pyyaml OK')"

echo "=== Check podman and buildah ==="
podman --version
buildah --version

echo "=== Setup complete ==="
