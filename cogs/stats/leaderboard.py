from __future__ import annotations
from typing import NamedTuple
from datetime import datetime
from datetime import timedelta as td

import asyncpg
import discord
from discord.ext import commands

from utils import HideoutCog, HideoutContext, View
from bot import HideoutManager


class DatabaseData(NamedTuple):
    rank: int
    message_count: int


class LeaderboardCard:
    # Options
    WIDTH = 1200
    HEIGHT = 2400
    OVERALL_PADDING = 50
    LEFT_TEXT_PADDING = 20

    DROP_SHADOW_OFFSET = (3, 3)
    DROP_SHADOW_ITERATIONS = 15
    DROP_SHADOW_EXTRA_SIZE = 10

    BG_COLOR = discord.Color.from_str("#1b1d21")

    """WIP. Using embed for now"""


class LeaderboardView(View):
    def __init__(self, embed: LeaderboardEmbed, author: discord.User | discord.Member):
        self.author = author
        self.current_embed: LeaderboardEmbed = embed
        super().__init__(timeout=300)

    async def interaction_check(self, interaction: discord.Interaction):  # type: ignore
        if interaction.user != self.author:
            return await interaction.response.send_message("This is not your view!", ephemeral=True)

        return True

    @discord.ui.button(style=discord.ButtonStyle.secondary, label="All Time", disabled=True)
    async def all_time_callback(self, interaction: discord.Interaction[HideoutManager], button: discord.ui.Button):  # type: ignore
        for btn in self.children:
            if isinstance(btn, discord.ui.Button):
                btn.disabled = False

        button.disabled = True

        embed = await self.current_embed.update_leaderboard(interval=None)

        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(style=discord.ButtonStyle.secondary, label="Last 30 Days")
    async def _30_day_callback(self, interaction: discord.Interaction[HideoutManager], button: discord.ui.Button):  # type: ignore
        for btn in self.children:
            if isinstance(btn, discord.ui.Button):
                btn.disabled = False

        button.disabled = True

        embed = await self.current_embed.update_leaderboard(interval="'30 DAYS'")

        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(style=discord.ButtonStyle.secondary, label="Last 7 Days")
    async def _7_day_callback(self, interaction: discord.Interaction[HideoutManager], button: discord.ui.Button):  # type: ignore
        for btn in self.children:
            if isinstance(btn, discord.ui.Button):
                btn.disabled = False

        button.disabled = True

        embed = await self.current_embed.update_leaderboard(interval="'7 DAYS'")

        await interaction.response.edit_message(embed=embed, view=self)


class LeaderboardEmbed(discord.Embed):
    def __init__(self, pool: asyncpg.Pool[asyncpg.Record], bot: HideoutManager):
        self._pool = pool
        self._bot = bot
        super().__init__(title="Leaderboard", color=discord.Color.from_str("#1b1d21"))

    async def update_leaderboard(self, interval: str | None) -> discord.Embed:
        query = """
        SELECT author_id, COUNT(*) as message_count FROM message_info 
        WHERE deleted = FALSE 
        AND is_bot = $1
        {0}
        GROUP BY author_id 
        ORDER BY message_count DESC LIMIT 10
        """
        self._data: list[asyncpg.Record] = await self._pool.fetch(
            query.format("--" if interval is None else f"AND created_at > NOW() - INTERVAL {interval}"), False
        )

        if not self._data:
            raise RuntimeError("No leaderboard can be generated.")

        for rank, user in enumerate(self._data, start=1):
            # Fetch the user
            pos_user = self._bot.get_user(user['author_id'])

            if not pos_user:
                pos_user = await self._bot.fetch_user(user['author_id'])

            self.add_field(name=f"Rank {rank}", value=f"{pos_user}\n{user['message_count']:,} messages", inline=False)

        return self


class LeaderboardCog(HideoutCog):
    @commands.hybrid_command()
    @commands.guild_only()
    async def leaderboard(self, ctx: HideoutContext):
        """Shows the top 10 leaderboard"""
        async with ctx.typing():
            LBEmbed = LeaderboardEmbed(ctx.bot.pool, ctx.bot)
            embed = await LBEmbed.update_leaderboard(interval=None)

            await ctx.send(embed=embed, view=LeaderboardView(LBEmbed, ctx.author))
