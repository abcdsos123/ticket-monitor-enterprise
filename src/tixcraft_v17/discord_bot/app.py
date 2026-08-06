from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from tixcraft_v17.config import (
    DISCORD_BOT_TOKEN,
    DISCORD_GUILD_ID,
    LOG_LEVEL,
)
from tixcraft_v17.discord_bot.commands import MonitorCommands
from tixcraft_v17.discord_bot.sender import QueueSender
from tixcraft_v17.utils.logging import configure_logging


logger = logging.getLogger(__name__)


class Bot(commands.Bot):
    async def setup_hook(self) -> None:
        await self.add_cog(MonitorCommands(self))
        await self.add_cog(QueueSender(self))

        if DISCORD_GUILD_ID:
            guild = discord.Object(id=int(DISCORD_GUILD_ID))

            # 先清除本機 Tree 中可能殘留的 Guild Commands。
            self.tree.clear_commands(guild=guild)

            # 將目前定義的 Global Commands 複製成 Guild Commands。
            self.tree.copy_global_to(guild=guild)

            # Guild Commands 同步速度快，適合開發及私人伺服器。
            guild_synced = await self.tree.sync(guild=guild)

            logger.info(
                "已同步 %d 個 Guild Slash Commands",
                len(guild_synced),
            )

            # 清除 Discord 上舊的 Global Commands，
            # 避免 Global 與 Guild 各出現一份。
            self.tree.clear_commands(guild=None)
            global_synced = await self.tree.sync()

            logger.info(
                "Global Slash Commands 已清除，目前剩餘 %d 個",
                len(global_synced),
            )

        else:
            synced = await self.tree.sync()

            logger.info(
                "已同步 %d 個 Global Slash Commands",
                len(synced),
            )


def create_bot() -> Bot:
    return Bot(
        command_prefix="!",
        intents=discord.Intents.default(),
    )


async def main() -> None:
    configure_logging(LOG_LEVEL)

    if not DISCORD_BOT_TOKEN:
        raise RuntimeError("尚未設定 DISCORD_BOT_TOKEN")

    async with create_bot() as bot:
        await bot.start(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())