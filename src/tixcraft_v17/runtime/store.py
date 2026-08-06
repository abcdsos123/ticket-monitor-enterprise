from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tixcraft_v17.utils.fileio import JsonFile

def now():return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
class RuntimeStore:
    def __init__(self,path:str|Path="data/runtime.json")->None:
        self.file=JsonFile(path,{"running":False,"paused":False,"round":0,"browser_alive":False,"current_event":None,"current_session":None,"last_event":None,"last_session":None,"last_check":None,"errors":0,"started_at":None})
    def get(self)->dict[str,Any]:return dict(self.file.read())
    def update(self,**changes:Any)->dict[str,Any]:
        def fn(d):d.update(changes); return dict(d)
        return self.file.update(fn)
    def touch(self)->dict[str,Any]:return self.update(last_check=now())
