from __future__ import annotations

import json
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from tixcraft_v17.config import AppConfig, DISCORD_ADMIN_ROLE_ID, DISCORD_OWNER_IDS
from tixcraft_v17.discord_bot.formatter import (
    BLUE,
    PURPLE,
    area_available,
    events_embed,
    money,
    session_totals,
    status_embed,
)
from tixcraft_v17.discord_bot.views import TicketPaginationView
from tixcraft_v17.enterprise import BackupManager, HealthService, StatsStore
from tixcraft_v17.monitor import ControlQueue
from tixcraft_v17.notifier import NotificationQueue
from tixcraft_v17.runtime import RuntimeStore
from tixcraft_v17.state import HistoryStore, StateStore, change_text
from tixcraft_v17.providers.detect import detect_provider


def interaction_channel_id(interaction: discord.Interaction) -> int | None:
    return interaction.channel_id


def is_admin(interaction: discord.Interaction) -> bool:
    if DISCORD_OWNER_IDS and interaction.user.id in DISCORD_OWNER_IDS:
        return True
    if DISCORD_OWNER_IDS:
        return False
    if not DISCORD_ADMIN_ROLE_ID:
        return True
    member = interaction.user
    return isinstance(member, discord.Member) and any(str(role.id) == DISCORD_ADMIN_ROLE_ID for role in member.roles)


class MonitorCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.runtime = RuntimeStore()
        self.state = StateStore()
        self.history = HistoryStore()
        self.queue = NotificationQueue()
        self.control = ControlQueue()
        self.health = HealthService(self.runtime)
        self.stats = StatsStore()
        self.backup = BackupManager()

    async def deny(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("⛔ 你沒有權限使用此控制指令。", ephemeral=True)

    def find_states(self, keyword: str | None = None) -> list[dict]:
        rows = self.state.event_sessions()
        if not keyword:
            return rows
        key = keyword.casefold().strip()
        return [
            row for row in rows
            if key in str(row.get("event_code", "")).casefold()
            or key in str(row.get("event_name", "")).casefold()
            or key in str(row.get("session_name", "")).casefold()
        ]


    @staticmethod
    def state_provider(row: dict) -> str:
        key = str(row.get("session_key", ""))
        return "kktix" if "::kktix::" in key else "tixcraft"

    def platform_states(self, provider: str, keyword: str | None = None) -> list[dict]:
        rows = [row for row in self.state.event_sessions() if self.state_provider(row) == provider]
        if not keyword:
            return rows
        key = keyword.casefold().strip()
        return [row for row in rows if key in str(row.get("event_code", "")).casefold() or key in str(row.get("event_name", "")).casefold() or key in str(row.get("session_name", "")).casefold()]

    def platform_events(self, provider: str):
        try:
            return [event for event in AppConfig.load().events if detect_provider(event.url, event.provider) == provider]
        except Exception:
            return []

    async def platform_event_autocomplete(self, provider: str, current: str) -> list[app_commands.Choice[str]]:
        key = current.casefold()
        matches = [event for event in self.platform_events(provider) if key in event.code.casefold() or key in event.name.casefold()]
        return [app_commands.Choice(name=f"{event.name[:70]} ({event.code})", value=event.code) for event in matches[:25]]

    async def tixcraft_event_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self.platform_event_autocomplete("tixcraft", current)

    async def kktix_event_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        return await self.platform_event_autocomplete("kktix", current)

    async def event_autocomplete(self, _: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        try:
            events = AppConfig.load().events
        except Exception:
            return []
        key = current.casefold()
        matches = [e for e in events if key in e.code.casefold() or key in e.name.casefold()]
        return [app_commands.Choice(name=f"{e.name[:70]} ({e.code})", value=e.code) for e in matches[:25]]

    @app_commands.command(name="ping", description="查看 Bot 延遲")
    async def ping(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="🏓 Pong", description=f"Discord 延遲：**{round(self.bot.latency * 1000)} ms**", color=BLUE)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="status", description="查看美化版監票控制中心")
    async def status(self, interaction: discord.Interaction) -> None:
        embed = status_embed(self.runtime.get(), self.state.event_sessions(), self.stats.get())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="events", description="顯示目前監控活動")
    async def events(self, interaction: discord.Interaction) -> None:
        try:
            embed = events_embed(AppConfig.load().events, self.state.event_sessions())
        except Exception as exc:
            embed = discord.Embed(title="❌ 設定讀取失敗", description=str(exc), color=0xE74C3C)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="ticket", description="依活動查看完整票區，可分頁瀏覽")
    @app_commands.describe(event="活動代碼或活動名稱", session="場次關鍵字；同活動多場次時可指定")
    @app_commands.autocomplete(event=event_autocomplete)
    async def ticket(self, interaction: discord.Interaction, event: str, session: str | None = None) -> None:
        rows = self.find_states(event)
        if session:
            key = session.casefold()
            rows = [r for r in rows if key in str(r.get("session_name", "")).casefold()]
        if not rows:
            await interaction.response.send_message("🔍 找不到票況紀錄，請先使用 `/events` 確認活動代碼。", ephemeral=True)
            return
        state = rows[0]
        session_key = str(state.get("session_key"))
        view = TicketPaginationView(lambda: self.state.get(session_key))
        await interaction.response.send_message(embed=view.embed, view=view, ephemeral=True)
        if len(rows) > 1 and not session:
            await interaction.followup.send(f"此活動共有 **{len(rows)}** 個場次，目前先顯示第一場；可使用 `session` 參數指定。", ephemeral=True)

    @app_commands.command(name="tickets", description="ticket 的相容指令")
    @app_commands.describe(event_code="活動代碼；留空顯示所有場次摘要")
    async def tickets(self, interaction: discord.Interaction, event_code: str | None = None) -> None:
        if event_code:
            rows = self.find_states(event_code)
            if not rows:
                await interaction.response.send_message("目前沒有指定活動的票況紀錄。", ephemeral=True)
                return
            state = rows[0]
            session_key = str(state.get("session_key"))
            view = TicketPaginationView(lambda: self.state.get(session_key))
            await interaction.response.send_message(embed=view.embed, view=view, ephemeral=True)
            return
        rows = self.state.event_sessions()
        embed = discord.Embed(title="🎫 全部場次票況摘要", color=BLUE)
        for row in rows[:25]:
            available, _, total, unknown = session_totals(row)
            icon = "🟢" if available else "🔴"
            embed.add_field(
                name=f"{icon} {row.get('event_name')}",
                value=f"{row.get('session_name')}\n有票票區 **{available}**｜" + (f"已知剩餘 **{total:,}** 張" if total else ("剩餘 **數量未知**" if unknown else "已知剩餘 **0** 張")),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="price", description="依活動與票價篩選票區")
    @app_commands.describe(event="活動代碼或名稱", price="票價，例如 3880")
    @app_commands.autocomplete(event=event_autocomplete)
    async def price(self, interaction: discord.Interaction, event: str, price: int) -> None:
        rows = self.find_states(event)
        matches = []
        for row in rows:
            for area in (row.get("areas") or {}).values():
                if area.get("price") == price or (area.get("price_min") is not None and area.get("price_max") is not None and int(area["price_min"]) <= price <= int(area["price_max"])):
                    matches.append((row, area))
        embed = discord.Embed(title=f"💰 {money(price)} 票區", color=0xF1C40F)
        if not matches:
            embed.description = "目前沒有符合此票價的票區紀錄。"
        for row, area in matches[:25]:
            icon = "🟢" if area_available(area) else "🔴"
            remain = f"剩餘 **{area['remaining']}** 張" if area.get("remaining") is not None else area.get("status", "未知")
            embed.add_field(name=f"{icon} {area.get('name')}", value=f"{row.get('session_name')}\n{remain}", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="area", description="依票區關鍵字搜尋")
    @app_commands.describe(keyword="例如 VIP、橙508", event="可選：限制活動")
    async def area(self, interaction: discord.Interaction, keyword: str, event: str | None = None) -> None:
        rows = self.find_states(event) if event else self.state.event_sessions()
        key = keyword.casefold()
        matches = []
        for row in rows:
            for area in (row.get("areas") or {}).values():
                if key in str(area.get("name", "")).casefold():
                    matches.append((row, area))
        embed = discord.Embed(title=f"🔍 票區搜尋：{keyword}", color=PURPLE)
        if not matches:
            embed.description = "找不到符合條件的票區。"
        for row, area in matches[:25]:
            icon = "🟢" if area_available(area) else "🔴"
            remain = f"剩餘 **{area['remaining']}** 張" if area.get("remaining") is not None else area.get("status", "未知")
            embed.add_field(name=f"{icon} {area.get('name')}", value=f"**{row.get('event_name')}**｜{row.get('session_name')}\n{money(area.get('price'))}｜{remain}", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)



    async def _platform_events_response(self, interaction: discord.Interaction, provider: str, label: str) -> None:
        events = self.platform_events(provider)
        states = self.platform_states(provider)
        embed = discord.Embed(title=f"🎫 {label} 監控活動", color=BLUE)
        if not events:
            embed.description = f"目前 config.json 沒有設定 {label} 活動。"
        for event in events[:25]:
            event_states = [row for row in states if row.get("event_code") == event.code]
            available = sum(session_totals(row)[0] for row in event_states)
            status = "啟用" if event.enabled else "停用"
            embed.add_field(name=f"{'🟢' if event.enabled else '⚪'} {event.name}", value=f"代碼：`{event.code}`｜{status}｜有票票區 **{available}**", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _platform_ticket_response(self, interaction: discord.Interaction, provider: str, event: str) -> None:
        rows = self.platform_states(provider, event)
        if not rows:
            await interaction.response.send_message("🔍 找不到此平台的票況紀錄，請先執行平台專用 check 指令。", ephemeral=True)
            return
        state = rows[0]
        session_key = str(state.get("session_key"))
        view = TicketPaginationView(lambda: self.state.get(session_key))
        await interaction.response.send_message(embed=view.embed, view=view, ephemeral=True)

    async def _platform_open_response(self, interaction: discord.Interaction, provider: str, event: str) -> None:
        events = self.platform_events(provider)
        key = event.casefold().strip()
        selected = next(
            (item for item in events if item.code.casefold() == key),
            None,
        )
        if selected is None:
            selected = next(
                (item for item in events if key in item.code.casefold() or key in item.name.casefold()),
                None,
            )
        if selected is None:
            await interaction.response.send_message("🔍 找不到指定平台的活動。", ephemeral=True)
            return

        label = "KKTIX" if provider == "kktix" else "拓元"
        emoji = "🎟️" if provider == "kktix" else "🌐"
        view = discord.ui.View(timeout=180)
        view.add_item(discord.ui.Button(label=f"開啟 {label}", emoji=emoji, url=selected.url))
        embed = discord.Embed(
            title=f"{emoji} 開啟 {label} 活動",
            description=f"**{selected.name}**\n活動代碼：`{selected.code}`",
            color=BLUE,
            url=selected.url,
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="tixcraft_events", description="只顯示拓元監控活動")
    async def tixcraft_events(self, interaction: discord.Interaction) -> None:
        await self._platform_events_response(interaction, "tixcraft", "拓元")

    @app_commands.command(name="kktix_events", description="只顯示 KKTIX 監控活動")
    async def kktix_events(self, interaction: discord.Interaction) -> None:
        await self._platform_events_response(interaction, "kktix", "KKTIX")

    @app_commands.command(name="tixcraft_open", description="開啟拓元活動頁")
    @app_commands.describe(event="拓元活動代碼或名稱")
    @app_commands.autocomplete(event=tixcraft_event_autocomplete)
    async def tixcraft_open(self, interaction: discord.Interaction, event: str) -> None:
        await self._platform_open_response(interaction, "tixcraft", event)

    @app_commands.command(name="kktix_open", description="開啟 KKTIX 活動頁")
    @app_commands.describe(event="KKTIX 活動代碼或名稱")
    @app_commands.autocomplete(event=kktix_event_autocomplete)
    async def kktix_open(self, interaction: discord.Interaction, event: str) -> None:
        await self._platform_open_response(interaction, "kktix", event)

    @app_commands.command(name="tixcraft_ticket", description="查看拓元活動票況")
    @app_commands.autocomplete(event=tixcraft_event_autocomplete)
    async def tixcraft_ticket(self, interaction: discord.Interaction, event: str) -> None:
        await self._platform_ticket_response(interaction, "tixcraft", event)

    @app_commands.command(name="kktix_ticket", description="查看 KKTIX 活動票況")
    @app_commands.autocomplete(event=kktix_event_autocomplete)
    async def kktix_ticket(self, interaction: discord.Interaction, event: str) -> None:
        await self._platform_ticket_response(interaction, "kktix", event)

    @app_commands.command(name="tixcraft_check", description="立即檢查拓元活動")
    @app_commands.autocomplete(event_code=tixcraft_event_autocomplete)
    async def tixcraft_check(self, interaction: discord.Interaction, event_code: str | None = None) -> None:
        if not is_admin(interaction): return await self.deny(interaction)
        self.control.request("check", event_code=event_code, provider="tixcraft", requester=str(interaction.user), channel_id=interaction_channel_id(interaction))
        await interaction.response.send_message("🔎 已加入拓元手動檢查。", ephemeral=True)

    @app_commands.command(name="kktix_check", description="立即檢查 KKTIX 活動")
    @app_commands.autocomplete(event_code=kktix_event_autocomplete)
    async def kktix_check(self, interaction: discord.Interaction, event_code: str | None = None) -> None:
        if not is_admin(interaction): return await self.deny(interaction)
        self.control.request("check", event_code=event_code, provider="kktix", requester=str(interaction.user), channel_id=interaction_channel_id(interaction))
        await interaction.response.send_message("🔎 已加入 KKTIX 手動檢查。", ephemeral=True)

    @app_commands.command(name="restart_tixcraft", description="只重啟拓元 Chrome")
    async def restart_tixcraft(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction): return await self.deny(interaction)
        self.control.request("restart_browser", provider="tixcraft", requester=str(interaction.user), channel_id=interaction_channel_id(interaction))
        await interaction.response.send_message("♻️ 已送出拓元 Chrome 重啟要求。", ephemeral=True)

    @app_commands.command(name="restart_kktix", description="只重啟 KKTIX Chrome")
    async def restart_kktix(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction): return await self.deny(interaction)
        self.control.request("restart_browser", provider="kktix", requester=str(interaction.user), channel_id=interaction_channel_id(interaction))
        await interaction.response.send_message("♻️ 已送出 KKTIX Chrome 重啟要求。", ephemeral=True)

    @app_commands.command(name="screenshot_tixcraft", description="擷取拓元 Chrome 畫面")
    async def screenshot_tixcraft(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction): return await self.deny(interaction)
        self.control.request("screenshot", provider="tixcraft", requester=str(interaction.user), channel_id=interaction_channel_id(interaction))
        await interaction.response.send_message("📸 已送出拓元截圖要求。", ephemeral=True)

    @app_commands.command(name="screenshot_kktix", description="擷取 KKTIX Chrome 畫面")
    async def screenshot_kktix(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction): return await self.deny(interaction)
        self.control.request("screenshot", provider="kktix", requester=str(interaction.user), channel_id=interaction_channel_id(interaction))
        await interaction.response.send_message("📸 已送出 KKTIX 截圖要求。", ephemeral=True)

    @app_commands.command(name="parser", description="查看最近一次票區 Parser Replay")
    async def parser_cmd(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction): return await self.deny(interaction)
        files = sorted(Path("logs/parser").glob("*.json"), reverse=True)
        if not files:
            await interaction.response.send_message("目前沒有 Parser Replay，請在 config.json 啟用 `parser_replay`。", ephemeral=True)
            return
        try:
            data = json.loads(files[0].read_text(encoding="utf-8"))
        except Exception as exc:
            await interaction.response.send_message(f"❌ Parser Replay 讀取失敗：{exc}", ephemeral=True)
            return
        embed = discord.Embed(title="🧪 最近 Parser Replay", color=PURPLE)
        embed.add_field(name="Raw", value=f"```text\n{str(data.get('raw', ''))[:900]}\n```", inline=False)
        embed.add_field(name="票區", value=str(data.get("area", "—")), inline=True)
        embed.add_field(name="票價", value=money(data.get("price")), inline=True)
        remaining = data.get("remaining")
        embed.add_field(name="剩餘", value=f"{remaining} 張" if remaining is not None else "數量未知", inline=True)
        embed.add_field(name="狀態", value=str(data.get("status", "未知")), inline=True)
        embed.add_field(name="語言", value=str(data.get("language", "UNKNOWN")), inline=True)
        embed.set_footer(text=files[0].name)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="history", description="查看最近票況異動")
    async def history_cmd(self, interaction: discord.Interaction) -> None:
        items = list(reversed(self.history.list(10)))
        embed = discord.Embed(title="🕓 最近票況異動", color=PURPLE)
        if not items:
            embed.description = "目前沒有異動紀錄。"
        for item in items:
            changes = "\n".join(f"• {change_text(c) if isinstance(c, dict) else c}" for c in item.get("changes", [])[:6]) or "無詳細內容"
            embed.add_field(name=f"🎤 {item.get('event_name')}｜{item.get('session_name')}", value=changes[:1024], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="summary", description="查看累計監控統計")
    async def summary(self, interaction: discord.Interaction) -> None:
        data = self.stats.get()
        embed = discord.Embed(title="📈 監控統計摘要", color=BLUE)
        embed.add_field(name="🔎 總檢查", value=f"**{data.get('checks', 0)}** 次", inline=True)
        embed.add_field(name="✅ 成功", value=f"**{data.get('successful_checks', 0)}** 次", inline=True)
        embed.add_field(name="❌ 失敗", value=f"**{data.get('failed_checks', 0)}** 次", inline=True)
        embed.add_field(name="🔔 通知", value=f"**{data.get('notifications', 0)}** 次", inline=True)
        embed.add_field(name="🖱️ 手動檢查", value=f"**{data.get('manual_checks', 0)}** 次", inline=True)
        embed.add_field(name="♻️ Chrome 重啟", value=f"**{data.get('browser_restarts', 0)}** 次", inline=True)
        embed.set_footer(text=f"開始時間：{data.get('started_at') or '—'}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="check", description="立即重新檢查並強制發出目前票況")
    async def check(self, interaction: discord.Interaction, event_code: str | None = None) -> None:
        if not is_admin(interaction): return await self.deny(interaction)
        self.control.request("check", event_code=event_code, requester=str(interaction.user), channel_id=interaction_channel_id(interaction))
        await interaction.response.send_message("🔎 已加入手動檢查，完成後會在本頻道發送精簡票況卡片。", ephemeral=True)

    @app_commands.command(name="notify_now", description="不重新抓網站，發送最近儲存票況")
    async def notify_now(self, interaction: discord.Interaction, event_code: str | None = None) -> None:
        if not is_admin(interaction): return await self.deny(interaction)
        self.control.request("notify_now", event_code=event_code, requester=str(interaction.user), channel_id=interaction_channel_id(interaction))
        await interaction.response.send_message("📣 已加入強制發送佇列。", ephemeral=True)

    @app_commands.command(name="pause", description="暫停自動監票")
    async def pause(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction): return await self.deny(interaction)
        self.runtime.update(paused=True)
        await interaction.response.send_message("⏸️ 已暫停自動監票。", ephemeral=True)

    @app_commands.command(name="resume", description="恢復自動監票")
    async def resume(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction): return await self.deny(interaction)
        self.runtime.update(paused=False)
        await interaction.response.send_message("▶️ 已恢復自動監票。", ephemeral=True)

    @app_commands.command(name="restart_browser", description="要求監票程序重啟 Chrome")
    async def restart_browser(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction): return await self.deny(interaction)
        self.control.request("restart_browser", requester=str(interaction.user), channel_id=interaction_channel_id(interaction))
        await interaction.response.send_message("♻️ 已送出 Chrome 重啟要求。", ephemeral=True)

    @app_commands.command(name="reload", description="重新載入 config.json")
    async def reload_cmd(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction): return await self.deny(interaction)
        self.control.request("reload_config", requester=str(interaction.user), channel_id=interaction_channel_id(interaction))
        await interaction.response.send_message("🔄 已送出設定重新載入要求。", ephemeral=True)

    @app_commands.command(name="screenshot", description="擷取目前 Chrome 畫面")
    async def screenshot_cmd(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction): return await self.deny(interaction)
        self.control.request("screenshot", requester=str(interaction.user), channel_id=interaction_channel_id(interaction))
        await interaction.response.send_message("📸 已送出截圖要求。", ephemeral=True)

    @app_commands.command(name="backup", description="立即備份 data 資料")
    async def backup_cmd(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction): return await self.deny(interaction)
        self.control.request("backup", requester=str(interaction.user), channel_id=interaction_channel_id(interaction))
        await interaction.response.send_message("💾 已送出備份要求。", ephemeral=True)

    @app_commands.command(name="health", description="查看程序健康狀態")
    async def health_cmd(self, interaction: discord.Interaction) -> None:
        data = self.health.snapshot()
        embed = discord.Embed(title="🩺 Enterprise Health", color=BLUE)
        for name, value in (("PID", data['pid']), ("CPU", f"{data['cpu_percent']}%"), ("記憶體", f"{data['memory_mb']} MB"), ("Monitor", data['running']), ("Chrome", data['browser_alive']), ("Heartbeat", data['heartbeat']), ("最後檢查", data['last_check'])):
            embed.add_field(name=name, value=f"`{value}`", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="queue", description="查看待送通知數")
    async def queue_status(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(f"📬 待送通知：**{len(self.queue.list())}** 筆", ephemeral=True)

    @app_commands.command(name="logs", description="查看最近 Log")
    async def logs_cmd(self, interaction: discord.Interaction, lines: int = 40) -> None:
        if not is_admin(interaction): return await self.deny(interaction)
        amount = max(1, min(lines, 100))
        content = self.health.tail_log(lines=amount)
        await interaction.response.send_message(f"```text\n{content[-1800:]}\n```", ephemeral=True)

    @app_commands.command(name="version", description="顯示程式版本")
    async def version_cmd(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("🎫 **Ticket Monitor Enterprise V19.1 Dual Provider**", ephemeral=True)

    @app_commands.command(name="export_csv", description="匯出目前票況 CSV（Owner Only）")
    async def export_csv_cmd(self, interaction: discord.Interaction) -> None:
        if not is_admin(interaction): return await self.deny(interaction)
        import csv, tempfile
        path=Path(tempfile.gettempdir())/"tixcraft_ticket_state.csv"
        with path.open("w",newline="",encoding="utf-8-sig") as fh:
            w=csv.writer(fh); w.writerow(["event","session","group","area","subtype","price","price_min","price_max","remaining","status","checked_at"])
            for row in self.state.event_sessions():
                for area in (row.get("areas") or {}).values():
                    w.writerow([row.get("event_name"),row.get("session_name"),area.get("group"),area.get("name"),area.get("subtype"),area.get("price"),area.get("price_min"),area.get("price_max"),area.get("remaining"),area.get("status"),row.get("checked_at")])
        await interaction.response.send_message(file=discord.File(path), ephemeral=True)
