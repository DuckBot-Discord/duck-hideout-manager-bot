from typing import Self

import discord
from discord import app_commands

from utils import github, HideoutCog
from bot import HideoutManager


EXCLUDED = ['LICENSE', 'README.md', '.gitignore']


class SelectAMessageView(discord.ui.View):
    def __init__(self, nodes: list[github.TreeNode], message: discord.Message):
        self.message = message
        self.nodes = nodes
        super().__init__()
        self.select_a_file.options = [
            discord.SelectOption(label=n.path) for n in sorted(nodes, key=lambda n: n.path) if n.path not in EXCLUDED
        ]

    @discord.ui.select(placeholder='Select a file...')
    async def select_a_file(self, interaction: discord.Interaction, selecet: discord.ui.Select[Self]):
        await interaction.response.edit_message(content='Please wait...', view=None, delete_after=20)
        node = discord.utils.get(self.nodes, path=selecet.values[0])
        if not node:
            return await interaction.edit_original_response(content='node not found somehow.')
        data = await node.fetch_filedata()
        if isinstance(data, list):
            return await interaction.edit_original_response(content='node is a folder.')
        try:
            content = data.decode()
            await self.message.edit(content='\n'.join(line.removesuffix('\\') for line in content.splitlines()))
        except discord.HTTPException as e:
            await interaction.edit_original_response(content=f"__**Failed to edit the message:**__\n{type(e).__name__}: {e}")
        else:
            await interaction.edit_original_response(content='done, edited!')


class CouncilMessages(HideoutCog):
    async def cog_load(self) -> None:
        self.repo = await self.bot.github.fetch_repo('DuckBot-Discord', 'council-messages')
        self.update_public_message = app_commands.ContextMenu(
            name='Update Message',
            callback=self.update_public_message_ctx_menu_callback,
        )
        self.update_public_message.default_permissions = discord.Permissions(manage_guild=True)
        self.bot.tree.add_command(self.update_public_message)
        return await super().cog_load()

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.update_public_message.name, type=self.update_public_message.type)
        return await super().cog_unload()

    async def update_public_message_ctx_menu_callback(
        self, interaction: discord.Interaction[HideoutManager], message: discord.Message
    ):
        if message.author != self.bot.user:
            return await interaction.response.send_message('That message was not sent by me.', ephemeral=True)
        await interaction.response.defer(thinking=True, ephemeral=True)
        tree = await self.repo.fetch_tree()
        nodes = [node for node in tree if node.type == 'blob']
        view = SelectAMessageView(nodes, message=message)
        await interaction.followup.send('Select a file.', view=view)
