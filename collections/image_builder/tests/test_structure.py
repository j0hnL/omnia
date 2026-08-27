"""
Test 1: Collection structural validation.
Verifies the collection has all required files, correct galaxy.yml,
proper role structure, and valid YAML throughout.
"""
import os
import yaml
import pytest

COLLECTION_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestGalaxyYml:
    """Validate galaxy.yml metadata."""

    def setup_method(self):
        with open(os.path.join(COLLECTION_ROOT, "galaxy.yml")) as f:
            self.galaxy = yaml.safe_load(f)

    def test_galaxy_yml_exists(self):
        assert os.path.isfile(os.path.join(COLLECTION_ROOT, "galaxy.yml"))

    def test_namespace_is_omnia(self):
        assert self.galaxy["namespace"] == "omnia"

    def test_name_is_open_image_builder(self):
        assert self.galaxy["name"] == "open_image_builder"

    def test_version_is_semver(self):
        parts = self.galaxy["version"].split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_has_description(self):
        assert len(self.galaxy.get("description", "")) > 10

    def test_has_license(self):
        assert "Apache-2.0" in self.galaxy.get("license", [])

    def test_has_authors(self):
        assert len(self.galaxy.get("authors", [])) > 0


class TestRequiredFiles:
    """Verify all required collection files exist."""

    REQUIRED_FILES = [
        "galaxy.yml",
        "README.md",
        "playbooks/build.yml",
        "playbooks/build_x86_64.yml",
        "playbooks/build_aarch64.yml",
        "plugins/modules/base_image_package_collector.py",
        "plugins/modules/image_package_collector.py",
        "plugins/modules/functional_group_parser.py",
        "plugins/module_utils/build_image/__init__.py",
        "plugins/module_utils/build_image/common_functions.py",
        "plugins/module_utils/build_image/config.py",
    ]

    @pytest.mark.parametrize("filepath", REQUIRED_FILES)
    def test_required_file_exists(self, filepath):
        full = os.path.join(COLLECTION_ROOT, filepath)
        assert os.path.isfile(full), f"Missing required file: {filepath}"


class TestRoleStructure:
    """Verify each role has required subdirectories and files."""

    ROLES = ["config_gen", "build", "local_storage", "repo_mirror",
             "fetch_packages", "image_creation", "cross_build"]

    @pytest.mark.parametrize("role", ROLES)
    def test_role_directory_exists(self, role):
        path = os.path.join(COLLECTION_ROOT, "roles", role)
        assert os.path.isdir(path), f"Role directory missing: roles/{role}"

    @pytest.mark.parametrize("role", ROLES)
    def test_role_has_tasks_main(self, role):
        path = os.path.join(COLLECTION_ROOT, "roles", role, "tasks", "main.yml")
        assert os.path.isfile(path), f"Missing tasks/main.yml in role: {role}"

    @pytest.mark.parametrize("role", ROLES)
    def test_role_has_meta(self, role):
        path = os.path.join(COLLECTION_ROOT, "roles", role, "meta", "main.yml")
        assert os.path.isfile(path), f"Missing meta/main.yml in role: {role}"

    @pytest.mark.parametrize("role", ROLES)
    def test_role_has_defaults(self, role):
        path = os.path.join(COLLECTION_ROOT, "roles", role, "defaults", "main.yml")
        # Not all roles require defaults (some only have vars)
        if os.path.isdir(os.path.join(COLLECTION_ROOT, "roles", role, "defaults")):
            assert os.path.isfile(path), f"defaults/ dir exists but main.yml missing in role: {role}"


def _find_yaml_files():
    """Find all YAML files in the collection (excluding .git, __pycache__, tests)."""
    yaml_files = []
    for root, _dirs, files in os.walk(COLLECTION_ROOT):
        if any(skip in root for skip in [".git", "__pycache__", "tests"]):
            continue
        for f in files:
            if f.endswith((".yml", ".yaml")) and not f.endswith(".j2"):
                rel = os.path.relpath(os.path.join(root, f), COLLECTION_ROOT)
                yaml_files.append(rel)
    return yaml_files


class TestYamlSyntax:
    """Validate all YAML files parse without errors."""

    @pytest.mark.parametrize("yaml_file", _find_yaml_files())
    def test_yaml_parses(self, yaml_file):
        full = os.path.join(COLLECTION_ROOT, yaml_file)
        with open(full, encoding="utf-8") as f:
            try:
                # Use safe_load_all to support multi-document YAML (k8s manifests)
                docs = list(yaml.safe_load_all(f))
                non_empty = [d for d in docs if d is not None]
                assert non_empty or os.path.getsize(full) == 0, \
                    f"YAML file parsed as None: {yaml_file}"
            except yaml.YAMLError as e:
                pytest.fail(f"YAML syntax error in {yaml_file}: {e}")


class TestExamples:
    """Validate example files exist and have required keys."""

    EXAMPLES = [
        "examples/standalone_x86_64.yml",
        "examples/standalone_aarch64_crossbuild.yml",
        "examples/offline_x86_64.yml",
    ]

    @pytest.mark.parametrize("example", EXAMPLES)
    def test_example_exists(self, example):
        assert os.path.isfile(os.path.join(COLLECTION_ROOT, example)), \
            f"Missing example: {example}"

    @pytest.mark.parametrize("example", EXAMPLES)
    def test_example_has_base_image_packages(self, example):
        with open(os.path.join(COLLECTION_ROOT, example)) as f:
            data = yaml.safe_load(f)
        assert "base_image_packages" in data, \
            f"Example {example} missing base_image_packages"
        assert len(data["base_image_packages"]) > 0

    @pytest.mark.parametrize("example", EXAMPLES)
    def test_example_has_os_version(self, example):
        with open(os.path.join(COLLECTION_ROOT, example)) as f:
            data = yaml.safe_load(f)
        assert "os_version" in data, f"Example {example} missing os_version"

    @pytest.mark.parametrize("example", EXAMPLES)
    def test_example_has_os_family(self, example):
        with open(os.path.join(COLLECTION_ROOT, example)) as f:
            data = yaml.safe_load(f)
        assert "os_family" in data, f"Example {example} missing os_family"
        assert data["os_family"] in ("rhel", "almalinux", "rocky", "fedora", "ubuntu", "debian"), \
            f"Example {example} has invalid os_family: {data['os_family']}"
