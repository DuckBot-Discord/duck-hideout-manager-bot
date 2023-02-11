import os
import logging
from typing import Union, Any

import discord
from discord import TextChannel, Thread, VoiceChannel
from discord.ext import commands

from utils import HideoutCog, HideoutGuildContext
from utils.constants import BOT_DEVS_ROLE, BOTS_ROLE, DUCK_HIDEOUT, GENERAL_CHANNEL, QUEUE_CHANNEL

from ._checks import hideout_only

log = logging.getLogger(__name__)


GuildMessageable = Union[TextChannel, VoiceChannel, Thread]


class Addbot(HideoutCog):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.no_auto: bool = os.getenv('NO_AUTO_FEATURES') is not None

    @commands.command()
    @hideout_only()
    async def addbot(self, ctx: HideoutGuildContext, bot_id: discord.User, *, reason: commands.clean_content):
        """Adds a bot to the bot queue."""

        if not bot_id.bot:
            raise commands.BadArgument('That does not seem to be a bot...')

        if bot_id in ctx.guild.members:
            raise commands.BadArgument('That bot is already in this server...')

        if await self.bot.pool.fetchval('SELECT owner_id FROM addbot WHERE bot_id = $1 AND pending = TRUE', bot_id.id):
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
                bot_id.id,
                reason,
            )
            bot_queue: discord.TextChannel = ctx.guild.get_channel(QUEUE_CHANNEL)  # type: ignore

            url = discord.utils.oauth_url(bot_id.id, scopes=['bot'], guild=ctx.guild)

            embed = discord.Embed(description=reason)
            embed.set_author(icon_url=bot_id.display_avatar.url, name=str(bot_id), url=url)
            embed.add_field(name='invite:', value=f'[invite {discord.utils.remove_markdown(str(bot_id))}]({url})')
            embed.set_footer(text=f"Requested by {ctx.author} ({ctx.author.id})")
            await bot_queue.send(embed=embed)
            await ctx.reply('✅ | Done, you will be @pinged when the bot is added!')

        elif confirm is False:
            await ctx.send('Cancelled.')

    @commands.Cog.listener('on_member_join')
    async def dhm_bot_queue_handler(self, member: discord.Member):
        if self.no_auto:
            return

        queue_channel: discord.TextChannel = member.guild.get_channel(QUEUE_CHANNEL)  # type: ignore
        if not member.bot or member.guild.id != DUCK_HIDEOUT:
            return

        if len(member.roles) > 1 and member.id != 216303189073461248:
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
            await general.send(f'{member} has been added, <@{mem_id}>', allowed_mentions=discord.AllowedMentions(users=True))

            mem = member.guild.get_member(mem_id)
            if mem is not None and not mem.get_role(BOT_DEVS_ROLE):
                await mem.add_roles(discord.Object(BOT_DEVS_ROLE))

    @commands.Cog.listener('on_member_remove')
    async def on_member_remove(self, member: discord.Member):
        if self.no_auto:
            return

        if member.guild.id != DUCK_HIDEOUT:
            return

        queue_channel: discord.TextChannel = member.guild.get_channel(QUEUE_CHANNEL)  # type: ignore

        if member.bot:
            await self.bot.pool.execute('UPDATE addbot SET added = FALSE WHERE bot_id = $1', member.id)
            embed = discord.Embed(title='Bot removed', description=f'{member} left.', colour=discord.Colour.red())
            mem_id: int = await self.bot.pool.fetchval('SELECT owner_id FROM addbot WHERE bot_id = $1', member.id)
            mem = member.guild.get_member(mem_id)

            if mem:
                embed.add_field(name='Added by', value=str(member), inline=False)
                await queue_channel.send(embed=embed)

            return
        _bot_ids = await self.bot.pool.fetch('SELECT bot_id FROM addbot WHERE owner_id = $1 AND added = TRUE', member.id)
        bots = [_ent for _ent in map(lambda ent: member.guild.get_member(ent['bot_id']), _bot_ids) if _ent is not None]

        if not bots:
            return

        for bot in bots:
            await self.bot.pool.execute('UPDATE addbot SET added = FALSE WHERE bot_id = $1', bot.id)
            try:
                await bot.kick(reason='Bot owner left the server.')
            except discord.HTTPException:
                pass

        embed = discord.Embed(
            title=f'{member} left!', description=f"**Kicking all their bots:**\n{', '.join(map(str, bots))}"
        )
        await queue_channel.send(embed=embed)

    @commands.Cog.listener('on_ready')
    async def on_ready(self):
        if self.no_auto:
            return
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
