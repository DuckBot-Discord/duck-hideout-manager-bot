from bot import HideoutManager

from .addbot import Addbot
from .pits import PitsManagement


class DuckHideout(Addbot, PitsManagement, name='Duck Hideout Stuff'):
    """Commands PitsManagement to the server, like pits and addbot."""


async def setup(bot: HideoutManager):
    await bot.add_cog(DuckHideout(bot))
