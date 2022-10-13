import asyncio
import contextlib
import logging
import re
from typing import Optional, Union

import asyncpg
import discord

from discord import app_commands
from discord.ext import commands
from utils import DuckCog, DuckContext, SilentCommandError
from utils.command import command, group
from utils.errors import ActionNotExecutable
from utils.time import ShortTime
from discord import TextChannel, VoiceChannel, Thread

from utils.timer import Timer


URL_REGEX = re.compile(r"^http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*(),]|)+$")
EMOJI_URL_PATTERN = re.compile(r'(https?://)?(media|cdn)\.discord(app)?\.(com|net)/emojis/(?P<id>[0-9]+)\.(?P<fmt>[A-z]+)')
DUCK_HIDEOUT = 774561547930304536
QUEUE_CHANNEL = 927645247226408961
BOTS_ROLE = 870746847071842374
BOT_DEVS_ROLE = 775516377057722390
COUNSELORS_ROLE = 896178155486855249
GENERAL_CHANNEL = 774561548659458081
PIT_CATEGORY = 915494807349116958


log = logging.getLogger(__name__)


GuildMessageable = Union[TextChannel, VoiceChannel, Thread]


async def setup(bot):
    await bot.add_cog(Hideout(bot))


def pit_owner_only():
    async def predicate(ctx: DuckContext):
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
    def predicate(ctx: DuckContext):
        if ctx.guild and ctx.guild.id == DUCK_HIDEOUT:
            return True
        raise SilentCommandError

    return commands.check(predicate)


def counselor_only():
    def predicate(ctx: DuckContext):
        if ctx.guild.get_role(COUNSELORS_ROLE) in ctx.author.roles:
            return True
        raise SilentCommandError
    
    return commands.check(predicate)


class Hideout(DuckCog, name='Duck Hideout Stuff', emoji='🦆', brief='Commands related to the server, like pits and addbot.'):
    """
    Commands related to the server, like pits and addbot.
    """

    def __init__(self, bot):
        super().__init__(bot)

    async def toggle_block(
        self,
        channel: discord.TextChannel,
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
            channel = channel.parent  # type: ignore
            if not channel:
                raise ActionNotExecutable("Couldn't block! This thread has no parent channel... somehow.")

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

    @command()
    @hideout_only()
    async def addbot(self, ctx: DuckContext, bot: discord.User, *, reason: commands.clean_content):
        """ Adds a bot to the bot queue.

        Parameters
        ----------
        bot: discord.User
            The bot to add to the queue.
        reason: commands.clean_content
            The reason why we should add your bot.
        """

        if not bot.bot:
            raise commands.BadArgument('That does not seem to be a bot...')

        if bot in ctx.guild.members:
            raise commands.BadArgument('That bot is already in this server...')

        if await self.bot.pool.fetchval('SELECT owner_id FROM addbot WHERE bot_id = $1 AND pending = TRUE', bot.id):
            raise commands.BadArgument('That bot is already in the queue...')
        
        confirm = await ctx.confirm(
            f'Does your bot comply with {ctx.guild.rules_channel.mention if ctx.guild.rules_channel else "<channel deleted?>"}?'
            f'\n If so, press one of these:',
        )

        if confirm is True:
            await self.bot.pool.execute(
                'INSERT INTO addbot (owner_id, bot_id, reason) VALUES ($1, $2, $3) '
                'ON CONFLICT (owner_id, bot_id) DO UPDATE SET pending = TRUE, added = FALSE, reason = $3',
                ctx.author.id,
                bot.id,
                reason,
            )
            bot_queue: discord.TextChannel = ctx.guild.get_channel(QUEUE_CHANNEL)  # type: ignore

            url = discord.utils.oauth_url(bot.id, scopes=['bot'], guild=ctx.guild)

            embed = discord.Embed(description=reason)
            embed.set_author(icon_url=bot.display_avatar.url, name=str(bot), url=url)
            embed.add_field(name='invite:', value=f'[invite {discord.utils.remove_markdown(str(bot))}]({url})')
            embed.set_footer(text=f"Requested by {ctx.author} ({ctx.author.id})")
            await bot_queue.send(embed=embed)
            await ctx.reply('✅ | Done, you will be @pinged when the bot is added!')

        elif confirm is False:
            await ctx.send('Cancelled.')

    @commands.Cog.listener('on_member_join')
    async def dhm_bot_queue_handler(self, member: discord.Member):
        with contextlib.suppress(discord.HTTPException):
            queue_channel: discord.TextChannel = member.guild.get_channel(QUEUE_CHANNEL)  # type: ignore
            if not member.bot or member.guild.id != DUCK_HIDEOUT:
                return

            if len(member.roles) > 1:
                await member.kick(reason='Was invited with permissions')
                return await queue_channel.send(f'{member} automatically kicked for having a role.')

            mem_id = await self.bot.pool.fetchval('SELECT owner_id FROM addbot WHERE bot_id = $1', member.id)
            if not mem_id:
                await member.kick(reason='Unauthorised bot')
                return await queue_channel.send(
                    f'{member} automatically kicked - unauthorised. Please re-invite using the `addbot` command.'
                )

            await self.bot.pool.execute('UPDATE addbot SET added = TRUE, pending = FALSE WHERE bot_id = $1', member.id)

            await member.add_roles(discord.Object(BOTS_ROLE))

            embed = discord.Embed(title='Bot added', description=f'{member} joined.', colour=discord.Colour.green())
            added_by = await discord.utils.get(
                member.guild.audit_logs(action=discord.AuditLogAction.bot_add, limit=5), target=member
            )
            if added_by and (added_by := added_by.user) is not None:
                embed.set_footer(text=f'Added by {added_by} ({added_by.id})')
            embed.add_field(name='Added by', value=str(member.guild.get_member(mem_id)), inline=False)

            await queue_channel.send(embed=embed)

            if mem_id:
                general: discord.TextChannel = member.guild.get_channel(GENERAL_CHANNEL)  # type: ignore
                await general.send(
                    f'{member} has been added, <@{mem_id}>', allowed_mentions=discord.AllowedMentions(users=True)
                )

                mem = member.guild.get_member(mem_id)
                if mem is not None and not mem.get_role(BOT_DEVS_ROLE):
                    await mem.add_roles(discord.Object(BOT_DEVS_ROLE))

    @commands.Cog.listener('on_member_remove')
    async def on_member_remove(self, member: discord.Member):
        if member.guild.id != DUCK_HIDEOUT:
            return

        queue_channel: discord.TextChannel = member.guild.get_channel(QUEUE_CHANNEL)  # type: ignore

        if member.bot:
            await self.bot.pool.execute('UPDATE addbot SET added = FALSE WHERE bot_id = $1', member.id)
            embed = discord.Embed(title='Bot removed', description=f'{member} left.', colour=discord.Colour.red())
            mem_id = await self.bot.pool.fetchval('SELECT owner_id FROM addbot WHERE bot_id = $1', member.id)
            mem = member.guild.get_member(mem_id)

            if mem:
                embed.add_field(name='Added by', value=str(member), inline=False)
                await queue_channel.send(embed=embed)

            return
        _bot_ids = await self.bot.pool.fetch('SELECT bot_id FROM addbot WHERE owner_id = $1 AND added = TRUE', member.id)
        bots = [_ent for _ent in map(lambda ent: member.guild.get_member(ent['bot_id']), _bot_ids) if _ent is not None]

        if not bots:
            return

        with contextlib.suppress(discord.HTTPException):
            for bot in bots:
                await self.bot.pool.execute('UPDATE addbot SET added = FALSE WHERE bot_id = $1', bot.id)
                await bot.kick(reason='Bot owner left the server.')

            embed = discord.Embed(
                title=f'{member} left!', description=f"**Kicking all their bots:**\n{', '.join(map(str, bots))}"
            )
            await queue_channel.send(embed=embed)

    @commands.Cog.listener('on_ready')
    async def on_ready(self):
        guild = self.bot.get_guild(DUCK_HIDEOUT)
        if not guild:
            return logging.error('Could not find Duck Hideout!', exc_info=False)

        bots = await self.bot.pool.fetch('SELECT * FROM addbot')
        queue_channel: discord.TextChannel = guild.get_channel(QUEUE_CHANNEL)  # type: ignore

        for bot in bots:
            bot_user = guild.get_member(bot['bot_id'])
            if not bot_user and bot['added'] is True:
                await self.bot.pool.execute('UPDATE addbot SET added = FALSE WHERE bot_id = $1', bot['bot_id'])
                await queue_channel.send(f'Bot {bot_user} was not found in the server. Updating database.')

            elif bot_user and bot['added'] is False:
                await self.bot.pool.execute(
                    'UPDATE addbot SET added = TRUE, pending = FALSE WHERE bot_id = $1', bot['bot_id']
                )

                if not bot_user.get_role(BOTS_ROLE):
                    await bot_user.add_roles(discord.Object(BOTS_ROLE), atomic=True)

                embed = discord.Embed(title='Bot added', description=f'{bot_user} joined.', colour=discord.Colour.green())
                mem_id = await self.bot.pool.fetchval('SELECT owner_id FROM addbot WHERE bot_id = $1', bot['bot_id'])
                embed.add_field(name='Added by', value=str(guild.get_member(mem_id)), inline=False)
                await queue_channel.send(embed=embed)

                if (member := guild.get_member(mem_id)) and not member.get_role(mem_id):
                    await member.add_roles(discord.Object(BOT_DEVS_ROLE), atomic=True)

            else:
                await self.bot.pool.execute('UPDATE addbot SET pending = FALSE WHERE bot_id = $1', bot['bot_id'])

    @hideout_only()
    @commands.is_owner()
    @command(name='register-bot', aliases=['rbot', 'rb'])
    async def _register_bot(self, ctx: DuckContext, owner: discord.Member, bot: discord.User):
        """ Register a bot to the database.
        
        Parameters
        ----------
        owner: discord.Member
            The owner of the bot to register to the database.
        bot: discord.User
            The bot to register to the database.
        """

        if owner.bot:
            raise commands.BadArgument('Owner must be a user.')

        if not bot.bot:
            raise commands.BadArgument('Bot must be a bot.')

        try:
            await self.bot.pool.execute(
                'INSERT INTO addbot (owner_id, bot_id, pending, added) VALUES ($1, $2, false, true)', owner.id, bot.id
            )
            await ctx.message.add_reaction('✅')

        except Exception as e:
            await ctx.message.add_reaction('❌')
            raise e

    @pit_owner_only()
    @group(name='pit', hybrid=True)
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_messages=True)
    async def pit(self, ctx: DuckContext):
        """ Pit management commands. """

        if ctx.invoked_subcommand is None and ctx.subcommand_passed is None:
            await ctx.send_help(ctx.command)

    @pit.command(name='ban')
    @pit_owner_only()
    @app_commands.rename(_for='for')
    async def pit_ban(self, ctx: DuckContext, member: discord.Member, _for: Optional[ShortTime]):
        """ Ban a member from the pit.

        Parameters
        ----------
        member: discord.Member
            The member to ban from this pit
        for: str
            For how much should this member stay banned? (e.g. 1h, 1d, 1h2m30s)
        """

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
            if _for:
                await self.bot.create_timer(
                    _for.dt, 'tempblock', ctx.guild.id, ctx.channel.id, member.id, ctx.author.id, precise=False
                )
                fmt = f'until {discord.utils.format_dt(_for.dt, "R")}'

            else:
                fmt = ''

            await ctx.send(f'✅ **|** Pit-banned **{discord.utils.remove_markdown(str(member))}** {fmt}')

    @pit.command(name='unban')
    @pit_owner_only()
    async def pit_unban(self, ctx: DuckContext, member: discord.Member):
        """ Unban a member from the pit.
        
        Parameters
        ----------
        member: discord.Member
            The member to unban from the pit.
        """

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
    @pit.command(name='setowner', aliases=['set-owner'], slash=False)
    async def pit_set_owner(self, ctx: DuckContext, member: discord.Member):
        """ Set the owner of a pit.
        
        Parameters
        ----------
        member: discord.Member
            The new pit owner.
        """

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
    @pit.command(name='create', slash=False)
    async def pit_create(self, ctx: DuckContext, owner: discord.Member, *, name: str):
        """ Create a pit.
        
        Parameters
        ----------
        owner: discord.Member
            The owner of the pit to create.
        name: str
            The name of the pit to create.
        """

        pit = await ctx.bot.pool.fetchval('''SELECT pit_id FROM pits WHERE pit_owner = $1''', owner.id)
        if pit is not None and ctx.guild.get_channel(pit):
            raise commands.BadArgument('User already owns a pit.')

        category: discord.CategoryChannel = ctx.guild.get_channel(PIT_CATEGORY)  # type: ignore

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
    @pit.command(name='delete', slash=False)
    async def pit_delete(self, ctx: DuckContext):
        """ Deletes a pit. """

        pit = await ctx.bot.pool.fetchval('''SELECT pit_id FROM pits WHERE pit_id = $1''', ctx.channel.id)
        if pit is None:
            raise commands.BadArgument('You are not in a pit.')
        
        try:
            channel = ctx.guild.get_channel(pit)
            await channel.delete(reason=f"pit delete command executed | {ctx.author} ({ctx.author.id})")
        
        except discord.Forbidden:
            raise commands.BadArgument('I do not have permission to delete a channel.')
        
        else:
            await ctx.bot.pool.execute('''DELETE FROM pits WHERE pit_id = $1''', ctx.channel.id)
            await ctx.send(f'✅ **|** Deleted **{channel.name}**')
            

    @command(hybrid=True)
    async def whoadd(self, ctx: DuckContext, bot: discord.Member):
        """Checks who added a specific bot.

        Parameters
        ----------
        bot: discord.Member
            The bot to check it's owner.
        """

        if not bot.bot:
            raise commands.BadArgument('This user is not a bot.')

        data = await self.bot.pool.fetchrow('SELECT * FROM addbot WHERE bot_id = $1', bot.id)

        if not data:
            raise commands.BadArgument('No data found...')

        embed = discord.Embed(title='Bot info', timestamp=ctx.message.created_at, color=bot.color)
        embed.set_author(name=str(bot), icon_url=bot.display_avatar.url)
        user: discord.User = await ctx.bot.get_or_fetch_user(data['owner_id'])  # type: ignore
        embed.add_field(name='Added by', value=f"{user.mention} (`{user.id}`)", inline=False)
        embed.add_field(name='Reason', value=data['reason'])
        embed.add_field(name='Joined at', value=discord.utils.format_dt(bot.joined_at or bot.created_at, 'R'))
        embed.set_footer(text=f'bot ID: {bot.id}')
        await ctx.send(embed=embed)

    @command()
    async def spooki(self, ctx: DuckContext, *, member: discord.Member):
        """toggles spooki role for a member."""
        if ctx.author.id != 1022842005920940063:
            return

        role_id = 988046268104335371
        if member._roles.has(role_id):
            await member.remove_roles(discord.Object(id=role_id))
            return await ctx.message.add_reaction('\N{HEAVY MINUS SIGN}')

        await member.add_roles(discord.Object(id=role_id))
        await ctx.message.add_reaction('\N{HEAVY PLUS SIGN}')

    @commands.Cog.listener('on_member_join')
    async def block_handler(self, member: discord.Member):
        """Blocks a user from your channel."""
        guild = member.guild
        if guild is None:
            return

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
                            reason='[MEMBER-JOIN] Automatic re-block for previously blocked user. See "db.blocked" for a list of blocked users.',
                        )
                        await asyncio.sleep(1)

                except discord.Forbidden:
                    log.debug(
                        f"Did not unblock user {member} in channel {channel} due to missing permissions.", exc_info=False
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
                return log.debug("Discarding blocked users for channel id {channel_id} as it can't be found.")

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
