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
    async def whatadd(self, ctx: HideoutContext, member: discord.Member):
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
