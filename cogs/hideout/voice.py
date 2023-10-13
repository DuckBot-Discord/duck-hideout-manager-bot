import discord
from discord.ext import commands

from utils import HideoutCog, JOINED, LEFT, DEAF, MUTE, SELF_DEAF, SELF_MUTE, NO_DEAF, NO_MUTE


class VoiceChatLogs(HideoutCog):
    @commands.Cog.listener('on_voice_state_update')
    async def voice_channel_notifications(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        ts = discord.utils.format_dt(discord.utils.utcnow(), 'T')
        if before.channel != after.channel:
            if before.channel:
                await before.channel.send(f"[{ts}] {LEFT} **{discord.utils.escape_markdown(member.display_name)}** left.")
            if after.channel:
                await after.channel.send(f"[{ts}] {JOINED} **{discord.utils.escape_markdown(member.display_name)}** joined.")

        channel = after.channel or before.channel
        if not channel:
            return

        if before.deaf != after.deaf:
            if before.deaf:
                await channel.send(
                    f"[{ts}] {NO_DEAF} **{discord.utils.escape_markdown(member.display_name)}** got undeafened."
                )
            if after.deaf:
                await channel.send(f"[{ts}] {DEAF} **{discord.utils.escape_markdown(member.display_name)}** got deafened.")

        if before.mute != after.mute:
            if before.mute:
                await channel.send(f"[{ts}] {NO_MUTE} **{discord.utils.escape_markdown(member.display_name)}** got unmuted.")
            if after.mute:
                await channel.send(f"[{ts}] {MUTE} **{discord.utils.escape_markdown(member.display_name)}** got muted.")

        if before.self_deaf != after.self_deaf:
            if before.self_deaf:
                await channel.send(
                    f"[{ts}] {NO_DEAF} **{discord.utils.escape_markdown(member.display_name)}** undeafened themselves."
                )
            if after.self_deaf:
                await channel.send(
                    f"[{ts}] {SELF_DEAF} **{discord.utils.escape_markdown(member.display_name)}** deafened themselves."
                )

        elif before.self_mute != after.self_mute:
            if before.self_mute:
                await channel.send(
                    f"[{ts}] {NO_MUTE} **{discord.utils.escape_markdown(member.display_name)}** unmuted themselves."
                )
            if after.self_mute:
                await channel.send(
                    f"[{ts}] {SELF_MUTE} **{discord.utils.escape_markdown(member.display_name)}** muted themselves."
                )
