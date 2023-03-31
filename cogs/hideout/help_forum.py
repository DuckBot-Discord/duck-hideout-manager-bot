from typing import Sequence

import discord
from discord.ext import commands

from utils import HideoutCog, HideoutGuildContext, SOLVED_TAG

from ._checks import is_help_forum_post, can_solve_thread


class HelpForum(HideoutCog):
    async def solve_thread(self, thread: discord.Thread, user: discord.abc.User) -> None:
        tags: Sequence[discord.abc.Snowflake] = thread.applied_tags

        if not any(tag.id == SOLVED_TAG for tag in tags):
            tags.append(discord.Object(id=SOLVED_TAG))  # type: ignore

        await thread.edit(
            locked=True,
            archived=True,
            applied_tags=tags[:5],
            reason=f'Marked as resolved by {user} (ID: {user.id})',
        )

    @is_help_forum_post()
    @commands.command(name='solved', aliases=('is_solved', 'is-solved'))
    @commands.max_concurrency(1, commands.BucketType.channel)
    async def solved(self, ctx: HideoutGuildContext):
        """Marks a help post as solved, which archives and locks it."""
        # Inspired by RoboDanny's solved command for discord.py
        # https://github.com/Rapptz/RoboDanny/blob/0a78d2741366cb26746b03b08528d4727d26497a/cogs/dpy.py#L519-L545
        assert isinstance(ctx.channel, discord.Thread)

        if can_solve_thread(ctx) and ctx.invoked_with == 'solved':
            await ctx.message.add_reaction('\N{WHITE HEAVY CHECK MARK}')
            await self.solve_thread(ctx.channel, ctx.author)
        else:
            msg = f"<@!{ctx.channel.owner_id}>, would you like to mark this thread as solved? This has been requested by {ctx.author.mention}."
            confirm = await ctx.confirm(
                msg, author_id=ctx.channel.owner_id, timeout=300, allowed_mentions=discord.AllowedMentions.all()
            )

            if ctx.channel.locked:
                return

            if confirm:
                await ctx.send(f'Thread marked as solved. Next time, you can do this yourself by running `-solved`.')
                await self.solve_thread(ctx.channel, ctx.channel.owner or ctx.author)
            elif confirm is False:
                await ctx.send('Not closing thread.')
