# Building Bootable Linux Images in One Command: Inside Omnia Image Builder

*How we built an Ansible collection that turns seven Linux distros into PXE-bootable HPC and AI cluster images — with zero host dependencies, cross-architecture support, and air-gapped builds.*

---

## The Problem Nobody Wants to Talk About

Every HPC and AI cluster starts the same way: someone has to build the OS images.

Not the fun part — not the Slurm configuration, not the GPU driver tuning, not the InfiniBand optimization. The unglamorous, tedious, error-prone process of producing a bootable Linux root filesystem that can be served over PXE to hundreds or thousands of bare-metal nodes.

In most organizations, this process looks like one of these:

- **The golden image.** One engineer manually installs an OS on a reference node, configures it by hand, snapshots the disk, and copies it to a PXE server. Nobody else knows how to reproduce it. When that engineer leaves, the image becomes a black box.

- **The script pile.** A collection of shell scripts accumulated over years, calling `yum install`, `dracut`, `mksquashfs` in sequence, with hardcoded paths and assumptions about the host OS. It works on the build server it was written for. It breaks everywhere else.

- **The heavyweight provisioner.** Deploy Foreman, Cobbler, or MAAS — full lifecycle provisioning platforms that require their own infrastructure, databases, and operational overhead. Overkill when you just need to produce an image.

We built `omnia.image_builder` because we wanted something that didn't exist: a tool that builds production-quality PXE-bootable images from a declarative YAML file, runs on any Linux machine, requires nothing installed beyond `podman` and Ansible, and supports every major distro, architecture, and deployment scenario HPC and AI clusters actually encounter.

## What We Built

The core idea is simple: **containerize everything**.

Instead of requiring the build host to have `dnf`, `debootstrap`, `dracut`, `createrepo`, or any other packaging tool installed, everything is handled by [OpenCHAMI image-thrillhouse](https://github.com/OpenCHAMI/image-thrillhouse) — a purpose-built tool that orchestrates `buildah`, package managers, and image publishing. The build host only needs `podman`, `buildah`, and Ansible. If `image-thrillhouse` isn't installed locally, it runs as a container automatically.

This means you can build a Rocky Linux 10 image from an Ubuntu 24.04 laptop. You can build an AlmaLinux 9 image from a Fedora 42 workstation. The host OS is irrelevant.

### The Architecture

The build pipeline has two Ansible roles backed by image-thrillhouse:

```
┌─────────────────────────────────────────────────────────────────┐
│  Build Host                                                      │
│                                                                  │
│  1. CONFIG_GEN (Ansible role)                                    │
│     Resolve packages, repos, RHEL subscription                   │
│     Generate image-thrillhouse YAML configs:                     │
│       configs/base.yaml          (base image)                    │
│       configs/<fg_name>.yaml     (per-compute-group)             │
│       configs/build_manifest.yml (build order)                   │
│                                                                  │
│  2. BUILD (Ansible role → image-thrillhouse)                     │
│     For each config in build_manifest.yml:                       │
│     ┌─────────────────────────────────────────────────────┐      │
│     │ image-thrillhouse build --config <config>.yaml      │      │
│     │                                                     │      │
│     │  meta:                                              │      │
│     │    name: rocky-x86_64_base                          │      │
│     │    from: scratch                                    │      │
│     │  layer:                                             │      │
│     │    manager: { name: dnf, options: {releasever: 10}} │      │
│     │    repos: [{path: ..., content: ...}]               │      │
│     │    actions: { install: {groups: [...], packages: [..]}│      │
│     │  publish:                                           │      │
│     │    - type: local                                    │      │
│     │    - type: squashfs                                 │      │
│     │    - type: registry  (optional)                     │      │
│     │    - type: s3        (optional)                     │      │
│     └─────────────────────────────────────────────────────┘      │
│     For cross-build: adds --arch aarch64 + QEMU binfmt_misc     │
│                                                                  │
│  3. EXPORT (PXE artifacts)                                       │
│     Extract vmlinuz from /boot/ or /lib/modules/                 │
│     Extract initramfs.img from /boot/                            │
│     Generate manifest.json + SHA256SUMS                          │
│                                                                  │
│  Output: <work_dir>/output/<image>/                              │
│    rootfs          (squashfs, zstd compressed)                   │
│    vmlinuz         (kernel binary)                               │
│    initramfs.img   (dracut initramfs)                            │
└─────────────────────────────────────────────────────────────────┘
```

The `config_gen` role translates your Ansible variables into image-thrillhouse's declarative YAML config format (`meta`/`layer`/`publish` schema). Then `image-thrillhouse` handles everything — package installation, buildah operations, initramfs generation, squashfs export, and optional publishing to registries or S3. The Ansible `build` role simply invokes `image-thrillhouse build` for each config.

### One Command, Seven Operating Systems

```bash
# Rocky Linux 10
ansible-playbook omnia.image_builder.build_x86_64 -e @rocky.yml

# Ubuntu 24.04
ansible-playbook omnia.image_builder.build_x86_64 -e @ubuntu.yml

# RHEL 9.5 (with subscription repos)
ansible-playbook omnia.image_builder.build_x86_64 -e @rhel.yml
```

The collection handles the differences automatically. RPM-based distros (RHEL, AlmaLinux, Rocky, Fedora) use `dnf` + `dracut`. Debian-based distros (Ubuntu, Debian) use `mmdebstrap` + `update-initramfs`. Wolfi uses a parent build from `wolfi-base` with `apk add` commands. The user provides the same YAML structure regardless — `os_family`, `os_version`, `repos`, `base_image_packages` — and the collection selects the right package manager and initramfs tool via image-thrillhouse.

This isn't just convenience. It means the same CI pipeline, the same Argo Workflow, the same operational process can produce images for any supported OS. When your cluster needs to migrate from CentOS to Rocky, or add Ubuntu nodes for a specific workload, you change a YAML file, not your tooling.

## The Parts That Were Hard

### Cross-Architecture Builds

HPC and AI clusters increasingly use ARM64 processors — NVIDIA Grace, AWS Graviton, Ampere Altra. Building ARM64 images traditionally requires ARM64 hardware, which most build environments don't have.

We solved this with **QEMU user-mode emulation**. The `build` role registers QEMU binfmt handlers via `podman run --privileged multiarch/qemu-user-static`, then passes `--arch aarch64` to `image-thrillhouse build`. The entire build runs under transparent emulation — `image-thrillhouse` handles the `dnf` invocation, RPM scriptlet execution, and `dracut` initramfs generation using QEMU's user-mode binary translation.

The download phase runs at native x86_64 speed (the dnf process itself is x86_64). Only RPM post-install scriptlets and `dracut` — which must execute ARM64 binaries — run under emulation at ~4x slower speed.

```bash
# Build ARM64 images on your x86_64 workstation
ansible-playbook omnia.image_builder.build_aarch64 \
  -e @examples/standalone_aarch64_crossbuild.yml
```

### Layered Compute Images

A real HPC cluster doesn't have one image. It has a shared base image (kernel, SSH, networking) and per-role compute images layered on top:

```yaml
compute_images_dict:
  slurm_control_node:
    functional_group: slurm_control_node
    packages: [slurm-slurmctld, slurm-slurmdbd, munge, mariadb-server]
  slurm_node:
    functional_group: slurm_node
    packages: [slurm-slurmd, munge, hwloc, numactl, ucx, pmix]
  gpu_node:
    functional_group: gpu_node
    packages: [slurm-slurmd, munge, nvidia-driver, cuda-toolkit]
```

The `config_gen` role generates a separate image-thrillhouse config for each compute group. Each compute config uses `meta.from:` to reference the base image, so image-thrillhouse layers the role-specific packages on top of the shared base. The output is a set of squashfs files that share the same base but have role-specific packages installed:

```
output/
├── base/                        ← kernel, dracut, SSH, NFS, RDMA
├── slurm_control_node_x86_64/  ← slurmctld + mariadb
├── slurm_node_x86_64/          ← slurmd + hwloc + ucx + pmix
└── gpu_node_x86_64/            ← slurmd + NVIDIA + CUDA
```

This is the image equivalent of multi-stage container builds. Each compute image is self-contained but shares the base layer's kernel and initramfs.

### Air-Gapped Builds

Government, defense, and high-security HPC environments can't reach the internet during builds. The `repo_mirror` role handles this by first syncing upstream RPM repositories to a local directory, rebuilding the repo metadata, and serving the mirror via an nginx container. Then the image build uses only the local mirror — fully disconnected.

```bash
# Phase 1: Sync packages (requires internet)
ansible-playbook omnia.image_builder.build_x86_64 \
  -e @examples/offline_x86_64.yml -e use_local_mirror=true

# Phase 2: Build images (fully offline)
# Same command — the mirror is cached locally
```

## The CI/CD Story

The collection ships with production-ready Argo Workflows manifests for Kubernetes-based CI/CD. A nightly CronWorkflow builds fresh images automatically:

```bash
# One-time setup on a k3s cluster
podman build -t ghcr.io/dell/omnia-image-builder:latest -f argo/Containerfile .
kubectl apply --server-side -k argo/
argo submit argo/workflow.yaml -n image-builder --watch
```

The workflow runs a privileged container (required for `buildah`), mounts a PVC for workspace and output, and builds a complete Rocky/AlmaLinux image in under 7 minutes. The ConfigMap holds all build configuration — OS, repos, packages — as a single YAML file.

RBAC is scoped to the `image-builder` namespace with minimal permissions: read-only access to pods, configmaps, and PVCs, plus write access to Argo's `workflowtaskresults`. No cluster-admin, no cross-namespace access.

## What This Means for HPC and AI

### For HPC Administrators

The "golden image" problem is solved. Image definitions are declarative YAML files that live in version control. Anyone on the team can build, modify, or audit them. When you need to add a package, patch a vulnerability, or upgrade the kernel, you edit a YAML file and re-run the playbook. The result is reproducible and verifiable — every image ships with `manifest.json` (build metadata and SHA256 checksums) and `SHA256SUMS` for integrity verification.

### For AI/ML Infrastructure Teams

GPU node images with CUDA and NVIDIA drivers pre-baked, ARM64 cross-builds for Grace Hopper deployments without ARM build hardware, and layered images that let you maintain a single base while customizing per-workload (training nodes vs. inference nodes vs. data preprocessing nodes).

### For the Open-Source Community

Nothing like this exists as a standalone, portable tool. The closest alternatives are:

| Tool | Limitation |
|---|---|
| **Warewulf** | Tightly coupled to its own provisioning stack |
| **lorax/livemedia-creator** | Fedora/RHEL only, requires matching host OS |
| **live-build** | Debian only |
| **Foreman/Cobbler** | Full provisioning platforms with heavy operational overhead |
| **Packer** | VM images, not bare-metal PXE images |

`omnia.image_builder` fills the gap between "write your own shell scripts" and "deploy an entire provisioning platform." It's an Ansible collection — install it, write a YAML file, run a playbook. If you already use Ansible for cluster management (and in HPC, you almost certainly do), this slots directly into your existing workflow.

## Try It

```bash
# Install
ansible-galaxy collection install omnia.image_builder

# Build a Rocky Linux 10 image
ansible-playbook omnia.image_builder.build_x86_64 \
  -e @examples/standalone_x86_64.yml

# Verify it
tools/validate_image.sh /var/lib/image-builder/output/base
```

The images are at `/var/lib/image-builder/output/`. Serve them over HTTP, point your PXE configuration at them, and boot your cluster.

---

*The `omnia.image_builder` collection is part of the [Omnia](https://github.com/dell/omnia) project by Dell Technologies. It works standalone or integrated with the broader Omnia HPC/AI cluster management platform. Apache 2.0 licensed.*
