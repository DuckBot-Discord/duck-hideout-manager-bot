# TODO: make stub files for `aggdraw`, `PIL` and `colorthief` to be strict-compatible.
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportMissingTypeStubs=false

import io
import itertools
from datetime import datetime as dt
from datetime import timedelta as td
from typing import NamedTuple

import aggdraw
import asyncpg
import discord
from colorthief import ColorThief
from discord import app_commands
from discord.ext import commands
from jishaku.functools import executor_function
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from utils import HideoutCog, HideoutContext


class ImageThief(ColorThief):
    def __init__(self, image: Image.Image) -> None:
        self.image = image


class DatabaseData(NamedTuple):
    times: list[tuple[dt, str]] | list[asyncpg.Record]
    rank: int
    max: int
    message_count: int
    edit_count: int
    delete_count: int
    bots_added: int
    requested: int


class ProfileCard:
    # Options
    WIDTH = 1200
    HEIGHT = 400
    STATUSBAR_HEIGHT = 25
    OVERALL_PADDING = 50
    AVATAR_BORDER_MARGIN = 10
    LEFT_TEXT_PADDING_L = 25
    AUTHOR_NAME_PADDING_RIGHT = 50
    BOTTOM_CORNER_FONT_PADDING = 50

    DROP_SHADOW_OFFSET = (3, 3)
    DROP_SHADOW_ITERATIONS = 15
    DROP_SHADOW_EXTRA_SIZE = 10

    # Calculations
    AVATAR_SIZE = HEIGHT - STATUSBAR_HEIGHT - ((OVERALL_PADDING + AVATAR_BORDER_MARGIN) * 2)
    AVATAR_BORDER_SIZE = HEIGHT - STATUSBAR_HEIGHT - (OVERALL_PADDING * 2)

    SECONDARY_COLOR = (165, 165, 165)
    BG_COLOR = discord.Color.from_str('#1b1d21')

    # constants
    STATUS_COLORS = {
        'online': discord.Colour.from_str('#43b581'),
        'offline': discord.Colour.from_str('#747f8d'),
        'idle': discord.Colour.from_str('#faa61a'),
        'dnd': discord.Colour.from_str('#f04747'),
    }

    def __init__(self, author: discord.abc.User) -> None:
        self.username_width: int = 0
        self.username_height: int = 0
        self.secondary_height: int = 0
        self.secondary_width: int = 0
        self.author: discord.abc.User = author
        self._data: DatabaseData | None = None
        self._avatar: bytes | None = None
        self.now = discord.utils.utcnow()
        self.canvas = Image.new('RGB', (self.WIDTH, self.HEIGHT), self.BG_COLOR.to_rgb())
        self.draw = ImageDraw.Draw(self.canvas)

    async def async_init(self, pool: asyncpg.Pool[asyncpg.Record]):
        # status info
        status_q = 'SELECT changed_at, status FROM status_history WHERE user_id = $1 ORDER BY changed_at DESC'
        status_f = await pool.fetch(status_q, self.author.id)

        self._avatar = await self.author.display_avatar.read()

        # Total messages and rank
        message_q = """
        WITH retained AS (
            SELECT author_id, COUNT(*) AS message_count FROM message_info WHERE deleted = FALSE AND is_bot = $2 GROUP BY author_id ORDER BY message_count DESC
        ),
        ranked AS (
            SELECT author_id, message_count, row_number() over () AS rank FROM retained
        )
        SELECT 
            (SELECT message_count FROM ranked WHERE author_id = $1), 
            (SELECT rank FROM ranked WHERE author_id = $1), 
            (SELECT COUNT(*) FROM message_info WHERE edited_at NOTNULL AND author_id = $1) AS edit_count,
            (SELECT COUNT(*) FROM message_info WHERE deleted = TRUE AND author_id = $1) AS edit_count,
            (SELECT COUNT(*) FROM ranked)
        """
        message_f = await pool.fetchrow(message_q, self.author.id, self.author.bot)
        if message_f:
            count, rank, edit_count, deleted, max = message_f
        else:
            count = rank = max = edit_count = deleted = 0

        # Bots added
        bots_q = """SELECT
            (SELECT COUNT(*) FROM addbot WHERE owner_id = $1 AND added = TRUE) AS added,
            (SELECT COUNT(*) FROM addbot WHERE owner_id = $1) as requested;"""
        bots_f = await pool.fetchrow(bots_q, self.author.id)
        if bots_f:
            added, requested = bots_f
        else:
            added = requested = 0
        self._data = DatabaseData(
            times=status_f,
            message_count=count or 0,
            rank=rank or 0,
            max=max or 0,
            edit_count=edit_count,
            delete_count=deleted,
            bots_added=added,
            requested=requested,
        )

    @property
    def data(self) -> DatabaseData:
        if not self._data:
            raise RuntimeError('Class not initialized, please call :coro:`.async_init`')
        return self._data

    @property
    def avatar(self) -> bytes:
        if not self._avatar:
            raise RuntimeError('Class not initialized, please call :coro:`.async_init`')
        return self._avatar

    @executor_function
    def full_render(self) -> io.BytesIO:
        buffer = io.BytesIO()
        self.paste_status_bar()
        self.paste_avatar()
        self.draw_avatar_border()
        self.draw_user_name()
        self.draw_secondary_text()
        corners = self.add_corners(
            self.canvas, self.STATUSBAR_HEIGHT - self.STATUSBAR_HEIGHT // 8, top_radius=self.OVERALL_PADDING
        )
        corners.save(buffer, format='PNG')
        buffer.seek(0)
        return buffer

    # Math functions
    def seconds_to_px(self, seconds: int) -> int:
        return int(seconds / (3600 * 24) * self.WIDTH)

    def calc_size(self, time: dt, color: str | None, now: dt, next_status: dt) -> tuple[int, int, discord.Colour]:
        assert color is not None
        x_seconds_from_right = int((now - time).total_seconds())
        x_seconds_width = x_seconds_from_right - int((now - next_status).total_seconds())
        return (
            self.WIDTH - self.seconds_to_px(x_seconds_from_right),
            self.seconds_to_px(x_seconds_width),
            self.STATUS_COLORS[color],
        )

    # Image modifiers
    def add_corners(self, image: Image.Image, radius: int, top_radius: int | None = None):
        """generate round corner for image"""  # Src: StackOverflow
        if top_radius is None:
            top_radius = radius
        mask = Image.new('L', image.size)  # filled with black by default
        draw = aggdraw.Draw(mask)
        brush = aggdraw.Brush('white')
        width, height = mask.size
        # upper-left corner
        draw.pieslice((0, 0, top_radius * 2, top_radius * 2), 90, 180, None, brush)
        # upper-right corner
        draw.pieslice((width - top_radius * 2, 0, width, top_radius * 2), 0, 90, None, brush)
        # bottom-left corner
        draw.pieslice((0, height - radius * 2, radius * 2, height), 180, 270, None, brush)
        # bottom-right corner
        draw.pieslice((width - radius * 2, height - radius * 2, width, height), 270, 360, None, brush)
        # center rectangle
        draw.rectangle((radius, radius, width - radius, height - radius), brush)

        # four edge rectangle
        draw.rectangle((top_radius, 0, width - top_radius, top_radius), brush)
        draw.rectangle((0, top_radius, top_radius, height - radius), brush)
        draw.rectangle((radius, height - radius, width - radius, height), brush)
        draw.rectangle((width - top_radius, top_radius, width, height - radius), brush)
        draw.flush()
        image = image.convert('RGBA')
        image.putalpha(mask)
        return image

    # Image generations
    def paste_status_bar(self):
        canvas = Image.new('RGBA', (self.WIDTH, self.STATUSBAR_HEIGHT), "white")
        draw = ImageDraw.Draw(canvas)
        ret: list[tuple[int, int, discord.Colour]] = []
        for (next, _), (current, status) in itertools.pairwise([(self.now, None)] + list(self.data.times)):
            offset, width, color = self.calc_size(current, status, self.now, next)
            ret.append((offset, width, color))
            if current < self.now - td(days=1):
                break
        else:
            try:
                ret.append((0, offset, color))  # type: ignore
            except NameError:
                ret.append((0, self.WIDTH, self.STATUS_COLORS['offline']))

        for offset, width, color in ret:
            draw.rectangle(((offset, 0), (offset + width, self.STATUSBAR_HEIGHT)), fill=(color.r, color.g, color.b))

        with Image.open('assets/images/profile/status_bar_fore.png') as fore:
            canvas.paste(fore, (0, 0), fore)

        self.canvas.paste(canvas, (0, self.HEIGHT - self.STATUSBAR_HEIGHT))

    def paste_avatar(self):
        avatar = Image.open(io.BytesIO(self.avatar))
        avatar = self.add_corners(avatar.resize((self.AVATAR_SIZE, self.AVATAR_SIZE)), self.AVATAR_SIZE // 6)
        position = (self.AVATAR_BORDER_MARGIN + self.OVERALL_PADDING, self.AVATAR_BORDER_MARGIN + self.OVERALL_PADDING)
        self.canvas.paste(avatar, position, avatar)

    def draw_avatar_border(self):
        color = ImageThief(Image.open(io.BytesIO(self.avatar))).get_color(quality=1)

        size = self.AVATAR_BORDER_SIZE

        border = Image.new('RGBA', (size, size), color)

        mask = Image.open('assets/images/profile/avatar_alphamask.png').resize((size, size)).convert('L')
        border.putalpha(mask)

        shadow = self.cached_drop_shadow()
        self.canvas.paste(shadow, (0, 0), shadow)
        self.canvas.paste(border, (self.OVERALL_PADDING, self.OVERALL_PADDING), border)

    def cached_drop_shadow(self) -> Image.Image:
        stem = "assets/images/profile/shadows/"
        filename = f"DS-{self.AVATAR_BORDER_SIZE}-{self.DROP_SHADOW_ITERATIONS}-{self.DROP_SHADOW_OFFSET}.png"
        try:
            return Image.open(stem + filename)
        except FileNotFoundError:
            pass

        size = self.AVATAR_BORDER_SIZE

        border = Image.new('RGBA', (size, size), 'black')
        mask = Image.open('assets/images/profile/avatar_alphamask.png').resize((size, size)).convert('L')
        border.putalpha(mask)

        width = size + abs(self.DROP_SHADOW_OFFSET[0]) + 2 * self.DROP_SHADOW_EXTRA_SIZE + self.OVERALL_PADDING
        height = size + abs(self.DROP_SHADOW_OFFSET[1]) + 2 * self.DROP_SHADOW_EXTRA_SIZE + self.OVERALL_PADDING

        shadow = Image.new('RGBA', (width, height), (0, 0, 0, 0))

        left = max(self.DROP_SHADOW_OFFSET[0], 0) + self.OVERALL_PADDING
        top = max(self.DROP_SHADOW_OFFSET[1], 0) + self.OVERALL_PADDING

        shadow.paste(border, (left, top), border)

        for _ in range(self.DROP_SHADOW_ITERATIONS):
            shadow = shadow.filter(ImageFilter.BLUR)

        shadow.save(stem + filename)
        return shadow

    def draw_user_name(self):
        # Add user name
        text_pos = (self.AVATAR_BORDER_SIZE + self.OVERALL_PADDING + self.LEFT_TEXT_PADDING_L, self.OVERALL_PADDING)
        if self.author.display_name == self.author.name:
            font = ImageFont.truetype('assets/fonts/Oswald-SemiBold.ttf', 60)
            for i in range(60, 0, -1):
                _, _, textx, texty = self.draw.textbbox((0, 0), str(self.author), font=font)
                self.username_width = textx
                self.username_height = texty
                if textx < self.WIDTH - text_pos[0] - self.AUTHOR_NAME_PADDING_RIGHT:
                    break
                font = ImageFont.truetype('assets/fonts/Oswald-SemiBold.ttf', i)

            self.draw.text(text_pos, str(self.author), font=font)
        else:
            font = ImageFont.truetype('assets/fonts/Oswald-SemiBold.ttf', 60)
            textx = 0
            texty = 60
            for i in range(60, 25, -1):
                _, _, textx, texty = self.draw.textbbox((0, 0), str(self.author.display_name), font=font)
                if textx <= self.WIDTH - text_pos[0] - self.AUTHOR_NAME_PADDING_RIGHT:
                    break
                font = ImageFont.truetype('assets/fonts/Oswald-SemiBold.ttf', i)

            self.username_width = textx
            self.username_height = texty
            self.draw.text(text_pos, str(self.author.display_name), font=font)

            base_textx = textx

            text_pos = (
                self.AVATAR_BORDER_SIZE + self.OVERALL_PADDING + self.LEFT_TEXT_PADDING_L,
                self.OVERALL_PADDING + texty,
            )
            font = ImageFont.truetype('assets/fonts/Oswald-SemiBold.ttf', 60)
            for i in range(60, 25, -1):
                _, _, textx, texty = self.draw.textbbox((0, 0), str(self.author), font=font)
                if textx <= base_textx:
                    break
                font = ImageFont.truetype('assets/fonts/Oswald-SemiBold.ttf', i)
            self.secondary_height = textx
            self.secondary_width = texty
            self.draw.text(text_pos, str(self.author), fill=self.SECONDARY_COLOR, font=font)

    def draw_secondary_text(self):
        top_text = f"RANK #{self.data.rank}"
        bottom_text = f"OUT OF {self.data.max} {'BOTS' if self.author.bot else 'USERS'}"

        # Top text (tt)
        ttfont = ImageFont.truetype('assets/fonts/Oswald-SemiBold.ttf', 60)
        _, _, ttx, tty = self.draw.textbbox((0, 0), top_text, font=ttfont)

        # Bottom Text (bt) needs font calculation
        btfont = ImageFont.truetype('assets/fonts/Oswald-SemiBold.ttf', 60)
        btx = 0
        bty = 0
        for i in range(59, 25, -1):
            _, _, btx, bty = self.draw.textbbox((0, 0), bottom_text, font=btfont)
            if btx <= ttx:
                break
            btfont = ImageFont.truetype('assets/fonts/Oswald-SemiBold.ttf', i)

        padl = self.AVATAR_BORDER_SIZE + self.OVERALL_PADDING + self.LEFT_TEXT_PADDING_L
        baseh = self.AVATAR_BORDER_SIZE + self.OVERALL_PADDING

        self.draw.text((padl, baseh - tty - bty), top_text, 'white', font=ttfont)
        self.draw.text((padl, baseh - bty), bottom_text, font=btfont, fill=self.SECONDARY_COLOR)

        # Left side text stack
        height = baseh
        to_rm = bty
        width = self.WIDTH - self.BOTTOM_CORNER_FONT_PADDING

        text = f"{self.data.delete_count:,} MESSAGES DELETED"
        _, _, msx, _ = self.draw.textbbox((0, 0), text, font=btfont)
        height -= to_rm
        self.draw.text((width - msx, height), text, font=btfont, fill=self.SECONDARY_COLOR)

        text = f"{self.data.edit_count:,} MESSAGES EDITED"
        _, _, msx, _ = self.draw.textbbox((0, 0), text, font=btfont)
        height -= to_rm
        self.draw.text((width - msx, height), text, font=btfont, fill=self.SECONDARY_COLOR)

        text = f"{self.data.message_count:,} MESSAGES SENT"
        _, _, msx, _ = self.draw.textbbox((0, 0), text, font=btfont)
        height -= to_rm
        self.draw.text((width - msx, height), text, font=btfont, fill=self.SECONDARY_COLOR)

        if self.data.requested:
            height -= to_rm // 3

            text = f"{self.data.bots_added} BOTS JOINED"
            _, _, msx, _ = self.draw.textbbox((0, 0), text, font=btfont)
            height -= to_rm
            self.draw.text((width - msx, height), text, font=btfont, fill=self.SECONDARY_COLOR)

            text = f"{self.data.requested} BOTS REQUESTED"
            _, _, msx, _ = self.draw.textbbox((0, 0), text, font=btfont)
            height -= to_rm
            self.draw.text((width - msx, height), text, font=btfont, fill=self.SECONDARY_COLOR)

        # Status text
        text = f"LAST 24 HOURS OF STATUS:"
        font = ImageFont.truetype('assets/fonts/Oswald-SemiBold.ttf', 22)
        _, _, _, msy = self.draw.textbbox((0, 0), text, font=font)
        self.draw.text((3, self.HEIGHT - self.STATUSBAR_HEIGHT - msy - 2), text, font=font, fill=self.SECONDARY_COLOR)

        text = f"NOW"
        _, _, msx, msy = self.draw.textbbox((0, 0), text, font=font)
        self.draw.text(
            (self.WIDTH - msx - 3, self.HEIGHT - self.STATUSBAR_HEIGHT - msy - 2), text, font=font, fill=self.SECONDARY_COLOR
        )


class ProfileCardCog(HideoutCog):
    @commands.hybrid_command()
    @app_commands.describe(user='The user whose profile you wish to get.')
    async def profile(self, ctx: HideoutContext, user: discord.Member | discord.User = commands.Author):
        """Shows your or someone else's profile."""
        async with ctx.typing():
            card = ProfileCard(user)
            await card.async_init(ctx.bot.pool)
            buffer = await card.full_render()
            await ctx.send(file=discord.File(buffer, filename='card.png'))
