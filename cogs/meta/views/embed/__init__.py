from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Optional

import asyncpg
import discord
from discord import ButtonStyle
from discord.ext import commands

import utils

from ...tags import TagsFromFetchedPageSource
from .modals import (
    AddFieldModal,
    ChooseATagName,
    EditAuthorModal,
    EditEmbedModal,
    EditFieldModal,
    EditFooterModal,
    EditWithModalButton,
)

if TYPE_CHECKING:
    from bot import HideoutManager

    from ... import Information

    BotInteraction = discord.Interaction[HideoutManager]


class Embed(discord.Embed):
    def __bool__(self) -> bool:
        return any(
            (
                self.title,
                self.url,
                self.description,
                self.fields,
                self.timestamp,
                self.author,
                self.thumbnail,
                self.footer,
                self.image,
            )
        )


class TagsWithOptionalOwners(TagsFromFetchedPageSource):
    def __init__(self, *args, **kwargs):
        self.bot: HideoutManager = kwargs.pop('bot')
        super().__init__(*args, **kwargs, colour=self.bot.color)

    def format_records(self, records: enumerate[asyncpg.Record]) -> str:
        ret = []
        for idx, tag in records:
            if 'owned' in tag.keys() and not tag['owned']:
                ret.append(f"{idx}. {tag['name']} (Owner: {str(self.bot.get_user(tag['owner_id']))})")
            else:
                ret.append(f"{idx}. {tag['name']}")
        return '\n'.join(ret)


class TagSelector(discord.ui.Select['TagSelectorMenu']):
    async def callback(self, interaction: BotInteraction):
        await interaction.response.defer()
        tag_id = self.values[0]
        assert self.view
        try:
            tag = await self.view.parent.cog.get_tag(int(tag_id), guild_id=None)
        except commands.BadArgument:
            return await interaction.followup.send('Tag not found... somehow.', ephemeral=True)
        async with interaction.client.safe_connection() as conn:
            await tag.edit(embed=self.view.parent.embed, content=tag.content, connection=conn)
        await interaction.edit_original_response(content=f'Added embed to tag {tag.name}', embed=None, view=None)
        self.view.stop()
        self.view.parent.stop()


class TagSelectorMenu(utils.ViewMenuPages):
    if TYPE_CHECKING:
        source: TagsFromFetchedPageSource

    def __init__(self, source: TagsFromFetchedPageSource, *, ctx: discord.Interaction[HideoutManager], parent: EmbedEditor):
        super().__init__(source, ctx=ctx, compact=True)
        self.parent = parent

    def fill_items(self) -> None:
        super().fill_items()
        if not self.children:
            self.add_item(self.go_to_parent)
        self.tag_selector = TagSelector()
        self.add_item(self.tag_selector)
        self.add_item(self.new_tag)

    def _update_labels(self, page_number: int) -> None:
        super()._update_labels(page_number)
        self.tag_selector.options = [
            discord.SelectOption(label=entry['name'][:100], value=str(entry['id']))
            for entry in self.source.entries[page_number * self.source.per_page : (page_number + 1) * self.source.per_page]
        ]

    @discord.ui.button(label='Go Back', style=discord.ButtonStyle.red)
    async def stop_pages(self, interaction: discord.Interaction, button: discord.ui.Button):
        """stops the pagination session."""
        await interaction.response.edit_message(embed=self.parent.current_embed, view=self.parent)
        self.stop()

    @discord.ui.button(label='Go Back', row=4)
    async def go_to_parent(self, interaction: BotInteraction, button: discord.ui.Button):
        await interaction.response.edit_message(view=self.parent)
        self.stop()

    @discord.ui.button(label='Add to new tag', row=4)
    async def new_tag(self, interaction: BotInteraction, button: discord.ui.Button):
        await interaction.response.send_modal(ChooseATagName(self.parent, title='Create a new tag.'))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        val = await super().interaction_check(interaction)
        if val:
            self.parent.timeout = 600
        return val

    async def on_timeout(self) -> None:
        self.ctx.client.views.discard(self)
        if self.message:
            try:
                await self.message.edit(view=self.parent)
            except discord.NotFound:
                pass


class UndoView(utils.View):
    def __init__(self, parent: 'EmbedEditor'):
        self.parent = parent
        super().__init__(timeout=10)

    @discord.ui.button(label='Undo deletion.')
    async def undo(self, interaction: BotInteraction, button: discord.ui.Button):
        self.stop()
        await interaction.channel.send(view=self.parent, embed=self.parent.current_embed)  # type: ignore
        await interaction.response.edit_message(view=None)
        await interaction.delete_original_response()

    async def on_timeout(self) -> None:
        self.parent.stop()


class DeleteButton(discord.ui.Button['EmbedEditor']):
    async def callback(self, interaction: BotInteraction):
        if interaction.message:
            await interaction.message.delete()
        await interaction.response.send_message(
            'Done!\n*This message goes away in 10 seconds*\n*You can use this to recover your progress.*',
            view=UndoView(self.view),  # type: ignore
            delete_after=10,
            ephemeral=True,
        )


class DeleteFieldWithSelect(utils.View):
    def __init__(self, parent_view: EmbedEditor):
        self.parent = parent_view
        super().__init__(timeout=300, bot=parent_view.bot)
        self.update_options()

    def update_options(self):
        self.pick_field.options = []
        for i, field in enumerate(self.parent.embed.fields):
            self.pick_field.add_option(label=f"{i + 1}) {field.name or ''[0:500]}", value=str(i))

    @discord.ui.select(placeholder='Select a field to delete.')
    async def pick_field(self, interaction: BotInteraction, select: discord.ui.Select):
        index = int(select.values[0])
        self.parent.embed.remove_field(index)
        await self.parent.update_buttons()
        await interaction.response.edit_message(embed=self.parent.current_embed, view=self.parent)
        self.stop()

    @discord.ui.button(label='Go back')
    async def cancel(self, interaction: BotInteraction, button: discord.ui.Button):
        await interaction.response.edit_message(view=self.parent)
        self.stop()

    async def on_timeout(self) -> None:
        if self.parent.message:
            await self.parent.message.edit(view=self.parent)


class EditFieldSelect(utils.View):
    def __init__(self, parent_view: EmbedEditor):
        self.parent = parent_view
        super().__init__(timeout=300, bot=parent_view.bot)
        for i, field in enumerate(parent_view.embed.fields):
            self.pick_field.add_option(label=f"{i + 1}) {field.name or ''[0:500]}", value=str(i))

    @discord.ui.select(placeholder='Select a field to edit.')
    async def pick_field(self, interaction: BotInteraction, select: discord.ui.Select):
        index = int(select.values[0])
        self.parent.timeout = 600
        await interaction.response.send_modal(EditFieldModal(self.parent, index))
        self.stop()

    @discord.ui.button(label='Go back')
    async def cancel(self, interaction: BotInteraction, button: discord.ui.Button):
        await interaction.response.edit_message(view=self.parent)
        self.stop()

    async def on_timeout(self) -> None:
        if self.parent.message:
            await self.parent.message.edit(view=self.parent)


class SendToView(utils.View):
    def __init__(self, *, parent: EmbedEditor):
        self.parent = parent
        super().__init__(timeout=300, bot=parent.cog.bot)

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[
            discord.ChannelType.text,
            discord.ChannelType.news,
            discord.ChannelType.voice,
            discord.ChannelType.private_thread,
            discord.ChannelType.public_thread,
        ],
    )
    async def pick_a_channel(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        await interaction.response.defer(ephemeral=True)
        channel = select.values[0]
        if not isinstance(interaction.user, discord.Member) or not interaction.guild:
            return await interaction.followup.send(
                'for some reason, discord thinks you are not a member of this server...', ephemeral=True
            )
        channel = interaction.guild.get_channel_or_thread(channel.id)
        if not isinstance(channel, discord.abc.Messageable):
            return await interaction.followup.send('That channel does not exist... somehow.', ephemeral=True)
        if not channel.permissions_for(interaction.user).send_messages:
            return await interaction.followup.send('You cannot send messages in that channel.', ephemeral=True)
        await channel.send(embed=self.parent.embed)
        await interaction.delete_original_response()
        await interaction.followup.send('Sent!', ephemeral=True)
        self.stop()

    @discord.ui.button(label='Go Back')
    async def stop_pages(self, interaction: discord.Interaction, button: discord.ui.Button):
        """stops the pagination session."""
        await interaction.response.edit_message(embed=self.parent.current_embed, view=self.parent)
        self.stop()

    async def on_timeout(self) -> None:
        self.parent.cog.bot.views.discard(self)
        if self.parent.message:
            try:
                await self.parent.message.edit(view=self.parent)
            except discord.NotFound:
                pass


class EmbedEditor(utils.View):
    def __init__(self, owner: discord.Member, cog: Information, *, timeout: Optional[float] = 600):
        self.cog: Information = cog
        self.owner: discord.Member = owner
        self.embed = Embed()
        self.showing_help = False
        self.message: Optional[discord.Message] = None
        super().__init__(timeout=timeout, bot=cog.bot)
        self.clear_items()
        self.add_items()

    @staticmethod
    def shorten(_embed: discord.Embed):
        embed = Embed.from_dict(deepcopy(_embed.to_dict()))
        while len(embed) > 6000 and embed.fields:
            embed.remove_field(-1)
        if len(embed) > 6000 and embed.description:
            embed.description = embed.description[: (len(embed.description) - (len(embed) - 6000))]
        return embed

    @property
    def current_embed(self) -> discord.Embed:
        if self.showing_help:
            return self.help_embed()
        if self.embed:
            if len(self.embed) < 6000:
                return self.embed
            else:
                return self.shorten(self.embed)
        return self.help_embed()

    async def interaction_check(self, interaction: BotInteraction, /):
        if interaction.user == self.owner:
            return True
        await interaction.response.send_message('This is not your menu.', ephemeral=True)

    def add_items(self):
        """This is done this way because if not, it would get too cluttered."""
        # Row 1
        self.add_item(discord.ui.Button(label='Edit:', style=ButtonStyle.blurple, disabled=True))
        self.add_item(EditWithModalButton(EditEmbedModal, label='Embed', style=ButtonStyle.blurple))
        self.add_item(EditWithModalButton(EditAuthorModal, row=0, label='Author', style=ButtonStyle.blurple))
        self.add_item(EditWithModalButton(EditFooterModal, row=0, label='Footer', style=ButtonStyle.blurple))
        self.add_item(DeleteButton(emoji='\N{WASTEBASKET}', style=ButtonStyle.red))
        # Row 2
        self.add_item(discord.ui.Button(row=1, label='Fields:', disabled=True, style=ButtonStyle.blurple))
        self.add_fields = EditWithModalButton(AddFieldModal, row=1, emoji='\N{HEAVY PLUS SIGN}', style=ButtonStyle.green)
        self.add_item(self.add_fields)
        self.add_item(self.remove_fields)
        self.add_item(self.edit_fields)
        self.add_item(self.reorder)
        # Row 3
        self.add_item(self.send)
        self.add_item(self.send_to)
        self.add_item(self.add_to_tag)
        self.add_item(self.help_page)
        # Row 4
        self.character_count = discord.ui.Button(row=3, label='0/6,000 Characters', disabled=True)
        self.add_item(self.character_count)
        self.fields_count = discord.ui.Button(row=3, label='0/25 Total Fields', disabled=True)
        self.add_item(self.fields_count)

    async def update_buttons(self):
        fields = len(self.embed.fields)
        if fields > 25:
            self.add_fields.disabled = True
        else:
            self.add_fields.disabled = False
        if not fields:
            self.remove_fields.disabled = True
            self.edit_fields.disabled = True
            self.reorder.disabled = True
        else:
            self.remove_fields.disabled = False
            self.edit_fields.disabled = False
            self.reorder.disabled = False
            self.help_page.disabled = True
        if self.embed:
            if len(self.embed) <= 6000:
                self.send.style = ButtonStyle.green
                self.send_to.style = ButtonStyle.green
                self.add_to_tag.style = ButtonStyle.green
            else:
                self.send.style = ButtonStyle.red
                self.send_to.style = ButtonStyle.red
                self.add_to_tag.style = ButtonStyle.red
            self.help_page.disabled = False
        else:
            self.send.style = ButtonStyle.red
            self.send_to.style = ButtonStyle.red
            self.add_to_tag.style = ButtonStyle.red

        self.character_count.label = f"{len(self.embed)}/6,000 Characters"
        self.fields_count.label = f"{len(self.embed.fields)}/25 Total Fields"

        if self.showing_help:
            self.help_page.label = 'Show My Embed'
        else:
            self.help_page.label = 'Show Help Page'

    def help_embed(self) -> Embed:
        embed = Embed(
            title='__`M⬇`__ This is the embed title',
            color=self.cog.bot.color,
            description=(
                "__`M⬇`__ This is the embed description. This field "
                "**supports** __*Mark*`Down`__, which means you can "
                "use features like ~~strikethrough~~, *italics*, **bold** "
                "and `mono`, and they will be rendered!"
                "\nText that supports MarkDown have this: __`M⬇`__"
            ),
            url='https://this-is.the/title-url',
        )
        embed.add_field(name='__`M⬇`__ This is a field name.', value='and this is the value. This field is in-line.')
        embed.add_field(name='Fields per line?', value='you can have up to **3** fields in a single line!')
        embed.add_field(
            name='Here is another field, but not in-line',
            value='Fields can have up to 256 characters in the name of a field, and up to 1,024 characters in the value!',
            inline=False,
        )
        embed.add_field(
            name='How do I use this interface?',
            value=(
                'To edit parts of the embed, you just use the buttons that appear below.'
                ' I will tell you if anything you put was not valid. Leaving a text field '
                'empty will make that field be removed.'
            ),
        )
        embed.set_author(
            name='This is the author of the embed',
            icon_url='https://cdn.duck-bot.com/file/AVATAR',
            url='https://this-is.the/author-url',
        )
        embed.set_image(url='https://cdn.duck-bot.com/file/IMAGE')
        embed.set_thumbnail(url='https://cdn.duck-bot.com/file/THUMBNAIL')
        footer_text = "This is the footer, which like the author, does not support markdown."
        if not self.embed and not self.showing_help:
            footer_text += '\n💢This embed will be replaced by yours once it has characters💢'
        embed.set_footer(icon_url='https://cdn.duck-bot.com/file/ICON', text=footer_text)
        return embed

    @discord.ui.button(row=1, emoji='\N{HEAVY MINUS SIGN}', style=ButtonStyle.red, disabled=True)
    async def remove_fields(self, interaction: BotInteraction, button: discord.ui.Button):
        await interaction.response.edit_message(view=DeleteFieldWithSelect(self))

    @discord.ui.button(row=1, emoji=utils.EDIT_PENCIL, disabled=True, style=ButtonStyle.green)
    async def edit_fields(self, interaction: BotInteraction, button: discord.ui.Button):
        await interaction.response.edit_message(view=EditFieldSelect(self))

    @discord.ui.button(row=1, label='Reorder', style=ButtonStyle.blurple, disabled=True)
    async def reorder(self, interaction: BotInteraction, button: discord.ui.Button):
        return await interaction.response.send_message(
            f'This function is currently unavailable.\nPlease use {self.cog.bot.constants.EDIT_PENCIL} and edit the `index`',
            ephemeral=True,
        )

    @discord.ui.button(label='Send', row=2, style=ButtonStyle.red)
    async def send(self, interaction: BotInteraction, button: discord.ui.Button):
        if not self.embed:
            return await interaction.response.send_message('Your embed is empty!', ephemeral=True)
        elif len(self.embed) > 6000:
            return await interaction.response.send_message(
                'You have exceeded the embed character limit (6000)', ephemeral=True
            )
        await interaction.channel.send(embed=self.embed)  # type: ignore
        await interaction.response.defer()
        await interaction.delete_original_response()

    @discord.ui.button(label='Send To', row=2, style=ButtonStyle.red)
    async def send_to(self, interaction: BotInteraction, button: discord.ui.Button):
        if not self.embed:
            return await interaction.response.send_message('Your embed is empty!', ephemeral=True)
        elif len(self.embed) > 6000:
            return await interaction.response.send_message(
                'You have exceeded the embed character limit (6000)', ephemeral=True
            )
        await interaction.response.edit_message(view=SendToView(parent=self))

    @discord.ui.button(label='Add To Tag', row=2, style=ButtonStyle.red)
    async def add_to_tag(self, interaction: BotInteraction, button: discord.ui.Button):
        if not self.embed:
            return await interaction.response.send_message('Your embed is empty!', ephemeral=True)
        elif len(self.embed) > 6000:
            return await interaction.response.send_message(
                'You have exceeded the embed character limit (6000)', ephemeral=True
            )
        if isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_guild:
            tags = await self.cog.bot.pool.fetch(
                """
                SELECT 
                    name, 
                    id,
                    owner_id,
                    CASE WHEN owner_id = $1 THEN true 
                         ELSE false 
                    END as owned
                FROM tags 
                WHERE 
                    points_to ISNULL 
                    AND guild_id = $2 
                ORDER BY
                    CASE WHEN name LIKE 'topic:%' THEN 0
                         WHEN owner_id = $1 THEN 1 
                         ELSE 2 
                    END,
                    name;   
                """,
                self.owner.id,
                self.owner.guild.id,
            )
        else:
            tags = await self.cog.bot.pool.fetch(
                'SELECT name, id FROM tags WHERE points_to ISNULL AND owner_id = $1 AND guild_id = $2 ORDER BY NAME',
                self.owner.id,
                self.owner.guild.id,
            )
        if not tags:
            return await interaction.response.send_modal(ChooseATagName(self, title='You do not have any tags'))
        source = TagsWithOptionalOwners(tags, member=self.owner, bot=self.cog.bot)
        menu = TagSelectorMenu(source, ctx=interaction, parent=self)
        await menu.start(edit_interaction=True)

    @discord.ui.button(label='Show Help Page', row=2, disabled=True)
    async def help_page(self, interaction: BotInteraction, button: discord.ui.Button):
        self.showing_help = not self.showing_help
        await self.update_buttons()
        await interaction.response.edit_message(embed=self.current_embed, view=self)

    async def on_timeout(self) -> None:
        if self.message:
            if self.embed:
                await self.message.edit(view=None)
            else:
                await self.message.delete()
