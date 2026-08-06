from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

from tixcraft_v17.runtime import RuntimeStore


class HealthService:
    def __init__(self, runtime: RuntimeStore | None = None) -> None:
        self.runtime = runtime or RuntimeStore()

    def snapshot(self) -> dict[str, Any]:
        process = psutil.Process(os.getpid())
        memory_mb = round(process.memory_info().rss / 1024 / 1024, 1)
        cpu_percent = process.cpu_percent(interval=0.05)
        runtime = self.runtime.get()
        return {
            "pid": process.pid,
            "cpu_percent": cpu_percent,
            "memory_mb": memory_mb,
            "running": bool(runtime.get("running")),
            "paused": bool(runtime.get("paused")),
            "browser_alive": bool(runtime.get("browser_alive")),
            "last_check": runtime.get("last_check"),
            "heartbeat": runtime.get("heartbeat"),
            "current_event": runtime.get("current_event"),
            "current_session": runtime.get("current_session"),
            "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }

    @staticmethod
    def tail_log(path: str | Path = "logs/tixcraft-v17.log", lines: int = 80) -> str:
        target = Path(path)
        if not target.exists():
            return "目前沒有 Log 檔案。"
        content = target.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(content[-max(1, lines):])
