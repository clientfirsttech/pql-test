# SPDX-License-Identifier: AGPL-3.0-only
"""When a service-principal certificate expires, read locally from the certificate file."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Warn from this many days before the certificate expires.
CERT_EXPIRY_WARNING_DAYS = 30

_PEM_CERT = re.compile(rb"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", re.DOTALL)


def certificate_expiry(path: str, password: Optional[str] = None) -> Optional[datetime]:
    """The certificate's expiry (UTC), or ``None`` when the file cannot be read or parsed.

    Handles PEM (the first certificate in the file) and PKCS#12 (``.pfx`` / ``.p12``). Only the
    public certificate is read; the private key is never used. Never raises: a status check
    must not fail because a certificate file moved.
    """
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives.serialization import pkcs12

        data = Path(path).read_bytes()
        match = _PEM_CERT.search(data)
        if match:
            cert = x509.load_pem_x509_certificate(match.group(0))
        else:
            _key, cert, _more = pkcs12.load_key_and_certificates(data, password.encode() if password else None)
            if cert is None:
                return None
        expires = getattr(cert, "not_valid_after_utc", None)
        if expires is None:  # cryptography < 42
            expires = cert.not_valid_after.replace(tzinfo=timezone.utc)
        return expires
    except Exception:  # noqa: BLE001 - any failure means "unknown expiry"
        return None
