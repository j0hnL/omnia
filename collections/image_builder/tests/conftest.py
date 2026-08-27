"""Shared fixtures for omnia.image_builder tests."""
import os
import sys
import pytest

# Collection root
COLLECTION_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Add plugins to path so modules can be imported in tests
sys.path.insert(0, os.path.join(COLLECTION_ROOT, "plugins"))


@pytest.fixture
def collection_root():
    return COLLECTION_ROOT
