from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

import discord

from tixcraft_v17.state import change_text

BLUE = 0x3498DB
GREEN = 0x2ECC71
YELLOW = 0xF1C40F
RED = 0xE74C3C
PURPLE = 0x9B59B6
GREY = 0x95A5A6


def _text(value: Any, fallback: str = "—") -> str:
    return fallback if value in (None, "", "None") else str(value)


def format_time(value: Any) -> str:
    text = _text(value)
    try:
        return datetime.fromisoformat(text).strftime("%Y/%m/%d %H:%M:%S")
    except (TypeError, ValueError):
        return text


def money(value: Any) -> str:
    try:
        return f"NT${int(value):,}"
    except (TypeError, ValueError):
        return "票價未提供"


def area_display_name(area: dict[str, Any]) -> str:
    """Show the price at the end of the ticket-area name, matching Tixcraft's layout."""
    name = _text(area.get("name"), "未命名票區")
    price = area.get("price")
    if price is None:
        return name
    try:
        price_text = str(int(price))
    except (TypeError, ValueError):
        return name
    # Avoid appending the same price twice when the source name already contains it.
    if name.rstrip().endswith(price_text):
        return name
    return f"{name} {price_text}"


def area_available(area: dict[str, Any]) -> bool:
    return area.get("status") in {"有票", "熱賣中"} or int(area.get("remaining") or 0) > 0


def area_icon(area: dict[str, Any]) -> str:
    if area_available(area):
        remaining = area.get("remaining")
        return "🟡" if remaining is not None and int(remaining) <= 10 else "🟢"
    if area.get("status") == "售完":
        return "🔴"
    return "⚪"


def session_totals(state: dict[str, Any]) -> tuple[int, int, int, int]:
    areas = list((state.get("areas") or {}).values())
    available = [a for a in areas if area_available(a)]
    known_remaining = [int(a["remaining"]) for a in available if a.get("remaining") is not None]
    unknown_count = sum(1 for a in available if a.get("remaining") is None)
    return len(available), len(areas) - len(available), sum(known_remaining), unknown_count


def session_color(state: dict[str, Any]) -> int:
    available, _, total, _ = session_totals(state)
    if available == 0:
        return RED
    return YELLOW if total and total <= 10 else GREEN


def area_line(area: dict[str, Any]) -> str:
    icon = area_icon(area)
    name = area_display_name(area)
    status = _text(area.get("status"), "未知")
    if area.get("remaining") is not None:
        detail = f"🎫 **{int(area['remaining']):,} 張**"
    elif status == "熱賣中":
        detail = "🔥 **熱賣中**"
    elif area_available(area):
        detail = "🎫 **數量未知**"
    else:
        detail = "❌ **已售完**" if status == "售完" else f"⚪ **{status}**"
    return f"{icon} **{name}**\n{detail}"


def ticket_pages(state: dict[str, Any], page_size: int = 8) -> list[discord.Embed]:
    areas = list((state.get("areas") or {}).values())
    areas.sort(key=lambda a: (not area_available(a), -(int(a.get("remaining") or 0)), str(a.get("name", ""))))
    chunks = [areas[i:i + page_size] for i in range(0, len(areas), page_size)] or [[]]
    available, sold, total, unknown = session_totals(state)
    pages: list[discord.Embed] = []
    for index, chunk in enumerate(chunks, start=1):
        embed = discord.Embed(
            title=f"🎫 {_text(state.get('event_name'), '票況查詢')}",
            description=(
                f"📅 **場次：** {_text(state.get('session_name'))}\n"
                f"📡 **頁面狀態：** {_text(state.get('page_status'), 'OK')}"
            ),
            color=session_color(state),
        )
        if chunk:
            for area in chunk:
                embed.add_field(name="", value=area_line(area), inline=False)
        else:
            embed.add_field(name="⚪ 尚無票區資料", value="監控程式尚未解析到票區。", inline=False)
        embed.add_field(name="📊 有票票區", value=f"**{available}** 個", inline=True)
        embed.add_field(name="❌ 售完／無票", value=f"**{sold}** 個", inline=True)
        embed.add_field(name="🪑 剩餘數量", value=(f"**{total:,}** 張" + (f"＋ **{unknown}** 區熱賣中／未標數量" if unknown else "")) if total or not unknown else "**數量未知**", inline=True)
        embed.set_footer(text=f"第 {index}/{len(chunks)} 頁｜最後更新：{format_time(state.get('checked_at'))}")
        pages.append(embed)
    return pages


def status_embed(runtime: dict[str, Any], states: Iterable[dict[str, Any]], stats: dict[str, Any]) -> discord.Embed:
    states = list(states)
    available_sessions = sum(1 for state in states if session_totals(state)[0] > 0)
    available_areas = sum(session_totals(state)[0] for state in states)
    remaining = sum(session_totals(state)[2] for state in states)
    unknown = sum(session_totals(state)[3] for state in states)
    running = bool(runtime.get("running")) and not bool(runtime.get("paused"))
    embed = discord.Embed(
        title="🎫 Tixcraft Monitor 控制中心",
        description="🟢 **監控運行中**" if running else "🟡 **監控目前暫停或未啟動**",
        color=GREEN if running else YELLOW,
    )
    embed.add_field(name="🎯 監控場次", value=f"**{len(states)}**", inline=True)
    embed.add_field(name="🎤 有票場次", value=f"**{available_sessions}**", inline=True)
    embed.add_field(name="🎫 有票票區", value=f"**{available_areas}**", inline=True)
    embed.add_field(name="🪑 剩餘數量", value=(f"**{remaining:,} 張**" + (f"＋{unknown} 區熱賣中／未標數量" if unknown else "")) if remaining or not unknown else "**數量未知**", inline=True)
    embed.add_field(name="🔄 檢查輪次", value=f"**{runtime.get('round', 0)}**", inline=True)
    embed.add_field(name="⚠️ 錯誤次數", value=f"**{runtime.get('errors', 0)}**", inline=True)
    embed.add_field(
        name="🧭 系統狀態",
        value=(
            f"{'🟢' if runtime.get('browser_alive') else '🔴'} Chrome\n"
            f"🟢 Discord\n"
            f"{'⏸️' if runtime.get('paused') else '▶️'} 自動監票"
        ),
        inline=True,
    )
    embed.add_field(
        name="📍 目前工作",
        value=f"活動：`{_text(runtime.get('current_event') or runtime.get('last_event'))}`\n場次：`{_text(runtime.get('current_session') or runtime.get('last_session'))}`",
        inline=True,
    )
    embed.add_field(
        name="📈 累計統計",
        value=(
            f"成功：**{stats.get('successful_checks', 0)}**\n"
            f"失敗：**{stats.get('failed_checks', 0)}**\n"
            f"通知：**{stats.get('notifications', 0)}**"
        ),
        inline=True,
    )
    embed.set_footer(text=f"最後檢查：{format_time(runtime.get('last_check'))}")
    return embed


def events_embed(events: Iterable[Any], states: Iterable[dict[str, Any]]) -> discord.Embed:
    states = list(states)
    embed = discord.Embed(title="🎪 目前監控活動", color=BLUE)
    for event in events:
        related = [s for s in states if s.get("event_code") == event.code]
        available_sessions = sum(1 for s in related if session_totals(s)[0])
        icon = "🟢" if event.enabled else "⚪"
        detail = f"`{event.code}`｜{'啟用' if event.enabled else '停用'}"
        if related:
            detail += f"｜{available_sessions}/{len(related)} 場有票"
        embed.add_field(name=f"{icon} {event.name}", value=detail, inline=False)
    embed.set_footer(text="使用 /ticket 活動代碼 查看票區")
    return embed


def _visible_change(change: dict[str, Any]) -> bool:
    return change.get("type") in {
        "NEW_AVAILABLE", "RESTOCKED", "SOLD_OUT",
        "REMAINING_UP", "REMAINING_DOWN",
    }


def _change_value(change: dict[str, Any]) -> str:
    kind = change.get("type")
    after = change.get("after") or {}
    if kind in {"NEW_AVAILABLE", "RESTOCKED"}:
        remaining = after.get("remaining")
        return f"🎫 **{int(remaining):,} 張**" if remaining is not None else ("🔥 **熱賣中**" if after.get("status")=="熱賣中" else "🎫 **數量未知**")
    if kind == "SOLD_OUT":
        return "❌ **已售完**"
    if kind in {"REMAINING_UP", "REMAINING_DOWN"}:
        before = int(change.get("before_remaining", 0))
        after_count = int(change.get("after_remaining", 0))
        delta = int(change.get("delta", after_count - before))
        sign = f"+{delta}" if delta > 0 else str(delta)
        return f"🎫 **{before:,} → {after_count:,}**（{sign}）"
    return ""


def _change_name(change: dict[str, Any]) -> str:
    area = change.get("after") or change.get("before") or {}
    name = _text(change.get("name") or area.get("name"), "未命名票區")
    price = area.get("price")
    if price is not None:
        try:
            p = str(int(price))
            if not name.rstrip().endswith(p):
                name = f"{name} {p}"
        except (TypeError, ValueError):
            pass
    return name


def compact_notification_embed(state: dict[str, Any], title: str = "🚨 票況異動", changes: list[dict[str, Any] | str] | None = None) -> discord.Embed:
    visible = [c for c in (changes or []) if isinstance(c, dict) and _visible_change(c)]
    embed = discord.Embed(
        title=title,
        description=(
            f"🎤 **{_text(state.get('event_name'))}**\n"
            f"📅 {_text(state.get('session_name'))}"
        ),
        color=session_color(state),
        url=state.get("session_url") or None,
    )

    if visible:
        for change in visible[:10]:
            embed.add_field(
                name=_change_name(change),
                value=_change_value(change),
                inline=False,
            )
    else:
        available_areas = [a for a in (state.get("areas") or {}).values() if area_available(a)]
        available_areas.sort(key=lambda a: (-(int(a.get("remaining") or 0)), area_display_name(a)))
        for area in available_areas[:8]:
            embed.add_field(name=area_display_name(area), value=(f"🎫 **{int(area['remaining']):,} 張**" if area.get("remaining") is not None else "🎫 **數量未知**"), inline=False)
        if not available_areas:
            embed.add_field(name="目前票況", value="❌ **暫無可購買票區**", inline=False)

    embed.set_footer(text=f"輸入 /ticket {state.get('event_code', '')} 查看完整票區｜{format_time(state.get('checked_at'))}")
    return embed

