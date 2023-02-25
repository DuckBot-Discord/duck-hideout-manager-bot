from re import Pattern, compile
from functools import partial

import discord
from discord.ext import commands

from utils import HideoutCog


class DiscordEvents(HideoutCog):
    REACTION_ROLES_BUTTON_REGEX: Pattern[str] = compile(r'RR::BUTTON::(?P<ROLE_ID>\d+)')

    @commands.Cog.listener('on_interaction')
    async def on_reaction_role(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return
        custom_id = (interaction.data or {}).get('custom_id', '')
        match = self.REACTION_ROLES_BUTTON_REGEX.fullmatch(custom_id)

        if match:
            role_id = int(match.group('ROLE_ID'))
            role = interaction.guild.get_role(role_id)
            if not role:
                return await interaction.response.send_message(
                    'Sorry, that role does not seem to exist anymore...', ephemeral=True
                )

            meth, message = (
                (partial(interaction.user.add_roles, atomic=True), 'Gave you the role **{}**')
                if role not in interaction.user.roles
                else (partial(interaction.user.remove_roles, atomic=True), 'Removed the role **{}**')
            )
            try:
                await meth(role)
            except discord.HTTPException as e:
                return await interaction.response.send_message(f"Failed to assign role: {e.text}", ephemeral=True)
            await interaction.response.send_message(message.format(role.name), ephemeral=True)
