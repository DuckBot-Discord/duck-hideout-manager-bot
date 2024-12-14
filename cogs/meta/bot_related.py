from collections import Counter

import discord
from discord import app_commands
from discord.ext import commands

from utils import HideoutCog, HideoutContext

from .tags import UnknownUser


class BotInformation(HideoutCog):
    @commands.hybrid_command()
    @app_commands.describe(bot="The bot to look up.")
    async def whoadd(self, ctx: HideoutContext, bot: discord.Member):
        """Checks who added a specific bot."""

        if not bot.bot:
            raise commands.BadArgument('This user is not a bot.')

        data = await self.bot.pool.fetchrow('SELECT * FROM addbot WHERE bot_id = $1', bot.id)

        if not data:
            raise commands.BadArgument('No data found...')

        embed = discord.Embed(title='Bot info', timestamp=ctx.message.created_at, color=bot.color)
        embed.set_author(name=str(bot), icon_url=bot.display_avatar.url)
        user: discord.User = await ctx.bot.get_or_fetch_user(data['owner_id'])
        embed.add_field(name='Added by', value=f"{user.mention} (`{user.id}`)", inline=False)
        embed.add_field(name='Reason', value=data['reason'])
        embed.add_field(name='Joined at', value=discord.utils.format_dt(bot.joined_at or bot.created_at, 'R'))
        embed.set_footer(text=f'bot ID: {bot.id}')
        await ctx.send(embed=embed)

    @commands.hybrid_command()
    @app_commands.describe(member='The member to look up.')
    async def whatadd(self, ctx: HideoutContext, member: discord.Member = commands.Author):
        """Checks the bots that a person added."""

        if member.bot:
            raise commands.BadArgument('This user is a bot.')

        data = await self.bot.pool.fetch('SELECT * FROM addbot WHERE owner_id = $1', member.id)

        if not data:
            raise commands.BadArgument('No data found...')

        embed = discord.Embed(title=f'{member}\'s bots', timestamp=ctx.message.created_at)

        for _, bot_id, is_added, _, reason in data:
            try:
                user = await ctx.bot.get_or_fetch_user(bot_id)
            except discord.HTTPException:
                user = UnknownUser(bot_id)

            embed.add_field(name=str(user), value=f"Added: {is_added}\nReason: {reason}", inline=False)
        await ctx.send(embed=embed)

    @commands.command()
    async def cleanup(self, ctx: HideoutContext, amount: int = 25):
        """
        Cleans up the bots messages. it defaults to 25 messages. If you or the bot don't have manage_messages permission, the search will be limited to 25 messages.
        """
        if (
            not isinstance(ctx.channel, discord.abc.GuildChannel)
            or not isinstance(ctx.author, discord.Member)
            or not ctx.guild
        ):
            raise commands.NoPrivateMessage  # it's a dm. Or something broke, either way, raise.

        if amount > 25:
            if not ctx.channel.permissions_for(ctx.author).manage_messages:
                await ctx.send("You must have `manage_messages` permission to perform a search greater than 25")
                return
            if not ctx.channel.permissions_for(ctx.guild.me).manage_messages:
                await ctx.send("I need the `manage_messages` permission to perform a search greater than 25")
                return

        use_bulk_delete = ctx.channel.permissions_for(ctx.guild.me).manage_messages

        actual_prefix = await self.bot.get_prefix(ctx.message)
        prefix = (actual_prefix,) if isinstance(actual_prefix, str) else tuple(actual_prefix)

        def check(msg: discord.Message):
            return msg.author == ctx.me or (use_bulk_delete and msg.content.startswith(prefix))

        deleted = await ctx.channel.purge(check=check, bulk=use_bulk_delete, limit=amount)

        spammers = Counter(m.author.display_name for m in deleted)

        deleted = len(deleted)
        messages = [f'{deleted} message{" was" if deleted == 1 else "s were"} removed.']

        if deleted:
            messages.append('')
            spammers = sorted(spammers.items(), key=lambda t: t[1], reverse=True)
            messages.extend(f'**{name}**: {count}' for name, count in spammers)

        to_send = '\n'.join(messages)

        if len(to_send) > 2000:
            await ctx.send(f'Successfully removed {deleted} messages.', delete_after=10)
        else:
            await ctx.send(to_send, delete_after=10)
