from __future__ import annotations

import logging
import typing
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple, Self

import discord
from discord.ext import menus
from discord.ui import Modal, TextInput

from .context import HideoutContext

if TYPE_CHECKING:
    from bot import HideoutManager

__all__: Tuple[str, ...] = ("ViewMenuPages",)


log = logging.getLogger('HideoutManager.paginators')  # noqa


class SkipToModal(Modal, title='Skip to page...'):
    page = TextInput[Self](
        label='Which page do you want to skip to?', max_length=10, placeholder='This prompt times out in 20 seconds...'
    )

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self.value = None
        self.interaction: typing.Optional[discord.Interaction] = None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.interaction = interaction
        self.value = self.page.value


class ViewMenuPages(discord.ui.View):
    # This Source Code Form is subject to the terms of the Mozilla Public
    # License, v. 2.0. If a copy of the MPL was not distributed with this
    # file, You can obtain one at http://mozilla.org/MPL/2.0/.
    #
    # Modified version of the RoboPages class, from R. Danny, source/credits:
    # https://github.com/Rapptz/RoboDanny/blob/rewrite/cogs/utils/paginator.py

    def __init__(
        self,
        source: menus.PageSource,
        *,
        ctx: HideoutContext | discord.Interaction[HideoutManager],
        check_embeds: bool = True,
        compact: bool = False,
    ):
        super().__init__()
        self.current_modal: typing.Optional[SkipToModal] = None
        self.source: menus.PageSource = source
        self.check_embeds: bool = check_embeds
        self.ctx: HideoutContext | discord.Interaction[HideoutManager] = ctx
        self.message: Optional[discord.Message] = None
        self.current_page: int = 0
        self.compact: bool = compact
        self.clear_items()
        self.fill_items()

    def fill_items(self) -> None:
        if not self.compact:
            self.numbered_page.row = 1
            self.stop_pages.row = 1

        if self.source.is_paginating():
            max_pages = self.source.get_max_pages()
            use_last_and_first = max_pages is not None and max_pages >= 2
            if use_last_and_first:
                self.add_item(self.go_to_first_page)
            self.add_item(self.go_to_previous_page)
            if not self.compact:
                self.add_item(self.go_to_current_page)
            self.add_item(self.go_to_next_page)
            if use_last_and_first:
                self.add_item(self.go_to_last_page)
            if not self.compact:
                self.add_item(self.numbered_page)
            self.add_item(self.stop_pages)

    async def _get_kwargs_from_page(self, page: int) -> Dict[str, Any]:
        # fmt: off
        value: dict[str, Any] | str | discord.Embed | Any = await discord.utils.maybe_coroutine(self.source.format_page, self, page)  # pyright: reportUnknownArgumentType=false
        if isinstance(value, dict):
            return value
        elif isinstance(value, str):
            return {'content': value, 'embed': None}
        elif isinstance(value, discord.Embed):
            return {'embed': value, 'content': None}
        else:
            return {}

    async def show_page(self, interaction: discord.Interaction, page_number: int) -> None:
        page: Any = await self.source.get_page(page_number)
        self.current_page = page_number
        kwargs = await self._get_kwargs_from_page(page)
        self._update_labels(page_number)
        if kwargs:
            if interaction.response.is_done():
                if self.message:
                    await self.message.edit(**kwargs, view=self)
            else:
                await interaction.response.edit_message(**kwargs, view=self)

    def _update_labels(self, page_number: int) -> None:
        self.go_to_first_page.disabled = page_number == 0
        if self.compact:
            max_pages = self.source.get_max_pages()
            self.go_to_last_page.disabled = max_pages is None or (page_number + 1) >= max_pages
            self.go_to_next_page.disabled = max_pages is not None and (page_number + 1) >= max_pages
            self.go_to_previous_page.disabled = page_number == 0
            return

        self.go_to_current_page.label = str(page_number + 1)
        self.go_to_previous_page.label = str(page_number)
        self.go_to_next_page.label = str(page_number + 2)
        self.go_to_next_page.disabled = False
        self.go_to_previous_page.disabled = False
        self.go_to_first_page.disabled = False

        max_pages = self.source.get_max_pages()
        if max_pages is not None:
            self.go_to_last_page.disabled = (page_number + 1) >= max_pages
            if (page_number + 1) >= max_pages:
                self.go_to_next_page.disabled = True
                self.go_to_next_page.label = '…'
            if page_number == 0:
                self.go_to_previous_page.disabled = True
                self.go_to_previous_page.label = '…'

    async def show_checked_page(self, interaction: discord.Interaction, page_number: int) -> None:
        max_pages = self.source.get_max_pages()
        try:
            if max_pages is None:
                # If it doesn't give maximum pages, it cannot be checked
                await self.show_page(interaction, page_number)
            elif max_pages > page_number >= 0:
                await self.show_page(interaction, page_number)
        except IndexError:
            # An error happened that can be handled, so ignore it.
            pass

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user and interaction.user.id in (self.ctx.client.owner_id, self.ctx.user.id):
            return True
        await interaction.response.send_message('This pagination menu cannot be controlled by you, sorry!', ephemeral=True)
        return False

    async def on_timeout(self) -> None:
        self.ctx.client.views.discard(self)
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.NotFound:
                pass

    def stop(self) -> None:
        self.ctx.client.views.discard(self)
        super().stop()

    async def on_error(self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item[Self], /) -> None:
        if interaction.response.is_done():
            await interaction.followup.send('An unknown error occurred, sorry', ephemeral=True)
        else:
            await interaction.response.send_message('An unknown error occurred, sorry', ephemeral=True)
        await self.ctx.client.exceptions.add_error(error=error, ctx=self.ctx)

    async def start(self, edit_interaction: bool = False) -> None:
        if self.check_embeds and not self.ctx.channel.permissions_for(self.ctx.guild.me).embed_links:  # type: ignore
            if isinstance(self.ctx, HideoutContext):
                await self.ctx.send('Bot does not have embed links permission in this channel.')
            else:
                if self.ctx.response.is_done():
                    await self.ctx.followup.send('Bot does not have embed links permission in this channel.')
            return

        await self.source._prepare_once()  # pyright: reportPrivateUsage=false
        page: Any = await self.source.get_page(0)  # pyright: reportUnknownMemberType=false
        kwargs = await self._get_kwargs_from_page(page)
        self._update_labels(0)
        if isinstance(self.ctx, HideoutContext):
            self.message = await self.ctx.send(**kwargs, view=self)
        else:
            if edit_interaction:
                await self.ctx.response.edit_message(**kwargs, view=self)
            else:
                await self.ctx.response.send_message(**kwargs, view=self)
            self.message = await self.ctx.original_response()
        self.ctx.client.views.add(self)

    @discord.ui.button(label='≪', style=discord.ButtonStyle.grey)
    async def go_to_first_page(self, interaction: discord.Interaction, button: discord.ui.Button[Self]):
        """go to the first page"""
        await self.show_page(interaction, 0)

    @discord.ui.button(label='Back', style=discord.ButtonStyle.blurple)
    async def go_to_previous_page(self, interaction: discord.Interaction, button: discord.ui.Button[Self]):
        """go to the previous page"""
        await self.show_checked_page(interaction, self.current_page - 1)

    @discord.ui.button(label='Current', style=discord.ButtonStyle.grey, disabled=True)
    async def go_to_current_page(self, interaction: discord.Interaction, button: discord.ui.Button[Self]):
        pass

    @discord.ui.button(label='Next', style=discord.ButtonStyle.blurple)
    async def go_to_next_page(self, interaction: discord.Interaction, button: discord.ui.Button[Self]):
        """go to the next page"""
        await self.show_checked_page(interaction, self.current_page + 1)

    @discord.ui.button(label='≫', style=discord.ButtonStyle.grey)
    async def go_to_last_page(self, interaction: discord.Interaction, button: discord.ui.Button[Self]):
        """go to the last page"""
        # The call here is safe because it's guarded by skip_if
        await self.show_page(interaction, self.source.get_max_pages() - 1)  # type: ignore

    @discord.ui.button(label='Skip to page...', style=discord.ButtonStyle.grey)
    async def numbered_page(self, interaction: discord.Interaction, button: discord.ui.Button[Self]):
        """lets you type a page number to go to"""
        if self.current_modal is not None and not self.current_modal.is_finished():
            self.current_modal.stop()

        self.current_modal = SkipToModal(timeout=20)
        await interaction.response.send_modal(self.current_modal)
        timed_out = await self.current_modal.wait()

        if timed_out:
            await interaction.followup.send('Took too long.', ephemeral=True)
        elif self.current_modal.interaction is None:
            return
        else:
            try:
                page = int(self.current_modal.value)  # type: ignore
            except ValueError:
                await self.current_modal.interaction.response.send_message('Invalid page number.', ephemeral=True)
            else:
                await self.current_modal.interaction.response.defer()
                await self.show_checked_page(interaction, page - 1)

    @discord.ui.button(label='Quit', style=discord.ButtonStyle.red)
    async def stop_pages(self, interaction: discord.Interaction, button: discord.ui.Button[Self]):
        """stops the pagination session."""
        await interaction.response.defer()
        await interaction.delete_original_response()
        self.stop()
