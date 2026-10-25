# SPDX-License-Identifier: BUSL-1.1
"""Tests for name-based dataset resolution (no GUID required).

Previously the CLI required ``--dataset-id <guid>`` to talk to the Power
BI Service, which forced callers to stash a dataset GUID per model as
repo secrets.  The CLI now derives the dataset's display name from the
``.SemanticModel`` directory stem and the resolver verifies the dataset
exists in the workspace via REST — so callers only need workspace +
SPN credentials.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from pql_test.runner import (
    Environment,
    ResolvedXmlaConnection,
    XmlaConnectionOptions,
    _resolve_service_xmla_connection,
    resolve_xmla_connection,
)


def _service_opts_with_name(name: str = "SampleModel") -> XmlaConnectionOptions:
    return XmlaConnectionOptions(
        tenant_id="t",
        workspace_id="w",
        dataset_name=name,
        client_id="c",
        client_secret="s",
        environment=Environment.PUBLIC,
    )


def test_dataset_name_field_exists_on_options():
    """Sanity: XmlaConnectionOptions exposes dataset_name."""
    opts = XmlaConnectionOptions(dataset_name="X")
    assert opts.dataset_name == "X"
    assert opts.dataset_id is None


def test_service_path_uses_dataset_name_directly_as_catalog():
    """When dataset_name is provided, the catalog comes from it (no GUID lookup)."""
    with (
        patch("pql_test.runner._acquire_service_principal_token", return_value="tok"),
        patch("pql_test.runner._resolve_pbi_workspace_name", return_value="MyWorkspace"),
        patch("pql_test.runner._verify_dataset_exists_in_workspace") as verify,
        patch("pql_test.runner._resolve_pbi_workspace_and_dataset_names") as legacy,
    ):
        conn = _resolve_service_xmla_connection(_service_opts_with_name("SampleModel"))

    assert conn.catalog == "SampleModel"
    assert conn.access_token == "tok"
    assert "MyWorkspace" in conn.server
    verify.assert_called_once()
    legacy.assert_not_called()


def test_service_path_still_supports_dataset_id_for_backward_compat():
    """Callers that still pass --dataset-id <guid> get the legacy lookup."""
    opts = XmlaConnectionOptions(
        tenant_id="t", workspace_id="w", dataset_id="d-guid",
        client_id="c", client_secret="s",
    )
    with (
        patch("pql_test.runner._acquire_service_principal_token", return_value="tok"),
        patch(
            "pql_test.runner._resolve_pbi_workspace_and_dataset_names",
            return_value=("MyWorkspace", "MyDataset"),
        ),
        patch("pql_test.runner._verify_dataset_exists_in_workspace") as verify,
    ):
        conn = _resolve_service_xmla_connection(opts)

    assert conn.catalog == "MyDataset"
    # Verify is the name-mode helper; GUID path doesn't need it.
    verify.assert_not_called()


def test_dataset_id_takes_precedence_when_both_set():
    """If a caller (rare) sets both, the GUID path runs because dataset_id branch is checked first."""
    opts = XmlaConnectionOptions(
        tenant_id="t", workspace_id="w",
        dataset_id="d-guid", dataset_name="WrongName",
        client_id="c", client_secret="s",
    )
    with (
        patch("pql_test.runner._acquire_service_principal_token", return_value="tok"),
        patch(
            "pql_test.runner._resolve_pbi_workspace_and_dataset_names",
            return_value=("MyWorkspace", "ResolvedFromGuid"),
        ),
    ):
        conn = _resolve_service_xmla_connection(opts)

    assert conn.catalog == "ResolvedFromGuid", "dataset_id wins when both are set"


def test_verify_dataset_failure_propagates_as_value_error():
    """If the deployed workspace doesn't contain the named dataset, fail clearly."""
    with (
        patch("pql_test.runner._acquire_service_principal_token", return_value="tok"),
        patch("pql_test.runner._resolve_pbi_workspace_name", return_value="MyWorkspace"),
        patch(
            "pql_test.runner._verify_dataset_exists_in_workspace",
            side_effect=ValueError("Dataset 'Missing' not found in workspace w. Available datasets: 'A', 'B'"),
        ),
    ):
        with pytest.raises(ValueError, match="not found in workspace"):
            _resolve_service_xmla_connection(_service_opts_with_name("Missing"))


def test_resolve_xmla_connection_accepts_dataset_name_only():
    """The public API gates on (dataset_id OR dataset_name), not dataset_id alone."""
    opts = _service_opts_with_name("SampleModel")
    with (
        patch("pql_test.runner._acquire_service_principal_token", return_value="tok"),
        patch("pql_test.runner._resolve_pbi_workspace_name", return_value="WS"),
        patch("pql_test.runner._verify_dataset_exists_in_workspace"),
    ):
        conn = resolve_xmla_connection("/some/path/SampleModel.SemanticModel", opts)
    assert conn is not None
    assert conn.catalog == "SampleModel"


def test_service_path_skipped_when_neither_id_nor_name():
    """tenant+workspace alone (without id OR name) should not attempt the service path."""
    opts = XmlaConnectionOptions(
        tenant_id="t", workspace_id="w",
        client_id="c", client_secret="s",
    )
    with (
        patch("pql_test.runner._acquire_service_principal_token") as token_call,
        patch("pql_test.runner.resolve_local_xmla_connection", return_value=None),
    ):
        conn = resolve_xmla_connection("/some/path/X.SemanticModel", opts)

    # Service token was never requested
    token_call.assert_not_called()
    assert conn is None
