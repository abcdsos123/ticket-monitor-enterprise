from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()


@dataclass(slots=True)
class EventConfig:
    code: str
    name: str
    url: str
    enabled: bool = True
    provider: str = "auto"


@dataclass(slots=True)
class AppConfig:
    check_interval_seconds: float = 30
    page_wait_seconds: int = 20
    navigation_delay_seconds: float = 1.5
    headless: bool = False
    tixcraft_browser_engine: str = "selenium"
    kktix_browser_engine: str = "nodriver"
    browser_profile_dir: str = "./data/chrome-profile-tixcraft"
    kktix_browser_profile_dir: str = "./data/chrome-profile-kktix"
    notify_initial_state: bool = True
    notify_changes: bool = True
    screenshot_on_error: bool = True
    auto_restart_browser: bool = True
    restart_after_consecutive_errors: int = 3
    config_reload_seconds: float = 15
    backup_interval_hours: float = 24
    backup_keep: int = 14
    debug_parser: bool = False
    parser_replay: bool = True
    events: list[EventConfig] = field(default_factory=list)
    source_path: str = "config/config.json"

    @classmethod
    def load(cls, path: str | Path = "config/config.json") -> "AppConfig":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(
                f"找不到 {p}，請複製 config/config.example.json 為 config/config.json"
            )
        raw: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
        return cls(
            check_interval_seconds=float(raw.get("check_interval_seconds", 30)),
            page_wait_seconds=int(raw.get("page_wait_seconds", 20)),
            navigation_delay_seconds=float(raw.get("navigation_delay_seconds", 1.5)),
            headless=bool(raw.get("headless", False)),
            tixcraft_browser_engine=str(raw.get("tixcraft_browser_engine", "selenium")).lower(),
            kktix_browser_engine=str(raw.get("kktix_browser_engine", raw.get("browser_engine", "nodriver"))).lower(),
            browser_profile_dir=str(raw.get("browser_profile_dir", "./data/chrome-profile-tixcraft")),
            kktix_browser_profile_dir=str(raw.get("kktix_browser_profile_dir", "./data/chrome-profile-kktix")),
            notify_initial_state=bool(raw.get("notify_initial_state", True)),
            notify_changes=bool(raw.get("notify_changes", True)),
            screenshot_on_error=bool(raw.get("screenshot_on_error", True)),
            auto_restart_browser=bool(raw.get("auto_restart_browser", True)),
            restart_after_consecutive_errors=int(raw.get("restart_after_consecutive_errors", 3)),
            config_reload_seconds=float(raw.get("config_reload_seconds", 15)),
            backup_interval_hours=float(raw.get("backup_interval_hours", 24)),
            backup_keep=int(raw.get("backup_keep", 14)),
            debug_parser=bool(raw.get("debug_parser", False)),
            parser_replay=bool(raw.get("parser_replay", True)),
            events=[EventConfig(**item) for item in raw.get("events", [])],
            source_path=str(p),
        )


DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID", "")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID", "")
DISCORD_ADMIN_ROLE_ID = os.getenv("DISCORD_ADMIN_ROLE_ID", "")
DISCORD_OWNER_IDS = {int(x.strip()) for x in os.getenv("DISCORD_OWNER_IDS", "").split(",") if x.strip().isdigit()}
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
