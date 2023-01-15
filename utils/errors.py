from __future__ import annotations

import logging
import typing
from typing import (
    Tuple,
)

import discord
from discord.ext.commands import CommandError, CheckFailure

log = logging.getLogger('Duckbot.utils.errors')

__all__: Tuple[str, ...] = (
    'DuckBotException',
    'DuckBotCommandError',
    'DuckBotNotStarted',
    'TimerError',
    'TimerNotFound',
    'SilentCommandError',
    'EntityBlacklisted',
    'ActionNotExecutable'
)


class DuckBotException(discord.ClientException):
    """The base exception for DuckBot. All other exceptions should inherit from this."""

    __slots__: Tuple[str, ...] = ()


class DuckBotCommandError(CommandError, DuckBotException):
    """The base exception for DuckBot command errors."""

    __slots__: Tuple[str, ...] = ()


class DuckBotNotStarted(DuckBotException):
    """An exeption that gets raised when a method tries to use :attr:`Duckbot.user` before
    DuckBot is ready.
    """

    __slots__: Tuple[str, ...] = ()

class ActionNotExecutable(DuckBotCommandError):
    def __init__(self, message):
        super().__init__(f'{message}')


class TimerError(DuckBotException):
    """The base for all timer base exceptions. Every Timer based error should inherit
    from this.
    """

    __slots__: Tuple[str, ...] = ()


class TimerNotFound(TimerError):
    """Raised when trying to fetch a timer that does not exist."""

    __slots__: Tuple[str, ...] = ('id',)

    def __init__(self, id: int) -> None:
        self.id: int = id
        super().__init__(f'Timer with ID {id} not found.')

class SilentCommandError(DuckBotCommandError):
    """This exception will be purposely ignored by the error handler
    and will not be logged. Handy for stopping something that can't
    be stopped with a simple ``return`` statement.
    """

    __slots__: Tuple[str, ...] = ()


class EntityBlacklisted(CheckFailure, DuckBotCommandError):
    """Raised when an entity is blacklisted."""

    __slots__: Tuple[str, ...] = ('entity',)

    def __init__(
        self,
        entity: typing.Union[
            discord.User,
            discord.Member,
            discord.Guild,
            discord.abc.GuildChannel,
        ],
    ) -> None:
        self.entity = entity
        super().__init__(f'{entity} is blacklisted.')
