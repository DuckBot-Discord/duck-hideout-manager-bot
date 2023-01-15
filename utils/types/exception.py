from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    TypedDict,
    Optional,
)

if TYPE_CHECKING:
    from discord.ext import commands
    import datetime


class _HideoutTracebackOptional(TypedDict, total=False):
    author: int
    guild: Optional[int]
    channel: int
    command: Optional[commands.Command]


class HideoutTraceback(_HideoutTracebackOptional):
    time: datetime.datetime
    exception: Exception
