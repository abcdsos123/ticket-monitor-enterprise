from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, TypedDict
from urllib.parse import urljoin, urlparse

from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

from tixcraft_v17.config import EventConfig
from tixcraft_v17.models import EventSnapshot, SessionSnapshot, TicketArea

PAUSED = ("Your Browsing Activity Has Been Paused", "您的瀏覽活動已暫停", "unusual behavior")
VERIFY = ("verify you are human", "身分驗證", "身份驗證", "驗證您是人類", "captcha")
GAME_SELECTORS = ("a[href*='/activity/game/']", "a[data-href*='/activity/game/']", "button[data-href*='/activity/game/']")
AREA_SELECTORS = ("a[href*='/ticket/area/']", "a[data-href*='/ticket/area/']", "button[data-href*='/ticket/area/']")
ROW_SELECTORS = ("#ticketPriceList li", "#zone li", ".zone-label", ".area-list li", "ul.area-list li", "table tbody tr", ".ticket-area", ".area")
BUTTON_WORDS = re.compile(r"立即購票|立即訂購|購票|Buy Tickets?", re.I)

AVAILABLE_WORDS = re.compile(r"熱賣中|立即訂購|立即購票|可購買|available|選擇|販售中|販売中", re.I)
SOLD_WORDS = re.compile(r"已售完|完售|售完|sold\s*out|暫無票|無票|完売", re.I)

REMAINING_PATTERNS = (
    re.compile(r"剩餘\s*(\d+)\s*(?:張)?", re.I),
    re.compile(r"剩\s*(\d+)\s*張", re.I),
    re.compile(r"(\d+)\s*張\s*(?:可售|可購買|剩餘)", re.I),
    re.compile(r"(\d+)\s*seat\s*\(s\)\s*remaining", re.I),
    re.compile(r"(\d+)\s*seats?\s*remaining", re.I),
    re.compile(r"remaining\s*:?\s*(\d+)", re.I),
    re.compile(r"available\s*:?\s*(\d+)", re.I),
    re.compile(r"残り\s*(\d+)\s*席?", re.I),
    re.compile(r"(\d+)\s*席", re.I),
)

class Link(TypedDict):
    name: str
    url: str


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("　", " ")).strip()


def normalize_area_name(value: str) -> str:
    """Create a comparison key while preserving the original display name."""
    text = clean_text(value).casefold()
    text = re.sub(r"[\s_\-－—–|｜/\\]+", "", text)
    text = re.sub(r"[()（）\[\]【】{}<>《》]", "", text)
    return text


def page_text(driver: WebDriver) -> str:
    try:
        return clean_text(driver.find_element(By.TAG_NAME, "body").text)
    except Exception:
        return clean_text(driver.page_source)


def detect_page_status(driver: WebDriver) -> str:
    text = (clean_text(driver.title) + " " + page_text(driver)).lower()
    if any(marker.lower() in text for marker in PAUSED):
        return "PAUSED"
    if any(marker.lower() in text for marker in VERIFY):
        return "VERIFY"
    return "OK"


def _url(driver: WebDriver, element: WebElement) -> str:
    for attr in ("href", "data-href"):
        try:
            value = clean_text(element.get_attribute(attr))
            if value and not value.lower().startswith("javascript:"):
                return urljoin(driver.current_url, value)
        except StaleElementReferenceException:
            return ""
    return ""


def _name(element: WebElement, default: str) -> str:
    for xpath in (
        "./ancestor::tr[1]",
        "./ancestor::li[1]",
        "./ancestor::*[contains(@class,'game')][1]",
        "./ancestor::*[contains(@class,'session')][1]",
        "./ancestor::*[contains(@class,'event')][1]",
    ):
        try:
            text = BUTTON_WORDS.sub("", clean_text(element.find_element(By.XPATH, xpath).text)).strip(" -｜|")
            if text:
                return text
        except (NoSuchElementException, StaleElementReferenceException):
            pass
    for attr in ("aria-label", "title", "data-title"):
        try:
            text = BUTTON_WORDS.sub("", clean_text(element.get_attribute(attr))).strip()
            if text:
                return text
        except StaleElementReferenceException:
            return default
    try:
        text = BUTTON_WORDS.sub("", clean_text(element.text)).strip()
        return text or default
    except StaleElementReferenceException:
        return default


def find_all_urls(driver: WebDriver, selectors: Iterable[str]) -> list[Link]:
    output: list[Link] = []
    seen: set[str] = set()
    for selector in selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
        except Exception:
            continue
        for element in elements:
            url = _url(driver, element)
            if not url or url in seen:
                continue
            seen.add(url)
            output.append({"name": _name(element, f"場次 {len(output) + 1}"), "url": url})
    return output


def find_game_urls(driver: WebDriver) -> list[Link]:
    return find_all_urls(driver, GAME_SELECTORS)


def find_area_urls(driver: WebDriver) -> list[Link]:
    return find_all_urls(driver, AREA_SELECTORS)


def session_key(event_code: str, url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    candidate = parts[-1] if parts else ""
    if candidate and candidate != event_code:
        return f"{event_code}::{candidate}"
    return f"{event_code}::{hashlib.sha1(url.encode()).hexdigest()[:12]}"


def parse_price(text: str) -> int | None:
    """Extract a ticket price even when it is attached to the area name.

    Tixcraft frequently renders strings such as ``3樓5800 剩餘 12`` without a
    whitespace boundary.  The previous parser required whitespace before the
    amount, so the same area alternated between ``3樓`` and ``3樓5800``.
    """
    cleaned = clean_text(text)

    explicit = re.search(r"(?:NT\$?|TWD|票價)\s*([1-9][0-9,]{2,4})", cleaned, re.I)
    if explicit:
        return int(explicit.group(1).replace(",", ""))

    # Prefer a 3-5 digit amount immediately before availability/status text.
    contextual = re.search(
        r"([1-9][0-9,]{2,4})(?=\s*(?:元|剩餘|剩|remaining|available|熱賣中|已售完|售完|完售|sold\s*out|$))",
        cleaned,
        re.I,
    )
    if contextual:
        return int(contextual.group(1).replace(",", ""))

    # Final fallback: use the last plausible ticket amount, not remaining count.
    candidates = re.findall(r"(?<!\d)([1-9][0-9,]{3,4})(?!\d)", cleaned)
    return int(candidates[-1].replace(",", "")) if candidates else None


def parse_price_range(text: str) -> tuple[int | None, int | None]:
    cleaned = clean_text(text)
    m = re.search(r"(?:NT\$?|TWD|\$)?\s*([1-9][0-9,]{3,4})\s*[-~～至]\s*(?:NT\$?|TWD|\$)?\s*([1-9][0-9,]{3,4})", cleaned, re.I)
    if not m: return None, None
    a,b=(int(x.replace(",","")) for x in m.groups())
    return min(a,b),max(a,b)

def parse_remaining(text: str) -> int | None:
    cleaned = clean_text(text)
    for pattern in REMAINING_PATTERNS:
        match = pattern.search(cleaned)
        if match:
            return int(match.group(1))
    return None


def parse_status(text: str, remaining: int | None = None) -> str:
    cleaned = clean_text(text)
    if remaining is None:
        remaining = parse_remaining(cleaned)

    # A concrete remaining count is stronger evidence than status words that may
    # leak in from a parent DOM node containing several ticket rows.
    if remaining is not None:
        return "有票" if remaining > 0 else "售完"
    if re.search(r"熱賣中", cleaned):
        return "熱賣中"
    if AVAILABLE_WORDS.search(cleaned):
        return "有票"
    if SOLD_WORDS.search(cleaned):
        return "售完"
    return "未知"


def detect_language(text: str) -> str:
    if re.search(r"[ぁ-んァ-ン一-龥]", text):
        if re.search(r"残り|完売|販売", text):
            return "JA"
        return "ZH"
    if re.search(r"[A-Za-z]", text):
        return "EN"
    return "UNKNOWN"


def parse_area_name(text: str, price: int | None) -> str:
    result = clean_text(text)
    if price is not None:
        # Remove both comma and non-comma forms, including prices attached to a
        # Chinese area name (for example: 3樓5800).
        price_forms = {str(price), f"{price:,}"}
        pattern = "|".join(re.escape(value) for value in sorted(price_forms, key=len, reverse=True))
        result = re.sub(rf"(?:NT\$?\s*)?(?:{pattern})", "", result, count=1, flags=re.I)
    cleanup_patterns = (
        r"剩餘\s*\d+\s*(?:張)?",
        r"剩\s*\d+\s*張",
        r"\d+\s*張\s*(?:可售|可購買|剩餘)",
        r"\d+\s*seat\s*\(s\)\s*remaining",
        r"\d+\s*seats?\s*remaining",
        r"remaining\s*:?\s*\d+",
        r"available\s*:?\s*\d+",
        r"残り\s*\d+\s*席?",
        r"\d+\s*席",
        r"熱賣中|立即訂購|立即購票|已售完|完售|售完|sold\s*out|可購買|available|選擇|販售中|販売中|完売",
    )
    result = re.sub("|".join(f"(?:{pattern})" for pattern in cleanup_patterns), "", result, flags=re.I)
    result = clean_text(result).strip(" -｜|")
    return result or clean_text(text)[:80]


def parse_ticket_text(text: str) -> dict[str, object]:
    raw = clean_text(text)
    price = parse_price(raw)
    remaining = parse_remaining(raw)
    status = parse_status(raw, remaining)
    area_name = parse_area_name(raw, price)
    normalized = normalize_area_name(area_name)
    return {
        "raw": raw,
        "area": area_name,
        "normalized_area": normalized,
        "price": price,
        "remaining": remaining,
        "status": status,
        "language": detect_language(raw),
    }


def _write_parser_replay(record: dict[str, object], directory: str | Path = "logs/parser") -> None:
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    (path / f"{stamp}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_ticket_page(driver: WebDriver, event: EventConfig, name: str, url: str, *, debug_parser: bool=False, parser_replay: bool=False) -> SessionSnapshot:
    snapshot=SessionSnapshot(event.code,event.name,session_key(event.code,url),clean_text(name) or "未命名場次",url,page_status=detect_page_status(driver))
    if snapshot.page_status!="OK": return snapshot
    rows=[]
    seen_elements=set()
    for selector in ROW_SELECTORS:
        try: elements=driver.find_elements(By.CSS_SELECTOR,selector)
        except Exception: continue
        for element in elements:
            try:
                marker=element.id
                raw=clean_text(element.text)
            except StaleElementReferenceException: continue
            if not raw or len(raw)>500 or marker in seen_elements: continue
            seen_elements.add(marker); rows.append(raw)
    parent_group=""; parent_min=parent_max=None; occurrence={}
    for raw in rows:
        pmin,pmax=parse_price_range(raw); parsed=parse_ticket_text(raw)
        # Price-only/group heading: remember it, but do not create a fake ticket area.
        has_status=parse_remaining(raw) is not None or AVAILABLE_WORDS.search(raw) or SOLD_WORDS.search(raw)
        if not has_status and (pmin is not None or parsed.get("price") is not None):
            parent_group=parse_area_name(raw, parsed.get("price") if isinstance(parsed.get("price"),int) else None)
            parent_min,parent_max=pmin,pmax
            continue
        area_name=str(parsed["area"]); subtype="best_available" if re.search(r"best\s*available",raw,re.I) else "normal"
        area_name=re.sub(r"\(?\s*best\s*available\s*\)?","",area_name,flags=re.I).strip()
        price=parsed["price"] if isinstance(parsed["price"],int) else None
        if price is None and parent_min is not None and parent_min==parent_max: price=parent_min
        ident="|".join((normalize_area_name(parent_group),normalize_area_name(area_name),subtype,str(price or ""),str(parent_min or ""),str(parent_max or "")))
        occurrence[ident]=occurrence.get(ident,0)+1; occ=occurrence[ident]; key=f"{ident}|{occ}"
        candidate=TicketArea(key=key,name=area_name,status=str(parsed["status"]),remaining=parsed["remaining"] if isinstance(parsed["remaining"],int) else None,
            price=price,price_min=parent_min,price_max=parent_max,group=parent_group,subtype=subtype,occurrence=occ,raw_text=raw)
        snapshot.areas[key]=candidate
        if debug_parser: print("[Parser]",candidate.to_dict())
        if parser_replay: _write_parser_replay(candidate.to_dict())
    if not snapshot.areas and find_area_urls(driver): snapshot.areas["購票入口|1"]=TicketArea("購票入口|1","購票入口","有票",raw_text="可進入票區")
    return snapshot


class TixcraftParser:
    def __init__(self, *, debug_parser: bool = False, parser_replay: bool = False) -> None:
        self.debug_parser = debug_parser
        self.parser_replay = parser_replay

    def discover_game_links(self, driver: WebDriver) -> list[Link]:
        return find_game_urls(driver)

    def discover_area_links(self, driver: WebDriver) -> list[Link]:
        return find_area_urls(driver)

    def parse_current(self, driver: WebDriver, event: EventConfig, name: str, url: str) -> SessionSnapshot:
        return parse_ticket_page(
            driver,
            event,
            name,
            url,
            debug_parser=self.debug_parser,
            parser_replay=self.parser_replay,
        )

    def empty_event(self, event: EventConfig) -> EventSnapshot:
        return EventSnapshot(event.code, event.name, event.url, [])
