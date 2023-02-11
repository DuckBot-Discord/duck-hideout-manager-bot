import datetime
import io
import itertools
import zoneinfo
from typing import TYPE_CHECKING, Any

import cachetools
import discord
from asyncpg import Pool, Record
from discord import app_commands
from discord.ext import commands
from jishaku.functools import executor_function
from PIL import Image, ImageDraw, ImageFont

from utils import HideoutCog, HideoutContext, fuzzy


class CalendarStatus:

    # SETTINGS
    WIDTH = 1200
    BAR_HEIGHT = 25

    if TYPE_CHECKING:
        member: discord.abc.User
        draw: ImageDraw.ImageDraw
        times: list[list[tuple[str | None, datetime.datetime]]]

    # constants
    STATUS_COLORS = {
        'online': discord.Colour.from_str('#43b581'),
        'offline': discord.Colour.from_str('#747f8d'),
        'idle': discord.Colour.from_str('#faa61a'),
        'dnd': discord.Colour.from_str('#f04747'),
        None: discord.Colour.from_str('#1b1d21'),
    }

    async def async_init(self, member: discord.abc.User, pool: Pool[Record]):
        self.member = member
        query = """
            WITH ret AS (
                SELECT status, changed_at AT TIME ZONE COALESCE((SELECT timezone FROM user_settings WHERE user_id = 10), 'UTC') AS changed_at
                FROM status_history WHERE user_id = $1
            )
            SELECT array_agg(ROW(status, changed_at) ORDER BY changed_at DESC) AS dts
            FROM ret
            WHERE changed_at > NOW() - INTERVAL '30 days'
            GROUP BY date_trunc('day', changed_at)
            ORDER BY date_trunc('day', changed_at) DESC
        """
        self.times = [r['dts'] for r in await pool.fetch(query, member.id)]

    # Math functions
    def seconds_to_px(self, seconds: int) -> int:
        return int(seconds / (3600 * 24) * self.WIDTH)

    def calc_size(
        self, time: datetime.datetime, color: str | None, next_status: datetime.datetime, sod: datetime.datetime
    ) -> tuple[int, int, discord.Colour]:

        x_seconds_from_left = int((time - sod).total_seconds())
        x_pixels_from_left = self.seconds_to_px(x_seconds_from_left)

        x_seconds_width = int((next_status - sod).total_seconds())
        x_pixels_width = self.seconds_to_px(x_seconds_width) - x_pixels_from_left

        status_color = self.STATUS_COLORS[color]

        with open('status.log', 'a') as fp:
            print(
                f"[X SECONDS FOR {time.strftime(f'%a %d %b | %X: {color}')}]",
                f"{x_seconds_from_left = }",
                f"{x_pixels_from_left = }",
                f"{x_seconds_width = }",
                f"{x_pixels_width = }",
                sep='\n',
                end='\n\n',
                file=fp,
            )

        return x_pixels_from_left, x_pixels_width, status_color

    @executor_function
    def full_render(self) -> io.BytesIO | str:
        if not self.times:
            return "No records found"
        buffer = io.BytesIO()
        height = self.BAR_HEIGHT * len(self.times)
        canvas = Image.new('RGB', size=(self.WIDTH, height))
        height -= self.BAR_HEIGHT
        first_next = None
        x: list[list[tuple[str | None, datetime.datetime]]] = [[(None, datetime.datetime.now())]]

        for yesterday, now in itertools.pairwise(x + self.times + x):
            canv = self.draw_status_bar(now, previous_last=yesterday[-1][0], first_next=first_next)
            first_next = now[0][0]
            canvas.paste(canv, (0, height))
            height -= self.BAR_HEIGHT
        canvas.save(buffer, format='PNG')
        buffer.seek(0)
        return buffer

    # Image generations
    def draw_status_bar(
        self,
        times: list[tuple[str | None, datetime.datetime]],
        previous_last: str | None,
        first_next: str | None,
    ) -> Image.Image:
        canvas = Image.new('RGBA', (self.WIDTH, 25), "white")
        draw = ImageDraw.Draw(canvas)
        eod = times[0][1].replace(hour=23, minute=59, second=59, microsecond=9999)
        sod = times[0][1].replace(hour=0, minute=0, second=0, microsecond=0)

        ret: list[tuple[int, int, discord.Colour]] = []

        times = [(first_next, eod)] + times + [(previous_last, sod)]

        with open('status.log', 'a') as fp:
            print(
                f'[STATUSES FOR]',
                *[time.strftime(f'{i}) %a %d %b | %X: {status}') for i, (status, time) in enumerate(times, start=1)],
                sep='\n',
                end='\n\n',
                file=fp,
            )

        for (_, next), (status, current) in itertools.pairwise(times):
            offset, width, color = self.calc_size(current, status, next_status=next, sod=sod)
            ret.append((offset, width, color))

        for offset, width, color in ret:
            draw.rectangle(((offset, 0), (offset + width, self.BAR_HEIGHT)), fill=(color.r, color.g, color.b))

        font = ImageFont.truetype('./assets/fonts/Oswald-SemiBold.ttf', 16)
        draw = ImageDraw.Draw(canvas)
        draw.text((0, 0), times[0][1].strftime('%a %d %b'), font=font)  # pyright: reportUnknownMemberType=false

        return canvas


class CalendarStatusCog(HideoutCog):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.processed: cachetools.LRUCache[str, list[app_commands.Choice[str]]] = cachetools.LRUCache(maxsize=200)

    @commands.hybrid_command(name='calendar-status', aliases=('calendarstatus', 'cs'))
    @app_commands.describe(user='The user whose calendar you wish to get.')
    async def calendar_status(self, ctx: HideoutContext, user: discord.Member | discord.User = commands.Author):
        """Gets yours or another user's calendar status log."""

        with open('status.log', 'w') as fp:
            fp.write('')

        async with ctx.typing():
            card = CalendarStatus()
            await card.async_init(user, ctx.bot.pool)
            file = await card.full_render()
        if isinstance(file, str):
            return await ctx.send(file)
        await ctx.send(file=discord.File(file, filename='calendar.png'))

    @commands.hybrid_command(name='set-timezone', aliases=('settz', 'tz'))
    @app_commands.rename(timezone_name='timezone-name')
    @app_commands.describe(timezone_name='Your time zone.')
    async def set_timezone(self, ctx: HideoutContext, *, timezone_name: str):
        """Sets your timezone to use for different features."""
        try:
            tz = zoneinfo.ZoneInfo(timezone_name)
        except zoneinfo.ZoneInfoNotFoundError:
            raise commands.BadArgument(f'Unknown time zone: {timezone_name[:100]!r}')
        query = (
            'INSERT INTO user_settings (user_id, timezone) VALUES ($1, $2)'
            'ON CONFLICT (user_id) DO UPDATE SET timezone = $2'
        )
        await self.bot.pool.execute(query, ctx.author.id, tz.key)
        await ctx.send(f'Updated your timezone to {tz}', ephemeral=True)

    @set_timezone.autocomplete('timezone_name')
    async def settz_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        try:
            return self.processed[current]
        except KeyError:
            results = fuzzy.extract(current, list(zoneinfo.available_timezones()), limit=25)
            processed = [app_commands.Choice(name=result, value=result) for result, _ in results]
            self.processed[current] = processed
            return processed

    @commands.command()
    async def time(self, ctx: HideoutContext, user: discord.Member | discord.User = commands.Author):
        """Shows a user's time, or yours."""
        query = "SELECT timezone FROM user_settings WHERE user_id = $1"
        tz_name = await self.bot.pool.fetchval(query, user.id)
        if not tz_name:
            raise commands.BadArgument(
                'User does not have a time zone set. Please use `/set-timezone timezone-name: <your timezone name>`'
            )
        tz = zoneinfo.ZoneInfo(tz_name)
        dt = datetime.datetime.now(tz)
        await ctx.send(
            dt.strftime("It is `%A, %B %m %Y at %I:%M %p` for **{}** ({})").format(
                discord.utils.escape_markdown(user.display_name), tz_name
            )
        )
