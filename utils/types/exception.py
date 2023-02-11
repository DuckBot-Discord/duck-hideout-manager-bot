from __future__ import annotations

from typing import TYPE_CHECKING, Optional, TypedDict, Any

if TYPE_CHECKING:
    import datetime

    from discord import app_commands
    from discord.ext import commands


class HideoutTracebackOptional(TypedDict, total=False):
    author: int
    guild: Optional[int]
    channel: int
    command: Optional[commands.Command[Any, ..., Any] | app_commands.Command[Any, ..., Any] | app_commands.ContextMenu]


class HideoutTraceback(HideoutTracebackOptional):
    time: datetime.datetime
    exception: Exception
