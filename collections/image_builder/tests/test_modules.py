"""
Test 3: Unit tests for custom Python modules.
Tests the module_utils functions directly (no AnsibleModule mock needed).
"""
import os
import sys
import json
import tempfile
import pytest

COLLECTION_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(COLLECTION_ROOT, "plugins"))

from module_utils.build_image.common_functions import (
    extract_rpm_package_names,
    deduplicate_list,
    is_additional_packages_enabled,
    is_admin_debug_enabled,
    get_allowed_additional_subgroups,
)
from module_utils.build_image.config import ROLE_SPECIFIC_KEYS, IMAGE_ROLE_KEYS


class TestExtractRpmPackageNames:
    """Test extract_rpm_package_names from common_functions."""

    def test_extracts_rpm_packages(self):
        items = [
            {"type": "rpm", "package": "kernel"},
            {"type": "rpm", "package": "dracut"},
            {"type": "pip", "package": "numpy"},
        ]
        result = extract_rpm_package_names(items)
        assert result == ["kernel", "dracut"]

    def test_empty_list(self):
        assert extract_rpm_package_names([]) == []

    def test_none_input(self):
        assert extract_rpm_package_names(None) == []

    def test_no_rpm_type(self):
        items = [{"type": "pip", "package": "torch"}]
        assert extract_rpm_package_names(items) == []

    def test_missing_package_key(self):
        items = [{"type": "rpm"}]
        assert extract_rpm_package_names(items) == []

    def test_non_list_input(self):
        assert extract_rpm_package_names("not a list") == []


class TestDeduplicateList:
    """Test deduplicate_list preserves order."""

    def test_removes_duplicates(self):
        assert deduplicate_list(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]

    def test_preserves_order(self):
        assert deduplicate_list(["z", "a", "m"]) == ["z", "a", "m"]

    def test_empty_list(self):
        assert deduplicate_list([]) == []

    def test_single_item(self):
        assert deduplicate_list(["x"]) == ["x"]

    def test_all_duplicates(self):
        assert deduplicate_list(["a", "a", "a"]) == ["a"]


class TestSoftwareConfigChecks:
    """Test is_additional_packages_enabled, is_admin_debug_enabled, etc."""

    SAMPLE_CONFIG = {
        "softwares": [
            {"name": "default_packages"},
            {"name": "additional_packages"},
            {"name": "admin_debug_packages"},
            {"name": "slurm_custom"},
        ],
        "additional_packages": [
            {"name": "slurm_node"},
            {"name": "service_kube_node"},
        ]
    }

    def test_additional_packages_enabled(self):
        assert is_additional_packages_enabled(self.SAMPLE_CONFIG) is True

    def test_additional_packages_disabled(self):
        config = {"softwares": [{"name": "default_packages"}]}
        assert is_additional_packages_enabled(config) is False

    def test_additional_packages_none_config(self):
        assert is_additional_packages_enabled(None) is False

    def test_admin_debug_enabled(self):
        assert is_admin_debug_enabled(self.SAMPLE_CONFIG) is True

    def test_admin_debug_disabled(self):
        config = {"softwares": [{"name": "default_packages"}]}
        assert is_admin_debug_enabled(config) is False

    def test_allowed_additional_subgroups(self):
        result = get_allowed_additional_subgroups(self.SAMPLE_CONFIG)
        assert result == ["slurm_node", "service_kube_node"]

    def test_allowed_additional_subgroups_empty(self):
        assert get_allowed_additional_subgroups(None) == []


class TestConfigConstants:
    """Test config.py constants are sane."""

    def test_role_specific_keys_not_empty(self):
        assert len(ROLE_SPECIFIC_KEYS) > 0

    def test_role_specific_keys_are_strings(self):
        assert all(isinstance(k, str) for k in ROLE_SPECIFIC_KEYS)

    def test_image_role_keys_subset_of_role_keys(self):
        for k in IMAGE_ROLE_KEYS:
            assert k in ROLE_SPECIFIC_KEYS, f"{k} in IMAGE_ROLE_KEYS but not in ROLE_SPECIFIC_KEYS"

    def test_known_roles_present(self):
        expected = ["slurm_node", "slurm_control_node", "service_kube_node", "login_node"]
        for role in expected:
            assert role in ROLE_SPECIFIC_KEYS


class TestModuleImports:
    """Verify all module files are importable Python."""

    MODULES = [
        "modules/base_image_package_collector.py",
        "modules/image_package_collector.py",
        "modules/functional_group_parser.py",
    ]

    @pytest.mark.parametrize("module_path", MODULES)
    def test_module_is_valid_python(self, module_path):
        full = os.path.join(COLLECTION_ROOT, "plugins", module_path)
        with open(full) as f:
            source = f.read()
        try:
            compile(source, module_path, "exec")
        except SyntaxError as e:
            pytest.fail(f"Syntax error in {module_path}: {e}")

    @pytest.mark.parametrize("module_path", MODULES)
    def test_module_has_documentation(self, module_path):
        full = os.path.join(COLLECTION_ROOT, "plugins", module_path)
        with open(full) as f:
            source = f.read()
        assert "DOCUMENTATION" in source, f"{module_path} missing DOCUMENTATION string"

    @pytest.mark.parametrize("module_path", MODULES)
    def test_module_has_main(self, module_path):
        full = os.path.join(COLLECTION_ROOT, "plugins", module_path)
        with open(full) as f:
            source = f.read()
        assert "def main()" in source, f"{module_path} missing main() function"

    @pytest.mark.parametrize("module_path", MODULES)
    def test_module_uses_fqcn_imports(self, module_path):
        full = os.path.join(COLLECTION_ROOT, "plugins", module_path)
        with open(full) as f:
            source = f.read()
        # Should NOT have old-style imports
        assert "from ansible.module_utils.build_image" not in source, \
            f"{module_path} uses old-style import instead of FQCN"
