from __future__ import annotations

from collections.abc import Callable

from app.services.vcs.base import VCSAdapter


def normalize_provider_name(provider: str | None) -> str:
    value = (provider or "").strip().lower()
    if not value:
        raise ValueError("provider is required")
    return value


class VCSProviderRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, VCSAdapter | None] = {}
        self._installation_getters: dict[str, Callable[[], int | None] | None] = {}

    def register(
        self,
        provider: str,
        *,
        adapter: VCSAdapter | None = None,
        installation_id_getter: Callable[[], int | None] | None = None,
    ) -> None:
        key = normalize_provider_name(provider)
        self._adapters[key] = adapter
        self._installation_getters[key] = installation_id_getter

    def get_adapter(self, provider: str | None) -> VCSAdapter | None:
        return self._adapters.get(normalize_provider_name(provider))

    def get_default_installation_id(self, provider: str | None) -> int | None:
        getter = self._installation_getters.get(normalize_provider_name(provider))
        return getter() if getter else None


provider_registry = VCSProviderRegistry()


def get_vcs_adapter(provider: str | None) -> VCSAdapter | None:
    return provider_registry.get_adapter(provider)


def get_default_installation_id(provider: str | None) -> int | None:
    return provider_registry.get_default_installation_id(provider)
