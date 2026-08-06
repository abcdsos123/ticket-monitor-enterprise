from __future__ import annotations

from selenium.webdriver.remote.webdriver import WebDriver

from tixcraft_v17.config import EventConfig
from tixcraft_v17.models import EventSnapshot, SessionSnapshot
from tixcraft_v17.parser import TixcraftParser
from tixcraft_v17.providers.base import OpenPage, TicketProvider
from tixcraft_v17.providers.detect import detect_provider


class TixcraftProvider(TicketProvider):
    name = "tixcraft"

    def __init__(self, parser: TixcraftParser, on_session=None) -> None:
        self.parser = parser
        self.on_session = on_session

    def supports(self, event: EventConfig) -> bool:
        return detect_provider(event.url, event.provider) == self.name

    def _session(self, value: str) -> None:
        if self.on_session:
            self.on_session(value)

    def check_event(self, driver: WebDriver, event: EventConfig, open_page: OpenPage) -> EventSnapshot:
        open_page(event.url)
        games = self.parser.discover_game_links(driver)
        sessions: list[SessionSnapshot] = []
        if not games:
            areas = self.parser.discover_area_links(driver)
            if areas:
                for link in areas:
                    self._session(link["name"])
                    open_page(link["url"])
                    sessions.append(self.parser.parse_current(driver, event, link["name"], link["url"]))
            else:
                self._session(event.name)
                sessions.append(self.parser.parse_current(driver, event, event.name, event.url))
            return EventSnapshot(event.code, event.name, event.url, sessions)

        for game in games:
            open_page(game["url"])
            areas = self.parser.discover_area_links(driver)
            if not areas:
                self._session(game["name"])
                sessions.append(self.parser.parse_current(driver, event, game["name"], game["url"]))
                continue
            for area in areas:
                name = area["name"] or game["name"]
                self._session(name)
                open_page(area["url"])
                sessions.append(self.parser.parse_current(driver, event, name, area["url"]))
                open_page(game["url"])
        return EventSnapshot(event.code, event.name, event.url, sessions)
