from __future__ import annotations
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from tixcraft_v17.utils.fileio import JsonFile

def now():return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
class NotificationQueue:
    def __init__(self,path:str|Path="data/notify_queue.json")->None:self.file=JsonFile(path,[])
    def list(self)->list[dict[str,Any]]:return list(self.file.read())
    def enqueue(self,message:str,*,level:str="info",metadata:dict[str,Any]|None=None,channel_id:int|None=None)->str:
        iid=uuid.uuid4().hex
        def fn(xs):xs.append({"id":iid,"level":level,"message":message,"metadata":metadata or {},"channel_id":channel_id,"created_at":now(),"attempts":0})
        self.file.update(fn); return iid
    def remove(self,iid:str)->None:self.file.update(lambda xs:xs.__setitem__(slice(None),[x for x in xs if x.get("id")!=iid]))
    def increment_attempts(self,iid:str)->None:
        def fn(xs):
            for x in xs:
                if x.get("id")==iid:x["attempts"]=int(x.get("attempts",0))+1
        self.file.update(fn)
