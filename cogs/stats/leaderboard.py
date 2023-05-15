from __future__ import annotations
from typing import NamedTuple
from datetime import datetime

import asyncpg
import discord
from discord.ext import commands

from utils import HideoutCog, HideoutContext
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


class LeaderboardView(discord.ui.View):
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
            if isinstance(btn, discord.Button):
                btn.disabled = False

        button.disabled = True

        embed = await self.current_embed.update_leaderboard(
            pool=interaction.client.pool, interval=interaction.guild.created_at, bot=interaction.client
        )

        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(style=discord.ButtonStyle.secondary, label="Last 30 Days")
    async def _30_day_callback(self, interaction: discord.Interaction[HideoutManager], button: discord.ui.Button):  # type: ignore
        for btn in self.children:
            if isinstance(btn, discord.Button):
                btn.disabled = False

        button.disabled = True

        embed = await self.current_embed.update_leaderboard(
            pool=interaction.client.pool, interval=f"30 DAYS", bot=interaction.client
        )

        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(style=discord.ButtonStyle.secondary, label="Last 7 Days")
    async def _7_day_callback(self, interaction: discord.Interaction[HideoutManager], button: discord.ui.Button):  # type: ignore
        for btn in self.children:
            if isinstance(btn, discord.Button):
                btn.disabled = False

        button.disabled = True

        embed = await self.current_embed.update_leaderboard(
            pool=interaction.client.pool, interval=f"7 DAYS", bot=interaction.client
        )

        await interaction.edit_original_response(embed=embed, view=self)


class LeaderboardEmbed(discord.Embed):
    def __init__(self):
        self.color = discord.Color.from_str("#1b1d21")
        self.title = "Leaderboard"

    async def update_leaderboard(
        self, pool: asyncpg.Pool[asyncpg.Record], interval: str | datetime, bot: HideoutManager
    ) -> discord.Embed:
        top_10_q = """
        SELECT author_id, COUNT(*) as message_count FROM message_info 
        WHERE deleted = FALSE 
        AND is_bot = $1 
        AND created_at > NOW() - $2::INTERVAL
        GROUP BY author_id 
        ORDER BY message_count DESC LIMIT 10
        """
        self.top_10_f_records: list[asyncpg.Record] = await pool.fetch(top_10_q, False, interval)

        if not self.top_10_f_records:
            raise RuntimeError("No leaderboard can be generated.")

        i = 1

        for user in self.top_10_f_records:
            # Fetch the user
            pos_user = bot.get_user(user['author_id'])

            if not pos_user:
                pos_user = await bot.fetch_user(user['author_id'])

            self.add_field(name=f"Rank {i}", value=pos_user, inline=False)

        return self


class LeaderboardCog(HideoutCog):
    @commands.hybrid_command()
    @commands.guild_only()
    async def leaderboard(self, ctx: HideoutContext):
        """Shows the top 10 leaderboard"""
        async with ctx.typing():
            LBEmbed = LeaderboardEmbed()
            embed = await LBEmbed.update_leaderboard(pool=ctx.bot.pool, interval=ctx.guild.created_at, bot=ctx.bot)

            await ctx.send(embed=embed, view=LeaderboardView(LBEmbed, ctx.author))
