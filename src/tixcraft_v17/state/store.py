from __future__ import annotations
from pathlib import Path
from typing import Any
from tixcraft_v17.utils.fileio import JsonFile
class StateStore:
    def __init__(self,path:str|Path="data/state.json")->None:self.file=JsonFile(path,{})
    def get_all(self)->dict[str,Any]:return dict(self.file.read())
    def get(self,key:str)->dict[str,Any]|None:return self.get_all().get(key)
    def set(self,key:str,value:dict[str,Any])->None:
        self.file.update(lambda d:d.__setitem__(key,value))
    def event_sessions(self,event_code:str|None=None)->list[dict[str,Any]]:
        vals=list(self.get_all().values())
        return [x for x in vals if not event_code or x.get("event_code")==event_code]
