from __future__ import annotations

import asyncio
import concurrent.futures
import logging

import random
import re
import sys
from collections import defaultdict
from typing import (
    TYPE_CHECKING,
    Generator,
    Optional,
    Sequence,
    Set,
    TypeVar,
    Type,
    Generic,
    Tuple,
    Any,
    Union,
    DefaultDict,
    overload,
)

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands

from utils import (
    constants,
    HideoutContext,
    HideoutExceptionManager,
    col,
    human_timedelta,
    TimerManager,
)
from utils.errors import *

try:
    from typing import ParamSpec
except ImportError:
    from typing_extensions import ParamSpec

if TYPE_CHECKING:
    from asyncpg import Pool, Connection
    from asyncpg.transaction import Transaction
    from aiohttp import ClientSession
    import datetime

DBT = TypeVar('DBT', bound='HideoutManager')
DCT = TypeVar('DCT', bound='HideoutContext')
T = TypeVar('T')
P = ParamSpec('P')

log = logging.getLogger('HideoutManager.main')

initial_extensions: Tuple[str, ...] = (
    # Helpers
    'utils.jishaku',
    'utils.context',
    'utils.command_errors',
    # Cogs
    'cogs.meta',
    'cogs.owner',
    'cogs.tags',
    'cogs.hideout',
)


class DbTempContextManager(Generic[DBT]):
    """A class to handle a short term pool connection.

    .. code-block:: python3

        async with DbTempContextManager(bot, 'postgresql://user:password@localhost/database') as pool:
            async with pool.acquire() as conn:
                await conn.execute('SELECT * FROM table')

    Attributes
    ----------
    bot: Type[:class:`HideoutManager`]
        A class reference to HideoutManager.
    uri: :class:`str`
        The URI to connect to the database with.
    """

    __slots__: Tuple[str, ...] = ('bot', 'uri', '_pool')

    def __init__(self, bot: Type[DBT], uri: str) -> None:
        self.bot: Type[DBT] = bot
        self.uri: str = uri
        self._pool: Optional[asyncpg.Pool] = None

    async def __aenter__(self) -> asyncpg.Pool:
        self._pool = pool = await self.bot.setup_pool(uri=self.uri)
        return pool

    async def __aexit__(self, *args) -> None:
        if self._pool:
            await self._pool.close()


class DbContextManager(Generic[DBT]):
    """A simple context manager used to manage database connections.

    .. note::

        Please note this was created instead of using `contextlib.asynccontextmanager` because
        I plan to add additional functionality to this class in the future.

    Attributes
    ----------
    bot: :class:`HideoutManager`
        The bot instance.
    timeout: :class:`float`
        The timeout for acquiring a connection.
    """

    __slots__: Tuple[str, ...] = ('bot', 'timeout', '_pool', '_conn', '_tr')

    def __init__(self, bot: DBT, *, timeout: float = 10.0) -> None:
        self.bot: DBT = bot
        self.timeout: float = timeout
        self._pool: asyncpg.Pool = bot.pool
        self._conn: Optional[Connection] = None
        self._tr: Optional[Transaction] = None

    async def acquire(self) -> Connection:
        return await self.__aenter__()

    async def release(self) -> None:
        return await self.__aexit__(None, None, None)

    async def __aenter__(self) -> Connection:
        self._conn = conn = await self._pool.acquire(timeout=self.timeout)
        self._tr = conn.transaction()
        await self._tr.start()
        return conn

    async def __aexit__(self, exc_type, exc, tb):
        if exc and self._tr:
            await self._tr.rollback()

        elif not exc and self._tr:
            await self._tr.commit()

        if self._conn:
            await self._pool.release(self._conn)


class HideoutHelper(TimerManager):
    def __init__(self, *, bot: HideoutManager) -> None:
        super().__init__(bot=bot)

    @overload
    @staticmethod
    def chunker(item: str, *, size: int = 2000) -> Generator[str, None, None]:
        ...

    @overload
    @staticmethod
    def chunker(item: Sequence[T], *, size: int = 2000) -> Generator[Sequence[T], None, None]:
        ...

    @staticmethod
    def chunker(item: Union[str, Sequence[T]], *, size: int = 2000) -> Generator[Union[str, Sequence[T]], None, None]:
        """Split a string into chunks of a given size.

        Parameters
        ----------
        item: :class:`str`
            The string to split.
        size: :class:`int`
            The size of each chunk. Defaults to 2000.
        """
        for i in range(0, len(item), size):
            yield item[i : i + size]

    def validate_locale(self, locale: str | discord.Locale | None, default: str = 'en_us') -> str:
        """Validate a locale.

        Parameters
        ----------
        locale: :class:`str`
            The locale to validate.

        Returns
        -------
        :class:`bool`
            Whether or not the locale is valid.
        """
        locale = str(locale).lower().replace('-', '_')
        if locale not in self.bot.allowed_locales:
            locale = self.validate_locale(default)
        return locale

class HideoutManager(commands.AutoShardedBot, HideoutHelper):
    if TYPE_CHECKING:
        user: discord.ClientUser

    def __init__(self, *, session: ClientSession, pool: Pool, error_wh: str, prefix: str) -> None:
        intents = discord.Intents.all()
        intents.typing = False

        super().__init__(
            command_prefix=commands.when_mentioned_or(prefix),
            case_insensitive=True,
            allowed_mentions=discord.AllowedMentions.none(),
            intents=intents,
            activity=discord.Activity(name=f"{prefix}help", type=discord.ActivityType.listening),
            strip_after_prefix=True,
            chunk_guilds_at_startup=False,
            max_messages=4000,
            help_command=commands.DefaultHelpCommand(verify_checks=False),
        )
        self.pool: Pool = pool
        self.session: ClientSession = session
        self._context_cls: Type[commands.Context] = commands.Context
        self.error_webhook_url: Optional[str] = error_wh
        self._start_time: Optional[datetime.datetime] = None
        self.allowed_locales: Set[str] = {'en_us', 'es_es', 'it'}

        self.exceptions: HideoutExceptionManager = HideoutExceptionManager(self)
        self.thread_pool: concurrent.futures.ThreadPoolExecutor = concurrent.futures.ThreadPoolExecutor(max_workers=20)

        self.constants = constants
        self.tree.error(self.on_tree_error)

        self.views: Set[discord.ui.View] = set()
        self._auto_spam_count: DefaultDict[int, int] = defaultdict(int)

    async def setup_hook(self) -> None:
        failed = False
        for extension in initial_extensions:
            result = await self.load_extension(extension)
            failed = failed or not result

        self.tree.copy_global_to(guild=discord.Object(id=774561547930304536))

        super(HideoutHelper, self).__init__(bot=self)

    @classmethod
    def temporary_pool(cls: Type[DBT], *, uri: str) -> DbTempContextManager[DBT]:
        """:class:`DbTempContextManager` A context manager that creates a
        temporary connection pool.

        Parameters
        ----------
        uri: :class:`str`
            The URI to connect to the database with.
        """
        return DbTempContextManager(cls, uri)

    @classmethod
    async def setup_pool(cls: Type[DBT], *, uri: str, **kwargs) -> asyncpg.Pool:
        """:meth: `asyncpg.create_pool` with some extra functionality.

        Parameters
        ----------
        uri: :class:`str`
            The Postgres connection URI.
        **kwargs:
            Extra keyword arguments to pass to :meth:`asyncpg.create_pool`.
        """  # copy_doc for create_pool maybe?

        def _encode_jsonb(value):
            # noinspection PyProtectedMember
            return discord.utils._to_json(value)

        def _decode_jsonb(value):
            # noinspection PyProtectedMember
            return discord.utils._from_json(value)

        old_init = kwargs.pop('init', None)

        async def init(con):
            await con.set_type_codec(
                'jsonb', schema='pg_catalog', encoder=_encode_jsonb, decoder=_decode_jsonb, format='text'
            )
            if old_init is not None:
                await old_init(con)

        pool = await asyncpg.create_pool(uri, init=init, **kwargs)
        log.info(f"{col(2)}Successfully created connection pool.")
        assert pool is not None, 'Pool is None'
        return pool

    @property
    def start_time(self) -> datetime.datetime:
        """:class:`datetime.datetime`: The time the bot was started."""
        result = self._start_time
        if not result:
            raise HideoutManagerNotStarted('The bot has not hit on-ready yet.')

        return result

    @discord.utils.cached_property
    def mention_regex(self) -> re.Pattern:
        """:class:`re.Pattern`: A regex pattern that matches the bot's mention.

        Raises
        ------
        AttributeError
            The bot has not hit on-ready yet.
        """
        return re.compile(rf"<@!?{self.user.id}>")

    @discord.utils.cached_property
    def invite_url(self) -> str:
        """:class:`str`: The invite URL for the bot.

        Raises
        ------
        HideoutManagerNotStarted
            The bot has not hit on-ready yet.
        """
        if not self.is_ready():
            raise HideoutManagerNotStarted('The bot has not hit on-ready yet.')

        return discord.utils.oauth_url(
            self.user.id, permissions=discord.Permissions(8), scopes=('bot', 'applications.commands')
        )

    @discord.utils.cached_property
    def uptime_timestamp(self) -> str:
        """:class:`str`: The uptime of the bot in a human-readable Discord timestamp format.

        Raises
        ------
        HideoutManagerNotStarted
            The bot has not hit on-ready yet.
        """
        if not self.is_ready():
            raise HideoutManagerNotStarted('The bot has not hit on-ready yet.')

        return discord.utils.format_dt(self.start_time)

    @discord.utils.cached_property
    def color(self) -> discord.Colour:
        """:class:`~discord.Color`: The vanity color of the bot."""
        return discord.Colour(0xF4D58C)

    @discord.utils.cached_property
    def colour(self) -> discord.Colour:
        """:class:`~discord.Colour`: The vanity colour of the bot."""
        return discord.Colour(0xF4D58C)

    @property
    def human_uptime(self) -> str:
        """:class:`str`: The uptime of the bot in a human-readable format.

        Raises
        ------
        HideoutManagerNotStarted
            The bot has not hit on-ready yet.
        """
        return human_timedelta(self.start_time)

    @property
    def done_emoji(self) -> discord.PartialEmoji:
        """:class:`~discord.PartialEmoji`: The emoji used to denote a command has finished processing."""
        return discord.PartialEmoji.from_str(random.choice(self.constants.DONE))

    def safe_connection(self, *, timeout: float = 10.0) -> DbContextManager:
        """A context manager that will acquire a connection from the bot's pool.

        This will neatly manage the connection and release it back to the pool when the context is exited.

        .. code-block:: python3

            async with bot.safe_connection(timeout=10) as conn:
                await conn.execute('SELECT * FROM table')
        """
        return DbContextManager(self, timeout=timeout)

    async def get_context(self, message: discord.Message, *, cls: Type[DCT] = None) -> Union[HideoutContext, commands.Context]:
        """|coro|

        Used to get the invocation context from the message.

        Parameters
        ----------
        message: :class:`~discord.Message`
            The message to get the prefix of.
        cls: Type[:class:`HideoutContext`]
            The class to use for the context.
        """
        new_cls = cls or self._context_cls
        return await super().get_context(message, cls=new_cls)

    async def on_connect(self):
        """|coro|

        Called when the bot connects to the gateway. Used to log to console
        some basic information about the bot.
        """
        log.info(f'{col(2)}Logged in as {self.user}! ({self.user.id})')

    async def on_ready(self):
        """|coro|

        Called when the internal cache of the bot is ready, and the bot is
        connected to the gateway.
        """
        log.info(f'{col(2)}All guilds are chunked and ready to go!')
        if not self._start_time:
            self._start_time = discord.utils.utcnow()

    async def on_message(self, message: discord.Message) -> Optional[discord.Message]:
        """|coro|

        Called every time a message is received by the bot. Used to check if the message
        has mentioned the bot, and if it has return a simple response.

        Returns
        -------
        Optional[:class:`~discord.Message`]
            The message that was created for replying to the user.
        """
        if self.mention_regex.fullmatch(message.content):
            return await message.reply(
                f"My prefix is `-`!"
            )

        await self.process_commands(message)

    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        """|coro|

        Called every time a message is edited.

        Parameters
        ----------
        before: :class:`~discord.Message`
            The message before it was edited.
        after: :class:`~discord.Message`
            The message after it was edited.
        """
        if before.content != after.content and await self.is_owner(after.author):
            await self.process_commands(after)

    async def on_error(self, event: str, *args: Any, **kwargs: Any) -> None:
        """|coro|

        Called when an error is raised, and it's not from a command.

        Parameters
        ----------
        event: :class:`str`
            The name of the event that raised the exception.
        args: :class:`Any`
            The positional arguments for the event that raised the exception.
        kwargs: :class:`Any`
            The keyword arguments for the event that raised the exception.
        """
        _, error, _ = sys.exc_info()
        if not error:
            raise

        await self.exceptions.add_error(error=error)  # type: ignore
        return await super().on_error(event, *args, **kwargs)

    async def on_tree_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        command = interaction.command
        if command and getattr(command, 'on_error', None):
            return

        if self.extra_events.get('on_app_command_error'):
            return interaction.client.dispatch('app_command_error', interaction, command, error)

        raise error from None

    # This is overridden, so we don't get so many annoying type errors when passing
    # a Member into is_owner  ## Nah chai it's your shitty type checker smh!
    @discord.utils.copy_doc(commands.Bot.is_owner)
    async def is_owner(self, user: Union[discord.User, discord.Member]) -> bool:
        return await super().is_owner(user)

    async def start(self, token: str, *, reconnect: bool = True, verbose: bool = True) -> None:
        """|coro|

        Starts the bot.

        Parameters
        ----------
        token: :class:`str`
            The authentication token. Do not prefix this token with
            anything as the library will do it for you.
        reconnect: :class:`bool`
            If we should attempt reconnecting, either due to internet
            failure or a specific failure on Discord's part. Certain
            disconnects that lead to bad state will not be handled (such as
            invalid sharding payloads or bad tokens).
        verbose: :class:`bool`
            If we should log debug events. Set this to ``False`` if you want
            to reduce the verbosity of the bot when logging mode is set to
            DEBUG. Defaults to ``True``.

        """
        if verbose is False:
            _gw_log = logging.getLogger('discord.gateway')
            _gw_log.disabled = True

            _cl_log = logging.getLogger('discord.client')
            _cl_log.disabled = True

            _ht_log = logging.getLogger('discord.http')
            _ht_log.disabled = True

            _ds_log = logging.getLogger('discord.state')
            _ds_log.disabled = True

        await super().start(token, reconnect=reconnect)

    async def close(self) -> None:
        """|coro|

        Closes the websocket connection and stops the event loop.

        """
        try:
            try:
                await self.cleanup_views()
            except Exception as e:
                log.error('Could not wait for view cleanups', exc_info=e)
        finally:
            await super().close()

    async def cleanup_views(self, *, timeout: float = 5.0) -> None:
        """Cleans up the views of the bot."""
        future = await asyncio.gather(*[v.on_timeout() for v in self.views], return_exceptions=True)
        for item in future:
            if isinstance(item, Exception):
                log.debug('A view failed to clean up', exc_info=item)

    @staticmethod
    async def get_or_fetch_member(guild: discord.Guild, user: Union[discord.User, int]) -> Optional[discord.Member]:
        """|coro|

        Used to get a member from a guild. If the member was not found, the function
        will return nothing.

        Parameters
        ----------
        guild: :class:`~discord.Guild`
            The guild to get the member from.
        user: Union[:class:`~discord.User`, :class:`int`]
            The user to get the member from.

        Returns
        -------
        Optional[:class:`~discord.Member`]
            The member that was requested.
        """
        uid = user.id if isinstance(user, discord.User) else user
        try:
            return guild.get_member(uid) or await guild.fetch_member(uid)
        except discord.HTTPException:
            return None

    async def get_or_fetch_user(self, user_id: int) -> Optional[discord.User]:
        """|coro|

        Used to get a member from a guild. If the member was not found, the function
        will return nothing.

        Parameters
        ----------
        user_id: :class:`int`
            The user ID to fetch

        Returns
        -------
        Optional[:class:`~discord.User`]
            The member that was requested.
        """
        try:
            return self.get_user(user_id) or await self.fetch_user(user_id)
        except discord.HTTPException:
            return None

    async def on_command(self, ctx: HideoutContext):
        """|coro|

        Called when a command is invoked.
        Handles automatic blacklisting of users that are abusing the bot.

        Parameters
        ----------
        ctx: HideoutContext
            The context of the command.
        """
        assert ctx.command is not None
        await self.pool.execute(
            "INSERT INTO commands (guild_id, user_id, command, timestamp) VALUES ($1, $2, $3, $4)",
            (ctx.guild and ctx.guild.id),
            ctx.author.id,
            ctx.command.qualified_name,
            ctx.message.created_at,
        )
