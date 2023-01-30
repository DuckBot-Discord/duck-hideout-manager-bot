import discord
from discord.ext import commands

from utils import HideoutContext, SilentCommandError
from utils.constants import COUNSELORS_ROLE, DUCK_HIDEOUT, PIT_CATEGORY


def pit_owner_only():
    async def predicate(ctx: HideoutContext):
        if await ctx.bot.is_owner(ctx.author):
            return True

        if (
            isinstance(ctx.channel, (discord.DMChannel, discord.GroupChannel, discord.PartialMessageable))
            or ctx.guild.id != DUCK_HIDEOUT
            or ctx.channel.category_id != PIT_CATEGORY
        ):
            raise SilentCommandError

        channel_id = await ctx.bot.pool.fetchval('SELECT pit_id FROM pits WHERE pit_owner = $1', ctx.author.id)
        if ctx.channel.id != channel_id:
            raise SilentCommandError
        return True

    return commands.check(predicate)


def hideout_only():
    def predicate(ctx: HideoutContext):
        if ctx.guild and ctx.guild.id == DUCK_HIDEOUT:
            return True
        raise SilentCommandError

    return commands.check(predicate)


def counselor_only():
    def predicate(ctx: HideoutContext):
        if not isinstance(ctx.author, discord.Member):
            return False
        if ctx.guild.get_role(COUNSELORS_ROLE) in ctx.author.roles:
            return True
        raise SilentCommandError

    return commands.check(predicate)
