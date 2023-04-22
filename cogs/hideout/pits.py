from __future__ import annotations

import asyncio
import datetime
import enum
import os
from logging import getLogger
from typing import Any, Optional

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils import ActionNotExecutable, HideoutCog, HideoutGuildContext, ShortTime, Timer
from utils.constants import ARCHIVE_CATEGORY, COUNSELORS_ROLE, PIT_CATEGORY

from ._checks import counselor_only, pit_owner_only

log = getLogger('HM.pit')
auto_archival_log = getLogger('HM.pit.auto-archival')

MANAGES_PIT_PERMISSIONS = discord.PermissionOverwrite(
    manage_messages=True, manage_channels=True, manage_threads=True, view_channel=True
)


class ArchiveMode(enum.Enum):
    LEAVE = "leave"
    INACTIVE = "inactive"
    MANUAL = "manual"


class ArchiveDuration(enum.Enum):
    TWENTY_FOUR_HOURS = 86_400
    THREE_DAYS = 259_200
    ONE_WEEK = 604_800
    ONE_MONTH = 2_419_200

    @classmethod
    def convert(cls, _: HideoutGuildContext, argument: str):
        try:
            as_integer = int(argument)
        except ValueError as error:
            raise commands.BadArgument(f"Invalid archive duration passed: {argument}") from error

        return cls(as_integer)


class PitsManagement(HideoutCog):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)

        self.no_auto: bool = os.getenv('NO_AUTO_FEATURES') is not None
        self.auto_archival_system = self.auto_archival.start()

    async def _try_get_latest_message(self, text_channel: discord.TextChannel) -> discord.Message | None:
        if text_channel.last_message:
            return text_channel.last_message

        async for message in text_channel.history(limit=1):
            return message

        return None

    @tasks.loop(seconds=1)
    async def auto_archival(self):
        NOW = datetime.datetime.now()
        records = await self.bot.pool.fetch('SELECT pit_id, archive_duration, archive_mode, last_message_sent_at FROM pits;')
        shortest: asyncpg.Record | None = None
        pit_ids_to_invalidate: list[list[int]] = []
        archive_category_found = self.bot.get_channel(ARCHIVE_CATEGORY)

        if not (archive_category_found and isinstance(archive_category_found, discord.CategoryChannel)):
            raise ActionNotExecutable('Could not find archive category')

        for record in records:
            pit_id: int = record['pit_id']
            pit = self.bot.get_channel(pit_id)
            is_archived = pit in archive_category_found.text_channels
            last_message_creation_date: datetime.datetime | None = record['last_message_sent_at']

            if (
                pit is None
                or not isinstance(pit, discord.TextChannel)
                or is_archived
                or last_message_creation_date is None
                or last_message_creation_date <= NOW
            ):
                pit_ids_to_invalidate.append([pit_id])

                continue
            elif not shortest:
                shortest = record

                continue

            shortest_last_message_creation_date = shortest['last_message_sent_at']

            if shortest_last_message_creation_date is None:
                latest_message = await self._try_get_latest_message(pit)

                if latest_message is not None:
                    shortest_last_message_creation_date = latest_message.created_at
                else:
                    shortest_last_message_creation_date = pit.created_at

            assert isinstance(
                shortest_last_message_creation_date, datetime.datetime
            ), 'Unable to get pit channel date or latest message creation date from pit'

            if last_message_creation_date < shortest_last_message_creation_date:
                shortest = record

        await self.bot.pool.executemany('''DELETE FROM pits WHERE pit_id=$1;''', pit_ids_to_invalidate)

        if shortest is None:
            return await asyncio.sleep(60)

        shortest_pit_id: int = shortest['pit_id']
        shortest_pit = self.bot.get_channel(shortest_pit_id)

        if shortest_pit is None or not isinstance(shortest_pit, discord.TextChannel):
            return

        latest_message: discord.Message | None = None
        shortest_last_message_creation_date = shortest['last_message_sent_at']

        if shortest_last_message_creation_date is None:
            latest_message = await self._try_get_latest_message(shortest_pit)

            if latest_message is not None:
                shortest_last_message_creation_date = latest_message.created_at
            else:
                shortest_last_message_creation_date = shortest_pit.created_at

        if shortest_last_message_creation_date is None:
            return

        archive_duration = ArchiveDuration(shortest['archive_duration'])
        archival_date = shortest_last_message_creation_date + datetime.timedelta(seconds=archive_duration.value)
        completion_delta = archival_date - NOW
        seconds_to_wait = float(completion_delta.total_seconds())

        await asyncio.sleep(seconds_to_wait)

        try:
            await shortest_pit.edit(category=archive_category_found, sync_permissions=True)
        except discord.Forbidden:
            auto_archival_log.warn(f'I do not have permission to edit channel "{shortest_pit}" with ID {shortest_pit.id}')
        else:
            auto_archival_log.info(f'Archived {shortest_pit}')

    @auto_archival.before_loop
    async def before_auto_archival(self):
        await self.bot.wait_until_ready()

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
        assert isinstance(ctx.channel, discord.TextChannel), "Command must be ran within a guild's text channel"

        latest_message = await self._try_get_latest_message(ctx.channel)
        latest_message_timestamp = latest_message.created_at if latest_message else None

        try:
            await ctx.bot.pool.execute(
                '''INSERT INTO pits (pit_id, pit_owner, archive_mode,
                archive_duration, last_message_sent_at) VALUES ($1, $2, NULL,
                $3, $4) ON CONFLICT (pit_id) DO UPDATE SET pit_owner = $2''',
                ctx.channel.id,
                member.id,
                ArchiveDuration.THREE_DAYS,
                latest_message_timestamp,
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
            channel = await ctx.guild.create_text_channel(
                name, category=category, overwrites={user: MANAGES_PIT_PERMISSIONS for user in users}
            )

        except discord.Forbidden:
            raise commands.BadArgument('I do not have permission to create a channel.')
        else:
            await ctx.bot.pool.execute(
                '''INSERT INTO pits (pit_id, pit_owner, archive_mode, archive_duration, last_message_sent_at) VALUES ($1, $2, NULL, $3, NULL)
                   ON CONFLICT (pit_owner) DO UPDATE SET pit_id = $1''',
                channel.id,
                owner.id,
                ArchiveDuration.THREE_DAYS,
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

    @pit.command(name='unarchive', with_app_command=False)
    async def pit_unarchive(self, ctx: HideoutGuildContext, *, channel: discord.TextChannel = commands.CurrentChannel):
        """Archives a pit."""
        record = await ctx.bot.pool.fetchrow('''SELECT * FROM pits WHERE pit_id = $1''', channel.id)

        if record is None:
            raise commands.BadArgument('Could not find pit')

        owner = await self.bot.get_or_fetch_member(ctx.guild, record['pit_owner'])
        pit = ctx.guild.get_channel(record["pit_id"])
        pits_category = ctx.guild.get_channel(PIT_CATEGORY)

        if owner is None:
            raise commands.BadArgument('Could not find pit owner from id')
        elif pit is None or not isinstance(pit, discord.TextChannel):
            raise commands.BadArgument('Could not find pit from id')
        elif pits_category is None or not isinstance(pits_category, discord.CategoryChannel):
            raise commands.BadArgument('Could not find valid pit category')

        archive_mode = ArchiveMode(record['archive_mode'])
        is_not_counselor = ctx.guild.get_role(COUNSELORS_ROLE) not in ctx.author.roles

        if archive_mode is ArchiveMode.MANUAL and ctx.author != owner or is_not_counselor:
            raise ActionNotExecutable('This pit was manually archived, only the pit owner and counsellors can unarchive it.')
        elif archive_mode is ArchiveMode.INACTIVE and is_not_counselor:
            raise ActionNotExecutable('This pit was marked as inactive, only the counsellors can unarchive it.')

        overs = {
            **pit.overwrites,
            ctx.guild.default_role: discord.PermissionOverwrite(),
        }

        try:
            await pit.edit(category=pits_category, overwrites=overs)
            await ctx.bot.pool.execute('''UPDATE pits SET archive_mode = NULL WHERE pit_id = $1''', pit.id)
        except discord.Forbidden:
            raise commands.BadArgument('I do not have permission to edit channels.')
        else:
            await ctx.send(f'✅ **|** Un-archived **{pit.name}**')

    @pit.command(name='setduration', with_app_command=False)
    async def pit_set_duration(self, ctx: HideoutGuildContext, duration: ArchiveDuration):
        assert isinstance(ctx.channel, discord.TextChannel), "Command must be ran within a guild's text channel"

        await self.bot.pool.execute(
            '''UPDATE pits SET archive_duration = $1 WHERE pit_id = $2;''',
            duration,
            ctx.channel.id,
        )
        self.auto_archival.restart()

    @commands.Cog.listener('on_member_join')
    async def block_handler(self, member: discord.Member):
        """Blocks a user from your channel."""
        if self.no_auto:
            return

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
        if self.no_auto:
            return

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
    async def pit_auto_archive_on_member_remove(self, member: discord.Member):
        """Automatically archives pits that are not used."""
        if self.no_auto:
            return

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
    async def pit_auto_unarchive_on_member_join(self, member: discord.Member):
        """Automatically archives pits that are not used."""
        if self.no_auto:
            return

        record = await self.bot.pool.fetchrow('''SELECT * FROM pits WHERE pit_owner = $1''', member.id)

        if not record or record['archive_mode'] != 'leave':
            return

        try:
            pit: discord.TextChannel | None = member.guild.get_channel(record["pit_id"])  # type: ignore
            if pit is None:
                return log.info(f'Could not find pit from id {record["pit_id"]}')

            pits_category: Optional[discord.CategoryChannel] = member.guild.get_channel(PIT_CATEGORY)  # type: ignore
            if pits_category is None:
                return log.critical(f'Could not find pits category')

            overs = {
                **pit.overwrites,
                member.guild.default_role: discord.PermissionOverwrite(),
                member: MANAGES_PIT_PERMISSIONS,
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
