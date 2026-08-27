# Omnia Image Builder

Build bootable Linux OS images with a single command. Uses [OpenCHAMI image-thrillhouse](https://github.com/OpenCHAMI/image-thrillhouse) as the core build engine. Supports RHEL, AlmaLinux, Rocky Linux, Fedora, Ubuntu, and Debian. Works on any Linux machine with `podman` and `buildah`.

```bash
ansible-playbook omnia.image_builder.build -e @examples/rocky_x86_64.yml
```

## Getting Started

### Install

```bash
# From Galaxy
ansible-galaxy collection install omnia.image_builder

# From source
cd collections/image_builder && ansible-galaxy collection build
ansible-galaxy collection install omnia-image_builder-1.0.0.tar.gz
```

### Prerequisites

- **Ansible** >= 2.14
- **podman**
- **buildah**
- **image-thrillhouse** *(optional — auto-pulled as a container if not installed)*

That's it. Everything else runs in containers automatically.

### Your first image in 3 steps

**Step 1.** Create a file called `my_images.yml`:

```yaml
os_family: rocky
os_version: "10.0"

repos:
  - name: baseos
    base_url: https://dl.rockylinux.org/pub/rocky/10/BaseOS/x86_64/os
    gpg: ""
  - name: appstream
    base_url: https://dl.rockylinux.org/pub/rocky/10/AppStream/x86_64/os
    gpg: ""

base_image_packages:
  - kernel
  - dracut
  - dracut-live
  - NetworkManager
  - openssh-server
  - chrony
  - sudo
```

**Step 2.** Build:

```bash
ansible-playbook omnia.image_builder.build -e @my_images.yml
```

**Step 3.** Your images are at `/var/lib/image-builder/output/`:

```
output/
└── base/
    ├── rootfs          ← squashfs root filesystem
    ├── vmlinuz         ← kernel
    └── initramfs.img   ← initramfs
```

Serve these files over HTTP and you have PXE-bootable images.

## Supported Operating Systems

| OS | `os_family` | Package manager | Example file |
|---|---|---|---|
| **RHEL** 9/10 | `rhel` | dnf | `examples/standalone_x86_64.yml` |
| **AlmaLinux** 9/10 | `almalinux` | dnf | `examples/almalinux_x86_64.yml` |
| **Rocky Linux** 9/10 | `rocky` | dnf | `examples/rocky_x86_64.yml` |
| **Fedora** 41/42 | `fedora` | dnf | `examples/fedora_x86_64.yml` |
| **Ubuntu** 24.04/22.04 | `ubuntu` | mmdebstrap | `examples/ubuntu_x86_64.yml` |
| **Debian** 12/11 | `debian` | mmdebstrap | `examples/debian_x86_64.yml` |

The collection automatically selects the correct package manager, container
image, package groups, and initramfs tooling for each OS family. RPM-based
distros use `dnf` + `dracut`; Debian-based distros use `mmdebstrap` + `update-initramfs`.

## Examples by Use Case

### I just want a basic bootable image

```bash
ansible-playbook omnia.image_builder.build -e @examples/rocky_x86_64.yml
```

### I want an HPC Slurm cluster

Build role-specific images for your Slurm cluster: controller, compute
nodes, and login nodes each get their own image layered on a shared base.

```yaml
os_family: rocky
os_version: "10.0"
repos:
  - name: baseos
    base_url: https://dl.rockylinux.org/pub/rocky/10/BaseOS/x86_64/os
    gpg: ""
  - name: appstream
    base_url: https://dl.rockylinux.org/pub/rocky/10/AppStream/x86_64/os
    gpg: ""
  - name: epel
    base_url: https://dl.fedoraproject.org/pub/epel/10/Everything/x86_64
    gpg: ""

base_image_packages:
  - kernel
  - dracut
  - dracut-live
  - dracut-network
  - NetworkManager
  - openssh-server
  - openssh-clients
  - chrony
  - sudo
  - iproute
  - iputils
  - nfs-utils
  - libibverbs       # InfiniBand / RDMA
  - rdma-core

compute_images_dict:
  slurm_control_node_x86_64:
    functional_group: slurm_control_node_x86_64
    packages:
      - slurm-slurmctld
      - slurm-slurmdbd
      - munge
      - mariadb-server
      - slurm-slurmrestd
  slurm_node_x86_64:
    functional_group: slurm_node_x86_64
    packages:
      - slurm-slurmd
      - slurm-pam_slurm
      - munge
      - hwloc
      - numactl
      - ucx
      - pmix
  login_node_x86_64:
    functional_group: login_node_x86_64
    packages:
      - slurm
      - munge
      - hwloc
      - environment-modules
      - lmod
  gpu_node_x86_64:
    functional_group: gpu_node_x86_64
    packages:
      - slurm-slurmd
      - munge
      - hwloc
      - numactl
      - ucx
      - pmix
      - nvidia-driver
      - cuda-toolkit
```

```bash
ansible-playbook omnia.image_builder.build -e @slurm_hpc_cluster.yml
```

Output:
```
output/
├── base/                          ← shared base (kernel, dracut, ssh, nfs, RDMA)
├── slurm_control_node_x86_64/    ← slurmctld + slurmdbd + mariadb + REST API
├── slurm_node_x86_64/            ← slurmd + hwloc + ucx + pmix
├── login_node_x86_64/            ← slurm client + modules + lmod
└── gpu_node_x86_64/              ← slurmd + NVIDIA driver + CUDA toolkit
```

### I want ARM images built on my x86_64 machine

```bash
ansible-playbook omnia.image_builder.build_aarch64 \
  -e @examples/standalone_aarch64_crossbuild.yml
```

### I need fully offline/air-gapped builds

```bash
ansible-playbook omnia.image_builder.build_x86_64 \
  -e @examples/offline_x86_64.yml
```

### I want to publish images to S3 for PXE boot

```yaml
publish_s3: true
s3_endpoint: "https://s3.example.com"        # empty = auto-deploy MinIO
```

```bash
# Pass S3 credentials via environment variables (never put them in YAML files)
S3_ACCESS=your_access_key S3_SECRET=your_secret_key \
  ansible-playbook omnia.image_builder.build -e @my_images.yml -e publish_s3=true
```

> **Security**: S3 credentials are passed to `image-thrillhouse` via `S3_ACCESS` and
> `S3_SECRET` environment variables. You can also set `s3_access_id` and `s3_secret_key`
> Ansible vars (via `-e` or vault) and the `build` role forwards them automatically.
> Never commit secrets to version control.

### I want to push images to a container registry

```yaml
registry_url: "registry.example.com:5000"
registry_ns: "my-cluster"
```

### I want to use this inside an Omnia deployment

```bash
ansible-playbook omnia.image_builder.build_x86_64 \
  -e omnia_integration=true \
  -e input_project_dir=/opt/omnia/input
```

### I want to automate image builds with Argo Workflows

The `argo/` directory contains production-ready Kubernetes manifests tested
on k3s + Argo Workflows v4.0.5. Builds complete in **~4.5 minutes**.

```bash
podman build -t ghcr.io/dell/omnia-image-builder:latest -f argo/Containerfile .
kubectl apply --server-side -k argo/
argo submit argo/workflow.yaml -n image-builder --watch
```

Edit `argo/configmap.yaml` to set your OS, repos, and packages. The output
PVC holds squashfs/kernel/initramfs files ready for PXE boot.

See [argo/README.md](argo/README.md) for full setup, k3s notes, and customization.

## How It Works

### What you provide

| Variable | Required? | What it is |
|---|---|---|
| `os_family` | Yes | `rhel`, `almalinux`, `rocky`, `fedora`, `ubuntu`, or `debian` |
| `os_version` | Yes | e.g. `"10.0"`, `"9.5"`, `"42"`, `"24.04"`, `"12"` |
| `repos` | RHEL: No* | List of package repositories (*auto-generated for RHEL, see below*) |
| `base_image_packages` | Yes | List of package names for the base image |
| `compute_images_dict` | No | Per-role package lists for layered images |
| `work_dir` | No | Build workspace (default: `/var/lib/image-builder`) |

### What the collection does

1. **`repo_mirror`** *(if `use_local_mirror=true`)* — downloads RPMs, creates local repo, serves via nginx
2. **`local_storage`** — creates output directory, optionally deploys MinIO
3. **`config_gen`** — resolves packages/repos and generates image-thrillhouse YAML configs
4. **`build`** — invokes `image-thrillhouse build` for each config (base first, then compute images)

The `config_gen` role translates your Ansible variables into the image-thrillhouse
YAML config format (`meta`/`layer`/`publish` schema). The `build` role then
invokes `image-thrillhouse` either as a host binary or via a container.

### What you get

Every image produces these files in `<output_dir>/<image_name>/`:

| File | What it is | Used for |
|---|---|---|
| `rootfs` | SquashFS root filesystem (zstd compressed) | Root filesystem for PXE boot |
| `vmlinuz` | Linux kernel | PXE kernel |
| `initramfs.img` | Initramfs with live + network support | PXE initramfs |
| `manifest.json` | Build metadata: sha256, sizes, OS, build date | Provenance + verification |
| `SHA256SUMS` | Checksums for all output files | `sha256sum -c SHA256SUMS` |

### Validating built images

Verify checksums and optionally boot-test the image under QEMU:

```bash
tools/validate_image.sh /var/lib/image-builder/output/base
```

This checks file presence, verifies SHA256SUMS, confirms the rootfs is a
valid squashfs, and (if `qemu-system-x86_64` is installed) boots the kernel +
initramfs + rootfs to confirm the image reaches a usable state.

## Reference

### Image output & storage

Images are **always** exported to `<work_dir>/output/<image_name>/`.

| `publish_s3` | `s3_endpoint` | What happens |
|---|---|---|
| `false` *(default)* | — | Local export only |
| `true` | your endpoint | Local export + upload to your S3 |
| `true` | *(empty)* | Local export + **auto-deploy MinIO** + upload |

### How images are built (step by step)

Whether building x86_64 natively or aarch64 via cross-build, every image goes
through the same pipeline. The `config_gen` role generates YAML configs, then
the `build` role invokes `image-thrillhouse` which handles package installation,
buildah operations, and publishing.

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
│     │    actions: { install: {groups: [...], packages: [..]} │      │
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

#### Why cross-builds are slower

| Step | x86_64 (native) | aarch64 (cross-build) |
|---|---|---|
| dnf download | Native speed | Native speed (same x86_64 process) |
| dnf RPM scriptlets | Native speed | **QEMU emulated** (depmod, kernel-install, ldconfig) |
| buildah import | Native speed | Native speed |
| dracut | Native speed | **QEMU emulated** |
| mksquashfs | Native speed | Native speed |

The RPM scriptlets (post-install scripts for kernel, systemd, etc.) must run
the target architecture's binaries. On cross-builds, QEMU user-mode emulation
handles this transparently but at ~4× slower speed. The actual package
download and unpacking is always native x86_64 speed because `dnf --forcearch`
only changes the package architecture, not the dnf process itself.

### Offline / air-gapped builds

```bash
ansible-playbook omnia.image_builder.build_x86_64 \
  -e @examples/offline_x86_64.yml
```

First run syncs packages from upstream. Subsequent runs use the cached local mirror
with zero network access.

### Containerized architecture

The host only needs `podman` + `buildah`. Everything else runs in containers:

| What | Container | Purpose |
|---|---|---|
| **Image builds** | `image-thrillhouse` | Core build engine (dnf/apt + buildah + publish) |
| RPM sync + createrepo | `almalinux` (EL) / `fedora` | Offline mirror sync |
| Repo HTTP server | `nginx:alpine` | Serve local RPM mirror |
| QEMU binfmt | `multiarch/qemu-user-static` | ARM emulation setup |
| MinIO S3 | `minio/minio` | Local object store (optional) |
| S3 operations | `minio/mc` | Bucket creation, uploads |

If `image-thrillhouse` is installed as a host binary, it uses host `buildah` directly.
Otherwise, it runs as a privileged container with bind-mounted host directories.

### All variables

<details>
<summary>Click to expand full variable reference</summary>

#### Required

| Variable | Example | Description |
|---|---|---|
| `os_family` | `"rocky"` | OS family: `rhel`, `almalinux`, `rocky`, `fedora`, `ubuntu`, `debian` |
| `os_version` | `"10.0"` | OS version tag (e.g. `"10.0"`, `"9.5"`, `"42"`, `"24.04"`, `"12"`) |
| `base_image_packages` | `["kernel", "dracut", ...]` | List of package names for the base image |
| `repos` | `[{name, base_url, gpg}]` | Package repos (auto-generated for RHEL if not provided) |

#### Optional — general

| Variable | Default | Description |
|---|---|---|
| `target_arch` | `"x86_64"` | Target architecture: `x86_64` or `aarch64` |
| `work_dir` | `"/var/lib/image-builder"` | Build workspace directory (configs, logs, installroots, output) |
| `output_dir` | `"<work_dir>/output"` | Where squashfs/kernel/initramfs are exported |
| `compute_images_dict` | `{}` | Dict of per-role compute image definitions (see Slurm example) |
| `package_groups` | *(auto per OS)* | Override default package groups (e.g. `["Minimal Install"]`) |
| `image_name_suffix` | `""` | Suffix appended to image names (e.g. `"_v2"`, `"_prod"`) |
| `ca_cert_path` | `""` | Path to a CA certificate for self-signed repo certs (empty = skip) |
| `gpg_check` | `true` | Enable RPM GPG signature verification (set `false` only for unsigned repos) |

#### Optional — registry

| Variable | Default | Description |
|---|---|---|
| `registry_url` | `""` | OCI registry URL to push images to (empty = skip publishing) |
| `registry_ns` | `"images"` | Registry namespace / project path |
| `registry_tls_verify` | `true` | Verify TLS certificates on registry push/pull |

#### Optional — S3 publishing

| Variable | Default | Description |
|---|---|---|
| `publish_s3` | `false` | Enable S3 uploads of built images |
| `s3_endpoint` | `""` | S3 endpoint URL (empty = auto-deploy local MinIO container) |
| `s3_bucket` | `"boot-images"` | S3 bucket name for image uploads |

> **Note:** S3 credentials are passed to `image-thrillhouse` via the `S3_ACCESS` and `S3_SECRET`
> environment variables. Set `s3_access_id` and `s3_secret_key` Ansible vars (via `-e` or vault)
> and the `build` role forwards them automatically.

#### Optional — MinIO auto-deploy

| Variable | Default | Description |
|---|---|---|
| `minio_container_name` | `"image-builder-minio"` | Podman container name for MinIO |
| `minio_image` | `"docker.io/minio/minio:latest"` | MinIO container image |
| `minio_data_dir` | `"<work_dir>/minio-data"` | Persistent data directory for MinIO |
| `minio_port` | `9000` | MinIO API port |
| `minio_console_port` | `9001` | MinIO web console port |
| `minio_root_user` | `""` *(auto-generated)* | MinIO root username |
| `minio_root_password` | `""` *(auto-generated)* | MinIO root password |

#### Optional — offline mirror (`repo_mirror` role)

| Variable | Default | Description |
|---|---|---|
| `use_local_mirror` | `false` | Enable local RPM repo mirror (add to playbook invocation) |
| `upstream_repos` | `[]` | Upstream RPM repos to sync from (same format as `repos`) |
| `mirror_packages` | `[]` | Specific packages to download with dependencies |
| `mirror_package_groups` | `["Minimal Install", "Development Tools"]` | DNF package groups to include |
| `mirror_dir` | `"<work_dir>/repo_mirror"` | Directory where RPMs and repo metadata are stored |
| `serve_port` | `8080` | HTTP port for the local nginx repo server |
| `skip_if_cached` | `true` | Skip download if mirror already has RPMs (enables offline re-runs) |
| `repo_container_name` | `"image-builder-repo"` | Podman container name for the nginx repo server |
| `repo_container_image` | `"docker.io/library/nginx:alpine"` | Container image for repo HTTP server |

#### Optional — image export

| Variable | Default | Description |
|---|---|---|
| `squashfs_compression` | `"zstd"` | SquashFS compression algorithm (`zstd`, `gzip`, `lzo`, `xz`) |
| `squashfs_comp_level` | `3` | Compression level (higher = smaller but slower) |

#### Optional — image-thrillhouse builder

| Variable | Default | Description |
|---|---|---|
| `image_thrillhouse_bin` | `"/usr/local/bin/image-thrillhouse"` | Path to image-thrillhouse binary (uses container if not found) |
| `image_thrillhouse_container` | `"ghcr.io/openchami/image-thrillhouse:latest"` | Container image for image-thrillhouse (fallback) |
| `build_log_level` | `"info"` | Log level for image-thrillhouse (`debug`, `info`, `warn`, `error`) |
| `build_retries` | `3` | Number of build retry attempts |
| `build_retry_delay` | `10` | Seconds between retries |

#### Optional — cross-build (aarch64 on x86_64)

| Variable | Default | Description |
|---|---|---|
| `qemu_binfmt_image` | `"docker.io/multiarch/qemu-user-static"` | Container image for QEMU binfmt_misc registration |
| `qemu_skip_if_registered` | `true` | Skip QEMU setup if target arch binfmt is already registered |

#### Optional — RHEL subscription

For `os_family: rhel`, the collection auto-detects RHEL repos in this priority order:
1. User-provided `repos` list (highest priority)
2. `rhel_satellite_url` (auto-generates CDN paths)
3. Entitlement certs in `/etc/pki/entitlement/` (registered system)
4. AlmaLinux fallback (if `rhel_fallback_to_alma: true`)

| Variable | Default | Description |
|---|---|---|
| `rhel_satellite_url` | `""` | Red Hat Satellite/Capsule URL (auto-generates repo paths) |
| `rhel_username` | `""` | RHEL subscription username (for future subscription-manager support) |
| `rhel_password` | `""` | RHEL subscription password |
| `rhel_org_id` | `""` | RHEL organization ID (for activation key auth) |
| `rhel_activation_key` | `""` | RHEL activation key (unattended/CI) |
| `rhel_fallback_to_alma` | `true` | Fall back to AlmaLinux repos if no RHEL credentials found |

Repo entries also support SSL client certificate fields for CDN access:

```yaml
repos:
  - name: baseos
    base_url: "https://cdn.redhat.com/content/dist/rhel10/10.0/x86_64/baseos/os"
    gpg: "file:///etc/pki/rpm-gpg/RPM-GPG-KEY-redhat-release"
    sslclientcert: "/etc/pki/entitlement/1234567890.pem"
    sslclientkey: "/etc/pki/entitlement/1234567890-key.pem"
    sslcacert: "/etc/rhsm/ca/redhat-uep.pem"
```

#### Optional — Omnia integration

| Variable | Default | Description |
|---|---|---|
| `omnia_integration` | `false` | Enable Omnia config file parsing (reads software_config.json etc.) |
| `input_project_dir` | `""` | Path to Omnia input directory containing config files |
| `metadata_file_path` | `"/opt/omnia/offline_repo/.data/localrepo_metadata.yml"` | Omnia local_repo metadata file path |
| `functional_groups_config_path` | `"/opt/omnia/.data/functional_groups_config.yml"` | Omnia functional groups configuration file |
| `enable_build_stream` | `false` | Enable GitLab CI build stream mode |

</details>

### Tested performance

Build host: **Dell PowerEdge** with 2× Intel Xeon Gold 6330 (56 cores / 112 threads @ 2.0 GHz),
377 GB RAM, RHEL 10.0, NVMe storage. Repos accessed over 10 Gbps network.

#### x86_64 image builds

| OS | Build time | rootfs | vmlinuz | initramfs |
|---|---|---|---|---|
| **Rocky 10** | **3m 54s** | 1.1 GB | 16 MB | 219 MB |
| **AlmaLinux 10** | **3m 31s** | 1.1 GB | 16 MB | 220 MB |
| **RHEL 10** | **3m 39s** | 1.1 GB | 16 MB | 220 MB |
| **Fedora 42** | **3m 38s** | 593 MB | 18 MB | 49 MB |

All builds include the packages listed in `base_image_packages` plus
OS-appropriate package groups. Times include package download, install,
dracut initramfs generation, buildah commit, and squashfs export.
Container images are cached for all runs.

RHEL/Rocky/AlmaLinux use "Minimal Install" + "Development Tools" groups.
Fedora uses `c-development` + `development-tools` groups (dnf5 requires
group IDs instead of display names). All OS families produce complete
PXE-bootable images with kernel, initramfs, and rootfs.

#### aarch64 cross-build (on same x86_64 host, no ARM hardware)

| OS | Build time | Image size |
|---|---|---|
| **Rocky 9.5** | **28m 29s** | 2.39 GB (buildah image) |

Cross-builds are ~4× slower than native x86_64 builds because RPM post-install
scriptlets (depmod, kernel-install, ldconfig) run under QEMU aarch64 emulation.
This is still significantly faster than the alternative of maintaining a dedicated
remote ARM build node with NFS and SSH.

#### Argo Workflow (Kubernetes, same host)

| Method | Build time | Notes |
|---|---|---|
| **Argo Workflow** | **4m 28s** | k3s v1.35.5, Argo v4.0.5, Rocky 10, privileged pod |

#### Offline/air-gapped builds (using local RPM mirror)

| OS | First run (sync + build) | Cached rebuild (fully offline) |
|---|---|---|
| **AlmaLinux 10** | 6m 42s | **2m 34s** |

First run syncs all RPMs from upstream repos (including group metadata) and creates
a local nginx-served mirror. Cached rebuilds use only the local mirror — **zero
network access required**.

**Disk space**: Each build uses ~3 GB (installroot + tar + squashfs). The offline
mirror adds ~9 GB for EL repos. Ensure at least **15 GB free** for direct builds
or **25 GB free** for offline builds.

## Collection Structure

```
image_builder/
├── galaxy.yml
├── README.md
├── argo/                 ← Argo Workflows deployment (Containerfile, manifests)
├── examples/
│   ├── rocky_x86_64.yml                    ← Rocky Linux 10
│   ├── almalinux_x86_64.yml               ← AlmaLinux 10
│   ├── fedora_x86_64.yml                   ← Fedora 42
│   ├── ubuntu_x86_64.yml                   ← Ubuntu 24.04
│   ├── debian_x86_64.yml                   ← Debian 12
│   ├── slurm_hpc_cluster.yml             ← HPC Slurm cluster (4 node roles)
│   ├── standalone_x86_64.yml              ← RHEL with direct repos
│   ├── standalone_aarch64_crossbuild.yml  ← ARM cross-build
│   └── offline_x86_64.yml                 ← Air-gapped build
├── playbooks/
│   ├── build.yml                           ← Unified build playbook (preferred)
│   ├── build_x86_64.yml                    ← x86_64 convenience wrapper
│   └── build_aarch64.yml                   ← aarch64 convenience wrapper
├── plugins/
│   ├── modules/                           ← Omnia integration only
│   └── module_utils/
├── roles/
│   ├── config_gen/       ← Generate image-thrillhouse YAML from Omnia vars (NEW)
│   ├── build/            ← Invoke image-thrillhouse CLI to build images (NEW)
│   ├── repo_mirror/      ← Local RPM mirror (containerized reposync + nginx)
│   ├── local_storage/    ← Output directory + optional MinIO S3 auto-deploy
│   ├── fetch_packages/   ← Package list resolution (legacy, replaced by config_gen)
│   ├── image_creation/   ← Direct buildah builds (legacy, replaced by build)
│   └── cross_build/      ← Cross-build via dnf --forcearch (legacy, replaced by build)
├── tools/                ← convert_omnia_config.py, validate_image.sh
├── Makefile              ← Developer tasks (make help)
├── CONTRIBUTING.md       ← Contributor guide
└── tests/                ← pytest test suite
```

## Using with Omnia

This collection is part of the [Dell Omnia](https://github.com/dell/omnia) ecosystem.
The recommended path is to use Omnia's software catalog, which gives you
version-controlled, per-role image definitions from a single config file.

### With Omnia's software catalog (recommended)

If you have an Omnia deployment with `software_config.json`, the collection
reads it directly — no manual package lists needed:

```bash
ansible-playbook omnia.image_builder.build_x86_64 \
  -e omnia_integration=true \
  -e input_project_dir=/opt/omnia/input
```

This automatically:

- Parses `software_config.json` for OS type, version, software bundles, and architectures
- Reads `config/<bundle>/default_packages.json` for base image packages
- Reads `config/<bundle>/<role>.json` for per-role compute packages (Slurm, K8s, etc.)
- Resolves `additional_packages.json` and `admin_debug_packages.json` if enabled
- Uses Omnia's `local_repo` metadata for repo URLs if available

### Convert Omnia config to standalone vars

The `tools/convert_omnia_config.py` script reads your `software_config.json` and
generates a standalone vars file you can use without Omnia at runtime:

```bash
python3 tools/convert_omnia_config.py /opt/omnia/input
```

This produces `image_builder_vars.yml` with all packages extracted from your
Omnia config. Add your repos and build:

```bash
# Edit image_builder_vars.yml to add your repos, then:
ansible-playbook omnia.image_builder.build_x86_64 -e @image_builder_vars.yml
```

Options:

```bash
# Specify output file
python3 tools/convert_omnia_config.py /opt/omnia/input -o my_cluster.yml

# Generate aarch64 vars
python3 tools/convert_omnia_config.py /opt/omnia/input --arch aarch64
```

The converter maps Omnia's software catalog structure to image_builder variables:

| Omnia source | image_builder variable |
|---|---|
| `software_config.json` → `cluster_os_type` | `os_family` |
| `software_config.json` → `cluster_os_version` | `os_version` |
| `config/default_packages.json` RPMs | `base_image_packages` |
| `config/additional_packages.json` RPMs | appended to `base_image_packages` |
| `slurm_custom` → `slurm_node` | `compute_images_dict.slurm_node_x86_64` |
| `slurm_custom` → `slurm_control_node` | `compute_images_dict.slurm_control_node_x86_64` |
| `service_k8s` → `service_kube_node` | `compute_images_dict.service_kube_node_x86_64` |

### Standalone (no Omnia required)

For users without an existing Omnia deployment, provide `repos`,
`base_image_packages`, and `os_family` directly. See the `examples/` directory
for ready-to-use configurations.

### What you gain over Omnia's built-in image builder

| Feature | Omnia built-in | This collection |
|---|---|---|
| OS support | RHEL only | RHEL, AlmaLinux, Rocky, Fedora, Ubuntu, Debian |
| Host dependencies | dnf, mksquashfs, mc on host | Only podman + buildah |
| ARM builds | Remote ARM node via SSH | Cross-build on x86_64 (no ARM hardware) |
| Offline builds | Requires Pulp | Built-in local mirror (containerized nginx) |
| CI/CD | Manual | Argo Workflows, GitOps-ready |
| Infrastructure | Requires OIM + Pulp + registry | No infrastructure required |

## Contributing

We welcome contributions from everyone — whether you're fixing a typo, adding
support for a new OS, building a new role, or improving documentation. This
project is part of the [Dell Omnia](https://github.com/dell/omnia) ecosystem
and follows its open-source values.

### How to contribute

```bash
cd collections/image_builder
make test      # run the 223-test pytest suite
make lint      # yamllint + ansible-lint
make help      # see all developer tasks
```

1. **Fork** the repo and create a feature branch
2. Make your changes in `collections/image_builder/`
3. Run `make test` and `make lint` (CI runs these on every PR)
4. Submit a **pull request** with a clear description of what you changed and why

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide, including how to
add a new OS family and test real builds on hardware.

### What we'd love help with

- **New OS support** — SUSE/openSUSE (zypper), Azure Linux, or other distros
- **New example files** — Kubernetes clusters, AI/ML workloads, scientific computing
- **ARM improvements** — faster cross-build, native ARM CI
- **Testing** — integration tests on real hardware, more QEMU boot validation
- **Documentation** — tutorials, blog posts, video walkthroughs
- **Roles** — new roles for monitoring, configuration management, firmware updates
- **Image signing** — cosign/sigstore integration, SBOM generation

### For AI agents

This collection is designed to be AI-friendly. If you're an AI coding assistant
working on this project:

- The `tests/` directory has pytest tests covering structure, variables,
  modules, OIM leak detection, and dev tooling. Run `make test` before submitting.
- The **core roles** are `config_gen` (generates image-thrillhouse YAML) and
  `build` (invokes the CLI). Legacy roles (`image_creation`, `cross_build`,
  `fetch_packages`) are kept for reference but superseded by the new roles.
- Role defaults are in `roles/<name>/defaults/main.yml` — start there to
  understand what each role does.
- The `examples/` directory shows working configurations for every supported
  workflow. Use them as templates for new features.
- Config templates in `roles/config_gen/templates/` use the image-thrillhouse
  `meta`/`layer`/`publish` YAML schema. Test on a real Linux system with
  `podman`, `buildah`, and `image-thrillhouse` before submitting.

### Code of conduct

This project follows the [Omnia Code of Conduct](https://github.com/dell/omnia/blob/main/CODE_OF_CONDUCT.md).

### Community

- **GitHub Issues**: [dell/omnia/issues](https://github.com/dell/omnia/issues) — bug reports, feature requests
- **Discussions**: [dell/omnia/discussions](https://github.com/dell/omnia/discussions) — questions, ideas, show & tell
- **Omnia project**: [github.com/dell/omnia](https://github.com/dell/omnia) — the full Dell Omnia platform

## License

Apache-2.0 — see [LICENSE](LICENSE) for details.

Built with love by the [Dell Omnia](https://github.com/dell/omnia) team, AI agents, and contributors.
