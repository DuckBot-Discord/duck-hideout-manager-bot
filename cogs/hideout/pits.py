from __future__ import annotations

import os
import asyncio
from logging import getLogger
from typing import Optional, Any

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands

from utils import ActionNotExecutable, HideoutCog, HideoutGuildContext, ShortTime, Timer
from utils.constants import ARCHIVE_CATEGORY, COUNSELORS_ROLE, PIT_CATEGORY

from ._checks import counselor_only, pit_owner_only

log = getLogger('HM.pit')


class PitsManagement(HideoutCog):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.no_auto: bool = os.getenv('NO_AUTO_FEATURES') is not None

    async def toggle_block(
        self,
        channel: discord.TextChannel | discord.ForumChannel | discord.Thread | None,
        member: discord.Member,
        blocked: bool = True,
        update_db: bool = True,
        reason: Optional[str] = None,
    ) -> None:
        """|coro|

        Toggle the block status of a member in a channel.

        Parameters
        ----------
        channel : `discord.abc.Messageable`
            The channel to block/unblock the member in.
        member : `discord.Member`
            The member to block/unblock.
        blocked : `bool`, optional
            Whether to block or unblock the member. Defaults to ``True``, which means block.
        update_db : `bool`, optional
            Whether to update the database with the new block status.
        reason : `str`, optional
            The reason for the block/unblock.
        """

        if isinstance(channel, discord.abc.PrivateChannel):
            raise commands.NoPrivateMessage()

        if isinstance(channel, discord.Thread):
            channel = channel.parent

            if not channel:
                raise ActionNotExecutable("Couldn't block! This thread has no parent channel... somehow.")

        if not channel:
            raise ActionNotExecutable('This ')

        val = False if blocked else None
        overwrites = channel.overwrites_for(member)

        overwrites.update(
            send_messages=val,
            add_reactions=val,
            create_public_threads=val,
            create_private_threads=val,
            send_messages_in_threads=val,
        )
        try:
            await channel.set_permissions(member, reason=reason, overwrite=overwrites)

        finally:
            if update_db:
                if blocked:
                    query = (
                        'INSERT INTO blocks (guild_id, channel_id, user_id) VALUES ($1, $2, $3) '
                        'ON CONFLICT (guild_id, channel_id, user_id) DO NOTHING'
                    )
                else:
                    query = "DELETE FROM blocks WHERE guild_id = $1 AND channel_id = $2 AND user_id = $3"

                async with self.bot.safe_connection() as conn:
                    await conn.execute(query, channel.guild.id, channel.id, member.id)

    async def format_block(self, guild: discord.Guild, user_id: int, channel_id: Optional[int] = None):
        """|coro|

        Format a block entry from the database into a human-readable string.

        Parameters
        ----------
        guild: :class:`discord.Guild`
            The guild the block is in.
        channel_id: :class:`int`
            The channel ID of the block.
        user_id: :class:`int`
            The user ID of the block.

        Returns
        -------
        :class:`str`
            The formatted block entry.
        """
        if channel_id:
            channel = guild.get_channel(channel_id)
            if channel is None:
                channel = '#deleted-channel - '

            else:
                channel = f"#{channel} ({channel_id}) - "

        else:
            channel = ''

        user = await self.bot.get_or_fetch_member(guild, user_id) or f"Unknown User"

        return f"{channel}@{user} ({user_id})"

    @pit_owner_only()
    @commands.hybrid_group(name='pit')
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    async def pit(self, ctx: HideoutGuildContext):
        """Pit management commands."""

        if ctx.invoked_subcommand is None and ctx.subcommand_passed is None:
            await ctx.send_help(ctx.command)

    @pit.command(name='ban')
    @pit_owner_only()
    @app_commands.describe(
        member='The member to ban from this pit.', duration='How long should this member stay banned? (e.g. 1h, 1d, 1h2m30s)'
    )
    async def pit_ban(self, ctx: HideoutGuildContext, member: discord.Member, duration: Optional[ShortTime]):
        """Ban a member from the pit."""

        if member.id == ctx.author.id:
            raise commands.BadArgument('You cannot ban yourself.')

        channel = ctx.channel
        if isinstance(channel, discord.Thread):
            channel = channel.parent

        if not isinstance(channel, discord.TextChannel):
            raise commands.BadArgument('Somehow, this channel does not exist or is not a text channel.')

        try:
            await self.toggle_block(
                channel=channel, member=member, blocked=True, reason=f'Pit Ban by {ctx.author} (ID: {ctx.author.id})'
            )
        except (discord.Forbidden, discord.HTTPException):
            await ctx.send('🥴 Something went wrong...')

        else:
            if duration:
                await self.bot.create_timer(
                    duration.dt, 'tempblock', ctx.guild.id, ctx.channel.id, member.id, ctx.author.id, precise=False
                )
                fmt = f'until {discord.utils.format_dt(duration.dt, "R")}'

            else:
                fmt = ''

            await ctx.send(f'✅ **|** Pit-banned **{discord.utils.remove_markdown(str(member))}** {fmt}')

    @pit.command(name='unban')
    @pit_owner_only()
    @app_commands.describe(member='The member to unban from this pit.')
    async def pit_unban(self, ctx: HideoutGuildContext, *, member: discord.Member):
        """Unban a member from the pit."""

        if member.id == ctx.author.id:
            raise commands.BadArgument('You cannot ban yourself.')

        channel = ctx.channel

        if isinstance(channel, discord.Thread):
            channel = channel.parent

        if not isinstance(channel, discord.TextChannel):
            raise commands.BadArgument('Somehow, this channel does not exist or is not a text channel.')

        try:
            await self.toggle_block(
                channel=channel, member=member, blocked=False, reason=f'Pit Unban by {ctx.author} (ID: {ctx.author.id})'
            )

        except (discord.Forbidden, discord.HTTPException) as e:
            await ctx.send('🥴 Something went wrong...')
            await self.bot.exceptions.add_error(error=e, ctx=ctx)

        else:
            await ctx.send(f'✅ **|** Pit-unbanned **{discord.utils.remove_markdown(str(member))}** from **{ctx.channel}**')

    @commands.is_owner()
    @pit.command(name='setowner', aliases=['set-owner'], with_app_command=False)
    async def pit_set_owner(self, ctx: HideoutGuildContext, *, member: discord.Member):
        """Set the owner of a pit."""

        try:
            await ctx.bot.pool.execute(
                '''INSERT INTO pits (pit_id, pit_owner) VALUES ($1, $2)
                                        ON CONFLICT (pit_id) DO UPDATE SET pit_owner = $2''',
                ctx.channel.id,
                member.id,
            )

        except asyncpg.UniqueViolationError:
            raise commands.BadArgument('This user is already the owner of a pit.')

        await ctx.message.add_reaction('✅')

    @counselor_only()
    @pit.command(name='create', with_app_command=False)
    async def pit_create(self, ctx: HideoutGuildContext, owner: discord.Member, *, name: str):
        """Create a pit."""

        pit_id: int | None = await ctx.bot.pool.fetchval('''SELECT pit_id FROM pits WHERE pit_owner = $1''', owner.id)
        if pit_id is not None and ctx.guild.get_channel(pit_id):
            raise commands.BadArgument('User already owns a pit.')

        category: discord.CategoryChannel | None = ctx.guild.get_channel(PIT_CATEGORY)  # type: ignore

        if category is None:
            raise commands.BadArgument('There is no category for pits, for some reason...')

        try:
            _bot_ids = await self.bot.pool.fetch('SELECT bot_id FROM addbot WHERE owner_id = $1 AND added = TRUE', owner.id)
            users = [
                _ent for _ent in map(lambda ent: owner.guild.get_member(ent['bot_id']), _bot_ids) if _ent is not None
            ] + [owner]
            overs = discord.PermissionOverwrite(
                manage_messages=True, manage_channels=True, manage_threads=True, view_channel=True
            )
            channel = await ctx.guild.create_text_channel(
                name, category=category, overwrites={user: overs for user in users}
            )

        except discord.Forbidden:
            raise commands.BadArgument('I do not have permission to create a channel.')

        else:
            await ctx.bot.pool.execute(
                '''INSERT INTO pits (pit_id, pit_owner) VALUES ($1, $2)
                                          ON CONFLICT (pit_owner) DO UPDATE SET pit_id = $1''',
                channel.id,
                owner.id,
            )
            await ctx.send(f'✅ **|** Created **{channel}**')

    @counselor_only()
    @pit.command(name='delete', with_app_command=False)
    async def pit_delete(self, ctx: HideoutGuildContext, *, channel: discord.TextChannel = commands.CurrentChannel):
        """Deletes a pit."""

        pit_id = await ctx.bot.pool.fetchval('''SELECT pit_id FROM pits WHERE pit_id = $1''', channel.id)
        if pit_id is None:
            raise commands.BadArgument('Could not find pit id')

        try:
            pit = ctx.guild.get_channel(pit_id)
            if pit is None:
                raise commands.BadArgument('Could not find pit')

            await pit.delete(reason=f"pit delete command executed | {ctx.author} ({ctx.author.id})")

        except discord.Forbidden:
            raise commands.BadArgument('I do not have permission to delete a channel.')

        else:
            await ctx.bot.pool.execute('''DELETE FROM pits WHERE pit_id = $1''', pit.id)
            await ctx.send(f'✅ **|** Deleted **{pit.name}**')

    @counselor_only()
    @pit.command(name='archive', with_app_command=False)
    async def pit_archive(self, ctx: HideoutGuildContext, *, channel: discord.TextChannel = commands.CurrentChannel):
        """Archives a pit."""

        pit_id: int | None = await ctx.bot.pool.fetchval('''SELECT pit_id FROM pits WHERE pit_id = $1''', channel.id)
        if pit_id is None:
            raise commands.BadArgument('Could not find pit id')

        try:
            pit: discord.TextChannel | None = ctx.guild.get_channel(pit_id)  # type: ignore
            if pit is None:
                raise commands.BadArgument('Could not find pit')

            archive: Optional[discord.CategoryChannel] = ctx.guild.get_channel(ARCHIVE_CATEGORY)  # type: ignore
            if archive is None:
                raise commands.BadArgument('Could not find archive category')

            counselors = ctx.guild.get_role(COUNSELORS_ROLE)
            if counselors is None:
                raise commands.BadArgument('Could not find counselors role')

            new_overwrites = {
                **pit.overwrites,
                ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                counselors: discord.PermissionOverwrite(view_channel=True),
                ctx.guild.me: discord.PermissionOverwrite(view_channel=True, manage_channels=True, manage_permissions=True),
            }
            await pit.edit(
                overwrites=new_overwrites, category=archive, reason=f"Pit archived by {ctx.author} ({ctx.author.id})"
            )
            await ctx.bot.pool.execute("UPDATE pits SET archive_mode = 'manual' WHERE pit_id = $1", pit.id)
        except discord.Forbidden:
            raise commands.BadArgument('I do not have permission to edit channels.')

        else:
            await ctx.send(f'✅ **|** Archived **{pit.name}**')

    @counselor_only()
    @pit.command(name='unarchive', with_app_command=False)
    async def pit_unarchive(self, ctx: HideoutGuildContext, *, channel: discord.TextChannel = commands.CurrentChannel):
        """Archives a pit."""

        record = await ctx.bot.pool.fetchrow('''SELECT * FROM pits WHERE pit_id = $1''', channel.id)
        if record is None:
            raise commands.BadArgument('Could not find pit')

        owner = await self.bot.get_or_fetch_member(ctx.guild, record['pit_owner'])
        if owner is None:
            raise commands.BadArgument('Could not find pit owner from id')

        try:
            pit: discord.TextChannel | None = ctx.guild.get_channel(record["pit_id"])  # type: ignore
            if pit is None:
                raise commands.BadArgument('Could not find pit from id')

            pits_category: Optional[discord.CategoryChannel] = ctx.guild.get_channel(PIT_CATEGORY)  # type: ignore
            if pits_category is None:
                raise commands.BadArgument('Could not find pit category')

            overs = {
                **pit.overwrites,
                ctx.guild.default_role: discord.PermissionOverwrite(),
            }

            await pit.edit(category=pits_category, overwrites=overs)
            await ctx.bot.pool.execute("UPDATE pits SET archive_mode = NULL WHERE pit_id = $1", pit.id)
        except discord.Forbidden:
            raise commands.BadArgument('I do not have permission to edit channels.')

        else:
            await ctx.send(f'✅ **|** Unarchived **{pit.name}**')

    @commands.Cog.listener('on_member_join')
    async def block_handler(self, member: discord.Member):
        """Blocks a user from your channel."""
        guild = member.guild

        channel_ids = await self.bot.pool.fetch(
            'SELECT channel_id FROM blocks WHERE guild_id = $1 AND user_id = $2', guild.id, member.id
        )

        for record in channel_ids:
            channel_id = record['channel_id']
            try:
                channel = guild.get_channel(channel_id) or await guild.fetch_channel(channel_id)

            except discord.HTTPException:
                log.debug(f"Discarding blocked users for channel id {channel_id} as it can't be found.")
                await self.bot.pool.execute(
                    'DELETE FROM blocks WHERE guild_id = $1 AND channel_id = $2', guild.id, channel_id
                )
                continue

            else:
                try:
                    if channel.permissions_for(guild.me).manage_permissions:
                        await self.toggle_block(
                            channel,  # type: ignore
                            member,
                            blocked=True,
                            update_db=False,
                            reason='[MEMBER-JOIN] Automatic re-block for previously blocked user.',
                        )
                        await asyncio.sleep(1)

                except discord.Forbidden:
                    log.debug(
                        f"Did not re-block user {member} in channel {channel} due to missing permissions.", exc_info=False
                    )
                    continue

                except discord.HTTPException:
                    log.debug(f"Unexpected error while re-blocking user {member} in channel {channel}.", exc_info=False)

    @commands.Cog.listener('on_tempblock_timer_complete')
    async def on_tempblock_timer_complete(self, timer: Timer):
        """Automatic temp block expire handler"""
        guild_id, channel_id, user_id, author_id = timer.args

        try:
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                return

            channel = guild.get_channel(channel_id)
            if channel is None:
                return

            # Can't really 100% rely on member cache, so we'll just try to fetch.
            member = await self.bot.get_or_fetch_member(guild, user_id)
            if not member:
                return log.debug(f"Discarding blocked users for channel id {channel_id} as it can't be found.")

            try:
                mod = self.bot.get_user(author_id) or await self.bot.fetch_user(author_id)
                f"{mod} (ID: {author_id})"
            except discord.HTTPException:
                mod = f"unknown moderator (ID: {author_id})"

            await self.toggle_block(
                channel,  # type: ignore
                member,
                blocked=False,
                update_db=False,
                reason=f'Expiring temp-block made on {timer.created_at} by {mod}',
            )

        finally:
            # Finally, we remove the user from the list of blocked users, regardless of any errors.
            await self.bot.pool.execute(
                'DELETE FROM blocks WHERE guild_id = $1 AND channel_id = $2 AND user_id = $3', guild_id, channel_id, user_id
            )

    @commands.Cog.listener('on_member_remove')
    async def pit_auto_archive(self, member: discord.Member):
        """Automatically archives pits that are not used."""

        pit_id: int | None = await self.bot.pool.fetchval('''SELECT pit_id FROM pits WHERE pit_owner = $1''', member.id)
        if pit_id is None:
            return log.error('Could not find pit id')

        try:
            pit: discord.TextChannel | None = member.guild.get_channel(pit_id)  # type: ignore
            if pit is None:
                return log.error('Could not find pit')

            archive: Optional[discord.CategoryChannel] = member.guild.get_channel(ARCHIVE_CATEGORY)  # type: ignore
            if archive is None:
                return log.error('Could not find archive category')

            counselors = member.guild.get_role(COUNSELORS_ROLE)
            if counselors is None:
                return log.error('Could not find counselors role')

            new_overwrites = {
                **pit.overwrites,
                member.guild.me: discord.PermissionOverwrite(
                    view_channel=True, manage_channels=True, manage_permissions=True
                ),
                member.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                counselors: discord.PermissionOverwrite(view_channel=True),
            }

            await pit.edit(overwrites=new_overwrites, category=archive, reason=f"Pit archived by automatically: member left")
            await self.bot.pool.execute("UPDATE pits SET archive_mode = 'leave' WHERE pit_id = $1", pit.id)
        except discord.Forbidden:
            return log.error('I do not have permission to edit channels.')
        else:
            await pit.send('Pit archived automatically: member left')

    @commands.Cog.listener('on_member_join')
    async def pit_auto_unarchive(self, member: discord.Member):
        """Automatically archives pits that are not used."""

        record = await self.bot.pool.fetchrow('''SELECT * FROM pits WHERE pit_owner = $1''', member.id)

        if not record or record['archive_mode'] != 'leave':
            return

        try:
            pit: discord.TextChannel | None = member.guild.get_channel(record["pit_id"])  # type: ignore
            if pit is None:
                raise commands.BadArgument('Could not find pit from id')

            pits_category: Optional[discord.CategoryChannel] = member.guild.get_channel(PIT_CATEGORY)  # type: ignore
            if pits_category is None:
                raise commands.BadArgument('Could not find pit category')

            overs = {
                **pit.overwrites,
                member.guild.default_role: discord.PermissionOverwrite(),
            }

            await pit.edit(category=pits_category, overwrites=overs)
            await self.bot.pool.execute("UPDATE pits SET archive_mode = NULL WHERE pit_id = $1", pit.id)
        except discord.Forbidden:
            return log.error('I do not have permission to edit channels.')
        else:
            await pit.send(
                f'Pit un-archived automatically: {member.mention} rejoined',
                allowed_mentions=discord.AllowedMentions(users=True),
            )
