"""Tests for the CI per-model dataset-secret routing helper.

The remote-tests CI workflow runs ``pql-test run-tests`` once per example
``.SemanticModel`` directory.  Every matrix entry must connect to the dataset
that actually contains *that* model's test functions; otherwise
``PQL.Assert.RetrieveTestsV2()`` returns the wrong tests (e.g. ``RLS.ANY.Tests``
when the matrix entry is the SampleModel).

This module verifies the routing helper that maps a model path to the secret
name carrying that model's dataset GUID.
"""

from __future__ import annotations

import pytest


def test_sample_model_routes_to_default_dataset_secret():
    """Given the SampleModel path, should select PQL_DATASET_ID."""
    from pql_test.ci_routing import dataset_secret_for_model

    assert (
        dataset_secret_for_model("examples/SampleModel.SemanticModel")
        == "PQL_DATASET_ID"
    )


def test_rls_model_routes_to_rls_dataset_secret():
    """Given the RLS_Model path, should select PQL_DATASET_ID_RLS."""
    from pql_test.ci_routing import dataset_secret_for_model

    assert (
        dataset_secret_for_model("examples/RLS_Model.SemanticModel")
        == "PQL_DATASET_ID_RLS"
    )


def test_ols_model_routes_to_ols_dataset_secret():
    """Given the OLS_Model path, should select PQL_DATASET_ID_OLS."""
    from pql_test.ci_routing import dataset_secret_for_model

    assert (
        dataset_secret_for_model("examples/OLS_Model.SemanticModel")
        == "PQL_DATASET_ID_OLS"
    )


def test_routing_is_case_insensitive_on_model_name():
    """Given a casing variation in the matrix path, should still route correctly."""
    from pql_test.ci_routing import dataset_secret_for_model

    assert (
        dataset_secret_for_model("examples/rls_model.SemanticModel")
        == "PQL_DATASET_ID_RLS"
    )


def test_routing_accepts_windows_path_separators():
    """Given a Windows-style backslash path, should still route correctly."""
    from pql_test.ci_routing import dataset_secret_for_model

    assert (
        dataset_secret_for_model("examples\\RLS_Model.SemanticModel")
        == "PQL_DATASET_ID_RLS"
    )


def test_unknown_model_raises_with_clear_message():
    """Given an unrecognised model path, should fail fast (no silent default)."""
    from pql_test.ci_routing import dataset_secret_for_model

    with pytest.raises(ValueError, match="Unknown model"):
        dataset_secret_for_model("examples/MysteryModel.SemanticModel")
