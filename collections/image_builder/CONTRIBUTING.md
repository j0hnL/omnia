# Contributing to Omnia Image Builder

Thanks for your interest in contributing! This collection is part of the
[Dell Omnia](https://github.com/dell/omnia) ecosystem and welcomes contributions
from everyone — humans and AI agents alike.

## Quick Start for Contributors

```bash
git clone https://github.com/dell/omnia.git
cd omnia/collections/image_builder

# Install dev dependencies
pip install pytest pyyaml ansible-core ansible-lint yamllint pre-commit
pre-commit install

# Run the test suite
make test

# Lint everything
make lint
```

## Development Workflow

1. **Fork** the repo and create a feature branch from `main`
2. Make your changes in `collections/image_builder/`
3. **Test**: `make test` (185 tests must pass)
4. **Lint**: `make lint` (yamllint + ansible-lint)
5. **Test on real hardware** if you changed build logic — see below
6. Commit with a clear message and open a **pull request**

## Testing

### Unit/structural tests (fast, no hardware)

```bash
make test            # full suite, verbose
make test-quiet      # minimal output
```

These cover collection structure, variable defaults, module syntax, FQCN
usage, and example validity. They run anywhere with Python + pyyaml.

### Integration tests (requires Linux + podman + buildah)

Structural tests can't catch build-time issues (dnf behavior, shell quoting,
symlinks). Always test real builds on a Linux host before submitting changes
to build logic:

```bash
make build-rocky     # Rocky 10
make build-alma      # AlmaLinux 10
make build-fedora    # Fedora 42
```

Verify the output has all three files at the expected sizes:

```bash
ls -lh /var/lib/image-builder/output/base/
# rootfs (~1 GB), vmlinuz (~16 MB), initramfs.img (~220 MB)
```

## Coding Guidelines

### Ansible

- Use **FQCN** everywhere: `omnia.open_image_builder.role_name`, `ansible.builtin.shell`
- Every role needs `meta/main.yml` and `defaults/main.yml`
- Keep OS-specific logic in the `os_family` mapping, not scattered conditionals
- Don't add comments to YAML unless they explain non-obvious behavior

### Shell inside Ansible tasks

The trickiest part of this collection is shell quoting across 4 layers
(Jinja2 → Ansible → host shell → container shell). **Lessons learned:**

- For anything with `$VAR`, pipes, or nested quotes inside `buildah run`,
  write a script file and copy it in — don't inline it.
- Use `/usr/bin/bash` not `/bin/bash` in `buildah run` (symlink timing).
- Use `tar + buildah add`, not `buildah copy`, to preserve usrmerge symlinks.
- See [.windsurf/skills.md](../../.windsurf/skills.md) for the full list.

### Adding a new OS family

1. Add the family to the `os_family` container-image mapping in:
   - `roles/image_creation/tasks/prepare_workspace.yml`
   - `roles/cross_build/tasks/prepare_workspace.yml`
   - `roles/repo_mirror/tasks/sync_packages.yml`
2. Add default package groups to `roles/image_creation/vars/main.yml`
   (`_default_package_groups`) and `roles/cross_build/vars/main.yml`
3. Create an example: `examples/<os>_x86_64.yml`
4. Add the family to `tests/test_structure.py` validation
5. Test a real build on that OS

## Project Structure

| Path | Purpose |
|---|---|
| `roles/` | The five build roles (fetch_packages, image_creation, etc.) |
| `playbooks/` | `build_x86_64.yml`, `build_aarch64.yml` |
| `plugins/` | Python modules for Omnia integration |
| `examples/` | Working configs for each OS and use case |
| `argo/` | Kubernetes deployment manifests |
| `tools/` | Utilities (convert_omnia_config.py) |
| `tests/` | pytest suite |

## Code of Conduct

This project follows the [Omnia Code of Conduct](https://github.com/dell/omnia/blob/main/CODE_OF_CONDUCT.md).

## Questions?

- **Issues**: [dell/omnia/issues](https://github.com/dell/omnia/issues)
- **Discussions**: [dell/omnia/discussions](https://github.com/dell/omnia/discussions)

Not sure where to start? Open an issue and ask — we're happy to help.
