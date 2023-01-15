from bot import HideoutManager
from .pits import PitsManagement
from .addbot import Addbot


class DuckHideout(Addbot, PitsManagement, name='Duck Hideout Stuff'):
    """Commands PitsManagement to the server, like pits and addbot."""


async def setup(bot: HideoutManager):
    await bot.add_cog(DuckHideout(bot))
