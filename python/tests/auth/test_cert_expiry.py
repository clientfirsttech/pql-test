# SPDX-License-Identifier: AGPL-3.0-only
"""Certificate expiry for `pql-test auth status`."""

from __future__ import annotations

import datetime as dt
import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

import pql_test.cli as cli_module
from pql_test.auth.cert_expiry import certificate_expiry
from pql_test.auth.models import AuthMethod, AuthStatus


def _make_cert(days_valid: int):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "pql-test")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=days_valid))
        .sign(key, hashes.SHA256())
    )
    return key, cert, serialization


class TestCertificateExpiry:
    def test_reads_expiry_from_a_pem_with_key_and_certificate(self, tmp_path):
        given = "a PEM file holding a private key then a certificate valid for 10 days"
        should = "return that certificate's expiry"
        key, cert, ser = _make_cert(10)
        pem = tmp_path / "c.pem"
        pem.write_bytes(
            key.private_bytes(ser.Encoding.PEM, ser.PrivateFormat.PKCS8, ser.NoEncryption())
            + cert.public_bytes(ser.Encoding.PEM)
        )

        expires = certificate_expiry(str(pem))

        assert expires is not None and 9 <= (expires - dt.datetime.now(dt.timezone.utc)).days <= 10, f"{given}: {should}"

    def test_reads_expiry_from_a_password_protected_pfx(self, tmp_path):
        given = "a .pfx protected by a password"
        should = "return the expiry when given the password"
        from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12

        key, cert, _ = _make_cert(40)
        pfx = tmp_path / "c.pfx"
        pfx.write_bytes(pkcs12.serialize_key_and_certificates(b"n", key, cert, None, BestAvailableEncryption(b"pw")))

        assert certificate_expiry(str(pfx), "pw") is not None, f"{given}: {should}"

    @pytest.mark.parametrize("content", [b"not a certificate", b""])
    def test_unreadable_file_gives_none(self, tmp_path, content):
        given = "a file that is not a certificate"
        should = "return None instead of raising"
        bad = tmp_path / "bad.pem"
        bad.write_bytes(content)

        assert certificate_expiry(str(bad)) is None, f"{given}: {should}"

    def test_missing_file_gives_none(self, tmp_path):
        assert certificate_expiry(str(tmp_path / "gone.pem")) is None


class TestAuthStatusCertificate:
    def _status(self, days: int) -> AuthStatus:
        return AuthStatus(
            authenticated=True,
            method=AuthMethod.SERVICE_PRINCIPAL_CERT,
            certificate_expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days, hours=1),
        )

    @pytest.mark.parametrize("days, warned", [(200, False), (30, True), (5, True), (-3, True)])
    def test_warns_within_thirty_days_or_when_expired(self, days, warned):
        given = f"a certificate with {days} day(s) left"
        should = "show the expiry and warn only inside the 30-day window"
        with patch("pql_test.auth.manager.AuthenticationManager.get_status", return_value=self._status(days)):
            result = CliRunner().invoke(cli_module.cli, ["auth", "status"])

        assert "Certificate expires:" in result.output, f"{given}: {should}"
        assert ("Warning: the service-principal certificate" in result.output) == warned, f"{given}: {should}"

    def test_json_includes_expiry_and_days(self):
        given = "auth status --format json with a certificate"
        should = "include certificateExpiresAt and certificateDaysRemaining"
        with patch("pql_test.auth.manager.AuthenticationManager.get_status", return_value=self._status(10)):
            result = CliRunner().invoke(cli_module.cli, ["auth", "status", "--format", "json"])

        data = json.loads(result.output[result.output.index("{"):])
        assert data["certificateDaysRemaining"] == 10 and data["certificateExpiresAt"], f"{given}: {should}"

    def test_no_certificate_line_for_other_methods(self):
        status = AuthStatus(authenticated=True, method=AuthMethod.SERVICE_PRINCIPAL_SECRET)
        with patch("pql_test.auth.manager.AuthenticationManager.get_status", return_value=status):
            result = CliRunner().invoke(cli_module.cli, ["auth", "status"])

        assert "Certificate" not in result.output
