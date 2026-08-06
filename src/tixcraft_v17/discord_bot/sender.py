from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import discord
from discord.ext import commands, tasks

from tixcraft_v17.config import DISCORD_CHANNEL_ID
from tixcraft_v17.discord_bot.formatter import compact_notification_embed
from tixcraft_v17.notifier import NotificationQueue
from tixcraft_v17.state import StateStore

logger = logging.getLogger(__name__)


class QueueSender(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.queue = NotificationQueue()
        self.state = StateStore()
        self.send_pending.start()

    def cog_unload(self) -> None:
        self.send_pending.cancel()

    @tasks.loop(seconds=2)
    async def send_pending(self) -> None:
        for item in self.queue.list()[:5]:
            item_id = str(item.get("id"))
            channel_id = item.get("channel_id") or DISCORD_CHANNEL_ID
            if not channel_id:
                continue
            try:
                channel = self.bot.get_channel(int(channel_id)) or await self.bot.fetch_channel(int(channel_id))
                message = str(item.get("message", ""))
                metadata = item.get("metadata") or {}
                level = str(item.get("level", "info"))

                if message.startswith("SCREENSHOT::"):
                    path = Path(message.split("::", 1)[1])
                    if path.exists():
                        await channel.send("📸 **Chrome 目前畫面**", file=discord.File(path))
                    else:
                        await channel.send("❌ 找不到截圖檔案。")
                elif level == "ticket" and metadata.get("session_key"):
                    state = self.state.get(str(metadata["session_key"]))
                    if state:
                        title = str(metadata.get("title") or ("🔎 手動票況檢查" if "手動票況檢查" in message else "📌 初始票況" if "初始票況" in message else "🚨 票況異動"))
                        changes = list(metadata.get("changes") or [])
                        if not changes and "異動：" in message:
                            changes = [line.removeprefix("• ").strip() for line in message.split("異動：", 1)[1].splitlines() if line.strip()]
                        await channel.send(embed=compact_notification_embed(state, title, changes), allowed_mentions=discord.AllowedMentions.none())
                    else:
                        await channel.send(message[:2000], allowed_mentions=discord.AllowedMentions.none())
                else:
                    colors = {"error": 0xE74C3C, "warning": 0xF1C40F, "info": 0x3498DB}
                    icons = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}
                    embed = discord.Embed(title=f"{icons.get(level, 'ℹ️')} 系統通知", description=message[:4000], color=colors.get(level, 0x3498DB))
                    await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

                self.queue.remove(item_id)
            except discord.DiscordException:
                logger.exception("Discord 通知傳送失敗")
                self.queue.increment_attempts(item_id)
                attempts = int(item.get("attempts", 0)) + 1
                await asyncio.sleep(min(60, 2 ** min(attempts, 5)))

    @send_pending.before_loop
    async def before_send_pending(self) -> None:
        await self.bot.wait_until_ready()
