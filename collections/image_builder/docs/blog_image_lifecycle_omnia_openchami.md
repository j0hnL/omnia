# Where Images Fit in the HPC and AI System Lifecycle

*Most of the tooling conversation in HPC focuses on scheduling, networking,
and GPU drivers. Nobody talks about images. That's the problem.*

---

## The Lifecycle Nobody Draws on the Whiteboard

Every HPC and AI cluster has a lifecycle. Hardware arrives, gets racked,
gets discovered, gets provisioned, runs workloads, gets patched, and
eventually gets decommissioned. There are mature tools for most of these
stages. Redfish handles discovery. DHCP and PXE handle boot. Slurm and
Kubernetes handle scheduling. Ansible handles configuration. Monitoring
handles observability.

But there's a gap in the middle of the pipeline that most sites fill with
tribal knowledge: **how do you build the OS image that boots on those
nodes?**

Not "how do you serve it" -- PXE and HTTP have that covered. Not "how do
you configure it after boot" -- Ansible and cloud-init handle that. The
specific question of how you go from "I need a bootable root filesystem
with these packages, this kernel, these drivers" to "here is a squashfs
I can put on a PXE server" -- that step is almost always a manual process,
a pile of shell scripts, or a side effect of a monolithic provisioning
platform that bundles image building with everything else.

## What OpenCHAMI Got Right

[OpenCHAMI](https://openchami.org) is a consortium-driven set of
microservices for managing HPC and AI systems. It grew out of Cray's
System Manager (CSM), battle-tested on exascale machines, then
re-engineered as MIT-licensed composable services.

The architecture is deliberately modular:

- **SMD** (State Management Daemon) -- inventory and node state
- **Boot Service / BSS** -- per-node boot parameters (kernel, initrd, root URL)
- **Magellan** -- hardware discovery via Redfish
- **OPAAL** -- OIDC-based authentication
- **Configurator / cloud-init** -- per-node configuration at boot

The key design decision: **OpenCHAMI doesn't build images.** It provisions
them. It tells each node which kernel to load, which initramfs to use, and
where to find the root filesystem. But it expects those artifacts to already
exist somewhere -- served over HTTP, stored in S3, hosted on NFS.

This is the right architectural boundary. Image building is a different
problem with different constraints (package management, chroot environments,
initramfs generation, cross-architecture support). Mixing it into the
provisioning control plane would violate the composability that makes
OpenCHAMI work.

But it means someone has to build those images.

## What Omnia Brings to the Table

[Dell Omnia](https://github.com/dell/omnia) is the operational layer. It
deploys Slurm, Kubernetes, InfiniBand drivers, storage integration, and
telemetry collection via Ansible playbooks. Omnia 2.x added a software
catalog that defines per-role package sets -- what goes on a Slurm controller
vs. a compute node vs. a GPU node vs. a login node.

Omnia has always had image building, but it was tightly coupled to the host:
RHEL-only, required `dnf` and `mksquashfs` installed locally, and didn't
support cross-architecture or air-gapped builds. The software catalog knew
*what* should be in each image, but the *how* of building it was fragile.

## Where `omnia.open_image_builder` Fits

This is the piece that connects Omnia's "what" to OpenCHAMI's "where."

```
                        Omnia software catalog
                            (what to build)
                                 │
                                 ▼
                    ┌───────────────────────┐
                    │ omnia.open_image_builder │
                    │                       │
                    │  config_gen → build    │
                    │                       │
                    │  YAML in → squashfs,  │
                    │  kernel, initramfs out │
                    └───────────┬───────────┘
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
                  HTTP        S3      Registry
                  server    (MinIO)    (OCI)
                    │           │           │
                    └───────────┼───────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │      OpenCHAMI        │
                    │                       │
                    │  BSS/boot-service     │
                    │  "boot this node with │
                    │   kernel X, initrd Y, │
                    │   root=http://Z"      │
                    └───────────┬───────────┘
                                │
                                ▼
                         Bare-metal nodes
```

The collection takes a declarative YAML file -- or reads Omnia's software
catalog directly -- and produces the three artifacts OpenCHAMI needs: a
squashfs root filesystem, a kernel, and an initramfs. It publishes them to
HTTP, S3, or an OCI registry. OpenCHAMI's boot service points nodes at
those URLs. The node boots.

No part of this chain requires the image builder to know about OpenCHAMI's
APIs. No part requires OpenCHAMI to know how the image was built. The
contract is three files and a URL. That's composability.

## Why This Matters More Than It Used To

Three things changed in the last few years that turned image management
from a nuisance into a real engineering problem:

**1. GPU driver versioning became a fleet-wide correctness issue.**

A GPU training job that spans 256 nodes will fail in unpredictable ways if
two nodes have different CUDA driver versions -- NCCL hangs, CUDA API
mismatches, jobs that crash on some nodes and not others. Configuration
drift in the GPU stack turns a routine training run into a debugging
session. The reliable defense is immutable images: every node boots from
the same squashfs, with the same driver version, verified by checksum.
You don't converge to a desired state. You boot into it.

**2. HPC clusters became heterogeneous.**

A single cluster now has x86_64 CPU nodes, ARM64 CPU nodes (Grace, Graviton),
GPU nodes with different NVIDIA generations, and maybe a partition running
a different OS for a specific workload. That's four or five different image
profiles, not one. Building them by hand doesn't scale. Building them from
a declarative spec -- where you change `target_arch: aarch64` or add
`nvidia-driver` to the package list -- does.

**3. Security and compliance started applying to HPC.**

Supply chain security, SBOMs, CVE scanning, and image provenance are
no longer just cloud concerns. When your cluster processes controlled data
or trains models on proprietary datasets, auditors want to know exactly
what's in the OS image. A squashfs built from a YAML spec with checksums
and a build manifest is auditable. A golden image that someone built on
a reference node in 2022 is not.

## The Immutable Image Pattern

The HPC community has been converging on what cloud infrastructure calls
the immutable image pattern: instead of building a base OS and then
running Ansible against live nodes to install packages and fix drift, you
bake everything into the image at build time. Nodes boot into a read-only
squashfs with a RAM-backed overlay for runtime state. Updates mean building
a new image and rebooting, not patching in place.

This is exactly what ORNL's Anchor project does (buildah + squashfs +
dracut module), what LANL does with OpenCHAMI on the 640-node Badger
cluster, what Freiburg does with their CI/CD pipeline for bwForCluster
NEMO 2, and what Warewulf has been doing for over twenty years with its
VNFS images.

`omnia.open_image_builder` is built for this pattern. The output is a
squashfs + kernel + initramfs, ready for PXE boot into a stateless,
read-only root. The image is reproducible (same YAML, same repos, same
image). The manifest.json includes SHA-256 checksums for every artifact.
The build runs in containers with no host-side state. You can run it in
CI, version-control the input YAML, and promote images through
dev/staging/production channels by moving files, not rebuilding.

## What This Doesn't Do

This collection builds images. It doesn't provision nodes, manage boot
parameters, run health checks, handle DHCP, or configure InfiniBand.
Those are jobs for OpenCHAMI, Omnia, Warewulf, or whatever provisioning
stack your site runs. The image builder doesn't care -- it produces files,
you serve them however you want.

It also doesn't replace container-based workload delivery. If your users
run their codes in Apptainer/Singularity containers, the OS image is just
the host environment -- kernel, drivers, scheduler, container runtime.
The science happens in the container. The image builder handles the host;
your users handle their containers.

## Getting Started

If you run Omnia + OpenCHAMI today:

```bash
# Build images from Omnia's software catalog
ansible-playbook omnia.open_image_builder.build \
  -e omnia_integration=true \
  -e input_project_dir=/opt/omnia/input

# Point OpenCHAMI's boot service at the output (syntax is illustrative)
ochami boot set \
  --kernel http://boot-server/images/base/vmlinuz \
  --initrd http://boot-server/images/base/initramfs.img \
  --params "root=live:http://boot-server/images/base/rootfs"
```

If you run standalone:

```bash
ansible-playbook omnia.open_image_builder.build \
  -e @examples/hpc_scientific_x86_64.yml
```

Eight minutes later you have a 1.1 GB squashfs with compilers, MPI,
scientific libraries, RDMA, and Slurm. No root required.

---

*`omnia.open_image_builder` is part of [Omnia](https://github.com/dell/omnia)
by Dell Technologies. [OpenCHAMI](https://openchami.org) is an independent
consortium of HPC operators and vendors. Both are open source.*
