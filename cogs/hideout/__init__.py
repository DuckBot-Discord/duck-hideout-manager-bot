from bot import HideoutManager

from .addbot import Addbot
from .boost_roles import BoostRoles
from .council import CouncilMessages
from .help_forum import HelpForum
from .moderation import Moderation
from .pits import PitsManagement
from .timed_guild_icons import TimedEvents
from .voice import VoiceChatLogs


class DuckHideout(
    Addbot,
    PitsManagement,
    Moderation,
    CouncilMessages,
    HelpForum,
    TimedEvents,
    VoiceChatLogs,
    BoostRoles,
    name='Duck Hideout Stuff',
):
    """Commands about the Duck Hideout the server, like pits and addbot."""


async def setup(bot: HideoutManager):
    await bot.add_cog(DuckHideout(bot))
