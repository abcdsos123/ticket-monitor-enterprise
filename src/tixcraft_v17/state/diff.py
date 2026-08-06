from __future__ import annotations

from typing import Any

from tixcraft_v17.parser.tixcraft import normalize_area_name


def _available(area: dict[str, Any] | None) -> bool:
    if not area:
        return False
    remaining = area.get("remaining")
    if isinstance(remaining, int):
        return remaining > 0
    return area.get("status") in {"有票", "熱賣中"}


def _identity(area: dict[str, Any], fallback_key: str = "") -> str:
    key=area.get("key") or fallback_key
    if key: return str(key)
    return "|".join((normalize_area_name(str(area.get("group") or "")), normalize_area_name(str(area.get("name") or "")), str(area.get("subtype") or "normal"), str(area.get("occurrence") or 1)))


def _richness(area: dict[str, Any]) -> tuple[int, int, int]:
    return (
        1 if area.get("remaining") is not None else 0,
        1 if area.get("price") is not None else 0,
        1 if area.get("status") in {"有票", "熱賣中", "售完"} else 0,
    )


def _index(areas: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for key, area in areas.items():
        identity = _identity(area, key)
        current = result.get(identity)
        if current is None or _richness(area) > _richness(current):
            result[identity] = area
    return result


def diff_snapshots(old: dict[str, Any] | None, new: dict[str, Any]) -> list[dict[str, Any]]:
    if old is None:
        return [{"type": "INITIAL"}]

    changes: list[dict[str, Any]] = []
    old_areas = _index(old.get("areas") or {})
    new_areas = _index(new.get("areas") or {})

    # Only compare rows present in both snapshots. A temporarily missing DOM row
    # is not evidence of sold-out and should never generate a user notification.
    for identity in sorted(set(old_areas) & set(new_areas)):
        before = old_areas[identity]
        after = new_areas[identity]
        display = after.get("name") or before.get("name") or identity

        before_available = _available(before)
        after_available = _available(after)
        before_remaining = before.get("remaining")
        after_remaining = after.get("remaining")

        if before_available and not after_available and after.get("status") == "售完":
            changes.append({"type": "SOLD_OUT", "name": display, "before": before, "after": after})
            continue
        if not before_available and after_available:
            changes.append({"type": "RESTOCKED", "name": display, "before": before, "after": after})

        if isinstance(before_remaining, int) and isinstance(after_remaining, int) and before_remaining != after_remaining:
            change_type = "REMAINING_UP" if after_remaining > before_remaining else "REMAINING_DOWN"
            changes.append({
                "type": change_type,
                "name": display,
                "before_remaining": before_remaining,
                "after_remaining": after_remaining,
                "delta": after_remaining - before_remaining,
                "before": before,
                "after": after,
            })

    # A truly new available row can be announced, but do not expose internal
    # labels such as "新增票區"; the formatter only displays name and quantity.
    for identity in sorted(set(new_areas) - set(old_areas)):
        after = new_areas[identity]
        if _available(after):
            changes.append({"type": "NEW_AVAILABLE", "name": after.get("name", identity), "after": after})

    if old.get("page_status") != new.get("page_status"):
        changes.append({
            "type": "PAGE_STATUS",
            "before_status": old.get("page_status"),
            "after_status": new.get("page_status"),
        })
    return changes


def change_text(change: dict[str, Any]) -> str:
    kind = change.get("type")
    name = change.get("name", "未命名票區")
    if kind == "INITIAL":
        return "INITIAL"
    if kind in {"NEW_AVAILABLE", "RESTOCKED"}:
        remaining = (change.get("after") or {}).get("remaining")
        return f"🎫 {name}：" + (f"{remaining} 張" if remaining is not None else "數量未知")
    if kind == "SOLD_OUT":
        return f"❌ {name}：已售完"
    if kind == "REMAINING_UP":
        return f"📈 {name}：{change['before_remaining']} → {change['after_remaining']}（+{change['delta']}）"
    if kind == "REMAINING_DOWN":
        return f"📉 {name}：{change['before_remaining']} → {change['after_remaining']}（{change['delta']}）"
    if kind == "PAGE_STATUS":
        return f"🌐 頁面狀態：{change.get('before_status')} → {change.get('after_status')}"
    return ""
