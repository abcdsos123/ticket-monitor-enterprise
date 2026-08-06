from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from selenium.webdriver.support.ui import WebDriverWait

from tixcraft_v17.browser import BrowserManager, KktixNodriverManager
from tixcraft_v17.enterprise import BackupManager, StatsStore
from tixcraft_v17.config import AppConfig, EventConfig
from tixcraft_v17.models import EventSnapshot, SessionSnapshot
from tixcraft_v17.monitor.control import ControlQueue
from tixcraft_v17.notifier import NotificationQueue
from tixcraft_v17.parser import TixcraftParser
from tixcraft_v17.parser.tixcraft import normalize_area_name
from tixcraft_v17.providers import KktixProvider, ProviderRegistry, TixcraftProvider
from tixcraft_v17.runtime import RuntimeStore
from tixcraft_v17.state import HistoryStore, StateStore, change_text, diff_snapshots

logger = logging.getLogger(__name__)


class MonitorService:
    def __init__(
        self,
        config: AppConfig,
        browsers: dict[str, BrowserManager | KktixNodriverManager],
        parser: TixcraftParser,
        runtime: RuntimeStore,
        state: StateStore,
        history: HistoryStore,
        queue: NotificationQueue,
        control: ControlQueue,
        stats: StatsStore | None = None,
        backup: BackupManager | None = None,
    ) -> None:
        self.config = config
        self.browsers = browsers
        self.parser = parser
        self.providers = ProviderRegistry([
            TixcraftProvider(parser, on_session=lambda value: runtime.update(current_session=value)),
            KktixProvider(on_session=lambda value: runtime.update(current_session=value)),
        ])
        self.runtime = runtime
        self.state = state
        self.history = history
        self.queue = queue
        self.control = control
        self.stats = stats or StatsStore()
        self.backup = backup or BackupManager(keep=config.backup_keep)
        self._stop = False
        self._consecutive_errors = 0
        self._config_mtime = Path(config.source_path).stat().st_mtime if Path(config.source_path).exists() else 0.0

    def stop(self) -> None:
        self._stop = True

    def _browser(self, provider: str) -> BrowserManager | KktixNodriverManager:
        try:
            return self.browsers[provider]
        except KeyError as exc:
            raise ValueError(f"缺少 {provider} 瀏覽器設定") from exc

    def _all_browsers_alive(self) -> bool:
        return all(browser.is_alive() for browser in self.browsers.values())

    def _open_with(self, browser: BrowserManager, url: str) -> None:
        driver = browser.get()
        driver.get(url)
        WebDriverWait(driver, self.config.page_wait_seconds).until(
            lambda current: current.execute_script("return document.readyState")
            in {"interactive", "complete"}
        )
        time.sleep(self.config.navigation_delay_seconds)

    def _debug(self, prefix: str, provider_name: str = "tixcraft") -> None:
        if not self.config.screenshot_on_error:
            return
        try:
            self._browser(provider_name).screenshot(
                Path("screenshots")
                / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}.png"
            )
        except Exception:
            logger.debug("儲存除錯截圖失敗", exc_info=True)

    def check_event(self, event: EventConfig) -> EventSnapshot:
        provider = self.providers.get(event)
        browser = self._browser(provider.name)
        logger.info("檢查活動 %s（provider=%s, engine=%s, profile=%s）", event.name, provider.name, getattr(browser, "engine", "selenium"), browser.profile_dir)
        # 不只依賴 isinstance：若使用者覆蓋部分檔案、開發環境發生模組重載，
        # 同名 class 可能來自不同 module instance，導致 isinstance 誤判。
        # nodriver manager 的穩定辨識依據是 engine 與 extract_event 能力。
        is_kktix_nodriver = (
            provider.name == "kktix"
            and getattr(browser, "engine", "") == "nodriver"
            and callable(getattr(browser, "extract_event", None))
        )
        if is_kktix_nodriver:
            return provider.check_event_nodriver(
                browser, event,
                wait_seconds=self.config.page_wait_seconds,
                delay_seconds=self.config.navigation_delay_seconds,
            )

        if not callable(getattr(browser, "get", None)):
            raise TypeError(
                f"瀏覽器管理器介面不相容：provider={provider.name}, "
                f"engine={getattr(browser, 'engine', 'unknown')}, "
                f"class={type(browser).__module__}.{type(browser).__qualname__}"
            )
        driver = browser.get()
        return provider.check_event(
            driver,
            event,
            lambda url: self._open_with(browser, url),
        )

    @staticmethod
    def diff(
        old: dict[str, Any] | None,
        new: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return diff_snapshots(old, new)

    @staticmethod
    def format_snapshot(
        snapshot: dict[str, Any],
        title: str = "🎫 目前票況",
        requester: str = "",
    ) -> str:
        lines = [
            title,
            f"活動：{snapshot.get('event_name')}",
            f"場次：{snapshot.get('session_name')}",
            f"頁面：{snapshot.get('page_status')}",
        ]

        areas = snapshot.get("areas", {})
        if areas:
            lines.append("")
            for area in areas.values():
                status = area.get("status")
                icon = "🟢" if status == "有票" else "🔴" if status == "售完" else "⚪"
                extras: list[str] = []
                if area.get("price") is not None:
                    extras.append(f"${area['price']:,}")
                if area.get("remaining") is not None:
                    extras.append(f"剩餘 {area['remaining']}")
                suffix = "｜" + "｜".join(extras) if extras else ""
                lines.append(
                    f"{icon} {area.get('name')}｜{status}{suffix}"
                )
        else:
            lines.append("")
            lines.append("未解析到票區資料。")

        lines.append("")
        lines.append(f"檢查時間：{snapshot.get('checked_at')}")
        if requester:
            lines.append(f"觸發者：{requester}")

        return "\n".join(lines)[:1900]

    def _save(
        self,
        snapshot: SessionSnapshot,
        *,
        force_notify: bool = False,
        requester: str = "",
        channel_id: int | None = None,
    ) -> None:
        data = snapshot.to_dict()
        old = self.state.get(snapshot.session_key)

        # Stabilize intermittent DOM output.  If Tixcraft temporarily omits the
        # price for an otherwise identical area, inherit the previous price.
        # If an entire previously populated area list disappears for one pass,
        # keep the last good snapshot instead of creating false restock alerts.
        if old and old.get("areas") and not data.get("areas") and data.get("page_status") == "OK":
            logger.warning("本輪未解析到票區，保留上一輪有效狀態：%s", snapshot.session_key)
            return
        if old:
            old_by_name = {
                normalize_area_name(str(area.get("name", key))): area
                for key, area in (old.get("areas") or {}).items()
            }
            for area in (data.get("areas") or {}).values():
                previous = old_by_name.get(normalize_area_name(str(area.get("name", ""))))
                if previous and area.get("price") is None and previous.get("price") is not None:
                    area["price"] = previous["price"]

        changes = self.diff(old, data)
        self.state.set(snapshot.session_key, data)

        meaningful = [
            item for item in changes
            if item.get("type") in {"NEW_AVAILABLE", "RESTOCKED", "SOLD_OUT", "REMAINING_UP", "REMAINING_DOWN"}
        ]
        should_notify = (
            (old is None and self.config.notify_initial_state)
            or (bool(meaningful) and self.config.notify_changes)
            or force_notify
        )

        if changes:
            self.history.append(
                {
                    "time": data["checked_at"],
                    "event_code": snapshot.event_code,
                    "event_name": snapshot.event_name,
                    "session_key": snapshot.session_key,
                    "session_name": snapshot.session_name,
                    "changes": changes,
                }
            )

        if should_notify:
            if force_notify:
                title = "🔎 手動票況檢查"
            elif changes == [{"type": "INITIAL"}]:
                title = "📌 初始票況"
            else:
                title = "🚨 票況異動"

            message = self.format_snapshot(data, title, requester)
            if meaningful:
                message += "\n\n異動：\n" + "\n".join(
                    f"• {change_text(item)}" for item in meaningful
                )

            self.queue.enqueue(
                message,
                level="ticket",
                metadata={
                    "event_code": snapshot.event_code,
                    "session_key": snapshot.session_key,
                    "title": title,
                    "changes": meaningful,
                },
                channel_id=channel_id,
            )

    def _find_events(
        self,
        event_code: str | None,
        provider_name: str | None = None,
    ) -> list[EventConfig]:
        enabled = [event for event in self.config.events if event.enabled]
        if provider_name:
            enabled = [
                event for event in enabled
                if self.providers.get(event).name == provider_name
            ]
        if not event_code:
            return enabled
        return [
            event
            for event in enabled
            if event.code.lower() == event_code.lower()
        ]

    def _run_check(
        self,
        events: list[EventConfig],
        *,
        force_notify: bool = False,
        requester: str = "",
        channel_id: int | None = None,
    ) -> None:
        if not events:
            self.queue.enqueue(
                "找不到指定活動，請使用 `/events` 查看活動代碼。",
                level="error",
                channel_id=channel_id,
            )
            return

        for event in events:
            self.stats.increment("checks")
            self.runtime.update(
                current_event=event.code,
                current_session=None,
            )
            try:
                result = self.check_event(event)
                self._consecutive_errors = 0
                self.stats.increment("successful_checks")
                for session in result.sessions:
                    self._save(
                        session,
                        force_notify=force_notify,
                        requester=requester,
                        channel_id=channel_id,
                    )
            except Exception as exc:
                logger.exception("監控失敗：%s", event.code)
                self._consecutive_errors += 1
                self.stats.increment("failed_checks")
                self._debug(event.code, self.providers.get(event).name)
                runtime = self.runtime.get()
                self.runtime.update(
                    errors=int(runtime.get("errors", 0)) + 1
                )
                self.queue.enqueue(
                    f"❌ {event.name} 檢查失敗："
                    f"{type(exc).__name__}: {exc}",
                    level="error",
                    channel_id=channel_id,
                )
                if (
                    self.config.auto_restart_browser
                    and self._consecutive_errors >= self.config.restart_after_consecutive_errors
                ):
                    try:
                        self._browser(self.providers.get(event).name).restart()
                        self.stats.increment("browser_restarts")
                        self._consecutive_errors = 0
                        self.queue.enqueue("♻️ 連續錯誤達門檻，Chrome 已自動重啟。", level="warning")
                    except Exception:
                        logger.exception("Chrome 自動重啟失敗")

    def _reload_config_if_changed(self, force: bool = False) -> bool:
        path = Path(self.config.source_path)
        if not path.exists():
            return False
        mtime = path.stat().st_mtime
        if not force and mtime <= self._config_mtime:
            return False
        self.config = AppConfig.load(path)
        self._config_mtime = mtime
        logger.info("設定檔已重新載入")
        return True

    def _find_states(self, event_code: str | None, provider_name: str | None = None) -> list[dict[str, Any]]:
        states = self.state.event_sessions(event_code)
        if not provider_name:
            return states
        token = f"::{provider_name}::"
        return [state for state in states if token in str(state.get("session_key", ""))]

    def _handle_commands(self) -> None:
        for command in self.control.pop_all():
            action = command.get("action")
            event_code = command.get("event_code")
            provider_name = command.get("provider")
            channel_id = command.get("channel_id")
            requester = command.get("requester", "")

            if action == "check":
                self.stats.increment("manual_checks")
                self._run_check(
                    self._find_events(event_code, provider_name),
                    force_notify=True,
                    requester=requester,
                    channel_id=channel_id,
                )
            elif action == "notify_now":
                states = self._find_states(event_code, provider_name)
                if not states:
                    self.queue.enqueue(
                        "目前沒有已儲存票況，請先使用 `/check`。",
                        channel_id=channel_id,
                    )
                for state in states:
                    self.queue.enqueue(
                        self.format_snapshot(
                            state,
                            "📣 強制發送目前票況",
                            requester,
                        ),
                        level="ticket",
                        channel_id=channel_id,
                    )
            elif action == "restart_browser":
                targets = [provider_name] if provider_name else list(self.browsers)
                restarted: list[str] = []
                for name in targets:
                    if name not in self.browsers:
                        continue
                    self._browser(name).restart()
                    restarted.append(name)
                    self.stats.increment("browser_restarts")
                label = "、".join(restarted) or "無有效平台"
                self.queue.enqueue(
                    f"✅ Chrome 已重新啟動：{label}。",
                    channel_id=channel_id,
                )
            elif action == "reload_config":
                try:
                    changed = self._reload_config_if_changed(force=True)
                    self.queue.enqueue("✅ 設定檔已重新載入。" if changed else "設定檔無變化。", channel_id=channel_id)
                except Exception as exc:
                    self.queue.enqueue(f"❌ 設定檔載入失敗：{exc}", level="error", channel_id=channel_id)
            elif action == "screenshot":
                targets = [provider_name] if provider_name else list(self.browsers)
                for name in targets:
                    if name not in self.browsers:
                        continue
                    try:
                        path = self._browser(name).screenshot(
                            Path("screenshots") / f"manual_{name}_{datetime.now():%Y%m%d_%H%M%S}.png"
                        )
                        self.queue.enqueue(f"SCREENSHOT::{path}", level="file", channel_id=channel_id)
                    except Exception as exc:
                        self.queue.enqueue(f"❌ {name} 截圖失敗：{exc}", level="error", channel_id=channel_id)
            elif action == "backup":
                try:
                    path = self.backup.create()
                    self.queue.enqueue(f"✅ 備份完成：{path.name}", channel_id=channel_id)
                except Exception as exc:
                    self.queue.enqueue(f"❌ 備份失敗：{exc}", level="error", channel_id=channel_id)

    def run_forever(self) -> None:
        runtime = self.runtime.get()
        self.runtime.update(
            running=True,
            started_at=runtime.get("started_at")
            or datetime.now().astimezone().isoformat(timespec="seconds"),
        )

        round_number = int(runtime.get("round", 0))
        next_auto_check = 0.0
        next_config_reload = 0.0
        next_backup = time.monotonic() + self.config.backup_interval_hours * 3600

        try:
            while not self._stop:
                self._handle_commands()
                now = time.monotonic()
                self.runtime.update(heartbeat=datetime.now().astimezone().isoformat(timespec="seconds"))
                if now >= next_config_reload:
                    try:
                        self._reload_config_if_changed()
                    except Exception:
                        logger.exception("自動重新載入設定失敗")
                    next_config_reload = now + self.config.config_reload_seconds
                if now >= next_backup:
                    try:
                        self.backup.create()
                    except Exception:
                        logger.exception("自動備份失敗")
                    next_backup = now + self.config.backup_interval_hours * 3600
                runtime = self.runtime.get()

                if runtime.get("paused"):
                    self.runtime.update(
                        browser_alive=self._all_browsers_alive()
                    )
                    time.sleep(1)
                    continue

                if now >= next_auto_check:
                    round_number += 1
                    self.runtime.update(round=round_number)
                    self._run_check(self._find_events(None))
                    next_auto_check = (
                        now + self.config.check_interval_seconds
                    )
                    self.runtime.update(
                        current_event=None,
                        current_session=None,
                        browser_alive=self._all_browsers_alive(),
                    )
                    self.runtime.touch()

                time.sleep(0.5)
        finally:
            self.runtime.update(
                running=False,
                browser_alive=self._all_browsers_alive(),
                current_event=None,
                current_session=None,
            )
