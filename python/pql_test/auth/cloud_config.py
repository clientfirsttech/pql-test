# SPDX-License-Identifier: BUSL-1.1
"""
Cloud environment configuration for sovereign clouds.
"""

from __future__ import annotations


class CloudConfig:
    """Cloud environment configuration for Azure sovereign clouds."""

    ENVIRONMENTS = {
        "Public": {
            "authority": "https://login.microsoftonline.com",
            "resource": "https://analysis.windows.net/powerbi/api",
        },
        "USGov": {
            "authority": "https://login.microsoftonline.us",
            "resource": "https://analysis.usgovcloudapi.net/powerbi/api",
        },
        "USGovHigh": {
            "authority": "https://login.microsoftonline.us",
            "resource": "https://high.analysis.usgovcloudapi.net/powerbi/api",
        },
        "USGovDoD": {
            "authority": "https://login.microsoftonline.us",
            "resource": "https://mil.analysis.usgovcloudapi.net/powerbi/api",
        },
        "Germany": {
            "authority": "https://login.microsoftonline.de",
            "resource": "https://analysis.cloudapi.de/powerbi/api",
        },
        "China": {
            "authority": "https://login.chinacloudapi.cn",
            "resource": "https://analysis.chinacloudapi.cn/powerbi/api",
        },
    }

    def get_authority(self, environment: str) -> str:
        """
        Get Azure AD authority URL for environment.

        Args:
            environment: Cloud environment name

        Returns:
            Authority URL for the specified environment (defaults to Public)
        """
        env_config = self.ENVIRONMENTS.get(environment, self.ENVIRONMENTS["Public"])
        return env_config["authority"]

    def get_resource_scope(self, environment: str) -> str:
        """
        Get Power BI resource scope for environment.

        Args:
            environment: Cloud environment name

        Returns:
            Resource scope URL with /.default suffix
        """
        env_config = self.ENVIRONMENTS.get(environment, self.ENVIRONMENTS["Public"])
        resource = env_config["resource"]
        return f"{resource}/.default"
