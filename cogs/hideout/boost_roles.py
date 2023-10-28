import logging
from contextlib import suppress
from io import BytesIO
from typing import Optional, Union

import discord
from discord import app_commands
from discord.utils import MISSING
from emoji import is_emoji

from utils import HideoutCog

from . import HideoutManager

Interaction = discord.Interaction[HideoutManager]
log = logging.getLogger(__name__)

class BoostRoles(HideoutCog):
    @staticmethod
    async def get_emoji(input: str) -> Optional[Union[str, bytes]]:
        if is_emoji(input):
            return input

        partial = discord.PartialEmoji.from_str(input)
        if partial.is_unicode_emoji():
            return input
            
        elif partial.id is None:
            return None

        return await partial.read()

    @HideoutCog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.premium_since and not after.premium_since:
            db = await self.bot.pool.fetchrow("SELECT * FROM booster_roles WHERE user_id = $1", after.id)

            if db is None:
                return

            role = after.guild.get_role(db["role_id"])

            if role is None:
                return

            try:
                await role.delete(reason=f"Nitro Boost Expired: {after}")

            except (discord.HTTPException, discord.Forbidden) as exc:
                log.error("Failed to delete booster role: %s (%s)", str(role), role.id, exc_info=exc)
        
        elif not before.premium_since and after.premium_since:
            db = await self.bot.pool.fetchrow("SELECT * FROM booster_roles WHERE user_id = $1", after.id)
            
            if db is None:
                return
            
            colour = discord.Colour.from_str(db["role_colour"])
            icon: Optional[bytes] = db["role_icon"]
            name: str = db["role_name"]
            
            try:
                reason = f"Member re-boosted: {after}"
                role = await after.guild.create_role(
                    name=name,
                    colour=colour,
                    display_icon=icon or MISSING,
                    reason=reason
                )
                below = after.guild.get_role(1079187727695740960)
                await role.edit(position=below.position + 1)  # type: ignore
                await after.add_roles(role, reason=reason)
            
            except Exception as exc:
                log.error("Failed to create or add booster role for %s (reboosting)", after, exc_info=exc)

    boost = app_commands.Group(name="boost", description="Commands for managing your boost.", guild_only=True)
    role = app_commands.Group(name="role", description="Commands for manging your boost role.", parent=boost)

    @role.command()
    @app_commands.describe(
        name="The name of the role.",
        colour="The colour of the role.",
        icon="Attachment for the icon.",
        emoji="An unicode- or Discord emoji.",
    )
    async def create(
        self,
        interaction: Interaction,
        name: str,
        colour: Optional[str] = None,
        icon: Optional[discord.Attachment] = None,
        emoji: Optional[str] = None,
    ):
        """Creates a new boost role."""
        assert interaction.guild and isinstance(interaction.user, discord.Member)

        res = await interaction.client.pool.fetchrow("SELECT * FROM booster_roles WHERE user_id = $1", interaction.user.id)
        if res is not None:
            return await interaction.response.send_message(
                "You already have a boost role, edit your current one with `/boost role edit`.", ephemeral=True
            )

        colour_: discord.Colour = discord.Colour.default()
        icon_: Optional[Union[str, discord.PartialEmoji, bytes]]

        if colour is not None:
            try:
                colour_ = discord.Colour.from_str(colour)

            except ValueError:
                return await interaction.response.send_message(
                    "Could not parse the colour, make sure it's a valid hex colour code.", ephemeral=True
                )

        if icon and emoji:
            return await interaction.response.send_message("You can not supply both `icon` and `emoji`.", ephemeral=True)

        elif emoji is not None:
            icon_ = await self.get_emoji(emoji)

        elif icon is not None:
            icon_ = await icon.read()

        else:
            icon_ = None

        try:
            role = await interaction.guild.create_role(name=name, colour=colour_, display_icon=icon_ or MISSING)
            await interaction.user.add_roles(role)
            await interaction.response.send_message(
                f"Successfully created your role {role.mention}.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )

            query = "INSERT INTO booster_roles VALUES ($1, $2, $3, $4, $5)"
            await interaction.client.pool.execute(
                query, role.id, interaction.user.id, name, str(role.colour), role.icon and await role.icon.read()
            )

        except discord.HTTPException:
            await interaction.response.send_message("Something went wrong when trying to create the role.", ephemeral=True)
            raise

    @role.command()
    @app_commands.describe(
        name="The name of the role.",
        colour="The colour of the role.",
        icon="Attachment for the icon.",
        emoji="An unicode- or Discord emoji.",
    )
    async def edit(
        self,
        interaction: Interaction,
        name: Optional[str] = None,
        colour: Optional[str] = None,
        icon: Optional[discord.Attachment] = None,
        emoji: Optional[str] = None,
    ):
        """Edits your boost role."""
        assert isinstance(interaction.user, discord.Member) and interaction.guild

        if interaction.guild.premium_subscriber_role not in interaction.user.roles:
            return await interaction.response.send_message("You're currently not boosting the server.", ephemeral=True)

        colour_: discord.Colour = discord.Colour.default()
        icon_ = ""

        db = await interaction.client.pool.fetchrow("SELECT * FROM booster_roles WHERE user_id = $1", interaction.user.id)
        if db is None:
            return await interaction.response.send_message(
                "You don't have a booster role, create one with `/boost role create`.", ephemeral=True
            )

        if not any((name, colour, icon, emoji)):
            return await interaction.response.send_message("You need to provide at least one argument.", ephemeral=True)

        if colour is not None:
            with suppress(ValueError):
                colour_ = discord.Colour.from_str(colour)

        if icon and emoji:
            return await interaction.response.send_message("You can not supply both `icon` and `emoji`.", ephemeral=True)

        if emoji is not None:
            conv = await self.get_emoji(emoji)
            if conv is None:
                return await interaction.response.send_message("Could not parse that emoji.", ephemeral=True)

            icon_ = conv

        elif icon is not None:
            if icon.size > 256 * 10**3:  # 256 kB
                return await interaction.response.send_message("The icon size needs to be less than 256kB.", ephemeral=True)

            icon_ = await icon.read()

        role = interaction.guild.get_role(db["role_id"])
        assert role

        role = await role.edit(
            name=name or MISSING,
            colour=colour_ if colour_ != discord.Colour.default() else MISSING,
            display_icon=icon_ or MISSING,
        )

        assert role

        query = """
            UPDATE booster_roles
                SET role_name = $1,
                    role_colour = $2,
                    role_icon = $3
                WHERE role_id = $4
            RETURNING *
        """

        db = await interaction.client.pool.fetchrow(
            query, role.name, str(role.colour), role.icon and await role.icon.read(), role.id
        )

        assert db

        embed: Optional[discord.Embed] = MISSING
        role_icon: Optional[discord.File] = MISSING
        if role.icon is not None:
            role_icon = discord.File(filename=f"icon.png", fp=BytesIO(db["role_icon"]))
            embed = discord.Embed().set_thumbnail(url="attachment://icon.png")

        text = (
            f"Successfully edited {role.mention}"
            f"\nName: {role}"
            f"\nColor: {db['role_colour'].upper()}"
        )
        await interaction.response.send_message(text, file=role_icon or MISSING, embed=embed or MISSING)

    @role.command()
    async def delete(self, interaction: Interaction):
        """Deletes your boost role."""
        db = await interaction.client.pool.fetchrow("SELECT * FROM booster_roles WHERE user_id = $1", interaction.user.id)

        if db is None:
            return await interaction.response.send_message("You don't have a boost role.", ephemeral=True)

        assert interaction.guild

        role = interaction.guild.get_role(db["role_id"])
        assert role

        await role.delete(reason=f"Nitro Boost Expired: {interaction.user}")
            
        await interaction.client.pool.execute("DELETE FROM booster_roles WHERE user_id = $1", interaction.user.id)
        await interaction.response.send_message("Successfully deleted your boost role.")
