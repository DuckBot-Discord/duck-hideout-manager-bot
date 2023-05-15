import discord
from discord.ext import commands

from .profile import ProfileCardCog
from .calendar import CalendarStatusCog
from .leaderboard import LeaderboardCog

from bot import HideoutManager


class Stats(ProfileCardCog, CalendarStatusCog, LeaderboardCog):
    """Tracks User Statistics"""

    @commands.Cog.listener('on_message')
    async def logs_add_message(self, message: discord.Message):
        if not message.guild or message.guild.id != self.bot.constants.DUCK_HIDEOUT:
            return
        if message.webhook_id:
            return
        query = "INSERT INTO message_info (author_id, message_id, channel_id, created_at, embed_count, attachment_count, is_bot) VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT DO NOTHING"
        await self.bot.pool.execute(
            query,
            message.author.id,
            message.id,
            message.channel.id,
            message.created_at,
            len(message.embeds),
            len(message.attachments),
            message.author.bot,
        )

    @commands.Cog.listener('on_raw_message_edit')
    async def log_update_message(self, payload: discord.RawMessageUpdateEvent):
        if payload.guild_id != self.bot.constants.DUCK_HIDEOUT:
            return
        if payload.cached_message:
            query = "UPDATE message_info SET embed_count = $1, attachment_count = $2, edited_at = $3 WHERE message_id = $4 AND channel_id = $5"
            await self.bot.pool.execute(
                query,
                len(payload.cached_message.embeds),
                len(payload.cached_message.attachments),
                discord.utils.utcnow(),
                payload.message_id,
                payload.channel_id,
            )
        else:
            query = "UPDATE message_info SET edited_at = $1 WHERE message_id = $2 AND channel_id = $3"
            await self.bot.pool.execute(
                query,
                discord.utils.utcnow(),
                payload.message_id,
                payload.channel_id,
            )

    @commands.Cog.listener('on_raw_message_delete')
    async def log_delete_message(self, payload: discord.RawMessageDeleteEvent):
        query = "UPDATE message_info SET deleted = TRUE WHERE message_id = $1 AND channel_id = $2"
        await self.bot.pool.execute(
            query,
            payload.message_id,
            payload.channel_id,
        )

    @commands.Cog.listener('on_raw_bulk_message_delete')
    async def log_bulk_delete_message(self, payload: discord.RawBulkMessageDeleteEvent):
        query = "UPDATE message_info SET deleted = TRUE WHERE message_id = $1 AND channel_id = $2"
        await self.bot.pool.executemany(query, [(mid, payload.channel_id) for mid in payload.message_ids])

    @commands.Cog.listener('on_presence_update')
    async def track_status_changes(self, before: discord.Member, after: discord.Member):
        if before.guild.id != self.bot.constants.DUCK_HIDEOUT:
            return
        if before.status == after.status:
            return
        query = "INSERT INTO status_history(user_id, status, changed_at) VALUES ($1, $2, $3)"
        await self.bot.pool.execute(query, after.id, str(after.status), discord.utils.utcnow())


async def setup(bot: HideoutManager):
    await bot.add_cog(Stats(bot))
