from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin, urlparse

from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from tixcraft_v17.config import EventConfig
from tixcraft_v17.models import EventSnapshot, SessionSnapshot, TicketArea
from tixcraft_v17.parser.tixcraft import (
    clean_text,
    normalize_area_name,
    parse_price,
    parse_price_range,
)
from tixcraft_v17.providers.base import OpenPage, TicketProvider
from tixcraft_v17.providers.detect import detect_provider

SOLD_WORDS = (
    "sold out",
    "售完",
    "已售完",
    "暫無票券",
    "額滿",
    "停止販售",
)


def _text_content(element) -> str:
    return clean_text(element.get_attribute("textContent") or "")


def _find_text(parent, selector: str) -> str:
    try:
        return _text_content(parent.find_element(By.CSS_SELECTOR, selector))
    except NoSuchElementException:
        return ""


def _status(raw_text: str) -> str:
    normalized = clean_text(raw_text).casefold()
    return "售完" if any(word.casefold() in normalized for word in SOLD_WORDS) else "有票"


def _session_key(code: str, url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if len(parts) >= 2 and parts[-1] == "new":
        token = parts[-2]
    else:
        token = parts[-1] if parts else ""
    token = token or hashlib.sha1(url.encode()).hexdigest()[:12]
    return f"{code}::kktix::{token}"


def _registration_links(driver: WebDriver) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for element in driver.find_elements(By.CSS_SELECTOR, "a[href]"):
        try:
            href = (element.get_attribute("href") or "").strip()
            if not href:
                continue
            href = urljoin(driver.current_url, href)
            if "/registrations/new" not in href or href in seen:
                continue
            seen.add(href)
            name = clean_text(element.get_attribute("textContent") or "")
            result.append({"name": name or "KKTIX 報名頁", "url": href})
        except StaleElementReferenceException:
            continue
    result.sort(key=lambda item: 0 if "kktix.com/events/" in item["url"] else 1)
    return result


def _fallback_name(raw: str, price_text: str, status: str) -> str:
    value = raw
    if price_text:
        value = value.replace(price_text, " ")
    for word in SOLD_WORDS:
        value = re.sub(re.escape(word), " ", value, flags=re.I)
    value = re.sub(r"[＋+－-]\s*\d+\s*[＋+]", " ", value)
    value = clean_text(value).strip(" -｜|")
    return value or f"KKTIX 票種 {status}"


class KktixProvider(TicketProvider):
    name = "kktix"

    def __init__(self, on_session=None) -> None:
        self.on_session = on_session

    def supports(self, event: EventConfig) -> bool:
        return detect_provider(event.url, event.provider) == self.name

    @staticmethod
    def _append_area(
        snapshot: SessionSnapshot,
        occurrence: dict[str, int],
        *,
        name: str,
        seat: str,
        price_text: str,
        raw_text: str,
        status: str,
    ) -> None:
        price = parse_price(price_text or raw_text)
        pmin, pmax = parse_price_range(price_text or raw_text)
        area_name = clean_text(name) or _fallback_name(raw_text, price_text, status)
        if seat and seat not in area_name:
            area_name = clean_text(f"{area_name}｜{seat}")

        base = "|".join(
            (
                normalize_area_name(area_name),
                str(price or ""),
                str(pmin or ""),
                str(pmax or ""),
            )
        )
        occurrence[base] = occurrence.get(base, 0) + 1
        occ = occurrence[base]
        key = f"kktix|{base}|{occ}"
        snapshot.areas[key] = TicketArea(
            key=key,
            name=area_name,
            status=status,
            remaining=None,
            price=price,
            price_min=pmin,
            price_max=pmax,
            group="KKTIX",
            subtype="normal",
            occurrence=occ,
            raw_text=raw_text,
        )

    def _parse_selenium(
        self,
        driver: WebDriver,
        event: EventConfig,
        name: str,
        url: str,
    ) -> SessionSnapshot:
        snapshot = SessionSnapshot(
            event.code,
            event.name,
            _session_key(event.code, url),
            clean_text(name) or event.name,
            url,
        )
        occurrence: dict[str, int] = {}

        for unit in driver.find_elements(By.CSS_SELECTOR, ".ticket-unit"):
            try:
                ticket_name = _find_text(unit, ".ticket-name")
                seat = _find_text(unit, ".ticket-seat")
                price_text = _find_text(unit, ".ticket-price")
                quantity_text = _find_text(unit, ".ticket-quantity")
                raw_text = _text_content(unit)
            except StaleElementReferenceException:
                continue
            if not raw_text:
                continue
            self._append_area(
                snapshot,
                occurrence,
                name=ticket_name,
                seat=seat,
                price_text=price_text,
                raw_text=raw_text,
                status=_status(f"{quantity_text} {raw_text}"),
            )

        if snapshot.areas:
            snapshot.page_status = (
                "IN_STOCK"
                if any(area.status == "有票" for area in snapshot.areas.values())
                else "OUT_OF_STOCK"
            )
        else:
            visible_text = clean_text(driver.find_element(By.TAG_NAME, "body").text)
            if re.search(r"尚未開賣|未開賣|coming\s*soon", visible_text, re.I):
                snapshot.page_status = "NOT_STARTED"
            elif re.search(r"報名已結束|活動已結束|registration\s*closed", visible_text, re.I):
                snapshot.page_status = "REGISTRATION_CLOSED"
            else:
                snapshot.page_status = "NO_TICKET_ROWS"
        return snapshot

    def check_event_nodriver(
        self,
        manager,
        event: EventConfig,
        *,
        wait_seconds: int,
        delay_seconds: float,
    ) -> EventSnapshot:
        payload = manager.extract_event(event.url, wait_seconds, delay_seconds)
        sessions: list[SessionSnapshot] = []

        for item in payload.get("sessions", []):
            url = str(item.get("url") or event.url)
            name = clean_text(str(item.get("name") or event.name))
            snapshot = SessionSnapshot(
                event.code,
                event.name,
                _session_key(event.code, url),
                name or event.name,
                url,
            )
            occurrence: dict[str, int] = {}

            for unit in item.get("units") or []:
                if not isinstance(unit, dict):
                    continue
                raw_text = clean_text(str(unit.get("raw_text") or ""))
                self._append_area(
                    snapshot,
                    occurrence,
                    name=clean_text(str(unit.get("name") or "")),
                    seat=clean_text(str(unit.get("seat") or "")),
                    price_text=clean_text(str(unit.get("price_text") or "")),
                    raw_text=raw_text,
                    status=_status(
                        f"{unit.get('quantity_text') or ''} {raw_text}"
                    ),
                )

            # 票種優先。只要有票種，絕不讓驗證判斷覆蓋解析結果。
            if snapshot.areas:
                snapshot.page_status = (
                    "IN_STOCK"
                    if any(area.status == "有票" for area in snapshot.areas.values())
                    else "OUT_OF_STOCK"
                )
            else:
                snapshot.page_status = str(
                    item.get("page_status") or "NO_TICKET_ROWS"
                )
            sessions.append(snapshot)

        if not sessions:
            sessions.append(
                SessionSnapshot(
                    event.code,
                    event.name,
                    _session_key(event.code, event.url),
                    event.name,
                    event.url,
                    page_status="NO_TICKET_ROWS",
                )
            )
        return EventSnapshot(event.code, event.name, event.url, sessions)

    def check_event(
        self,
        driver: WebDriver,
        event: EventConfig,
        open_page: OpenPage,
    ) -> EventSnapshot:
        open_page(event.url)
        links = _registration_links(driver)
        targets = links or [{"name": event.name, "url": event.url}]
        sessions: list[SessionSnapshot] = []

        for target in targets:
            if self.on_session:
                self.on_session(target["name"])
            open_page(target["url"])
            try:
                WebDriverWait(driver, 30).until(
                    lambda current: len(
                        current.find_elements(By.CSS_SELECTOR, ".ticket-unit")
                    ) > 0
                    or current.find_elements(By.CSS_SELECTOR, "#registrationsNewApp")
                )
            except Exception:
                pass
            sessions.append(
                self._parse_selenium(
                    driver,
                    event,
                    target["name"],
                    target["url"],
                )
            )

        return EventSnapshot(event.code, event.name, event.url, sessions)
