from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Sequence, Tuple, TypeVar, Union, overload

import discord
from discord.ext import commands

from utils.helpers import View

if TYPE_CHECKING:
    from discord import AllowedMentions, Embed, File, Message, MessageReference, PartialMessage
    from discord.message import Message

    from bot import HideoutManager


__all__: Tuple[str, ...] = ('HideoutContext', 'HideoutGuildContext', 'ConfirmationView')

BotT = TypeVar('BotT', bound='HideoutManager')


class ConfirmationView(View):
    def __init__(self, ctx: HideoutContext, *, owner_id: Optional[int] = None, timeout: int = 60) -> None:
        super().__init__(timeout=timeout, bot=ctx.bot)
        self.owner_id = owner_id or ctx.author.id
        self.ctx = ctx
        self.value = None
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.owner_id

    async def on_timeout(self) -> None:
        if self.message:
            for item in self.children:
                item.disabled = True  # type: ignore

            await self.message.edit(content=f'Timed out waiting for a response from <@{self.owner_id}>.', view=self)

    @discord.ui.button(label='Confirm', style=discord.ButtonStyle.primary)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button[ConfirmationView]) -> None:
        await interaction.response.defer()

        self.value = True
        self.stop()
        await interaction.delete_original_response()

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button[ConfirmationView]) -> None:
        await interaction.response.defer()
        self.value = False
        self.stop()

        await interaction.delete_original_response()


class HideoutContext(commands.Context['HideoutManager']):
    """The subclassed Context to allow some extra functionality."""

    __slots__: Tuple[str, ...] = ()

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.is_error_handled = False

    @property
    def user(self):
        return self.author

    @property
    def client(self):
        return self.bot

    @property
    def created_at(self):
        return self.message.created_at

    @property
    def channel_id(self):
        return self.channel.id

    @discord.utils.cached_property
    def color(self) -> discord.Color:
        """:class:`~discord.Color`: Returns HideoutManager's color, or the author's color. Falls back to blurple"""

        def check(color: discord.Color):
            return color not in {discord.Color.default(), None}

        checks = (
            me_color if check(me_color := self.me.color) else None,
            you_color if check(you_color := self.author.color) else None,
            self.bot.color,
        )

        result = discord.utils.find(lambda e: e, checks)
        if not result:
            raise RuntimeError('Unreachable code has been reached')

        return result

    @overload
    async def send(  # type: ignore
        self,
        content: Optional[str] = None,
        *,
        tts: bool = False,
        embed: Optional[Embed] = None,
        embeds: Optional[Sequence[Embed]] = None,
        file: Optional[File] = None,
        files: Optional[Sequence[File]] = None,
        delete_after: Optional[float] = None,
        nonce: Optional[Union[str, int]] = None,
        allowed_mentions: Optional[AllowedMentions] = None,
        reference: Optional[Union[Message, MessageReference, PartialMessage]] = None,
        mention_author: Optional[bool] = None,
        view: Optional[discord.ui.View] = None,
        suppress_embeds: bool = False,
        ephemeral: bool = False,
    ) -> Message:
        ...

    async def send(self, content: str | None = None, **kwargs: Any) -> Message:
        """|coro|

        Sends a message to the invoking context's channel.

        View :meth:`~discord.ext.commands.Context.send` for more information of parameters.

        Returns
        -------
        :class:`~discord.Message`
            The message that was created.
        """
        if kwargs.get('embed') and kwargs.get('embeds'):
            raise ValueError('Cannot send both embed and embeds')

        embeds = kwargs.pop('embeds', []) or ([kwargs.pop('embed')] if kwargs.get('embed', None) else [])
        if embeds:
            for embed in embeds:
                if embed.color is None:
                    # Made this the bot's vanity colour, although we'll
                    # be keeping self.color for other stuff like userinfo
                    embed.color = self.bot.color

            kwargs['embeds'] = embeds

        if kwargs.get('view') and kwargs.get('delete_button'):
            raise TypeError("'view' and 'delete_button' cannot be passed together.")

        return await super().send(content, **kwargs)

    async def confirm(
        self,
        content: str | None = None,
        /,
        *,
        owner: Optional[int] = None,
        timeout: int = 30,
        delete_after: bool = True,
        **kwargs: Any,
    ) -> bool | None:
        """|coro|

        Prompts a confirmation message that users can confirm or deny.

        Parameters
        ----------
        content: str | None
            The content of the message. Can be an embed.
        owner: int | None
            The owner of this view. Defaults to ctx.author.id
        timeout: int | None
            The timeout for the confirmation.
        kwargs:
            Additional keyword arguments to pass to `self.send`.

        Returns
        -------
        :class:`bool`
            Whether the user confirmed or not.
            None if the view timed out.
        """
        view = ConfirmationView(self, timeout=timeout, owner_id=owner)
        try:
            view.message = await self.channel.send(content, **kwargs, view=view)
            await view.wait()
            return view.value
        except discord.HTTPException:
            view.stop()
            return None

    @discord.utils.cached_property
    def reference(self) -> discord.Message | None:
        if not self.message:
            return None
        if not self.message.reference:
            return None
        resolved = self.message.reference.resolved
        if not isinstance(resolved, discord.Message):
            return None
        return resolved


class HideoutGuildContext(HideoutContext):
    if TYPE_CHECKING:
        guild: discord.Guild
        author: discord.Member


async def setup(bot: HideoutManager) -> None:
    """Sets up the HideoutContext class.

    Parameters
    ----------
    bot: HideoutManager
        The bot to set up the HideoutContext class for.
    """
    bot.context_class = HideoutContext


async def teardown(bot: HideoutManager) -> None:
    """Tears down the HideoutContext class.

    Parameters
    ----------
    bot: HideoutManager
        The bot to tear down the HideoutContext class for.
    """
    bot.context_class = commands.Context
