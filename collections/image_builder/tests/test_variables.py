"""
Test 4: Variable consistency and defaults validation.
Ensures roles have sensible defaults and no undefined required vars
slip through.
"""
import os
import yaml
import pytest

COLLECTION_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ROLES = ["config_gen", "build", "local_storage", "repo_mirror",
         "fetch_packages", "image_creation", "cross_build"]


class TestDefaultValues:
    """Verify role defaults have expected keys and sensible values."""

    @pytest.mark.parametrize("role", ROLES)
    def test_defaults_file_parses(self, role):
        path = os.path.join(COLLECTION_ROOT, "roles", role, "defaults", "main.yml")
        if not os.path.isfile(path):
            pytest.skip(f"No defaults/main.yml for {role}")
        with open(path) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict), f"defaults/main.yml for {role} is not a dict"

    def test_fetch_packages_has_standalone_vars(self):
        path = os.path.join(COLLECTION_ROOT, "roles", "fetch_packages", "defaults", "main.yml")
        with open(path) as f:
            data = yaml.safe_load(f)
        assert "base_image_packages" in data
        assert "repos" in data
        assert "os_version" in data
        assert "os_family" in data
        assert "omnia_integration" in data
        assert data["omnia_integration"] is False, "omnia_integration should default to false"
        assert data["os_family"] in ("rhel", "almalinux", "rocky", "fedora")

    def test_image_creation_no_oim_defaults(self):
        path = os.path.join(COLLECTION_ROOT, "roles", "image_creation", "defaults", "main.yml")
        with open(path) as f:
            data = yaml.safe_load(f)
        assert "oim_node_name" not in data, "oim_node_name should not be in defaults"
        assert "domain_name" not in data, "domain_name should not be in defaults"
        assert "oim_shared_path" not in data, "oim_shared_path should not be in defaults"
        assert "work_dir" in data

    def test_cross_build_no_oim_defaults(self):
        path = os.path.join(COLLECTION_ROOT, "roles", "cross_build", "defaults", "main.yml")
        with open(path) as f:
            data = yaml.safe_load(f)
        assert "oim_node_name" not in data
        assert "domain_name" not in data
        assert "oim_shared_path" not in data
        assert "work_dir" in data

    def test_local_storage_defaults(self):
        path = os.path.join(COLLECTION_ROOT, "roles", "local_storage", "defaults", "main.yml")
        with open(path) as f:
            data = yaml.safe_load(f)
        assert "work_dir" in data
        assert "output_dir" in data
        assert "publish_s3" in data
        assert data["publish_s3"] is False, "publish_s3 should default to false"

    def test_repo_mirror_defaults(self):
        path = os.path.join(COLLECTION_ROOT, "roles", "repo_mirror", "defaults", "main.yml")
        with open(path) as f:
            data = yaml.safe_load(f)
        assert "upstream_repos" in data
        assert "mirror_dir" in data
        assert "serve_port" in data
        assert "skip_if_cached" in data
        assert data["skip_if_cached"] is True

    def test_config_gen_defaults(self):
        path = os.path.join(COLLECTION_ROOT, "roles", "config_gen", "defaults", "main.yml")
        with open(path) as f:
            data = yaml.safe_load(f)
        assert "os_family" in data
        assert "os_version" in data
        assert "base_image_packages" in data
        assert "repos" in data
        assert "work_dir" in data
        assert "omnia_integration" in data
        assert data["omnia_integration"] is False

    def test_config_gen_no_oim_defaults(self):
        path = os.path.join(COLLECTION_ROOT, "roles", "config_gen", "defaults", "main.yml")
        with open(path) as f:
            data = yaml.safe_load(f)
        assert "oim_node_name" not in data
        assert "domain_name" not in data
        assert "oim_shared_path" not in data

    def test_build_defaults(self):
        path = os.path.join(COLLECTION_ROOT, "roles", "build", "defaults", "main.yml")
        with open(path) as f:
            data = yaml.safe_load(f)
        assert "work_dir" in data
        assert "image_thrillhouse_bin" in data
        assert "image_thrillhouse_container" in data
        assert "build_log_level" in data
        assert "target_arch" in data

    def test_build_no_oim_defaults(self):
        path = os.path.join(COLLECTION_ROOT, "roles", "build", "defaults", "main.yml")
        with open(path) as f:
            data = yaml.safe_load(f)
        assert "oim_node_name" not in data
        assert "domain_name" not in data

    def test_work_dir_not_opt_omnia(self):
        """Ensure no role sets work_dir default to /opt/omnia.
        Omnia integration paths in fetch_packages are allowed since
        they're gated behind omnia_integration: true."""
        for role in ROLES:
            path = os.path.join(COLLECTION_ROOT, "roles", role, "defaults", "main.yml")
            if not os.path.isfile(path):
                continue
            with open(path) as f:
                data = yaml.safe_load(f)
            if data and "work_dir" in data:
                assert "/opt/omnia" not in str(data["work_dir"]), \
                    f"Role {role} work_dir defaults to /opt/omnia"


class TestPlaybookVariables:
    """Verify playbooks use correct variable names."""

    PLAYBOOKS = [
        "playbooks/build.yml",
        "playbooks/build_x86_64.yml",
        "playbooks/build_aarch64.yml",
    ]

    @pytest.mark.parametrize("playbook", PLAYBOOKS)
    def test_playbook_no_oim_host(self, playbook):
        with open(os.path.join(COLLECTION_ROOT, playbook)) as f:
            content = f.read()
        assert "oim_host" not in content, f"{playbook} still references oim_host"
        assert "oim_node_name" not in content, f"{playbook} still references oim_node_name"

    @pytest.mark.parametrize("playbook", PLAYBOOKS)
    def test_playbook_uses_build_host(self, playbook):
        with open(os.path.join(COLLECTION_ROOT, playbook)) as f:
            content = f.read()
        assert "build_host" in content, f"{playbook} should use build_host variable"

    @pytest.mark.parametrize("playbook", PLAYBOOKS)
    def test_playbook_has_config_gen_or_local_storage(self, playbook):
        with open(os.path.join(COLLECTION_ROOT, playbook)) as f:
            content = f.read()
        has_config_gen = "omnia.open_image_builder.config_gen" in content
        has_local_storage = "omnia.open_image_builder.local_storage" in content
        assert has_config_gen or has_local_storage, \
            f"{playbook} missing config_gen or local_storage role"

    @pytest.mark.parametrize("playbook", PLAYBOOKS)
    def test_playbook_has_repo_mirror_option(self, playbook):
        with open(os.path.join(COLLECTION_ROOT, playbook)) as f:
            content = f.read()
        assert "repo_mirror" in content, f"{playbook} missing repo_mirror role"
