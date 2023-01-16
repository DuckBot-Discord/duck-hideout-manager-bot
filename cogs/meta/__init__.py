from bot import HideoutManager
from .embed import EmbedMaker
from .help import Help
from .tags import Tags
from .botinfo import BotInformation


class Information(EmbedMaker, Help, Tags, BotInformation):
    """Commands meant to display information."""


async def setup(bot: HideoutManager):
    await bot.add_cog(Information(bot))
