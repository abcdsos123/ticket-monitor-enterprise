from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import discord

from tixcraft_v17.discord_bot.formatter import ticket_pages


def state_provider(state: dict[str, Any]) -> str:
    """Best-effort provider detection for a stored ticket state."""
    explicit = str(state.get("provider") or "").strip().casefold()
    if explicit in {"tixcraft", "kktix"}:
        return explicit

    session_key = str(state.get("session_key") or "").casefold()
    if "::kktix::" in session_key:
        return "kktix"
    if "::tixcraft::" in session_key:
        return "tixcraft"

    url = str(state.get("session_url") or state.get("event_url") or "")
    host = urlparse(url).netloc.casefold()
    if "kktix" in host:
        return "kktix"
    return "tixcraft"


def platform_open_label(state: dict[str, Any]) -> tuple[str, str]:
    provider = state_provider(state)
    if provider == "kktix":
        return "開啟 KKTIX", "🎟️"
    return "開啟拓元", "🌐"


class TicketPaginationView(discord.ui.View):
    def __init__(
        self,
        state_loader: Callable[[], dict[str, Any] | None],
        *,
        timeout: float = 180,
    ) -> None:
        super().__init__(timeout=timeout)
        self.state_loader = state_loader
        self.state = state_loader() or {}
        self.pages = ticket_pages(self.state)
        self.index = 0
        self._add_platform_open_button()
        self._sync_buttons()

    def _add_platform_open_button(self) -> None:
        url = str(self.state.get("session_url") or "").strip()
        if not url:
            return
        label, emoji = platform_open_label(self.state)
        self.add_item(discord.ui.Button(label=label, emoji=emoji, url=url))

    @property
    def embed(self) -> discord.Embed:
        return self.pages[self.index]

    def _sync_buttons(self) -> None:
        self.previous.disabled = self.index <= 0
        self.next.disabled = self.index >= len(self.pages) - 1

    async def _edit(self, interaction: discord.Interaction) -> None:
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.embed, view=self)

    @discord.ui.button(label="上一頁", emoji="◀️", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.index = max(0, self.index - 1)
        await self._edit(interaction)

    @discord.ui.button(label="下一頁", emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.index = min(len(self.pages) - 1, self.index + 1)
        await self._edit(interaction)

    @discord.ui.button(label="更新資料", emoji="🔄", style=discord.ButtonStyle.primary)
    async def refresh(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        latest = self.state_loader()
        if not latest:
            await interaction.response.send_message("找不到最新票況資料。", ephemeral=True)
            return
        self.state = latest
        self.pages = ticket_pages(latest)
        self.index = min(self.index, len(self.pages) - 1)
        await self._edit(interaction)
