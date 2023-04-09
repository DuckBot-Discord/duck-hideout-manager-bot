from __future__ import annotations

from typing import TYPE_CHECKING, Tuple

from discord.ext import commands

from utils import errors

if TYPE_CHECKING:
    from bot import HideoutManager

    from .bot_bases.context import HideoutContext

__all__: Tuple[str, ...] = ()


async def on_command_error(ctx: HideoutContext, error: Exception) -> None:
    """|coro|

    A handler called when an error is raised while invoking a command.

    Parameters
    ----------
    ctx: :class:`HideoutContext`
        The context for the command.
    error: :class:`commands.CommandError`
        The error that was raised.
    """
    if ctx.is_error_handled is True:
        return

    error = getattr(error, 'original', error)

    ignored = (
        commands.CommandNotFound,
        commands.CheckFailure,
        errors.SilentCommandError,
        errors.EntityBlacklisted,
    )

    if isinstance(error, ignored):
        return
    elif isinstance(error, (commands.UserInputError, errors.HideoutManagerException)):
        await ctx.send(str(error), ephemeral=True)
    elif isinstance(error, commands.CommandInvokeError):
        return await on_command_error(ctx, error.original)
    elif isinstance(error, errors.HideoutManagerNotStarted):
        await ctx.send('Oop! Hideoutbot has not started yet, try again soon.', ephemeral=True)
    else:
        await ctx.bot.exceptions.add_error(error=error, ctx=ctx)


async def setup(bot: HideoutManager):
    """adds the event to the bot

    Parameters
    ----------
    bot: :class:`HideoutManager`
        The bot to add the event to.
    """
    bot.add_listener(on_command_error)
