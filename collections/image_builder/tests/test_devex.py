"""
Test 5: Developer experience and new feature files.
Verifies Makefile, CONTRIBUTING.md, CI workflows, tools, and
multi-OS support files exist and are well-formed.
"""
import os
import stat
import yaml
import pytest

COLLECTION_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(COLLECTION_ROOT))


class TestDevExFiles:
    """Developer experience files exist."""

    DEVEX_FILES = [
        "Makefile",
        "CONTRIBUTING.md",
        ".yamllint",
        ".pre-commit-config.yaml",
    ]

    @pytest.mark.parametrize("f", DEVEX_FILES)
    def test_devex_file_exists(self, f):
        assert os.path.isfile(os.path.join(COLLECTION_ROOT, f)), f"Missing {f}"


class TestTools:
    """Utility scripts exist and are valid."""

    def test_convert_omnia_config_exists(self):
        path = os.path.join(COLLECTION_ROOT, "tools", "convert_omnia_config.py")
        assert os.path.isfile(path)

    def test_convert_omnia_config_valid_python(self):
        path = os.path.join(COLLECTION_ROOT, "tools", "convert_omnia_config.py")
        with open(path) as f:
            compile(f.read(), path, "exec")

    def test_validate_image_script_exists(self):
        path = os.path.join(COLLECTION_ROOT, "tools", "validate_image.sh")
        assert os.path.isfile(path)


class TestMultiOS:
    """Multi-OS support: examples and family detection."""

    DEB_EXAMPLES = ["examples/ubuntu_x86_64.yml", "examples/debian_x86_64.yml"]

    @pytest.mark.parametrize("example", DEB_EXAMPLES)
    def test_deb_example_exists(self, example):
        assert os.path.isfile(os.path.join(COLLECTION_ROOT, example))

    @pytest.mark.parametrize("example", DEB_EXAMPLES)
    def test_deb_example_valid(self, example):
        with open(os.path.join(COLLECTION_ROOT, example)) as f:
            data = yaml.safe_load(f)
        assert data["os_family"] in ("ubuntu", "debian")
        assert "os_version" in data
        assert "base_image_packages" in data

    def test_deb_example_uses_mmdebstrap(self):
        """Debian/Ubuntu examples should work with config_gen's mmdebstrap backend."""
        path = os.path.join(COLLECTION_ROOT, "roles", "config_gen", "vars", "main.yml")
        with open(path) as f:
            data = yaml.safe_load(f)
        assert "mmdebstrap" in str(data.get("_pkg_manager_map", {})), \
            "config_gen missing mmdebstrap backend for Debian/Ubuntu"


class TestImageThrillhouseIntegration:
    """Verify image-thrillhouse integration roles exist and are well-formed."""

    def test_config_gen_has_base_template(self):
        path = os.path.join(COLLECTION_ROOT, "roles", "config_gen",
                            "templates", "base-config.yaml.j2")
        assert os.path.isfile(path), "Missing config_gen base-config template"

    def test_config_gen_has_compute_template(self):
        path = os.path.join(COLLECTION_ROOT, "roles", "config_gen",
                            "templates", "compute-config.yaml.j2")
        assert os.path.isfile(path), "Missing config_gen compute-config template"

    def test_config_gen_base_template_uses_thrillhouse_schema(self):
        path = os.path.join(COLLECTION_ROOT, "roles", "config_gen",
                            "templates", "base-config.yaml.j2")
        with open(path) as f:
            content = f.read()
        assert "meta:" in content, "base template missing 'meta:' (image-thrillhouse schema)"
        assert "layer:" in content, "base template missing 'layer:' (image-thrillhouse schema)"
        assert "publish:" in content, "base template missing 'publish:' (image-thrillhouse schema)"
        assert "commands:" in content, "base template missing 'commands:' (image-thrillhouse schema)"
        assert "groups:" in content, "base template missing 'groups:' for DNF package groups"
        assert "'@" not in content, "base template uses @-prefixed groups instead of groups: field"
        # Verify the YAML key uses tls-verify (hyphen), not tls_verify (underscore)
        # The Jinja2 variable registry_tls_verify correctly uses underscores
        import re
        assert not re.search(r'^\s+tls_verify:', content, re.MULTILINE), \
            "base template uses tls_verify: instead of tls-verify:"

    def test_build_role_has_detect_builder(self):
        path = os.path.join(COLLECTION_ROOT, "roles", "build",
                            "tasks", "detect_builder.yml")
        assert os.path.isfile(path), "Missing build/tasks/detect_builder.yml"

    def test_build_role_has_build_one(self):
        path = os.path.join(COLLECTION_ROOT, "roles", "build",
                            "tasks", "build_one.yml")
        assert os.path.isfile(path), "Missing build/tasks/build_one.yml"

    def test_build_role_invokes_image_thrillhouse(self):
        path = os.path.join(COLLECTION_ROOT, "roles", "build",
                            "tasks", "build_one.yml")
        with open(path) as f:
            content = f.read()
        assert "image-thrillhouse" in content or "image_thrillhouse" in content, \
            "build_one.yml doesn't invoke image-thrillhouse"

    def test_unified_playbook_exists(self):
        path = os.path.join(COLLECTION_ROOT, "playbooks", "build.yml")
        assert os.path.isfile(path), "Missing unified playbooks/build.yml"

    def test_unified_playbook_uses_new_roles(self):
        path = os.path.join(COLLECTION_ROOT, "playbooks", "build.yml")
        with open(path) as f:
            content = f.read()
        assert "omnia.image_builder.config_gen" in content, \
            "build.yml missing config_gen role"
        assert "omnia.image_builder.build" in content, \
            "build.yml missing build role"


class TestCIWorkflows:
    """GitHub Actions CI workflows exist."""

    WORKFLOWS = [
        ".github/workflows/image-builder-ci.yml",
        ".github/workflows/image-builder-nightly.yml",
    ]

    @pytest.mark.parametrize("wf", WORKFLOWS)
    def test_workflow_exists(self, wf):
        assert os.path.isfile(os.path.join(REPO_ROOT, wf)), f"Missing {wf}"

    @pytest.mark.parametrize("wf", WORKFLOWS)
    def test_workflow_valid_yaml(self, wf):
        path = os.path.join(REPO_ROOT, wf)
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "jobs" in data, f"{wf} has no jobs"


class TestManifestGeneration:
    """The export task generates a manifest."""

    def test_export_generates_manifest(self):
        path = os.path.join(COLLECTION_ROOT, "roles", "local_storage",
                            "tasks", "export_image.yml")
        with open(path) as f:
            content = f.read()
        assert "manifest.json" in content, "export_image.yml doesn't generate manifest.json"
        assert "sha256" in content.lower(), "manifest doesn't include checksums"
        assert "SHA256SUMS" in content, "export doesn't write SHA256SUMS"
