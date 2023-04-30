from bot import HideoutManager
from .minesweeper import Minesweeper


class Games(Minesweeper):
    """Discord Games, fun!"""


async def setup(bot: HideoutManager):
    await bot.add_cog(Games(bot))
