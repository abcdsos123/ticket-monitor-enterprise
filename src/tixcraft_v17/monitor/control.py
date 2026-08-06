from __future__ import annotations
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tixcraft_v17.utils.fileio import JsonFile

def now():return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
class ControlQueue:
    def __init__(self,path:str|Path="data/control_queue.json")->None:self.file=JsonFile(path,[])
    def request(self,action:str,*,event_code:str|None=None,provider:str|None=None,requester:str="",channel_id:int|None=None)->str:
        iid=uuid.uuid4().hex
        self.file.update(lambda xs:xs.append({"id":iid,"action":action,"event_code":event_code,"provider":provider,"requester":requester,"channel_id":channel_id,"created_at":now()}))
        return iid
    def pop_all(self)->list[dict[str,Any]]:
        def fn(xs):out=list(xs); xs.clear(); return out
        return self.file.update(fn)
