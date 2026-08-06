from __future__ import annotations
import json, os, tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, TypeVar
from filelock import FileLock
T=TypeVar("T")

class JsonFile:
    """跨程序安全的 JSON 儲存；寫入採暫存檔 + os.replace。"""
    def __init__(self, path: str|Path, default: Any) -> None:
        self.path=Path(path); self.default=default
        self.lock=FileLock(str(self.path)+".lock", timeout=10)

    def _read_unlocked(self) -> Any:
        if not self.path.exists(): return deepcopy(self.default)
        try: return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError): return deepcopy(self.default)

    def read(self) -> Any:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock: return self._read_unlocked()

    def _write_unlocked(self, data: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd,tmp=tempfile.mkstemp(prefix=self.path.name+".",suffix=".tmp",dir=self.path.parent)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as f:
                json.dump(data,f,ensure_ascii=False,indent=2); f.flush(); os.fsync(f.fileno())
            os.replace(tmp,self.path)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def write(self, data: Any) -> None:
        with self.lock: self._write_unlocked(data)

    def update(self, fn: Callable[[Any],T]) -> T:
        with self.lock:
            data=self._read_unlocked(); result=fn(data); self._write_unlocked(data); return result
