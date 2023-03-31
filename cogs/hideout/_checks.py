import discord
from discord.ext import commands

from utils import HideoutContext, HideoutGuildContext, SilentCommandError
from utils.constants import COUNSELORS_ROLE, DUCK_HIDEOUT, PIT_CATEGORY, HELP_FORUM


def pit_owner_only():
    async def predicate(ctx: HideoutGuildContext):
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
    def predicate(ctx: HideoutGuildContext):
        if ctx.guild and ctx.guild.id == DUCK_HIDEOUT:
            return True
        raise SilentCommandError

    return commands.check(predicate)


def counselor_only():
    def predicate(ctx: HideoutContext):
        if not isinstance(ctx.author, discord.Member) or not ctx.guild:
            return False
        if ctx.guild.get_role(COUNSELORS_ROLE) in ctx.author.roles:
            return True
        raise SilentCommandError

    return commands.check(predicate)


def is_help_forum_post():
    def predicate(ctx: HideoutGuildContext):
        if not ctx.guild:
            raise commands.NoPrivateMessage
        if not isinstance(ctx.channel, discord.Thread) or ctx.channel.parent_id != HELP_FORUM:
            raise SilentCommandError
        return True

    return commands.check(predicate)


def can_solve_thread(ctx: HideoutGuildContext):
    assert isinstance(ctx.channel, discord.Thread)

    perms = ctx.channel.permissions_for(ctx.author)
    return perms.manage_messages or ctx.channel.owner_id == ctx.author.id
