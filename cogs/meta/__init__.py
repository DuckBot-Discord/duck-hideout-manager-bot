from bot import HideoutManager

from .bot_related import BotInformation
from .embed import EmbedMaker
from .help import Help
from .tags import Tags


class Information(EmbedMaker, Help, Tags, BotInformation):
    """Commands meant to display information."""


async def setup(bot: HideoutManager):
    await bot.add_cog(Information(bot))
