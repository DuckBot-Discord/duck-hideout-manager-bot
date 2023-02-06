import discord
from discord.ext import commands
from typing import Annotated
from utils import HideoutCog, HideoutContext, UntilFlag, ShortTime, Timer
from ._checks import hideout_only, counselor_only

class BanFlags(commands.FlagConverter):
    time: ShortTime

class Moderation(HideoutCog):
    @hideout_only()
    @counselor_only()
    @commands.command()
    async def ban(self, ctx: HideoutContext, member: discord.Member, *, reason: UntilFlag[Annotated[str, commands.clean_content], BanFlags]):
        if member == ctx.author:
            return await ctx.send("You can't ban yourself!")

        if ctx.author.top_role <= member.top_role:
            return await ctx.send("You can't ban someone who has a role higher or equal to yours!")
        
        if ctx.guild.me.top_role <= member.top_role:
            return await ctx.send("I can't ban this member!")

        time = reason.flags.time
        if time:
            await self.bot.create_timer(time.dt, 'tempban', ctx.guild.id, member.id, precise=False)
            fmt = f"until {discord.utils.format_dt(time.dt, 'R')}"
        else:
            fmt = ""

        await member.send(f"You have been banned from Duck Hideout. Reason: {reason.value} {f'Banned until: {fmt}' if fmt else ''}")
        await ctx.send(f"Banned {member} for **{reason}** {fmt}")
    
    @commands.Cog.listener("on_tempban_time_complete")
    async def on_tempban_time_complete(self, timer: Timer):
        guild_id, member_id = timer.args
        try:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return
            
            await guild.unban(discord.Object(id=member_id))

        except discord.HTTPException:
            pass
