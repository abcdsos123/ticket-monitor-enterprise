from __future__ import annotations
from pathlib import Path
from typing import Any
from tixcraft_v17.utils.fileio import JsonFile
class HistoryStore:
    def __init__(self,path:str|Path="data/history.json",max_items:int=2000)->None:self.file=JsonFile(path,[]); self.max_items=max_items
    def list(self,limit:int=20)->list[dict[str,Any]]:return list(self.file.read())[-limit:]
    def append(self,item:dict[str,Any])->None:
        def fn(xs):xs.append(item); del xs[:-self.max_items]
        self.file.update(fn)
