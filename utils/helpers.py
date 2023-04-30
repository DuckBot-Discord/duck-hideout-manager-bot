from __future__ import annotations

import asyncio
import logging
import re
import time as time_lib
from datetime import datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Optional, Tuple, TypeVar, Union, Self

import discord
from discord.ext import commands

try:
    from typing import ParamSpec
except ImportError:
    from typing_extensions import ParamSpec

from .errors import *

if TYPE_CHECKING:
    from bot import HideoutManager


T = TypeVar('T')
P = ParamSpec('P')
BET = TypeVar('BET', bound='discord.guild.BanEntry')

CDN_REGEX = re.compile(
    r'(https?://)?(media|cdn)\.discord(app)?\.(com|net)/attachments/'
    r'(?P<channel_id>[0-9]+)/(?P<message_id>[0-9]+)/(?P<filename>[\S]+)'
)
URL_REGEX = re.compile(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*(),]|%[0-9a-fA-F][0-9a-fA-F])+')

__all__: Tuple[str, ...] = (
    'col',
    'mdr',
    'cb',
    'add_logging',
    'format_date',
    'DeleteButton',
    'View',
)


def col(color: int | None = None, /, *, fmt: int = 0, bg: bool = False) -> str:
    """
    Returns the ascii color escape string for the given number.

    :param color: The color number.
    :param fmt: The format number.
    :param bg: Whether to return as a background color
    """
    base = "\u001b["
    if fmt != 0:
        base += "{fmt};"
    if color is None:
        base += "{color}m"
        color = 0
    else:
        if bg is True:
            base += "4{color}m"
        else:
            base += "3{color}m"
    return base.format(fmt=fmt, color=color)


def mdr(entity: Any) -> str:
    """Returns the string of an object with discord markdown removed.

    Parameters
    ----------
    entity: Any
        The object to remove markdown from.

    Returns
    -------
    str
        The string of the object with markdown removed.
    """
    return discord.utils.remove_markdown(discord.utils.escape_mentions(str(entity)))


def cb(text: str, /, *, lang: str = 'py'):
    """Wraps a string into a code-block, and adds zero width
    characters to avoid the code block getting cut off.

    Parameters
    ----------
    text: str
        The text to wrap.
    lang: str
        The code language to use.

    Returns
    -------
    str
        The wrapped text.
    """
    text = text.replace('`', '\u200b`')
    return f'```{lang}\n{text}\n```'


def format_date(date: datetime) -> str:
    """Formats a date to a string in the preferred way.

    Parameters
    ----------
    date: datetime.datetime
        The date to format.

    Returns
    -------
    str
        The formatted date.
    """
    return date.strftime("%b %d, %Y %H:%M %Z")


def add_logging(func: Callable[P, Union[Awaitable[T], T]]) -> Callable[P, Union[Awaitable[T], T]]:
    """
    Used to add logging to a coroutine or function.

    .. code-block:: python3
        >>> async def foo(a: int, b: int) -> int:
        >>>     return a + b

        >>> logger = add_logging(foo)
        >>> result = await logger(1, 2)
        >>> print(result)
        3

        >>> def foo(a: int, b: int) -> int:
        >>>     return a + b

        >>> logger = add_logging(foo)
        >>> result = logger(1, 2)
        >>> print(result)
        3
    """

    async def _async_wrapped(*args: P.args, **kwargs: P.kwargs) -> Awaitable[T]:
        start = time_lib.time()
        result = await func(*args, **kwargs)  # type: ignore
        print(f'{func.__name__} took {time_lib.time() - start:.2f} seconds')

        return result  # type: ignore

    def _sync_wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
        start = time_lib.time()
        result = func(*args, **kwargs)
        print(f'{func.__name__} took {time_lib.time() - start:.2f} seconds')

        return result  # type: ignore

    return _async_wrapped if asyncio.iscoroutinefunction(func) else _sync_wrapped  # type: ignore


class DeleteButtonCallback(discord.ui.Button['DeleteButton']):
    """Internal."""

    async def callback(self, interaction: discord.Interaction) -> Any:
        try:
            if interaction.message:
                await interaction.message.delete()
        finally:
            if self.view:
                self.view.stop()


class View(discord.ui.View):
    def __new__(cls, *args: Any, **kwargs: Any):
        self = super().__new__(cls)
        self.on_timeout = cls._wrap_timeout(self)
        return self

    def __init__(self, *, timeout: Optional[float] = 180, bot: Optional[HideoutManager] = None):
        super().__init__(timeout=timeout)
        self.bot: Optional[HideoutManager] = bot
        if bot:
            bot.views.add(self)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item[Any]) -> None:
        bot: HideoutManager = interaction.client  # type: ignore
        await bot.exceptions.add_error(error=error)
        if interaction.response.is_done():
            await interaction.followup.send(f"Sorry! something went wrong....", ephemeral=True)
        else:
            await interaction.response.send_message(f"Sorry! something went wrong....", ephemeral=True)

    def stop(self) -> None:
        if self.bot:
            self.bot.views.discard(self)
        return super().stop()

    @classmethod
    def _wrap_timeout(cls, self: Self):
        original_on_timeout = self.on_timeout

        async def on_timeout():
            if self.bot:
                self.bot.views.discard(self)
            await original_on_timeout()

        return on_timeout

    def __del__(self) -> None:
        if self.bot:
            self.bot.views.discard(self)


class DeleteButton(discord.ui.View):
    """
    A button that deletes the message.

    Parameters
    ----------
    message: :class:`discord.Message`
        The message to delete.
    author: :class:`discord.Member`
        The person who can interact with the button.
    style: :class:`discord.ButtonStyle`
        The style of the button. Defaults to red.
    label: :class:`str`
        The label of the button. Defaults to 'Delete'.
    emoji: :class:`str`
        The emoji of the button. Defaults to None.
    """

    def __init__(self, *args: Any, **kwargs: Any):
        self.bot: Optional[HideoutManager] = None
        self._message = kwargs.pop('message', None)
        self.author = kwargs.pop('author')
        self.delete_on_timeout = kwargs.pop('delete_on_timeout', True)

        super().__init__(timeout=kwargs.pop('timeout', 180))

        self.add_item(
            DeleteButtonCallback(
                style=kwargs.pop('style', discord.ButtonStyle.red),
                label=kwargs.pop('label', 'Delete'),
                emoji=kwargs.pop('emoji', None),
            )
        )
        if isinstance(self.bot, commands.Bot):
            self.bot.views.add(self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Checks if the user is the right one."""
        return interaction.user == self.author

    async def on_timeout(self) -> None:
        """Deletes the message on timeout."""
        if self.message:
            try:
                if self.delete_on_timeout:
                    await self.message.delete()
                else:
                    await self.message.edit(view=None)
            except discord.HTTPException:
                pass
        if self.bot:
            self.bot.views.discard(self)

    def stop(self) -> None:
        """Stops the view."""
        if self.bot:
            self.bot.views.discard(self)
        super().stop()

    @property
    def message(self) -> Optional[discord.Message]:
        """The message to delete."""
        return self._message

    @message.setter
    def message(self, message: discord.Message) -> None:
        self._message = message
        try:
            self.bot = message._state._get_client()  # type: ignore
        except Exception as e:
            logging.error(f'Failed to get client from message %s: %s', message, exc_info=e)

    @classmethod
    async def to_destination(
        cls, destination: discord.abc.Messageable | discord.Webhook, *args: Any, **kwargs: Any
    ) -> 'DeleteButton':
        if kwargs.get('view', None):
            raise TypeError('Cannot pass a view to to_destination')

        view = cls(
            style=kwargs.pop('style', discord.ButtonStyle.red),
            label=kwargs.pop('label', 'Delete'),
            emoji=kwargs.pop('emoji', None),
            author=kwargs.pop('author'),
            timeout=kwargs.pop('timeout', 180),
            delete_on_timeout=kwargs.pop('delete_on_timeout', True),
        )
        message = await destination.send(*args, **kwargs, view=view)
        view.message = message

        if view.bot:
            view.bot.views.add(view)

        return view
