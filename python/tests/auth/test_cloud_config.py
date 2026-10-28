# SPDX-License-Identifier: AGPL-3.0-only
"""
Tests for pql_test.auth.cloud_config — Cloud environment configuration.
"""

from __future__ import annotations

import pytest

from pql_test.auth.cloud_config import CloudConfig


def test_cloud_config_public_authority():
    """CloudConfig: should return Public cloud authority."""
    config = CloudConfig()
    authority = config.get_authority("Public")
    assert authority == "https://login.microsoftonline.com"


def test_cloud_config_public_scope():
    """CloudConfig: should return Public cloud Power BI scope."""
    config = CloudConfig()
    scope = config.get_resource_scope("Public")
    assert scope == "https://analysis.windows.net/powerbi/api/.default"


def test_cloud_config_usgov():
    """CloudConfig: should return USGov cloud configuration."""
    config = CloudConfig()
    authority = config.get_authority("USGov")
    scope = config.get_resource_scope("USGov")
    
    assert authority == "https://login.microsoftonline.us"
    assert scope == "https://analysis.usgovcloudapi.net/powerbi/api/.default"


def test_cloud_config_usgovhigh():
    """CloudConfig: should return USGovHigh cloud configuration."""
    config = CloudConfig()
    authority = config.get_authority("USGovHigh")
    scope = config.get_resource_scope("USGovHigh")
    
    assert authority == "https://login.microsoftonline.us"
    assert scope == "https://high.analysis.usgovcloudapi.net/powerbi/api/.default"


def test_cloud_config_usgovdod():
    """CloudConfig: should return USGovDoD cloud configuration."""
    config = CloudConfig()
    authority = config.get_authority("USGovDoD")
    scope = config.get_resource_scope("USGovDoD")
    
    assert authority == "https://login.microsoftonline.us"
    assert scope == "https://mil.analysis.usgovcloudapi.net/powerbi/api/.default"


def test_cloud_config_germany():
    """CloudConfig: should return Germany cloud configuration."""
    config = CloudConfig()
    authority = config.get_authority("Germany")
    scope = config.get_resource_scope("Germany")
    
    assert authority == "https://login.microsoftonline.de"
    assert scope == "https://analysis.cloudapi.de/powerbi/api/.default"


def test_cloud_config_china():
    """CloudConfig: should return China cloud configuration."""
    config = CloudConfig()
    authority = config.get_authority("China")
    scope = config.get_resource_scope("China")
    
    assert authority == "https://login.chinacloudapi.cn"
    assert scope == "https://analysis.chinacloudapi.cn/powerbi/api/.default"


def test_cloud_config_unknown_defaults_to_public():
    """CloudConfig: should default to Public for unknown environment."""
    config = CloudConfig()
    authority = config.get_authority("UnknownCloud")
    scope = config.get_resource_scope("UnknownCloud")
    
    assert authority == "https://login.microsoftonline.com"
    assert scope == "https://analysis.windows.net/powerbi/api/.default"
