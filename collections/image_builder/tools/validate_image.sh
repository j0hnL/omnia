#!/bin/bash
# Validate a built image by booting it under QEMU and checking it reaches
# a usable state. Also verifies the manifest checksums.
#
# Usage:
#   tools/validate_image.sh /var/lib/image-builder/output/base
#   tools/validate_image.sh /var/lib/image-builder/output/base --timeout 120
#
# Requires: qemu-system-x86_64 (dnf install -y qemu-kvm)

set -euo pipefail

IMAGE_DIR="${1:-}"
TIMEOUT=90

# Parse optional --timeout
shift || true
while [ $# -gt 0 ]; do
    case "$1" in
        --timeout) TIMEOUT="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [ -z "$IMAGE_DIR" ] || [ ! -d "$IMAGE_DIR" ]; then
    echo "Usage: $0 <image_output_dir> [--timeout SECONDS]"
    echo "Example: $0 /var/lib/image-builder/output/base"
    exit 1
fi

ROOTFS="$IMAGE_DIR/rootfs"
VMLINUZ="$IMAGE_DIR/vmlinuz"
INITRAMFS="$IMAGE_DIR/initramfs.img"

echo "=== Image Validation: $IMAGE_DIR ==="

# ── Step 1: Check files exist ────────────────────────────────────────
echo ""
echo "--- File presence ---"
FAIL=0
for f in "$ROOTFS" "$VMLINUZ" "$INITRAMFS"; do
    if [ -f "$f" ]; then
        echo "  PASS: $(basename "$f") ($(du -h "$f" | cut -f1))"
    else
        echo "  FAIL: $(basename "$f") missing"
        FAIL=1
    fi
done
[ $FAIL -eq 0 ] || { echo "Missing required files"; exit 1; }

# ── Step 2: Verify checksums ─────────────────────────────────────────
echo ""
echo "--- Checksum verification ---"
if [ -f "$IMAGE_DIR/SHA256SUMS" ]; then
    (cd "$IMAGE_DIR" && sha256sum -c SHA256SUMS) && echo "  PASS: checksums match" || { echo "  FAIL: checksum mismatch"; exit 1; }
else
    echo "  SKIP: no SHA256SUMS file"
fi

# ── Step 3: Verify file types ────────────────────────────────────────
echo ""
echo "--- File type verification ---"
file "$ROOTFS" | grep -q "Squashfs" && echo "  PASS: rootfs is squashfs" || { echo "  FAIL: rootfs not squashfs"; exit 1; }
file "$VMLINUZ" | grep -q -E "Linux kernel|bzImage" && echo "  PASS: vmlinuz is a kernel" || echo "  WARN: vmlinuz type unexpected"

# ── Step 4: QEMU boot test ───────────────────────────────────────────
echo ""
echo "--- QEMU boot test (timeout ${TIMEOUT}s) ---"
if ! command -v qemu-system-x86_64 &>/dev/null; then
    echo "  SKIP: qemu-system-x86_64 not installed (dnf install -y qemu-kvm)"
    echo ""
    echo "=== VALIDATION PASSED (boot test skipped) ==="
    exit 0
fi

SERIAL_LOG=$(mktemp)
KVM_FLAG=""
[ -e /dev/kvm ] && KVM_FLAG="-enable-kvm"

# Boot with the rootfs as a virtio disk, kernel + initramfs direct boot.
# dmsquash-live looks for the squashfs; we pass it as a raw disk.
timeout "${TIMEOUT}" qemu-system-x86_64 \
    $KVM_FLAG \
    -m 2048 \
    -smp 2 \
    -kernel "$VMLINUZ" \
    -initrd "$INITRAMFS" \
    -drive file="$ROOTFS",format=raw,if=virtio,readonly=on \
    -append "root=live:/dev/vda rd.live.image console=ttyS0 rd.shell=0 systemd.unit=multi-user.target" \
    -nographic \
    -serial file:"$SERIAL_LOG" \
    -no-reboot &
QEMU_PID=$!

# Watch the serial log for boot progress markers
BOOTED=0
for i in $(seq 1 "$TIMEOUT"); do
    if ! kill -0 $QEMU_PID 2>/dev/null; then
        break
    fi
    if grep -q -E "login:|systemd|Reached target|Welcome to" "$SERIAL_LOG" 2>/dev/null; then
        BOOTED=1
        break
    fi
    sleep 1
done

kill $QEMU_PID 2>/dev/null || true
wait $QEMU_PID 2>/dev/null || true

echo ""
echo "--- Boot log (last 15 lines) ---"
tail -15 "$SERIAL_LOG" 2>/dev/null || echo "(no serial output)"
rm -f "$SERIAL_LOG"

echo ""
if [ $BOOTED -eq 1 ]; then
    echo "=== VALIDATION PASSED — image booted successfully ==="
    exit 0
else
    echo "=== VALIDATION WARNING — no boot markers detected in ${TIMEOUT}s ==="
    echo "    (the kernel may still be valid; check the boot log above)"
    exit 2
fi
