from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


class BackupManager:
    def __init__(
        self,
        source_dir: str | Path = "data",
        backup_dir: str | Path = "backups",
        keep: int = 14,
    ) -> None:
        self.source_dir = Path(source_dir)
        self.backup_dir = Path(backup_dir)
        self.keep = max(1, keep)

    def create(self) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive = self.backup_dir / f"tixcraft_data_{stamp}.zip"
        base = archive.with_suffix("")
        shutil.make_archive(str(base), "zip", root_dir=self.source_dir)
        self.prune()
        return archive

    def prune(self) -> None:
        files = sorted(
            self.backup_dir.glob("tixcraft_data_*.zip"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        for old in files[self.keep :]:
            old.unlink(missing_ok=True)
