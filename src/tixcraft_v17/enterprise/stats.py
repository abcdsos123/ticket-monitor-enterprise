from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from tixcraft_v17.utils.fileio import JsonFile


class StatsStore:
    def __init__(self, path: str | Path = "data/stats.json") -> None:
        self.file = JsonFile(
            path,
            {
                "checks": 0,
                "successful_checks": 0,
                "failed_checks": 0,
                "notifications": 0,
                "browser_restarts": 0,
                "manual_checks": 0,
                "started_at": None,
                "updated_at": None,
            },
        )

    def get(self) -> dict[str, Any]:
        return dict(self.file.read())

    def increment(self, key: str, amount: int = 1) -> dict[str, Any]:
        data = self.get()
        data[key] = int(data.get(key, 0)) + amount
        data["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        if not data.get("started_at"):
            data["started_at"] = data["updated_at"]
        self.file.write(data)
        return data
