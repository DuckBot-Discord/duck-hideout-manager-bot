from __future__ import annotations

import re
from typing import Any, Generic, Tuple, Type, TypeVar

import discord
from discord.ext import commands

from .bot_bases.context import HideoutContext

BET = TypeVar('BET', bound='discord.guild.BanEntry')
FCT = TypeVar('FCT', bound='commands.FlagConverter')
CT = TypeVar('CT', bound='commands.Converter[Any]')
T = TypeVar('T')

__all__: Tuple[str, ...] = ('UntilFlag',)


class UntilFlag(Generic[T, FCT]):
    """A converter that will convert until a flag is reached.

    **Example**

    .. code-block:: python3

        from typing import Optional

        from discord.ext import commands

        class SendFlags(commands.commands.FlagConverter, prefix='--', delimiter=' '):
            channel: Optional[discord.TextChannel] = None
            reply: Optional[discord.Message] = None

        @commands.command()
        async def send(self, ctx: HideoutContext, *, text: UntilFlag[SendFlags]):
            '''Send a message to a channel.'''
            channel = text.flags.channel or ctx.channel
            await channel.send(text.value)

    Attributes
    ----------
    value: :class:`str`
        The value of the converter.
    flags: :class:`commands.FlagConverter`
        The resolved flags.
    """

    def __init__(self, value: T, converter: Type[T], flags: FCT) -> None:
        # fmt: off
        self.value = value
        self.flags = flags

        if hasattr(converter, '__metadata__'):
            # Annotated[X, Y] can access Y via __metadata__
            converter = converter.__metadata__[0]  # type: ignore

        self._converter: Type[T] = converter
        self._regex: re.Pattern[str] = self.flags.__commands_flag_regex__  # pyright: ignore[reportUnknownMemberType=false, reportGeneralTypeIssues]
        self._start: str = (self.flags.__commands_flag_prefix__)  # pyright: ignore[reportUnknownMemberType=false, reportGeneralTypeIssues]

    def __class_getitem__(cls, item: Tuple[Type[T], Type[commands.FlagConverter]]) -> UntilFlag[T, FCT]:
        converter, flags = item
        return cls(value='...', flags=flags(), converter=converter)

    def validate_value(self, argument: str) -> bool:
        """Used to validate the parsed value without flags.
        Defaults to checking if the argument is a valid string.

        If overridden, this method should return a boolean or raise an error.
        Can be a coroutine

        Parameters
        ----------
        argument: :class:`str`
            The argument to validate.

        Returns
        -------
        :class:`str`
            Whether or not the argument is valid.

        Raises
        ------
        :class:`commands.BadArgument`
            No value was given
        """
        stripped = argument.strip()
        if not stripped or stripped.startswith(self._start):
            raise commands.BadArgument(f'No body has been specified before the flags.')
        return True

    async def convert(self, ctx: HideoutContext, argument: str) -> UntilFlag[T, FCT]:
        """|coro|

        The main convert method of the converter. This will take the given flag converter and
        use it to delimit the flags from the value.

        Parameters
        ----------
        ctx: :class:`HideoutContext`
            The context of the command.
        argument: :class:`str`
            The argument to convert.

        Returns
        -------
        :class:`UntilFlag`
            The converted argument.
        """
        value = self._regex.split(argument, maxsplit=1)[0]
        converted_value: T = await commands.run_converters(ctx, self._converter, value, ctx.current_parameter)  # type: ignore

        if not await discord.utils.maybe_coroutine(self.validate_value, argument):
            raise commands.BadArgument('Failed to validate argument preceding flags.')

        flags = await self.flags.convert(ctx, argument=argument[len(value) :])
        return UntilFlag(value=converted_value, flags=flags, converter=self._converter)
