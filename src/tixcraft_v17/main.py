from __future__ import annotations

import logging
import signal

from tixcraft_v17.browser import BrowserManager, KktixNodriverManager
from tixcraft_v17.config import AppConfig, LOG_LEVEL
from tixcraft_v17.enterprise import BackupManager, StatsStore
from tixcraft_v17.monitor import ControlQueue, MonitorService
from tixcraft_v17.notifier import NotificationQueue
from tixcraft_v17.parser import TixcraftParser
from tixcraft_v17.runtime import RuntimeStore
from tixcraft_v17.state import HistoryStore, StateStore
from tixcraft_v17.utils.logging import configure_logging

logger = logging.getLogger(__name__)


def main() -> None:
    configure_logging(LOG_LEVEL)
    config = AppConfig.load()
    if config.tixcraft_browser_engine != "selenium":
        raise ValueError("拓元目前僅支援 tixcraft_browser_engine=selenium")
    if config.kktix_browser_engine != "nodriver":
        raise ValueError("KKTIX 方案二必須設定 kktix_browser_engine=nodriver")
    browsers = {
        "tixcraft": BrowserManager(
            headless=config.headless,
            profile_dir=config.browser_profile_dir,
        ),
        "kktix": KktixNodriverManager(
            headless=config.headless,
            profile_dir=config.kktix_browser_profile_dir,
            page_timeout=max(45, config.page_wait_seconds + 15),
        ),
    }
    service = MonitorService(
        config,
        browsers,
        TixcraftParser(debug_parser=config.debug_parser, parser_replay=config.parser_replay),
        RuntimeStore(),
        StateStore(),
        HistoryStore(),
        NotificationQueue(),
        ControlQueue(),
        StatsStore(),
        BackupManager(keep=config.backup_keep),
    )

    def stop(*_: object) -> None:
        logger.info("收到停止訊號")
        service.stop()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        service.run_forever()
    finally:
        for browser in browsers.values():
            if hasattr(browser, "close_loop"):
                browser.close_loop()
            else:
                browser.stop()


if __name__ == "__main__":
    main()
