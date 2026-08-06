from tixcraft_v17.monitor.service import MonitorService
from tixcraft_v17.state.diff import diff_snapshots


def area(name, status, remaining, price=6880):
    return {"name": name, "status": status, "remaining": remaining, "price": price}


def test_initial():
    assert MonitorService.diff(None, {"areas": {}}) == [{"type": "INITIAL"}]


def test_name_spacing_does_not_create_added_removed():
    old = {"areas": {"VIPA|6880": area("VIPA", "有票", 14)}}
    new = {"areas": {"vipa|6880": area("VIP A", "有票", 13)}}
    changes = MonitorService.diff(old, new)
    assert [change["type"] for change in changes] == ["REMAINING_DOWN"]


def test_remaining_increase():
    old = {"areas": {"a": area("VIP A", "有票", 13)}}
    new = {"areas": {"a": area("VIP A", "有票", 25)}}
    change = MonitorService.diff(old, new)[0]
    assert change["type"] == "REMAINING_UP"
    assert change["delta"] == 12


def test_sold_out():
    old = {"areas": {"a": area("VIP A", "有票", 1)}}
    new = {"areas": {"a": area("VIP A", "售完", 0)}}
    assert MonitorService.diff(old, new)[0]["type"] == "SOLD_OUT"


def test_price_appearance_does_not_create_missing_and_new_pair():
    old = {"areas": {"3樓": {"name": "3樓", "price": None, "remaining": 12, "status": "有票"}}, "page_status": "OK"}
    new = {"areas": {"3樓": {"name": "3樓", "price": 5800, "remaining": 12, "status": "有票"}}, "page_status": "OK"}
    assert diff_snapshots(old, new) == []


def test_missing_area_is_not_treated_as_sold_out():
    old = {"areas": {"3樓": {"name": "3樓", "price": 5800, "remaining": 12, "status": "有票"}}, "page_status": "OK"}
    new = {"areas": {}, "page_status": "OK"}
    assert diff_snapshots(old, new) == []
