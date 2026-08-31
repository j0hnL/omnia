# Argo Workflows Deployment

Run the Omnia Image Builder as an automated Argo Workflow in Kubernetes.
Tested on k3s v1.35.5 + Argo Workflows v4.0.5, builds complete in **~4.5 minutes**.

## Prerequisites

- Kubernetes cluster (k3s, k8s, OpenShift)
- [Argo Workflows](https://argoproj.github.io/workflows/) installed
- Nodes with `privileged` pod support (required for buildah)

## Quick Start

### 1. Build the builder container image

```bash
cd collections/image_builder
podman build -t ghcr.io/dell/omnia-image-builder:latest -f argo/Containerfile .
podman push ghcr.io/dell/omnia-image-builder:latest
```

Update the `image:` field in `workflow.yaml` and `cronworkflow.yaml` if using
a different registry.

### 2. Edit the ConfigMap

Edit `configmap.yaml` with your OS, repos, and packages.

### 3. Deploy

```bash
kubectl apply --server-side -k argo/
```

### 4. Run a build

```bash
argo submit argo/workflow.yaml -n image-builder --watch
```

### 5. Check output

```bash
kubectl run verify --rm -it --restart=Never \
  --image=almalinux:10 \
  --overrides='{"spec":{"containers":[{"name":"v","image":"almalinux:10","command":["bash","-c","ls -lh /output/base/; file /output/base/*"],"volumeMounts":[{"name":"o","mountPath":"/output"}]}],"volumes":[{"name":"o","persistentVolumeClaim":{"claimName":"image-output"}}]}}' \
  -n image-builder
```

## k3s Notes

If running on k3s, you may need:

- **fuse-overlayfs snapshotter** — required if the root filesystem is LiveOS/overlay:
  ```bash
  dnf install -y fuse-overlayfs
  curl -sfL https://get.k3s.io | INSTALL_K3S_SKIP_SELINUX_RPM=true \
    INSTALL_K3S_EXEC='server --snapshotter=fuse-overlayfs' sh -
  ```

- **`--server-side` apply** — Argo CRD annotations exceed the default 262 KB limit:
  ```bash
  kubectl apply --server-side -k argo/
  ```

- **Import builder image** — k3s uses containerd, not podman:
  ```bash
  podman save omnia-image-builder:latest -o /tmp/builder.tar
  k3s ctr images import --no-unpack /tmp/builder.tar
  ```
  Then set `imagePullPolicy: Never` in the workflow YAML.

- **Argo artifact config** — the quick-start uses a test artifact driver that
  doesn't exist. Patch the configmap:
  ```bash
  kubectl patch configmap workflow-controller-configmap -n argo \
    --type merge -p '{"data":{"artifactRepository":"archiveLogs: false\n"}}'
  kubectl rollout restart deployment/workflow-controller -n argo
  ```

## Nightly Rebuilds

The `cronworkflow.yaml` rebuilds images at 2:00 AM daily (America/Chicago).

```bash
argo cron suspend nightly-image-rebuild -n image-builder
argo cron resume nightly-image-rebuild -n image-builder
```

## Customization

### Different OS

Edit `configmap.yaml` — change `os_family`, `os_version`, and `repos`.

### Multiple architectures

Create a second Workflow that uses `build_aarch64` instead of `build_x86_64`.

### Custom packages

Add packages to `base_image_packages` in the ConfigMap. For compute node
roles, add a `compute_images_dict` section (see the Slurm example in the
main README).

## Files

| File | Purpose |
|---|---|
| `Containerfile` | Builder image (almalinux:10 + ansible + buildah + collection) |
| `namespace.yaml` | Dedicated namespace for image builds |
| `rbac.yaml` | ServiceAccount + Role (includes Argo workflowtaskresults) |
| `pvc.yaml` | 20 GB output PVC + 30 GB workspace PVC |
| `configmap.yaml` | Image build configuration (OS, repos, packages) |
| `workflow.yaml` | One-shot build workflow (privileged, /dev/fuse mount) |
| `cronworkflow.yaml` | Nightly scheduled rebuild at 2:00 AM |
| `kustomization.yaml` | Kustomize overlay for `kubectl apply -k` |

## Testing Without Argo

Test the builder image locally with podman before deploying to Kubernetes:

```bash
mkdir -p /tmp/image-output /tmp/image-workspace
podman run --rm --privileged \
  -v ./examples/rocky_x86_64.yml:/config/image-vars.yml:z \
  -v /tmp/image-output:/output:z \
  -v /tmp/image-workspace:/workspace:z \
  ghcr.io/dell/omnia-image-builder:latest \
  omnia.image_builder.build_x86_64 \
  -e @/config/image-vars.yml \
  -e output_dir=/output \
  -e work_dir=/workspace
```

## Tested Results

| Step | Time |
|---|---|
| Builder image build | 31s |
| Argo Workflow (Rocky 10) | **4m 28s** |
| Output | 1.1 GB rootfs, 16 MB vmlinuz, 219 MB initramfs |
