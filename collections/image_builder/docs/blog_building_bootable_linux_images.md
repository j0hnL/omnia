# Building Bootable Linux Images in One Command

*An Ansible collection that turns a YAML file into a PXE-bootable squashfs. Seven distros, two architectures, no root required.*

---

## The Dirty Secret of HPC Cluster Deployments

Nobody brags about their image build process at conferences. That's because
most of them are embarrassing.

The typical HPC image pipeline falls into one of three categories, all bad:

1. **The golden image.** Somebody installed Rocky on a reference node in 2019,
   ran a bunch of `yum install` commands they half-remember, snapshotted the
   disk, and copied it to the PXE server. That person left the company two
   years ago. Nobody touches the image. Nobody *can* touch the image.

2. **The script pile.** Forty shell scripts in a directory called `build_stuff/`,
   written by three different people over five years, with hardcoded paths to
   a build server that was decommissioned in 2023. The scripts work if you
   squint hard enough and happen to be running the exact same RHEL minor
   release as the original author.

3. **The enterprise provisioner.** Foreman, Cobbler, or MAAS — each requiring
   its own database, web UI, and a full-time administrator who becomes the
   single point of failure the "golden image" approach was supposed to avoid.

We built `omnia.open_image_builder` because we wanted to type one command and
get a bootable squashfs. Not "one command after you deploy three services and
configure a database." One actual command.

```bash
ansible-playbook omnia.open_image_builder.build -e @my_image.yml
```

## How It Works

The entire build runs inside containers. The host needs `podman`, `buildah`,
`squashfs-tools`, and Ansible. No root required -- rootless podman works.

[OpenCHAMI image-thrillhouse](https://github.com/OpenCHAMI/image-thrillhouse)
does the heavy lifting — it wraps `buildah` with package manager orchestration
and image publishing. Our Ansible collection generates the config YAML that
drives it and handles the operational details: QEMU setup for cross-builds,
repo mirroring for air-gapped environments, and S3/registry publishing.

The pipeline:

1. **config_gen** — translates your Ansible vars into image-thrillhouse YAML
2. **build** — runs `image-thrillhouse build --config <file>` for each image
3. **export** — pulls kernel + initramfs out of the built image for PXE

You provide `os_family`, `repos`, and `base_image_packages`. The collection
picks the right package manager (`dnf` for RPM, `mmdebstrap` for Debian, `apk`
for Wolfi), generates the correct config, and produces a squashfs.

Seven distros work today: RHEL, AlmaLinux, Rocky, Fedora, Ubuntu, Debian, and
Wolfi. Same YAML structure for all of them. The host OS doesn't matter — build
Rocky images on Ubuntu, build Fedora images on RHEL, nobody cares.

## What It Actually Costs You

Real numbers from a Dell PowerEdge (2x Xeon Gold 6330, NVMe, RHEL 10.2).
Install times below exclude package download -- they reflect what you'd see
with a local repo mirror. Total wall-clock times (with network download)
are shown for reference.

| Image | Install | Dracut | Squashfs | Total (w/ download) | Size | Packages |
|---|---|---|---|---|---|---|
| Rocky 10 base | ~2m | 1m 0s | ~1m | 6m 48s | 865 MB | 436 |
| HPC Scientific | ~3m | 1m 5s | ~1m 20s | 8m 23s | 1.1 GB | 696 |
| GPU Developer (CUDA) | ~4m | 1m 8s | ~3m 40s | 18m 25s | 5.5 GB | 761 |
| Rocky 10 aarch64 (cross) | ~8m | ~6m | ~1m | 21m 23s | 724 MB | 432 |
| Wolfi base | -- | -- | -- | 6m 10s | 39 MB | 15 |

> **Note on timings:** DNF combines download and install into one step, so
> we can't cleanly separate them from a single run. The "Install" column
> estimates the local-mirror case by subtracting observed download overhead.
> The "Total (w/ download)" column is the measured wall-clock time with
> packages fetched over the network. With the `repo_mirror` role serving
> packages from a local nginx container, download time drops to near-zero.

The HPC Scientific image is the interesting one: 1.1 GB for a complete
compute node with gcc, gfortran, OpenMPI, FFTW, HDF5, NetCDF, LAPACK, UCX,
RDMA, Slurm, and Lmod. With a local mirror, that builds in roughly five
minutes.

The GPU image is 5.5 GB because CUDA libraries are ~4 GB. Network download
dominates -- 13 minutes of the 18 minute build is DNF downloading and
installing packages. With a local CUDA mirror, this drops to under 10 minutes.

Wolfi at 39 MB is a different animal entirely -- minimal container base, no
kernel, no compilers. Wolfi's package ecosystem targets cloud-native workloads,
not Fortran and InfiniBand. Good for inference endpoints and monitoring services
running alongside the cluster, not for the nodes running MPI jobs.

## Cross-Architecture Builds Without ARM Hardware

This was the part that took the most iteration to get right.

The goal: build aarch64 images on an x86_64 machine. No ARM build server, no
cross-compilation toolchain, no tears.

The approach: QEMU user-mode emulation. Register binfmt_misc handlers for
aarch64, then let DNF install ARM packages into a scratch container. RPM
scriptlets (depmod, ldconfig, kernel-install) execute aarch64 binaries
transparently under QEMU. dracut runs under emulation too.

The trick is in the DNF config. We don't pass any architecture flag to
image-thrillhouse — it doesn't need to know. The `config_gen` role detects
when `target_arch` differs from the host and injects two lines into the
generated `dnf.conf`:

```ini
[main]
arch=aarch64
ignorearch=True
```

That's it. DNF fetches aarch64 packages, RPM installs them with QEMU handling
the scriptlets, and image-thrillhouse never knows the difference. The download
phase runs at native x86_64 speed. Only the scriptlets and dracut — which must
execute ARM binaries — take the QEMU hit, roughly 3x slower than native.

21 minutes for a full aarch64 image on x86_64 hardware. Not fast, but fast
enough to run nightly in CI without dedicated ARM infrastructure.

**One caveat:** this approach works for scratch builds (RPM-based distros)
because the package manager controls the architecture. For parent-image builds
like Wolfi, cross-arch requires image-thrillhouse's `--manifest` + `--arch`
mode to pull the correct platform variant of the base image.

## Layered Images for Real Clusters

A production HPC cluster doesn't run one image. The Slurm controller needs
`slurmctld` and `mariadb`. Compute nodes need `slurmd`, `hwloc`, `ucx`, and
`pmix`. GPU nodes need all of that plus NVIDIA drivers and CUDA. Login nodes
need `lmod` and `environment-modules`.

The collection handles this with `compute_images_dict`:

```yaml
compute_images_dict:
  slurm_control_node:
    packages: [slurm-slurmctld, slurm-slurmdbd, munge, mariadb-server]
  slurm_node:
    packages: [slurm-slurmd, munge, hwloc, numactl, ucx, pmix]
  gpu_node:
    packages: [slurm-slurmd, munge, nvidia-driver, cuda-toolkit]
```

Each entry gets its own image-thrillhouse config, layered on top of the shared
base. One playbook run, one base image, N compute images. Each is a
self-contained squashfs. The kernel and initramfs are inherited from the base
image -- compute images add only their role-specific packages.

## Air-Gapped Builds

Some environments can't touch the internet. The `repo_mirror` role syncs
upstream repos to a local directory served by nginx in a container. First run
needs the network. After that, zero external access.

```bash
ansible-playbook omnia.open_image_builder.build \
  -e @examples/offline_x86_64.yml -e use_local_mirror=true
```

Budget ~9 GB for the local mirror (BaseOS + AppStream), ~3 GB per built image.

## The Omnia Connection

If you run Dell Omnia, the collection reads your `software_config.json`
directly. It replaces the built-in image builder with seven-distro support,
containerized builds, and cross-architecture ARM — no host-installed `dnf`,
`mksquashfs`, or `mc` required.

If you don't run Omnia, the collection works standalone. No dependency on
Omnia's infrastructure, software catalog, or operational model. Just an
Ansible collection you install from Galaxy.

## No Root Required

The entire pipeline runs under rootless podman. The `--privileged` and
`--user root` flags in the podman invocation operate within a user namespace
-- full capabilities inside the container, zero elevated privileges on the
host. We tested this end-to-end on RHEL 10.2: a regular user builds a Rocky 10
image in 6 minutes, gets a squashfs, kernel, initramfs, and manifest with
verified checksums. No sudo anywhere in the chain.

The one exception is QEMU binfmt_misc registration for cross-architecture
builds, which writes to `/proc/sys/fs/binfmt_misc` and requires real root.
But that's a one-time setup -- ask your admin to run it once and it persists
across reboots.

## What's Left

- **Image signing** — cosign/sigstore integration and SBOM generation
- **More distros** — SUSE/openSUSE, Azure Linux, Alpine
- **Faster cross-builds** — native ARM CI instead of QEMU emulation
- **Boot testing** — automated QEMU boot validation in CI

## Try It

```bash
ansible-galaxy collection install omnia.open_image_builder

ansible-playbook omnia.open_image_builder.build \
  -e @examples/rocky_x86_64.yml
```

Images land in `/var/lib/image-builder/output/`. Serve over HTTP, point PXE
at them, boot your cluster.

---

*`omnia.open_image_builder` is part of [Omnia](https://github.com/dell/omnia)
by Dell Technologies. Apache 2.0.*
