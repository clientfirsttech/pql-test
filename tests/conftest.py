"""Pytest fixtures for pql-test tests."""

import os
import tempfile

import pytest

from pql_test.core.auth import PqlAuth


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Provide a temporary config directory for auth tests."""
    config_dir = tmp_path / ".pql-test"
    config_dir.mkdir()
    return str(config_dir)


@pytest.fixture
def auth(tmp_config_dir):
    """Provide a PqlAuth instance backed by a temporary config dir."""
    return PqlAuth(config_dir=tmp_config_dir)
