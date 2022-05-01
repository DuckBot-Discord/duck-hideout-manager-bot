from __future__ import annotations

from typing import TYPE_CHECKING

from .block import Block
from .standard import StandardModeration

if TYPE_CHECKING:
    from bot import DuckBot


class Moderation(
    StandardModeration,
    Block,
    emoji='\N{HAMMER AND PICK}',
    brief='Moderation commands!',
):
    """Moderation commands."""


async def setup(bot: DuckBot):
    await bot.add_cog(Moderation(bot))
