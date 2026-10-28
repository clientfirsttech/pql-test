# SPDX-License-Identifier: AGPL-3.0-only
"""
Unit tests for [python/pql_test/runner/pbi_rest.py](../pql_test/runner/pbi_rest.py).

All HTTP and MSAL calls are mocked — no network required.
"""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from pql_test.runner.pbi_rest import (
    _acquire_service_principal_token,
    _resolve_pbi_workspace_and_dataset_names,
    _resolve_pbi_workspace_name,
    _verify_dataset_exists_in_workspace,
)


def _fake_response(payload: dict) -> MagicMock:
    """Build a context-manager-compatible urlopen return value."""
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    resp.read.return_value = json.dumps(payload).encode()
    return resp


# ---------------------------------------------------------------------------
# _resolve_pbi_workspace_and_dataset_names
# ---------------------------------------------------------------------------


class TestResolvePbiWorkspaceAndDatasetNames:
    def test_returns_both_names_from_rest_calls(self):
        def fake_urlopen(req):
            url = req.full_url
            if "/datasets/" in url:
                return _fake_response({"name": "My Dataset"})
            return _fake_response({"name": "My Workspace"})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            ws, ds = _resolve_pbi_workspace_and_dataset_names(
                workspace_id="ws-guid",
                dataset_id="ds-guid",
                access_token="tok",
            )
        assert ws == "My Workspace"
        assert ds == "My Dataset"

    def test_sends_bearer_token_header(self):
        seen_headers: dict = {}

        def fake_urlopen(req):
            seen_headers.update(dict(req.header_items()))
            if "/datasets/" in req.full_url:
                return _fake_response({"name": "D"})
            return _fake_response({"name": "W"})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            _resolve_pbi_workspace_and_dataset_names(
                workspace_id="w",
                dataset_id="d",
                access_token="the-token",
            )
        # urllib normalizes header names to Title-Case
        assert seen_headers.get("Authorization") == "Bearer the-token"

    def test_uses_custom_api_prefix_for_sovereign_cloud(self):
        seen_urls: list[str] = []

        def fake_urlopen(req):
            seen_urls.append(req.full_url)
            return _fake_response({"name": "x"})

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            _resolve_pbi_workspace_and_dataset_names(
                workspace_id="w",
                dataset_id="d",
                access_token="t",
                api_prefix="https://api.powerbigov.us",
            )
        assert all(u.startswith("https://api.powerbigov.us/v1.0/myorg") for u in seen_urls)


# ---------------------------------------------------------------------------
# _resolve_pbi_workspace_name
# ---------------------------------------------------------------------------


class TestResolvePbiWorkspaceName:
    def test_returns_workspace_display_name(self):
        with patch(
            "urllib.request.urlopen",
            return_value=_fake_response({"name": "Prod Workspace"}),
        ):
            result = _resolve_pbi_workspace_name("ws-guid", "tok")
        assert result == "Prod Workspace"


# ---------------------------------------------------------------------------
# _verify_dataset_exists_in_workspace
# ---------------------------------------------------------------------------


class TestVerifyDatasetExistsInWorkspace:
    def test_returns_none_when_dataset_present(self):
        payload = {"value": [{"name": "Model A"}, {"name": "Model B"}]}
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            # No exception raised → success
            _verify_dataset_exists_in_workspace("ws", "Model B", "tok")

    def test_match_is_case_insensitive(self):
        payload = {"value": [{"name": "SampleModel"}]}
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            _verify_dataset_exists_in_workspace("ws", "samplemodel", "tok")

    def test_raises_when_dataset_missing(self):
        payload = {"value": [{"name": "OtherModel"}]}
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            with pytest.raises(ValueError, match="not found in workspace"):
                _verify_dataset_exists_in_workspace("ws-guid", "SampleModel", "tok")

    def test_error_message_lists_available_datasets(self):
        payload = {"value": [{"name": "A"}, {"name": "B"}]}
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            with pytest.raises(ValueError) as exc_info:
                _verify_dataset_exists_in_workspace("ws", "C", "tok")
        assert "'A'" in str(exc_info.value)
        assert "'B'" in str(exc_info.value)

    def test_error_message_says_none_when_workspace_empty(self):
        payload = {"value": []}
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            with pytest.raises(ValueError) as exc_info:
                _verify_dataset_exists_in_workspace("ws", "X", "tok")
        assert "<none>" in str(exc_info.value)

    def test_entries_with_missing_name_do_not_crash(self):
        payload = {"value": [{"name": None}, {"name": "Real"}]}
        with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
            _verify_dataset_exists_in_workspace("ws", "Real", "tok")


# ---------------------------------------------------------------------------
# _acquire_service_principal_token
# ---------------------------------------------------------------------------


class TestAcquireServicePrincipalToken:
    def test_returns_access_token_on_success(self):
        fake_app = MagicMock()
        fake_app.acquire_token_for_client.return_value = {
            "access_token": "eyJ0eXAi.fake",
            "expires_in": 3600,
        }
        with patch(
            "pql_test.runner.pbi_rest.msal.ConfidentialClientApplication",
            return_value=fake_app,
        ):
            token = _acquire_service_principal_token(
                tenant_id="t", client_id="c", client_secret="s",
            )
        assert token == "eyJ0eXAi.fake"

    def test_builds_authority_from_login_url_and_tenant(self):
        fake_app = MagicMock()
        fake_app.acquire_token_for_client.return_value = {"access_token": "tok"}
        with patch(
            "pql_test.runner.pbi_rest.msal.ConfidentialClientApplication",
            return_value=fake_app,
        ) as ctor:
            _acquire_service_principal_token(
                tenant_id="my-tenant",
                client_id="c",
                client_secret="s",
                login_url="https://login.microsoftonline.us",
            )
        _, kwargs = ctor.call_args
        assert kwargs["authority"] == "https://login.microsoftonline.us/my-tenant"

    def test_scopes_include_resource_url_default(self):
        fake_app = MagicMock()
        fake_app.acquire_token_for_client.return_value = {"access_token": "tok"}
        with patch(
            "pql_test.runner.pbi_rest.msal.ConfidentialClientApplication",
            return_value=fake_app,
        ):
            _acquire_service_principal_token(
                tenant_id="t",
                client_id="c",
                client_secret="s",
                resource_url="https://analysis.usgovcloudapi.net/powerbi/api",
            )
        args, _ = fake_app.acquire_token_for_client.call_args
        # scopes is a kwarg — accept either form
        scopes = fake_app.acquire_token_for_client.call_args.kwargs.get("scopes") or args[0]
        assert scopes == ["https://analysis.usgovcloudapi.net/powerbi/api/.default"]

    def test_raises_runtime_error_with_error_description(self):
        fake_app = MagicMock()
        fake_app.acquire_token_for_client.return_value = {
            "error": "invalid_client",
            "error_description": "AADSTS7000215: Invalid client secret provided.",
        }
        with patch(
            "pql_test.runner.pbi_rest.msal.ConfidentialClientApplication",
            return_value=fake_app,
        ):
            with pytest.raises(RuntimeError) as exc_info:
                _acquire_service_principal_token(
                    tenant_id="t", client_id="c", client_secret="s",
                )
        assert "AADSTS7000215" in str(exc_info.value)

    def test_raises_runtime_error_with_error_code_when_no_description(self):
        fake_app = MagicMock()
        fake_app.acquire_token_for_client.return_value = {"error": "unauthorized_client"}
        with patch(
            "pql_test.runner.pbi_rest.msal.ConfidentialClientApplication",
            return_value=fake_app,
        ):
            with pytest.raises(RuntimeError, match="unauthorized_client"):
                _acquire_service_principal_token(
                    tenant_id="t", client_id="c", client_secret="s",
                )

    def test_raises_runtime_error_with_unknown_when_empty_result(self):
        fake_app = MagicMock()
        fake_app.acquire_token_for_client.return_value = {}
        with patch(
            "pql_test.runner.pbi_rest.msal.ConfidentialClientApplication",
            return_value=fake_app,
        ):
            with pytest.raises(RuntimeError, match="Unknown error"):
                _acquire_service_principal_token(
                    tenant_id="t", client_id="c", client_secret="s",
                )

    def test_raises_import_error_when_msal_unavailable(self):
        with patch("pql_test.runner.pbi_rest.HAS_MSAL", False):
            with pytest.raises(ImportError, match="msal"):
                _acquire_service_principal_token(
                    tenant_id="t", client_id="c", client_secret="s",
                )
