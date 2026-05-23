"""CI per-model dataset-secret routing.

The remote-tests CI workflow runs ``pql-test run-tests`` once per example
``.SemanticModel`` directory in a matrix.  Each matrix entry must connect to
the dataset that actually contains *that* model's test functions; otherwise
``PQL.Assert.RetrieveTestsV2()`` returns tests from a different model
(e.g. ``RLS.ANY.Tests`` showing up under the SampleModel job).

This module maps a matrix model path to the environment-variable / secret
name carrying the right dataset GUID, and exposes a small CLI so the
workflow YAML can shell into it without embedding routing logic in YAML.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import PurePosixPath, PureWindowsPath


_MODEL_TO_SECRET: dict[str, str] = {
    "samplemodel.semanticmodel": "PQL_DATASET_ID",
    "rls_model.semanticmodel": "PQL_DATASET_ID_RLS",
    "ols_model.semanticmodel": "PQL_DATASET_ID_OLS",
}


def _model_dir_name(model_path: str) -> str:
    """Return the ``.SemanticModel`` directory name from *model_path*."""
    # Normalise both POSIX and Windows separators without depending on the
    # host OS, because the workflow runs on Windows but tests may run on
    # any platform.
    posix_name = PurePosixPath(model_path).name
    windows_name = PureWindowsPath(model_path).name
    # PurePosixPath leaves backslashes intact; PureWindowsPath leaves forward
    # slashes intact.  Pick whichever produced an actual directory name.
    return windows_name if len(windows_name) < len(posix_name) else posix_name


def dataset_secret_for_model(model_path: str) -> str:
    """Return the env-var name that holds the dataset GUID for *model_path*.

    Raises :class:`ValueError` when the model is not in the known routing
    table so the workflow fails fast instead of silently connecting to the
    wrong dataset.
    """
    key = _model_dir_name(model_path).lower()
    try:
        return _MODEL_TO_SECRET[key]
    except KeyError:
        known = ", ".join(sorted(_MODEL_TO_SECRET)) or "<none>"
        raise ValueError(
            f"Unknown model directory '{key}' — known models: {known}"
        ) from None


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: print the env-var name for the given model path."""
    parser = argparse.ArgumentParser(
        prog="pql-test-ci-route",
        description="Print the dataset-secret env-var name for a model path.",
    )
    parser.add_argument("model_path", help="Path to the .SemanticModel directory")
    args = parser.parse_args(argv)
    try:
        print(dataset_secret_for_model(args.model_path))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
