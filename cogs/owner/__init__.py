from traceback import format_exception

from discord.ext import commands

from bot import HideoutManager
from utils import HideoutContext, cb

from .sql import SQLCommands


class Owner(
    SQLCommands,
    command_attrs=dict(hidden=True),
):
    """The Cog for All owner commands."""

    async def cog_check(self, ctx: HideoutContext) -> bool:  # pyright: reportIncompatibleMethodOverride=false
        """Check if the user is a bot owner."""
        if await ctx.bot.is_owner(ctx.author):
            return True
        raise commands.NotOwner

    @commands.command()
    async def rall(self, ctx: HideoutContext):
        paginator = commands.Paginator(prefix='', suffix='')
        for extension in list(self.bot.extensions.keys()):
            try:
                await self.bot.reload_extension(extension)
                paginator.add_line(f"\N{CLOCKWISE RIGHTWARDS AND LEFTWARDS OPEN CIRCLE ARROWS} `{extension}`")

            except Exception as e:
                if isinstance(e, commands.ExtensionFailed):
                    e = e.original
                paginator.add_line(f'\N{WARNING SIGN} Failed to load extension: `{extension}`', empty=True)
                error = ''.join(format_exception(type(e), e, e.__traceback__))
                paginator.add_line(cb(error))

        for page in paginator.pages:
            await ctx.send(page)


async def setup(bot: HideoutManager):
    await bot.add_cog(Owner(bot))
