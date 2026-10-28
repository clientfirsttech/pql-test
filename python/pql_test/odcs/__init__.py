# SPDX-License-Identifier: MIT
"""``pql-test contract``: generate PQL.Assert DAX test suites from ODCS data contracts."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("pql-test")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0"

__all__ = ["__version__"]
