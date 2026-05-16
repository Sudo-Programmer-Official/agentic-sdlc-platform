from __future__ import annotations

import json
import logging
import time
import urllib.request
from dataclasses import dataclass
from typing import Any

import jwt
from cryptography import x509


FIREBASE_CERTS_URL = "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"


@dataclass
class _CertCache:
    certs: dict[str, str]
    fetched_at: float


_CERT_CACHE: _CertCache | None = None
_CERT_TTL_SECONDS = 3600


class FirebaseAuthError(ValueError):
    pass


log = logging.getLogger("app.firebase_auth")


def _fetch_certs() -> dict[str, str]:
    global _CERT_CACHE
    now = time.time()
    if _CERT_CACHE and now - _CERT_CACHE.fetched_at < _CERT_TTL_SECONDS:
        return _CERT_CACHE.certs
    with urllib.request.urlopen(FIREBASE_CERTS_URL, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise FirebaseAuthError("Unable to fetch Firebase signing certificates.")
    certs = {str(k): str(v) for k, v in payload.items()}
    _CERT_CACHE = _CertCache(certs=certs, fetched_at=now)
    return certs


def verify_firebase_bearer_token(token: str, *, project_id: str) -> dict[str, Any]:
    if not token or not token.strip():
        raise FirebaseAuthError("Firebase token is missing.")
    if not project_id or not project_id.strip():
        raise FirebaseAuthError("Firebase project is not configured.")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        log.warning("Firebase auth failed: invalid token header project_id=%s error=%s", project_id, type(exc).__name__)
        raise FirebaseAuthError("Invalid Firebase token header.") from exc

    kid = str(header.get("kid") or "").strip()
    if not kid:
        log.warning("Firebase auth failed: missing kid project_id=%s", project_id)
        raise FirebaseAuthError("Firebase token is missing key id.")

    certs = _fetch_certs()
    cert = certs.get(kid)
    if not cert:
        log.warning("Firebase auth failed: signing key not found project_id=%s kid=%s", project_id, kid)
        raise FirebaseAuthError("Unable to resolve Firebase signing key.")
    try:
        public_key = x509.load_pem_x509_certificate(cert.encode("utf-8")).public_key()
    except Exception as exc:  # pragma: no cover - defensive parsing guard
        log.warning("Firebase auth failed: unable to parse x509 cert project_id=%s kid=%s error=%s", project_id, kid, type(exc).__name__)
        raise FirebaseAuthError("Unable to resolve Firebase signing key.") from exc

    issuer = f"https://securetoken.google.com/{project_id}"
    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=project_id,
            issuer=issuer,
            options={"require": ["exp", "iat", "aud", "iss", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        log.warning("Firebase auth failed: token expired project_id=%s kid=%s", project_id, kid)
        raise FirebaseAuthError("Firebase token verification failed.") from exc
    except jwt.InvalidAudienceError as exc:
        log.warning("Firebase auth failed: invalid audience project_id=%s kid=%s", project_id, kid)
        raise FirebaseAuthError("Firebase token verification failed.") from exc
    except jwt.InvalidIssuerError as exc:
        log.warning("Firebase auth failed: invalid issuer project_id=%s kid=%s", project_id, kid)
        raise FirebaseAuthError("Firebase token verification failed.") from exc
    except jwt.MissingRequiredClaimError as exc:
        log.warning(
            "Firebase auth failed: missing claim project_id=%s kid=%s claim=%s",
            project_id,
            kid,
            getattr(exc, "claim", "unknown"),
        )
        raise FirebaseAuthError("Firebase token verification failed.") from exc
    except jwt.PyJWTError as exc:
        log.warning("Firebase auth failed: jwt verification error project_id=%s kid=%s error=%s", project_id, kid, type(exc).__name__)
        raise FirebaseAuthError("Firebase token verification failed.") from exc

    sub = str(claims.get("sub") or "").strip()
    if not sub:
        log.warning("Firebase auth failed: missing sub after verify project_id=%s kid=%s", project_id, kid)
        raise FirebaseAuthError("Firebase token subject is missing.")
    return claims
