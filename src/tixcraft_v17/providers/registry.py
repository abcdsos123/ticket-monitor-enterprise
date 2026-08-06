from __future__ import annotations

from tixcraft_v17.config import EventConfig
from tixcraft_v17.providers.base import TicketProvider
from tixcraft_v17.providers.detect import detect_provider


class ProviderRegistry:
    def __init__(self, providers: list[TicketProvider]) -> None:
        self._providers = {provider.name: provider for provider in providers}

    def get(self, event: EventConfig) -> TicketProvider:
        name = detect_provider(event.url, event.provider)
        try:
            return self._providers[name]
        except KeyError as exc:
            raise ValueError(f"不支援的售票平台：{name}（{event.url}）") from exc

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._providers)
