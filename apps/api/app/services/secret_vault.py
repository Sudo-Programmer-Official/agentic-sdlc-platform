from __future__ import annotations

import os
import re


def _normalize_ref(vault_ref: str) -> str:
    return re.sub(r"[^A-Z0-9]", "_", (vault_ref or "").upper())


def _secret_env_key(vault_ref: str) -> str:
    return f"DEPLOYMENT_SECRET_{_normalize_ref(vault_ref)}"


def resolve_vault_secret(vault_ref: str | None) -> str | None:
    ref = (vault_ref or "").strip()
    if not ref:
        return None
    key = _secret_env_key(ref)
    value = os.getenv(key)
    if value and value.strip():
        return value.strip()
    return None


def store_vault_secret(vault_ref: str, secret_value: str) -> str:
    ref = (vault_ref or "").strip()
    if not ref:
        raise ValueError("vault_ref is required")
    value = (secret_value or "").strip()
    if not value:
        raise ValueError("secret_value is required")
    os.environ[_secret_env_key(ref)] = value
    return ref
