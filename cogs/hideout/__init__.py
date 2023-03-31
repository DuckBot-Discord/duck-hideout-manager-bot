from bot import HideoutManager

from .addbot import Addbot
from .pits import PitsManagement
from .moderation import Moderation
from .council import CouncilMessages
from .help_forum import HelpForum


class DuckHideout(Addbot, PitsManagement, Moderation, CouncilMessages, HelpForum, name='Duck Hideout Stuff'):
    """Commands PitsManagement to the server, like pits and addbot."""


async def setup(bot: HideoutManager):
    await bot.add_cog(DuckHideout(bot))
