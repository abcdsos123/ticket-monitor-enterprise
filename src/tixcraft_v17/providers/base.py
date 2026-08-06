from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from selenium.webdriver.remote.webdriver import WebDriver

from tixcraft_v17.config import EventConfig
from tixcraft_v17.models import EventSnapshot


class OpenPage(Protocol):
    def __call__(self, url: str) -> None: ...


class TicketProvider(ABC):
    """Common contract for ticketing platforms.

    Providers only read publicly visible ticket state. They do not log in,
    reserve seats, solve CAPTCHAs, or enter checkout flows.
    """

    name: str

    @abstractmethod
    def supports(self, event: EventConfig) -> bool:
        raise NotImplementedError

    @abstractmethod
    def check_event(self, driver: WebDriver, event: EventConfig, open_page: OpenPage) -> EventSnapshot:
        raise NotImplementedError
