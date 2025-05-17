import discord

from aiohttp.web import Request, json_response
from discord.ext.duck.webserver import WebserverCog, route

from bot import HideoutManager
from utils import HideoutCog, DUCK_HIDEOUT
from discord import app_commands


def _404(detail: str):
    return json_response({'detail': detail}, status=404)


class Spotify(WebserverCog, HideoutCog, port=8716):
    @route('get', '/spotify/{user_id}')
    async def get_user_activity(self, request: Request):
        guild = self.bot.get_guild(DUCK_HIDEOUT)
        if not guild:
            return _404("no_guild")

        user_id = request.match_info["user_id"]
        if not user_id.isdigit() or not (user := guild.get_member(int(user_id))):
            return _404("no_member")

        spotify = next((a for a in user.activities if isinstance(a, discord.Spotify)), None)
        if not spotify:
            return _404("no_activity")

        return json_response(dict(title=spotify.title, artist=spotify.artist, track_id=spotify.track_id))

    @route('get', '/obsession/{user_id}')
    async def get_user_obsession(self, request: Request):
        try:
            user_id = int(request.match_info["user_id"])
        except:
            return _404("invalid_id")

        obsession = await self.bot.pool.fetchrow("SELECT * FROM obsessions WHERE user_id = $1", user_id)
        if not obsession:
            return _404("no_obsession")

        return json_response(dict(title=obsession["title"], artist=obsession["artist"], track_id=obsession["track_id"]))

    obsession = app_commands.Group(name='obsession', description='Manages song obsessions.')

    @obsession.command(name='set')
    async def set_obsession(self, interaction: discord.Interaction):
        """Sets your song obsession to your currently-playing spotify track."""
        if not interaction.guild:
            return
        user = interaction.guild.get_member(interaction.user.id)

        spotify = next((a for a in user and user.activities or [] if isinstance(a, discord.Spotify)), None)

        if not spotify:
            return await interaction.response.send_message(
                "I don't think you're listening to spotify."
                "\n-# Discord sometimes breaks. Not sure why, so perhaps try again later?",
                ephemeral=True,
            )

        await self.bot.pool.execute(
            "INSERT INTO obsessions (user_id, title, artist, track_id) VALUES ($1, $2, $3, $4) "
            "ON CONFLICT (user_id) DO UPDATE SET (title, artist, track_id) = ($2, $3, $4)",
            interaction.user.id,
            spotify.title,
            spotify.artist,
            spotify.track_id,
        )

        await interaction.response.send_message(
            f"Set your obsession to **{spotify.title}** by **{spotify.artist}**", ephemeral=True
        )

    @obsession.command(name='unset')
    async def unset_obsession(self, interaction: discord.Interaction):
        """Removes your song obsession from the database."""

        await self.bot.pool.execute("DELETE FROM obsessions WHERE user_id = $1", interaction.user.id)
        await interaction.response.send_message("Obsession unset.", ephemeral=True)


async def setup(bot: HideoutManager):
    await bot.add_cog(Spotify(bot))
