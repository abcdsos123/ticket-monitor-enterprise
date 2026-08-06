from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

def now_iso()->str: return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

@dataclass(slots=True)
class TicketArea:
    key: str
    name: str
    status: str
    remaining: int|None=None
    price: int|None=None
    price_min: int|None=None
    price_max: int|None=None
    group: str=""
    subtype: str="normal"
    occurrence: int=1
    raw_text: str=""
    def to_dict(self)->dict[str,Any]:
        return {"key":self.key,"name":self.name,"status":self.status,"remaining":self.remaining,
        "price":self.price,"price_min":self.price_min,"price_max":self.price_max,"group":self.group,
        "subtype":self.subtype,"occurrence":self.occurrence,"raw_text":self.raw_text}

@dataclass(slots=True)
class SessionSnapshot:
    event_code:str; event_name:str; session_key:str; session_name:str; session_url:str
    page_status:str="OK"; areas:dict[str,TicketArea]=field(default_factory=dict); checked_at:str=field(default_factory=now_iso)
    @property
    def available_count(self)->int: return sum(1 for a in self.areas.values() if a.status in {"有票","熱賣中"} or (a.remaining or 0)>0)
    def to_dict(self)->dict[str,Any]:
        return {"event_code":self.event_code,"event_name":self.event_name,"session_key":self.session_key,"session_name":self.session_name,
        "session_url":self.session_url,"page_status":self.page_status,"areas":{k:v.to_dict() for k,v in self.areas.items()},
        "checked_at":self.checked_at,"available_count":self.available_count}

@dataclass(slots=True)
class EventSnapshot:
    event_code:str; event_name:str; event_url:str; sessions:list[SessionSnapshot]=field(default_factory=list); checked_at:str=field(default_factory=now_iso)
    def to_dict(self)->dict[str,Any]: return {"event_code":self.event_code,"event_name":self.event_name,"event_url":self.event_url,"sessions":[s.to_dict() for s in self.sessions],"checked_at":self.checked_at}
