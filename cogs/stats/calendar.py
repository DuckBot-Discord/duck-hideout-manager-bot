from __future__ import annotations

import datetime
import io
import itertools
import math
import os
import zoneinfo
from typing import Any, Sequence

import cachetools
import discord
import numpy as np
from discord import app_commands
from discord.ext import commands
from jishaku.functools import executor_function
from PIL import Image, ImageDraw, ImageFont

from utils import HideoutCog, HideoutContext, fuzzy
from bot import HideoutManager


def seconds_to_px(seconds: int | float) -> int:
    return math.floor(seconds / (3600 * 24) * 1200)


class CalendarStatus:
    WIDTH = 1200

    STATUS_COLORS_MAP = {
        'online': np.array([*discord.Colour.from_str('#43b581').to_rgb(), 255]),
        'offline': np.array([*discord.Colour.from_str('#747f8d').to_rgb(), 255]),
        'idle': np.array([*discord.Colour.from_str('#faa61a').to_rgb(), 255]),
        'dnd': np.array([*discord.Colour.from_str('#f04747').to_rgb(), 255]),
        None: np.array([255, 255, 255, 255]),
    }

    def __init__(self, bot: HideoutManager) -> None:
        self.bot = bot

    async def async_init(self, user_id: int, show_warning: bool = True):
        self.show_missing_timezone_warning = show_warning
        query = """
            SELECT status, changed_at AT TIME ZONE COALESCE((SELECT timezone FROM user_settings WHERE user_id = $1), 'UTC') AS changed_at
            FROM status_history WHERE user_id = $1
            AND changed_at > NOW() - INTERVAL '30 days'
            ORDER BY changed_at ASC
        """
        self.time_zone_name: str | None = await self.bot.pool.fetchval(
            "SELECT timezone FROM user_settings WHERE user_id = $1", user_id
        )
        time_zone = zoneinfo.ZoneInfo(self.time_zone_name or 'UTC')

        results = await self.bot.pool.fetch(query, user_id)
        if not results:
            return "I do not have any status history for that user..."
        times: list[tuple[str | None, datetime.datetime]] = [(r['status'], r['changed_at']) for r in results]

        self.first = times[0][1].replace(hour=0, minute=0, second=0, microsecond=0)
        self.last = times[-1][1].replace(hour=23, minute=59, second=59, microsecond=9999)

        self.times = (
            [(None, self.first)]
            + times
            + [(times[-1][0], datetime.datetime.now(time_zone).replace(tzinfo=None))]
            + [(None, self.last)]
        )

        self.days = (self.last - self.first).days + 1

        self.HEIGHT = self.days * 25

        self.tz_offset = datetime.datetime.now(time_zone).strftime('UTC%z')

    @staticmethod
    def tripletwise(iterable: Sequence[Any]):
        a, b, c = itertools.tee(iterable, 3)
        next(b, None)
        next(c, None)
        next(c, None)
        return zip(a, b, c)

    @executor_function
    def full_render(self) -> tuple[io.BytesIO, str | None]:
        # at some point, this function should be made cleaner. but for now it works.

        # pyright: reportUnknownMemberType=false
        array = np.zeros((self.HEIGHT, self.WIDTH, 4))
        font = ImageFont.truetype('assets/fonts/Oswald-SemiBold.ttf', 19)

        canvas = Image.new('RGB', size=(self.WIDTH + 100, self.HEIGHT + 25), color='white')
        canvas_draw = ImageDraw.Draw(canvas)

        lines_overlay = Image.new('RGBA', size=(self.WIDTH, self.HEIGHT), color=(0, 0, 0, 0))
        lines_draw = ImageDraw.Draw(lines_overlay)

        for i in range(24):
            lines_draw.line(
                [(int(i * self.WIDTH / 24), 0), (int(i * self.WIDTH / 24), self.HEIGHT)],
                fill=(50, 50, 50, 128),
                width=3,
            )
            canvas_draw.text(((i * (self.WIDTH / 24)) + 98, -3), f'|{i:0>2}', fill='black', font=font)

        canvas_draw.text((2, -3), self.tz_offset, fill='black', font=font)

        for (yesterday_color, yesterday), (color, today), (next_color, tomorrow) in self.tripletwise(self.times):
            length = seconds_to_px((tomorrow - today).total_seconds())
            initial = seconds_to_px(today.second + (today.minute * 60) + (today.hour * 60 * 60))
            day = (today - self.first).days

            if (yesterday - self.first).days < day or yesterday_color is None:
                # This is to fill the first portion, and add dates.
                array[day * 25 : (day + 1) * 25, : initial + 10] = self.STATUS_COLORS_MAP[yesterday_color]
                canvas_draw.text((2, (day + 1) * 25 - 3), today.strftime('%a %d %b'), fill='black', font=font)

            array[day * 25 : (day + 1) * 25, initial : initial + length + 10] = self.STATUS_COLORS_MAP[color]

            if next_color is None:
                array[day * 25 : (day + 1) * 25, initial : self.WIDTH] = self.STATUS_COLORS_MAP[None]

        buffer = io.BytesIO()
        arr = array.astype(np.uint8)
        image = Image.fromarray(arr).convert('RGB')
        canvas.paste(image, (100, 25))
        canvas.paste(lines_overlay, (100, 25), lines_overlay)
        canvas.save(buffer, format='PNG')
        buffer.seek(0)

        message = None
        if self.time_zone_name:
            message = f"User's time zone: `{self.time_zone_name}`"
        elif self.show_missing_timezone_warning:
            message = "You don't have a time zone set! Use /set-timezone to set it and display your calendar at your local time zone."

        return buffer, message


class CalendarStatusCog(HideoutCog):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.processed: cachetools.LRUCache[str, list[app_commands.Choice[str]]] = cachetools.LRUCache(maxsize=200)

    @commands.hybrid_command(name='calendar-status', aliases=('calendarstatus', 'cs'))
    @app_commands.describe(user='The user whose calendar you wish to get.')
    async def calendar_status(self, ctx: HideoutContext, user: discord.Member | discord.User = commands.Author):
        """Gets yours or another user's calendar status log."""
        os.system('cls')
        async with ctx.typing():

            status = CalendarStatus(self.bot)
            error = await status.async_init(user.id, show_warning=ctx.author == user)
            if error:
                return await ctx.send(error)
            image, content = await status.full_render()
            return await ctx.send(content, file=discord.File(image, filename=f'{user.id}-status-history.png'))

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
            dt.strftime("It is `%A, %B %d %Y at %I:%M %p` for **{}** ({})").format(
                discord.utils.escape_markdown(user.display_name), tz_name
            )
        )
