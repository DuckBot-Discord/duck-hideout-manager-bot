from __future__ import annotations

import asyncio
import datetime
import io
import logging
from typing import NamedTuple

import asyncpg
import discord
from discord.ext import commands
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from bot import HideoutManager
from utils import HideoutCog, HideoutContext, View

logging.getLogger('matplotlib.font_manager').setLevel(logging.INFO)


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
        self.message: discord.Message | None = None
        super().__init__(timeout=300)

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user != self.author:
            return await interaction.response.send_message("This is not your view!", ephemeral=True)

        return True

    async def on_timeout(self):
        for btn in self.children:
            if isinstance(btn, discord.ui.Button):
                btn.disabled = True

        if self.message:
            await self.message.edit(view=self)

    @discord.ui.button(style=discord.ButtonStyle.secondary, label="All Time", disabled=True)
    async def all_time_callback(self, interaction: discord.Interaction[HideoutManager], button: discord.ui.Button):
        for btn in self.children:
            if isinstance(btn, discord.ui.Button):
                btn.disabled = False

        button.disabled = True

        embed = await self.current_embed.update_leaderboard(interval=None)

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(style=discord.ButtonStyle.secondary, label="Last 30 Days")
    async def _30_day_callback(self, interaction: discord.Interaction[HideoutManager], button: discord.ui.Button):
        for btn in self.children:
            if isinstance(btn, discord.ui.Button):
                btn.disabled = False

        button.disabled = True

        embed = await self.current_embed.update_leaderboard(interval="'30 DAYS'")

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(style=discord.ButtonStyle.secondary, label="Last 7 Days")
    async def _7_day_callback(self, interaction: discord.Interaction[HideoutManager], button: discord.ui.Button):
        for btn in self.children:
            if isinstance(btn, discord.ui.Button):
                btn.disabled = False

        button.disabled = True

        embed = await self.current_embed.update_leaderboard(interval="'7 DAYS'")

        await interaction.response.edit_message(embed=embed, view=self)


class LeaderboardEmbed(discord.Embed):
    def __init__(self, pool: asyncpg.Pool[asyncpg.Record], bot: HideoutManager, creator: discord.User | discord.Member):
        self._pool = pool
        self._bot = bot
        self._creator = creator
        super().__init__(title="Leaderboard", color=discord.Color.from_str("#1b1d21"))

    async def update_leaderboard(self, interval: str | None) -> discord.Embed:
        self.clear_fields()

        query = """
        WITH counts AS (
            SELECT 
                author_id, 
                COUNT(*) as message_count
            FROM message_info  
            WHERE deleted = FALSE  
            AND is_bot = $1 
            {0}
            GROUP BY author_id  
            ORDER BY message_count DESC
        ), ret AS (
            SELECT *, row_number() over() as rank FROM counts
        )
        SELECT * FROM ret
        WHERE (message_count > (SELECT message_count FROM ret LIMIT 1 OFFSET 10))
        OR author_id = $2
        """
        self._data: list[asyncpg.Record] = await self._pool.fetch(
            query.format("--" if interval is None else f"AND created_at > NOW() - INTERVAL {interval}"),
            False,
            self._creator.id,
        )

        if not self._data:
            raise RuntimeError("No leaderboard can be generated.")

        for user in self._data:
            # Fetch the user
            pos_user = self._bot.get_user(user['author_id'])

            if not pos_user:
                pos_user = await self._bot.fetch_user(user['author_id'])

            self.add_field(
                name=f"Rank {user['rank']}", value=f"{pos_user}\n{user['message_count']:,} messages", inline=False
            )

        return self


class LeaderboardCog(HideoutCog):
    @commands.hybrid_command(aliases=['lb'])
    @commands.guild_only()
    async def leaderboard(self, ctx: HideoutContext):
        """Shows the top 10 leaderboard"""
        async with ctx.typing():
            LBEmbed = LeaderboardEmbed(ctx.bot.pool, ctx.bot, ctx.author)
            embed = await LBEmbed.update_leaderboard(interval=None)
            v = LeaderboardView(LBEmbed, ctx.author)

            v.message = await ctx.send(embed=embed, view=v)

    @staticmethod
    def generate_graph(data: list[tuple[discord.abc.User, list[asyncpg.Record]]]) -> discord.File:
        figure = Figure(figsize=(20, 15), dpi=100)
        plot = figure.add_subplot()
        plot.set_xlabel("message count")
        plot.set_ylabel("Date")
        plot.set_title(f"Message statistics")
        plot.xaxis_date(tz=datetime.timezone.utc)

        for user, entries in data:
            x_axis = []
            y_axis = []

            for entry in entries:
                message_count = entry['message_count']

                x_axis.append(entry['day'])
                y_axis.append(message_count)

            plot.plot(x_axis, y_axis, linewidth=1, label=user.name)

        plot.legend()
        renderer = FigureCanvasAgg(figure)
        buffer = io.BytesIO()

        renderer.print_png(buffer)
        buffer.seek(0)

        return discord.File(buffer, filename="test.png")

    @commands.command(name='message-stats')
    async def message_stats(self, ctx: commands.Context, *users: discord.Member | discord.User):
        """Sends message stats for a user.

        Parameters
        ----------
        users: discord.Member
            The users (max of 10) to query. Defaults to you.
        """
        users_as_a_set = {*users[:10]} if users else {ctx.author}
        query = """
            SELECT 
                DATE_TRUNC('day', created_at) as day, 
                COUNT(*) as message_count
            FROM message_info
            WHERE author_id = $1
            GROUP BY day ORDER BY day DESC;
        """

        data = []

        async with ctx.typing():
            for user in users_as_a_set:
                message_info_list = await ctx.bot.pool.fetch(query, user.id)
                data.append((user, message_info_list))

            graph = await asyncio.to_thread(self.generate_graph, data)

            await ctx.send(file=graph)
