from __future__ import annotations

from typing import TYPE_CHECKING, Any, Tuple

from discord.ext import commands

from .errors import *

if TYPE_CHECKING:
    from bot import HideoutManager

__all__: Tuple[str, ...] = ('HideoutCog',)


class HideoutCog(commands.Cog):
    """The base class for all HideoutManager cogs.

    Attributes
    ----------
    bot: HideoutManager
        The bot instance.
    """

    __slots__: Tuple[str, ...] = ('bot',)

    def __init__(self, bot: HideoutManager, *args: Any, **kwargs: Any) -> None:
        self.bot: HideoutManager = bot

        next_in_mro = next(iter(self.__class__.__mro__))
        if hasattr(next_in_mro, '__is_jishaku__') or isinstance(next_in_mro, self.__class__):
            kwargs['bot'] = bot

        super().__init__(*args, **kwargs)
