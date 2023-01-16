from __future__ import annotations

import asyncio
import contextlib
import inspect
import io
import typing
from collections import defaultdict
from typing import Optional, Union, Type, List, TypeVar, Callable

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands, menus

from utils import HideoutCog, HideoutContext, ViewMenuPages
from cogs.hideout._checks import COUNSELORS_ROLE

T = TypeVar('T')
CO_T = TypeVar("CO_T", bound='Union[Type[commands.Converter], commands.Converter]')
AWARD_EMOJI = [chr(i) for i in range(129351, 129351 + 3)] + ['\N{SPORTS MEDAL}'] * 2


def copy_doc(original: Callable) -> Callable[[T], T]:
    def decorator(overridden: T) -> T:
        overridden.__doc__ = original.__doc__
        return overridden

    return decorator


class Tag:
    """
    Represents a tag.

    Attributes
    ----------
    id: int
        The ID of the tag.
    name: str
        The name of the tag.
    content: str
        The content of the tag.
    embed: Optional[discord.Embed]
        The embed of the tag.
    owner_id: int
        The ID of the owner of the tag.
    """

    __slots__ = ("name", "content", "embed", "id", "owner_id", "guild_id", "_cs_raw")

    def __init__(self, payload: dict):
        self.id: int = payload["id"]
        self.name: str = payload["name"]
        self.content: str = payload["content"]

        self.embed: Optional[discord.Embed]
        if embed := payload["embed"]:
            self.embed = discord.Embed.from_dict(embed)
        else:
            self.embed = None

        self.owner_id: int = payload["owner_id"]
        self.guild_id: int = payload["guild_id"]

    @discord.utils.cached_slot_property('_cs_raw')
    def raw(self):
        r = discord.utils.escape_markdown(self.content)
        return r.replace('<', '\\<')

    async def edit(
        self,
        connection: typing.Union[asyncpg.Connection, asyncpg.Pool],
        content: Union[str, commands.clean_content],
        embed: Optional[discord.Embed] = discord.utils.MISSING,
    ) -> None:
        """Edits the tag's content and embed.

        Parameters
        ----------
        content: Union[str, commands.clean_content]
            The new content of the tag.
        embed: Optional[discord.Embed]
            The new embed of the tag.
            If None, the embed will be removed.
        connection: Union[asyncpg.Connection, asyncpg.Pool]
            The connection to use.
        """
        if embed is not discord.utils.MISSING:
            embed = embed.to_dict() if embed else None  # type: ignore
            query = "UPDATE tags SET content = $1, embed = $2 WHERE id = $3"
            args = (content, embed, self.id)

            def update():
                self.content = content  # type: ignore
                self.embed = embed

        else:
            query = "UPDATE tags SET content = $1 WHERE id = $2"
            args = (content, self.id)

            def update():
                self.content = content  # type: ignore

        await connection.execute(query, *args)
        update()

    async def transfer(self, connection: typing.Union[asyncpg.Connection, asyncpg.Pool], user: discord.Member):
        """Transfers the tag to another user.

        Parameters
        ----------
        user: discord.User
            The user to transfer the tag to.
        connection: Union[asyncpg.Connection, asyncpg.Pool]
            The connection to use.
        """
        query = "UPDATE tags SET owner_id = $1 WHERE id = $2"
        await connection.execute(query, user.id, self.id)
        self.owner_id = user.id

    async def delete(self, connection: typing.Union[asyncpg.Connection, asyncpg.Pool]):
        """Deletes the tag.

        Parameters
        ----------
        connection: Union[asyncpg.Connection, asyncpg.Pool]
            The connection to use.
        """
        query = "DELETE FROM tags WHERE id = $1"
        await connection.execute(query, self.id)

    async def use(self, connection: typing.Union[asyncpg.Connection, asyncpg.Pool]):
        """Adds one to the tag's usage count.

        Parameters
        ----------
        connection: Union[asyncpg.Connection, asyncpg.Pool]
            The connection to use.
        """
        query = "UPDATE tags SET uses = uses + 1 WHERE id = $1"
        await connection.execute(query, self.id)

    async def add_alias(
        self,
        connection: typing.Union[asyncpg.Connection, asyncpg.Pool],
        alias: typing.Union[str, TagName],
        user: discord.User | discord.Member,
    ):
        """Adds an alias to the tag.

        Parameters
        ----------
        alias: Union[str, TagName]
            The alias to add.
        user: discord.User
            The user who added the alias.
        connection: Union[asyncpg.Connection, asyncpg.Pool]
            The connection to use.
        """
        query = (
            "INSERT INTO tags (name, owner_id, guild_id, points_to) VALUES "
            "($1, $2, (SELECT guild_id FROM tags WHERE id = $3), $3)"
        )
        await connection.execute(query, alias, user.id, self.id)


# noinspection PyShadowingBuiltins
class UnknownUser(discord.Object):
    # noinspection PyPep8Naming
    class display_avatar:
        url = "https://cdn.discordapp.com/embed/avatars/0.png"

    def __init__(self, id: int):
        super().__init__(id=id, type=discord.User)

    def __str__(self):
        return "@Unknown User#0000"

    @property
    def mention(self):
        return "<@{}>".format(self.id)


class TagName(commands.clean_content):
    def __init__(self, *, lower=True):
        self.lower = lower
        super().__init__()

    def __class_getitem__(cls, attr: bool):
        if not isinstance(attr, bool):
            raise TypeError("Expected bool, not {}".format(type(attr).__name__))
        return TagName(lower=attr)

    # Taken from R.Danny's code because I'm lazy
    async def actual_conversion(self, ctx: HideoutContext, converted: str, error: Type[discord.DiscordException]):
        """The actual conversion function after clean content has done its job."""
        lower = converted.lower().strip()

        if not lower:
            raise error('Missing tag name.')

        if len(lower) > 200:
            raise error('Tag name is a maximum of 200 characters.')

        first_word, _, _ = lower.partition(' ')

        # get tag command.
        root: commands.Group = ctx.bot.get_command('tag')  # type: ignore # known type
        if first_word in root.all_commands:
            raise error('This tag name starts with a reserved word.')

        if lower.startswith('topic:') and not ctx.author.get_role(COUNSELORS_ROLE):
            raise error('Tag name starts with a reserved key (`topic:` - moderator only)')

        if lower.startswith('category:') and not await ctx.bot.is_owner(ctx.author):
            raise error('Tag name starts with a reserved key (`category:` - owner only)')

        return converted if not self.lower else lower

    # msg commands
    async def convert(self, ctx, argument):
        converted = await super().convert(ctx, argument)
        return await self.actual_conversion(ctx, converted, commands.BadArgument)  # type: ignore


class TagsFromFetchedPageSource(menus.ListPageSource):
    def __init__(
        self,
        tags: typing.List[asyncpg.Record],
        *,
        per_page: int = 10,
        member: discord.Member | discord.User | None = None,
        ctx: HideoutContext,
    ):
        super().__init__(tags, per_page=per_page)
        self.member = member
        self.ctx = ctx

    async def format_page(self, menu: menus.MenuPages, entries: typing.List[asyncpg.Record]):
        source = enumerate(entries, start=menu.current_page * self.per_page + 1)
        formatted = '\n'.join(f"{idx}. {tag['name']} (ID: {tag['id']})" for idx, tag in source)
        embed = discord.Embed(title=f"Tags List", description=formatted, colour=self.ctx.bot.colour)
        if self.member:
            embed.set_author(name=str(self.member), icon_url=self.member.display_avatar.url)
        embed.set_footer(text=f"Page {menu.current_page + 1}/{self.get_max_pages()} ({len(self.entries)} entries)")
        return embed


class Tags(HideoutCog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tags_in_progress = defaultdict(set)

    @staticmethod
    def maybe_file(text: str, *, filename='tag') -> dict:
        """Checks if text is greater than 2000 characters

        Parameters
        ----------
        text: str
            The text to check.
        filename: str
            The filename to use.
            Defaults to 'tag'.

        Returns
        -------
        dict
            The file object.
        """
        if len(text) > 2000:
            return {"file": discord.File(io.BytesIO(text.encode()), filename=f"{filename}.txt")}
        return {"content": text}

    @staticmethod
    def maybe_codeblock(content: str | None = None, file: discord.File | None = None, *, filename='tag') -> dict:
        """Maybe puts `text` in a code block.

        **Example**

        .. code-block:: python3
            await ctx.send(**self.maybe_codeblock(**self.maybe_file(text)))
            # or
            await ctx.send(**self.maybe_codeblock(content=text))

        Parameters
        ----------
        content: str
            The text to check.
        file: discord.File``
            The file to check.
        filename: str
            The filename to use.
            Defaults to 'tag'.

        Returns
        -------
        str
            The formatted text.
        """
        if content and len(content) <= 1992:
            return {'content': f"```\n{content}\n```"}
        elif content:
            return {'file': discord.File(io.BytesIO(content.encode()), filename="tag.txt")}
        else:
            return {'file': file}

    async def get_tag(
        self,
        tag: Union[str, commands.clean_content],
        guild_id: Optional[int],
        *,
        connection: Optional[Union[asyncpg.Connection, asyncpg.Pool]] = None,
    ) -> Tag:
        """Gets a tag

        Parameters
        ----------
        tag: str
            The tag to get
        guild_id: int
            The guild id to get the tag from. If
            None, the tag will be retrieved from
            the global tags.
        connection: Optional[Union[asyncpg.Connection, asyncpg.Pool]]
            The connection to use. If None,
            the bot's pool will be used.

        Returns
        -------
        Tag
            The tag.
        """
        connection = connection or self.bot.pool
        query = """
            SELECT id, name, content, embed, owner_id, guild_id FROM tags 
            WHERE (LOWER(name) = LOWER($1::TEXT) and (guild_id = $2) and (content is not null)) 
            OR (id = (
                SELECT points_to FROM tags 
                    WHERE LOWER(name) = LOWER($1::TEXT) 
                    AND guild_id = $2 
                    AND points_to IS NOT NULL
                ))
            LIMIT 1 -- just in case
        """

        fetched_tag = await connection.fetchrow(query, tag, guild_id)
        if fetched_tag is None:
            query = """
                SELECT name FROM tags
                WHERE (guild_id = $1 OR guild_id IS NULL) 
                AND LOWER(name) % LOWER($2::TEXT)
                ORDER BY similarity(name, $2) DESC
                LIMIT 3
            """
            similar = await connection.fetch(query, guild_id, tag)
            if not similar:
                raise commands.BadArgument(f"Tag not found.")
            joined = '\n'.join(r['name'] for r in similar)
            raise commands.BadArgument(f"Tag not found. Did you mean...\n{joined}")

        return Tag(fetched_tag)

    @contextlib.contextmanager
    def reserve_tag(self, name, guild_id):
        """Simple context manager to reserve a tag."""
        if name in self._tags_in_progress[guild_id]:
            raise commands.BadArgument("Sorry, this tag is already being created!")
        try:
            self._tags_in_progress[guild_id].add(name)
            yield None
        finally:
            self._tags_in_progress[guild_id].discard(name)

    async def make_tag(
        self,
        guild: Optional[discord.Guild],
        owner: Union[discord.User, discord.Member],
        tag: Union[str, commands.clean_content],
        content: Union[str, commands.clean_content],
    ) -> Tag:
        """Creates a tag.

        Parameters
        ----------
        guild: Optional[discord.Guild]
            The guild the tag will be bound to.
        owner: Union[discord.User, discord.Member]
            The owner of the tag.
        tag: Union[str, TagName]
            The name of the tag.
        content: Union[str, commands.clean_content]
            The content of the tag.

        Returns
        -------
        Tag
            The tag.
        """
        with self.reserve_tag(tag, guild.id if guild else None):
            try:
                async with self.bot.safe_connection() as conn:
                    stuff = await conn.fetchrow(
                        """
                        INSERT INTO tags (name, content, guild_id, owner_id) VALUES ($1, $2, $3, $4)
                        RETURNING id, name, content, embed, owner_id, guild_id
                    """,
                        tag,
                        content,
                        guild.id if guild else None,
                        owner.id,
                    )
                    return Tag(stuff)  # type: ignore
            except asyncpg.UniqueViolationError:
                raise commands.BadArgument("This tag already exists!")
            except asyncpg.StringDataRightTruncationError:
                raise commands.BadArgument("Tag name too long! Max 100 characters.")
            except asyncpg.CheckViolationError:
                raise commands.BadArgument("No content was provided!")
            except Exception as e:
                await self.bot.exceptions.add_error(error=e)
                raise commands.BadArgument(f"Could not create tag.")

    async def wait_for(
        self,
        channel: discord.abc.MessageableChannel,
        author: discord.Member | discord.User,
        *,
        timeout: int = 60,
        converter: CO_T | Type[CO_T] | None = None,
        ctx: HideoutContext | None = None,
    ) -> Union[str, CO_T]:
        """Waits for a message to be sent in a channel.

        Parameters
        ----------
        channel: discord.TextChannel
            The channel to wait for a message in.
        author: discord.Member
            The member to wait for a message from.
        timeout: int
            The timeout in seconds. Defaults to 60.
        converter: commands.Converter
            The converter to use. Defaults to None.
        ctx: commands.Context
            The context to use for the converter, if passed.
        """
        try:

            def check(msg: discord.Message):
                return msg.channel == channel and msg.author == author

            message: discord.Message = await self.bot.wait_for('message', timeout=timeout, check=check)

            if converter is not None:
                try:
                    if inspect.isclass(converter) and issubclass(converter, commands.Converter):
                        if inspect.ismethod(converter.convert):
                            content = await converter.convert(ctx, message.content)
                        else:
                            content = await converter().convert(ctx, message.content)  # type: ignore
                    elif isinstance(converter, commands.Converter):
                        content = await converter.convert(ctx, message.content)  # type: ignore
                    else:
                        content = message.content
                except commands.CommandError:
                    raise
                except Exception as exc:
                    raise commands.ConversionError(converter, exc) from exc  # type: ignore
            else:
                content = message.content

            if not content:
                raise commands.BadArgument('No content was provided... Somehow...')
            if isinstance(content, str) and len(content) > 2000:
                raise commands.BadArgument('Content is too long! 2000 characters max.')
            return content
        except asyncio.TimeoutError:
            raise commands.BadArgument(f'Timed out waiting for message from {str(author)}...')

    @commands.group(name='tag', invoke_without_command=True)
    async def tag(self, ctx: HideoutContext, *, name: TagName):
        """Base tags command. Also shows a tag."""
        tag = await self.get_tag(name, ctx.guild.id)
        if tag.embed and ctx.channel.permissions_for(ctx.me).embed_links:  # type: ignore
            await ctx.channel.send(tag.content, embed=tag.embed)
        else:
            await ctx.channel.send(tag.content)
        await tag.use(self.bot.pool)

    @tag.command(name='create', aliases=['new', 'add'])
    async def tag_create(self, ctx: HideoutContext, tag: TagName(lower=False), *, content: commands.clean_content):  # type: ignore
        """Creates a tag."""
        if len(str(content)) > 2000:
            raise commands.BadArgument("Tag content is too long! Max 2000 characters.")
        tag_ = await self.make_tag(ctx.guild, ctx.author, tag, content)
        await ctx.send(f"Tag {tag_.name!r} successfully created!")

    @tag.command(name='make', ignore_extra=False)
    @commands.max_concurrency(1, commands.BucketType.member)
    async def tag_make(self, ctx: HideoutContext):
        """Interactive prompt to make a tag."""
        await ctx.send('Hello, what name would you like to give this tag?')
        try:
            name = await self.wait_for(ctx.channel, ctx.author, converter=TagName(lower=False), ctx=ctx)
        except commands.BadArgument as e:
            cmd = f"{ctx.clean_prefix}{ctx.command.qualified_name if ctx.command else '<Unknown Command>'}"
            raise commands.BadArgument(f"{e} Please use {cmd!r} to try again.")

        args = (name, ctx.guild.id)
        with self.reserve_tag(*args):
            query = """
                SELECT EXISTS(
                    SELECT * FROM tags
                    WHERE name = $1
                    AND CASE WHEN ( $2::BIGINT = 0 ) THEN ( guild_id IS NULL ) ELSE ( guild_id = $2 ) END
                )
            """
            check = await self.bot.pool.fetchval(query, *args)
            if check:
                cmd = f"{ctx.clean_prefix}{ctx.command.qualified_name if ctx.command else '<Unknown Command>'}"
                raise commands.BadArgument(f'A tag with the name {name!r} already exists! Please use {cmd} to try again.')
            await ctx.send('What would you like the content of this tag to be?')
            content = await self.wait_for(
                ctx.channel, ctx.author, converter=commands.clean_content, ctx=ctx, timeout=60 * 10
            )

        await self.make_tag(ctx.guild, ctx.author, name, content)
        await ctx.send(f'Tag {name!r} successfully created!')

    @tag.command(name='claim')
    async def tag_claim(self, ctx: HideoutContext, name: TagName):
        """Claims a tag from a user that isn't in this server anymore."""
        tag = await self.get_tag(name, ctx.guild.id)
        user = await self.bot.get_or_fetch_member(guild=ctx.guild, user=tag.owner_id)
        if user:
            await ctx.send('Tag owner still in this server.')
            return
        assert isinstance(ctx.author, discord.Member)
        await tag.transfer(self.bot.pool, ctx.author)
        await ctx.send(f'Tag {name!r} successfully claimed!')

    @tag.command(name='edit')
    async def tag_edit(self, ctx: HideoutContext, tag: TagName, *, content: commands.clean_content):
        """Edits a tag."""
        is_mod = await self.bot.is_owner(ctx.author)
        is_mod = is_mod or ctx.author.guild_permissions.manage_messages
        async with self.bot.safe_connection() as conn:
            tagobj = await self.get_tag(tag, ctx.guild.id, connection=conn)
            if tagobj.owner_id != ctx.author.id or not is_mod:
                raise commands.BadArgument(
                    f"Could not edit tag. Are you sure it exists{'' if is_mod else ' and you own it'}?"
                )
            await tagobj.edit(conn, content)
        await ctx.send(f'Successfully edited tag!')

    @tag.command(name='append')
    async def tag_append(self, ctx: HideoutContext, tag: TagName, *, content: commands.clean_content):
        """Appends content to a tag.

        This will add a new line before the content being appended."""
        is_mod = await self.bot.is_owner(ctx.author)
        is_mod = is_mod or ctx.author.guild_permissions.manage_messages
        async with self.bot.safe_connection() as conn:
            query = """
                WITH edited AS (
                    UPDATE tags
                    SET content = content || E'\n' || $1
                    WHERE name = $2
                    AND CASE WHEN ( $3::BIGINT = 0 ) THEN ( guild_id IS NULL ) ELSE ( guild_id = $3 ) END
                    AND (owner_id = $4 OR $5::BOOL = TRUE)
                        -- $5 will be true for moderators
                    RETURNING *
                )
                SELECT EXISTS ( SELECT * FROM edited )
            """
            confirm = await conn.fetchval(query, content, tag, ctx.guild.id, ctx.author.id, is_mod)
            if confirm:
                await ctx.send(f'Succesfully edited tag!')
            else:
                await ctx.send(f"Could not edit tag. Are you sure it exists{'' if is_mod else ' and you own it'}?")

    @tag.command(name='delete')
    async def tag_delete(self, ctx: HideoutContext, *, tag: TagName):
        """Deletes one of your tags"""
        async with self.bot.safe_connection() as conn:
            query = """
                WITH deleted AS (
                    DELETE FROM tags
                        WHERE LOWER(name) = LOWER($1::TEXT)
                        AND CASE WHEN ( $2::BIGINT = 0 ) THEN ( guild_id IS NULL ) ELSE ( guild_id = $2 ) END
                        AND (owner_id = $3 OR $4::BOOL = TRUE)
                            -- $4 will be true for moderators.
                        RETURNING name, points_to
                )
                SELECT deleted.name, (
                    SELECT name
                        FROM tags
                        WHERE id = (deleted.points_to)
                ) AS parent
                FROM deleted
            """

            is_mod = await self.bot.is_owner(ctx.author)
            is_mod = is_mod or ctx.author.guild_permissions.manage_messages

            tag_p = await conn.fetchrow(query, tag, ctx.guild.id, ctx.author.id, is_mod)

            if tag_p is None:
                await ctx.send(f"Could not delete tag. Are you sure it exists{'' if is_mod else '  and you own it'}?")
            elif tag_p['parent'] is not None:
                await ctx.send(f"Tag {tag_p['name']!r} that points to {tag_p['parent']!r} deleted!")
            else:
                await ctx.send(f"Tag {tag_p['name']!r} and corresponding aliases deleted!")

    @tag.command(name='delete-id')
    async def tag_delete_id(self, ctx: HideoutContext, *, tag_id: int):
        """Deletes a tag by ID."""
        async with self.bot.safe_connection() as conn:
            query = """
                WITH deleted AS (
                    DELETE FROM tags
                        WHERE id = $1
                        AND CASE WHEN ( $2::BIGINT = 0 ) THEN ( guild_id IS NULL ) ELSE ( guild_id = $2 ) END
                        AND (owner_id = $3 OR $4::BOOL = TRUE)
                            -- $4 will be true for moderators.
                        RETURNING name, points_to
                )
                SELECT deleted.name, (
                    SELECT name
                        FROM tags
                        WHERE id = (deleted.points_to)
                ) AS parent
                FROM deleted
            """

            is_mod = await self.bot.is_owner(ctx.author)
            is_mod = is_mod or ctx.author.guild_permissions.manage_messages

            tag_p = await conn.fetchrow(query, tag_id, ctx.guild.id, ctx.author.id, is_mod)

            if tag_p is None:
                await ctx.send(f"Could not delete tag. Are you sure it exists{'' if is_mod else '  and you own it'}?")
            elif tag_p['parent'] is not None:
                await ctx.send(f"Tag {tag_p['name']!r} that points to {tag_p['parent']!r} deleted!")
            else:
                await ctx.send(f"Tag {tag_p['name']!r} and corresponding aliases deleted!")

    @tag.command(name='purge')
    async def tag_purge(self, ctx: HideoutContext, member: typing.Union[discord.Member, discord.User]):
        """Purges all tags from a user"""
        is_owner = is_mod = await self.bot.is_owner(ctx.author)
        is_mod = is_mod or ctx.author.guild_permissions.manage_messages

        if not is_mod:
            await ctx.send("You do not have permission to purge tags!")
            return

        query = """
            SELECT COUNT(*) FROM tags 
            WHERE CASE WHEN ( $1::BIGINT = 0 ) THEN ( guild_id IS NULL ) ELSE ( guild_id = $1 ) END
            AND owner_id = $2
        """
        args = (ctx.guild.id, member.id)

        amount: int | None = self.bot.pool.fetchval(query, *args)  # type: ignore

        if amount == 0 or amount is None:
            await ctx.send(f"{member} has no tags!")
            return

        result = await ctx.confirm(
            f"Are you sure you want to purge {member}'s tags?\n"
            f"This will delete {amount} tag{'s' if amount > 1 else ''}.\n"
            f"**This action cannot be undone!**"
        )

        if result is None:
            return
        elif result is False:
            await ctx.send("Aborted!")
            return

        if not is_owner:
            if not ctx.guild or not (ctx.guild.get_member(ctx.author.id) or ctx.author).guild_permissions.manage_messages:
                return await ctx.send('You no longer have the required permissions to purge tags!')

        async with self.bot.safe_connection() as conn:
            query = """
                WITH deleted AS (
                    DELETE FROM tags
                        WHERE CASE WHEN ( $1::BIGINT = 0 ) THEN ( guild_id IS NULL ) ELSE ( guild_id = $2 ) END
                        AND owner_id = $2
                        RETURNING name, points_to
                )
                SELECT COUNT(*) FROM deleted
            """

            tag_p = await conn.fetchval(query, ctx.guild.id, member.id)

            await ctx.send(f"Deleted all of {member}'s tags ({tag_p} tags deleted)!")

    @tag.command(name='alias')
    async def tag_alias(self, ctx: HideoutContext, alias: TagName, *, points_to: TagName):
        """Creates an alias for a tag.

        Parameters
        ----------
        alias: str
            The name of the new alias.
        points_to: str
            The name of the tag to point to.
        """
        async with self.bot.safe_connection() as conn:
            try:
                tag = await self.get_tag(points_to, ctx.guild.id, connection=conn)
            except commands.BadArgument:
                return await ctx.send(f"Tag {points_to!r} does not exist!")
            try:
                await tag.add_alias(conn, alias, ctx.author)
            except asyncpg.UniqueViolationError:
                return await ctx.send(f"Tag {alias!r} already exists!")
            except Exception as e:
                await self.bot.exceptions.add_error(error=e, ctx=ctx)
                return await ctx.send(f"Could not create alias!")
            await ctx.send(f"Alias {alias!r} that points to {points_to!r} created!")

    @tag.command(name='info', aliases=['owner'])
    async def tag_info(self, ctx: HideoutContext, *, tag: TagName):
        """Gets information about a tag"""
        query = """
            WITH original_tag AS (
                SELECT * FROM tags
                WHERE LOWER(name) = LOWER($1::TEXT)
                AND CASE WHEN ( $2::BIGINT = 0 ) THEN ( guild_id IS NULL ) ELSE ( guild_id = $2 ) END
            )

            SELECT 
                original_tag.name,
                original_tag.owner_id,
                original_tag.created_at,
                (original_tag.points_to IS NOT NULL) as is_alias,
                (SELECT tags.name FROM tags WHERE tags.id = original_tag.points_to) AS parent,
                uses,
                (CASE WHEN ( original_tag.points_to IS NULL ) THEN ( 
                SELECT COUNT(*) FROM tags WHERE tags.points_to = original_tag.id ) END ) AS aliases
            FROM original_tag
        """
        args = (query, tag, ctx.guild.id)
        data = await self.bot.pool.fetchrow(*args)
        if not data:
            raise commands.BadArgument('Tag not found.')
        name, owner_id, created_at, is_alias, parent, uses, aliases_amount = data
        owner = await self.bot.get_or_fetch_user(owner_id) or UnknownUser(owner_id)

        embed = discord.Embed(title=name, timestamp=created_at)
        embed.set_author(name=str(owner), icon_url=owner.display_avatar.url)
        embed.add_field(name='Owner', value=f'{owner.mention}')
        if is_alias:
            embed.add_field(name='Original Tag', value=parent)
            embed.set_footer(text='Alias created at')
        else:
            embed.add_field(name='Uses', value=uses)
            embed.add_field(name='Aliases', value=f"Has {aliases_amount} aliases", inline=False)
            embed.set_footer(text='Tag created at')
        await ctx.send(embed=embed)

    @tag.command(name='list')
    async def tag_list(self, ctx: HideoutContext, *, member: Optional[discord.Member] = None):
        """Lists all tags owned by a member."""
        query = """
            SELECT name, id FROM tags
            WHERE CASE WHEN ( $1::BIGINT = 0 ) 
                        THEN ( guild_id IS NULL ) 
                        ELSE ( guild_id = $1 ) END
            AND ( owner_id = $2 OR $2::BIGINT = 0 )
            ORDER BY name
        """
        args = (ctx.guild.id, member.id if member else 0)
        tags = await self.bot.pool.fetch(query, *args)

        if not tags:
            return await ctx.send("This server has no tags!" if not member else f"{member} owns no tags!")

        paginator = ViewMenuPages(source=TagsFromFetchedPageSource(tags, member=member, ctx=ctx), ctx=ctx)
        await paginator.start()

    @tag.command(name='search')
    async def tag_search(self, ctx: HideoutContext, *, query: str):
        """Searches for tags."""
        db_query = """
            SELECT name, id FROM tags
            WHERE CASE WHEN ( $1::BIGINT = 0 ) THEN ( guild_id IS NULL ) ELSE ( guild_id = $1 ) END
            AND similarity(name, $2) > 0
            ORDER BY similarity(name, $2) DESC
            LIMIT 200
        """
        args = (ctx.guild.id, query)
        tags = await self.bot.pool.fetch(db_query, *args)
        if not tags:
            return await ctx.send("No tags found with that query...")

        paginator = ViewMenuPages(source=TagsFromFetchedPageSource(tags, member=None, ctx=ctx), ctx=ctx)
        await paginator.start()

    @tag.command(name='raw')
    async def tag_raw(self, ctx: HideoutContext, *, tag: TagName):
        """Sends a raw tag."""
        tagobj = await self.get_tag(tag, ctx.guild.id)
        await ctx.send(**self.maybe_file(tagobj.raw))

    async def get_guild_or_global_stats(self, ctx: HideoutContext, guild: discord.Guild | None, embed):
        """Gets the tag stats of a guild.

        Parameters
        ----------
        ctx: HideoutContext
            The context of the command.
        guild: discord.Guild
            The guild to get the tag stats of.
            If ``None``, gets the global tag stats.
        embed: discord.Embed
            The base embed.
        """

        guild_id = guild.id if guild else 0

        # Top tags

        query = """
            SELECT name, uses,
            COUNT(*) OVER () AS total_tags,
            SUM(uses) OVER () AS total_uses
            FROM tags
            WHERE CASE WHEN ( $1::BIGINT = 0 ) THEN ( guild_id IS NULL ) ELSE ( guild_id = $1 ) END
            ORDER BY uses DESC
            LIMIT 5;
            """
        data = await self.bot.pool.fetch(query, guild_id)

        embed.description = (
            f"{data[0]['total_tags']} tags in total, " f"{data[0]['total_uses']} uses in total."
            if data
            else "No data available...."
        )

        top_tags = [f"{AWARD_EMOJI[index]} {name} (used {uses} times)" for index, (name, uses, _, _) in enumerate(data)]

        embed.add_field(name='Top Tags', value='\n'.join(top_tags) or '\u200b', inline=False)

        # Top creators

        query = """
            SELECT COUNT(*) as tag_amount, owner_id
            FROM tags WHERE CASE WHEN ( $1::BIGINT = 0 ) THEN ( guild_id IS NULL ) ELSE ( guild_id = $1 ) END
            GROUP BY owner_id
            ORDER BY tag_amount DESC
            LIMIT 5;
            """

        data = await self.bot.pool.fetch(query, guild_id)

        top_creators = [
            f"{AWARD_EMOJI[index]} <@{owner_id}> (owns {tag_amount} tags)"
            for index, (tag_amount, owner_id) in enumerate(data)
        ]

        embed.add_field(name='Top Tag Creators', value='\n'.join(top_creators) or '\u200b', inline=False)

        # Top users

        query = """
            SELECT COUNT(*) as tag_amount, user_id
            FROM commands WHERE CASE WHEN ( $1::BIGINT = 0 ) THEN ( TRUE ) ELSE ( guild_id = $1 ) END
            AND CASE WHEN ( $1::BIGINT = 0 ) THEN ( command = 'tag global' ) ELSE ( command = 'tag' ) END
            GROUP BY user_id
            ORDER BY tag_amount DESC
            LIMIT 5;
            """

        data = await self.bot.pool.fetch(query, guild_id)

        top_users = [
            f"{AWARD_EMOJI[index]} <@{user_id}> ({tag_amount} tags used)" for index, (tag_amount, user_id) in enumerate(data)
        ]

        embed.add_field(name='Top Tag Users', value='\n'.join(top_users) or '\u200b', inline=False)

        await ctx.send(embed=embed)

    async def user_tag_stats(self, ctx: HideoutContext, member: discord.Member | discord.User, guild: discord.Guild | None):
        """Gets the tag stats of a member.

        Parameters
        ----------
        ctx: HideoutContext
            The context to get the number of tags in.
        member: discord.Member
            The member to get the stats for.
        guild: discord.Guild
            The guild to get the stats for.
            If ``None``, gets the global tag stats.
        """

        embed = discord.Embed()
        embed.set_author(name=f"{member.name} Tag Stats", icon_url=member.display_avatar.url)
        args = (member.id, guild.id if guild else 0)

        # tags created

        query = """
            SELECT COUNT(*) as tag_amount,
            SUM(uses) as total_uses
            FROM tags WHERE owner_id = $1
            AND CASE WHEN ( $2::BIGINT = 0 ) THEN ( guild_id IS NULL ) ELSE ( guild_id = $2 ) END
            """
        data = await self.bot.pool.fetchrow(query, *args)

        if data:
            tags = f"{data['tag_amount']:,}"
            uses = f"{data['total_uses']:,}"
        else:
            tags = 'None'
            uses = 0

        embed.add_field(name='Owned Tags', value=f"{tags} tags")
        embed.add_field(name='Owned Tag Uses', value=f"{uses} uses")

        # tags used

        query = """
            SELECT COUNT(*) as tag_amount
            FROM commands WHERE user_id = $1
            AND CASE WHEN ( $2::BIGINT = 0 ) THEN ( guild_id IS NULL ) ELSE ( guild_id = $2 ) END
            AND command = 'tag';
            """

        data = await self.bot.pool.fetchrow(query, *args)
        embed.add_field(name='Tag Command Uses', value=f"{data['tag_amount']:,} uses" if data else 'None')

        # top tags
        query = """
            SELECT name, uses
            FROM tags WHERE owner_id = $1
            AND CASE WHEN ( $2::BIGINT = 0 ) THEN ( guild_id IS NULL ) ELSE ( guild_id = $2 ) END
            ORDER BY uses DESC
            LIMIT 5;
            """

        data = await self.bot.pool.fetch(query, *args)

        top_tags = [f"{AWARD_EMOJI[index]} {name} (used {uses} times)" for index, (name, uses) in enumerate(data)]

        embed.add_field(name='Top Tags', value='\n'.join(top_tags) or '\u200b', inline=False)

        await ctx.send(embed=embed)

    @tag.command(name='stats')
    async def tag_stats(self, ctx: HideoutContext, member: Optional[discord.Member] = None):
        """Gets the tag stats of a member or this server."""
        if member is None:
            embed = discord.Embed()
            embed.set_author(name=f"{ctx.guild.name} Tag Stats", icon_url=ctx.guild.icon.url if ctx.guild.icon else None)
            await self.get_guild_or_global_stats(ctx, guild=ctx.guild, embed=embed)
        else:
            await self.user_tag_stats(ctx, member, ctx.guild)

    @tag.command(name='remove-embed')
    async def tag_remove_embed(self, ctx: HideoutContext, *, tag: TagName):
        """Removes an embed from a tag.

        To add an embed, use the ``embed`` command.
        Example:
         ``-embed <flags> --save <tag name>`` where flags are the embed flags.
         See ``-embed --help`` for more information about the flags"""
        query = """
            WITH updated AS (
                UPDATE tags SET embed = NULL
                WHERE name = $1 
                AND CASE WHEN ( $2::BIGINT = 0 ) THEN ( guild_id IS NULL ) ELSE ( guild_id = $2 ) END
                AND (owner_id = $3 or $4::bool = TRUE )
                    -- $4 will be true for moderators.
                RETURNING *
            )
            SELECT EXISTS ( SELECT * FROM updated )
        """
        is_mod = await self.bot.is_owner(ctx.author)

        if isinstance(ctx.author, discord.Member):
            is_mod = is_mod or ctx.author.guild_permissions.manage_messages

        args = (tag, ctx.guild.id, ctx.author.id, is_mod)
        exists = await self.bot.pool.fetchval(query, *args)

        if not exists:
            return await ctx.send(f"Could not edit tag. Are you sure it exists{'' if is_mod else '  and you own it'}?")
        await ctx.send(f"Successfully edited tag!")

    @app_commands.command(name='tag')
    @app_commands.describe(
        tag_name='The tag to show.', ephemeral='Whether to show the tag only to you.', raw='Whether to show the raw tag.'
    )
    @app_commands.rename(tag_name='tag-name', raw='raw-content')
    async def slash_tag(
        self,
        interaction: discord.Interaction,
        *,
        tag_name: str,
        ephemeral: Optional[bool] = None,
        raw: Optional[typing.Literal['Yes', 'No', 'Send As File', 'Send Using Code Block']] = None,
    ):
        """Shows a tag. For more commands, use the "tag" message command."""
        tag = await self.get_tag(tag_name, interaction.guild.id if interaction.guild else None)
        if raw == 'Yes':
            kwargs = {**self.maybe_file(tag.raw, filename=tag.name), 'ephemeral': True if ephemeral is None else ephemeral}
        elif raw == 'Send As File':
            kwargs = {
                'file': discord.File(io.BytesIO(tag.content.encode()), filename=f'{tag.name}.txt'),
                'ephemeral': True if ephemeral is None else ephemeral,
            }
        elif raw == 'Send Using Code Block':
            kwargs = {**self.maybe_codeblock(content=tag.content), 'ephemeral': True if ephemeral is None else ephemeral}
        else:
            kwargs = {'content': tag.content, 'embed': tag.embed, 'ephemeral': False if ephemeral is None else ephemeral}

        await interaction.response.send_message(**kwargs)

        try:
            query = "INSERT INTO commands (guild_id, user_id, command) VALUES ($1, $2, 'tag')"
            await tag.use(self.bot.pool)
            await self.bot.pool.execute(query, interaction.guild.id if interaction.guild else None, interaction.user.id)
        except Exception as e:
            await self.bot.exceptions.add_error(error=e)

    @slash_tag.autocomplete('tag_name')
    async def tag_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete for the `/tag` command."""
        query = """
            WITH tags AS (
                SELECT name FROM tags 
                WHERE (guild_id = $1 OR guild_id IS NULL)
                AND ( CASE WHEN LENGTH($2) > 0 THEN ( SIMILARITY(name, $2) > (
                    CASE WHEN LENGTH($2) > 3 THEN 0.175 ELSE 0.05 END
                ) ) ELSE TRUE END )
                ORDER BY similarity(name, $2) LIMIT 50
            )
            SELECT DISTINCT name FROM tags ORDER BY name LIMIT 25
            
        """
        tags = await self.bot.pool.fetch(query, interaction.guild.id if interaction.guild else None, current)
        if tags:
            return [app_commands.Choice(name=f"{tag['name']}"[0:100], value=tag['name']) for tag in tags]
        return [app_commands.Choice(name='No tags found matching your query...', value='list')]
