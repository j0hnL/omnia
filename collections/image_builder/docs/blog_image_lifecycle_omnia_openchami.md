# Where Images Fit in the HPC and AI System Lifecycle

*This tool builds OS images. It does not provision nodes, decide when they
reboot, or manage your fleet. Here's why that matters and where it fits.*

---

## The Gap in the Pipeline

Every HPC and AI cluster has a lifecycle: discover hardware, provision it,
boot it, run workloads, patch it, repeat. There are mature tools for most
of these stages. Redfish handles discovery. OpenCHAMI and Warewulf handle
provisioning. Slurm and Kubernetes handle scheduling. Ansible and cloud-init
handle configuration.

But between "I need a bootable root filesystem with these packages" and
"here is a squashfs I can serve over HTTP" -- that step is almost always
a pile of shell scripts or a side effect of a monolithic provisioning
platform that bundles image building with everything else.

`omnia.open_image_builder` fills that gap and nothing else.

## What This Tool Does

It takes a YAML file and produces three artifacts: a squashfs root
filesystem, a kernel, and an initramfs. It publishes them to HTTP, S3,
or an OCI registry. That's the entire scope.

```
  YAML spec ──→ image-thrillhouse ──→ squashfs + vmlinuz + initramfs
```

It doesn't know or care what provisions your nodes. It doesn't know
what boot service points nodes at those files. The contract between this
tool and the rest of your infrastructure is three files and a URL.

## What This Tool Does NOT Do

This is the important part. Building the image is one step in a lifecycle
that has at least five steps this tool doesn't handle:

| Step | Who handles it | Not this tool |
|---|---|---|
| **Build the image** | `omnia.open_image_builder` | -- |
| **Validate the image** | Your CI pipeline (container tests, boot tests) | Not built in |
| **Decide which nodes get the image** | Your provisioning system (OpenCHAMI, Warewulf, Omnia) | Not built in |
| **Drain jobs and reboot nodes** | Your scheduler (Slurm, K8s) + admin policy | Not built in |
| **Serve the image** | HTTP server, S3, NFS | Not built in |
| **Personalize nodes at boot** | cloud-init, OpenCHAMI configurator | Not built in |
| **Rollback on failure** | Your deployment pipeline | Not built in |

An image builder that also tries to drain Slurm jobs, reboot nodes, and
manage deployment channels is no longer an image builder -- it's a
provisioning platform. We already have those. This tool is deliberately
small so it composes with whatever you already run.

## How It Connects to OpenCHAMI and Omnia

[OpenCHAMI](https://openchami.org) tells each node which kernel, initramfs,
and root filesystem URL to use at boot. It expects those artifacts to already
exist. This tool produces them.

[Dell Omnia](https://github.com/dell/omnia) defines per-role package sets
via its software catalog -- what goes on a Slurm controller vs. a GPU node
vs. a login node. This tool reads that catalog and builds the images.

```
  Omnia catalog ──→ open_image_builder ──→ HTTP/S3 ──→ OpenCHAMI boot service ──→ nodes
          (what)              (build)         (serve)            (provision)        (boot)
```

Each piece is independent. You can use this tool without Omnia (provide
your own YAML). You can use it without OpenCHAMI (serve the squashfs
however you want). You can use Omnia and OpenCHAMI without this tool
(build images some other way).

## Keeping Images Current

Building an image once is easy. Keeping it current -- security patches,
kernel updates, driver upgrades -- is where most sites fall apart.

The collection ships Argo Workflows manifests for two patterns:

**Nightly rebuild** -- pick up upstream patches automatically:

```yaml
# argo/cronworkflow.yaml (shipped with the collection)
apiVersion: argoproj.io/v1alpha1
kind: CronWorkflow
metadata:
  name: nightly-image-rebuild
spec:
  schedule: "0 2 * * *"
  concurrencyPolicy: Replace
  workflowSpec:
    templates:
      - name: build
        container:
          image: ghcr.io/dell/omnia-image-builder:latest
          args:
            - |
              ansible-playbook omnia.open_image_builder.build_x86_64 \
                -e @/config/image-vars.yml
          securityContext:
            privileged: true
```

**PR-triggered rebuild** -- build on every change to the image spec:

```yaml
# Example: GitHub Actions workflow triggered by PR
name: Build OS Image
on:
  pull_request:
    paths: ['image-specs/**']

jobs:
  build:
    runs-on: [self-hosted, linux, x86_64]
    steps:
      - uses: actions/checkout@v4
      - name: Build image
        run: |
          ansible-playbook omnia.open_image_builder.build \
            -e @image-specs/hpc_scientific.yml \
            -e output_dir=${{ runner.temp }}/images
      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: os-image-${{ github.sha }}
          path: ${{ runner.temp }}/images/
```

The nightly build ensures your images pick up security patches without
human intervention. The PR-triggered build ensures every change to the
image spec is reviewed, built, and tested before it reaches production.

**What these pipelines don't do:** decide when nodes actually boot the new
image. That's a scheduling and operations decision. Your admin (or your
automation) needs to:

1. Validate the new image (boot it on a test node, run health checks)
2. Promote it to a production URL (update a symlink, change a pointer)
3. Drain running jobs from target nodes (Slurm `scontrol`)
4. Update boot parameters (OpenCHAMI API, Warewulf `wwctl`)
5. Reboot nodes into the new image

This tool handles step zero -- building the artifact. Steps 1-5 are your
operations workflow. Sites like Freiburg (bwForCluster NEMO 2) handle
promotion with pointer files and four deployment channels. LANL uses
layered OCI builds with buildah where unchanged layers stay bit-for-bit
identical. Each site wires it differently because the operations decisions
are site-specific.

## Why Immutable Images Over Ansible on Live Nodes

You can run Ansible against live nodes to install patches. People do. But:

- **Drift is cumulative.** A failed play leaves a node in an intermediate
  state. Across 2,000 nodes, some fraction are always slightly different.
- **A squashfs has a checksum.** Either a node runs the blessed image or
  it doesn't. No partial state.
- **Rollback is a URL change.** Not "run a different playbook and hope."

The right split: bake the software stack into the image at build time.
Personalize identity at boot (hostname, IP, Slurm config) via cloud-init.

## Getting Started

```bash
ansible-playbook omnia.open_image_builder.build \
  -e @examples/hpc_scientific_x86_64.yml
```

Eight minutes. 1.1 GB squashfs. Compilers, MPI, RDMA, Slurm. No root
required. What you do with it after that is up to you.

---

*`omnia.open_image_builder` is part of [Omnia](https://github.com/dell/omnia)
by Dell Technologies. [OpenCHAMI](https://openchami.org) is an independent
consortium of HPC operators and vendors. Both are open source.*
