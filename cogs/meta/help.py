from __future__ import annotations

import difflib
import re
from typing import TYPE_CHECKING, Annotated, Any, Callable, Iterable, List, Optional

import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands

from utils import HideoutCog, HideoutContext, cb, human_join

if TYPE_CHECKING:
    from cogs.meta import Information
    from cogs.meta.tags import Tag


class Help(HideoutCog):
    show_hidden: bool = False
    verify_checks: bool = True
    indent = 2

    @property
    def tags(self) -> Information:
        return self  # type: ignore

    async def filter_commands(
        self,
        ctx: HideoutContext,
        command_list: Iterable[commands.Command[Any, ..., Any]],
        /,
        *,
        sort: bool = True,
        verify_checks: Optional[bool] = None,
        show_hidden: Optional[bool] = None,
        key: Optional[Callable[[commands.Command[Any, ..., Any]], Any]] = None,
    ) -> List[commands.Command[Any, ..., Any]]:
        if sort and key is None:
            key = lambda c: c.name

        show_hidden = self.show_hidden if show_hidden is None else show_hidden
        verify_checks = self.verify_checks if show_hidden is None else show_hidden

        iterator = command_list if show_hidden else filter(lambda c: not c.hidden, command_list)
        if verify_checks is False:
            # if we do not need to verify the checks then we can just
            # run it straight through normally without using await.
            return sorted(iterator, key=key) if sort else list(iterator)  # type: ignore # the key shouldn't be None

        if verify_checks is None and not ctx.guild:
            # if verify_checks is None and we're in a DM, don't verify
            return sorted(iterator, key=key) if sort else list(iterator)  # type: ignore

        # if we're here then we need to check every command if it can run
        async def predicate(cmd: commands.Command[Any, ..., Any]) -> bool:
            try:
                return await cmd.can_run(ctx)
            except commands.CommandError:
                return False

        ret = []
        for cmd in iterator:
            valid = await predicate(cmd)
            if valid:
                ret.append(cmd)

        if sort:
            ret.sort(key=key)
        return ret

    def commands_to_str(self, command_list: Iterable[commands.Command[Any, ..., Any]]) -> list[str]:
        ret = []
        for command in command_list:
            if isinstance(command, commands.Group) and command.commands:
                ret.append(f"__{command.qualified_name}__")
            else:
                ret.append(command.qualified_name)
        return ret

    async def send_main_page(self, ctx: HideoutContext):
        embed = discord.Embed(
            title='Duck Hideout Help Desk',
            description="\N{BLACK TELEPHONE} You've reached the help desk. How may I help you?",
            timestamp=ctx.message.created_at,
        )
        embed.add_field(
            name='\N{BLACK QUESTION MARK ORNAMENT} Getting Help',
            value=("Use the `-help <entry>` command to get help on a\n" "specific command, category or topic."),
            inline=False,
        )
        query = """
            SELECT array_agg(substr(name, 7)) FROM tags 
            WHERE LOWER(name) LIKE 'topic:%' AND (guild_id = $1)
        """
        topics: list[str] = await self.bot.pool.fetchval(query, ctx.guild.id)
        joined = f"__{human_join(topics, delim='__, __', final='__ or __', spaces=False)}__"
        embed.add_field(
            name='\N{GLOWING STAR} Topics',
            value=f"Handwritten guides by our moderation team.\n{joined}",
            inline=False,
        )
        embed.add_field(
            name='\N{FILE FOLDER} Categories',
            value=(
                'Groups of commands with similar subject. Commands '
                '\nthat are __underlined__ are groups, which means they have'
                '\nassociated sub-commands. To see the sub-commands,'
                '\nuse `-help <command>`.'
            ),
            inline=False,
        )
        for name, cog in sorted(self.bot.cogs.items(), key=lambda m: m[0]):
            commands = await self.filter_commands(ctx, cog.get_commands())
            if not commands:
                continue
            joined = f"{human_join(self.commands_to_str(commands), final='and')}"
            embed.add_field(
                name=f'{name.title()}',
                value=f"{joined}",
                inline=False,
            )
        embed.set_footer(
            text='Thanks for being a part of our community!', icon_url='https://cdn.duck-bot.com/file/orange-heart'
        )
        ctx.bot.temporary_pool
        await ctx.send(embed=embed)

    async def send_topic_help(self, ctx: HideoutContext, topic: Tag):
        embed = topic.embed
        if embed and not embed.color:
            embed.color = self.bot.color
        await ctx.send(topic.content, embed=embed)

    async def format_command(self, ctx: HideoutContext, command: commands.Command, x: bool = False) -> str:
        prefix = ''
        if isinstance(command, (commands.HybridCommand, commands.HybridGroup)):
            if command.with_app_command and not getattr(command, 'commands', None):
                prefix = '[/]'

        lock = ''
        if x:
            try:
                can_run = await command.can_run(ctx)
            except commands.CommandError:
                can_run = False
            lock = '' if can_run else '\N{HEAVY MULTIPLICATION X}'

        parent: Optional[commands.Group[Any, ..., Any]] = command.parent  # type: ignore # the parent will be a Group
        entries = []
        while parent is not None:
            if not parent.signature or parent.invoke_without_command:
                entries.append(parent.name)
            else:
                entries.append(parent.name + ' ' + parent.signature)
            parent = parent.parent  # type: ignore
        parent_sig = ' '.join(reversed(entries))

        alias = command.name if not parent_sig else parent_sig + ' ' + command.name
        return f'{lock}{prefix}{alias} {command.signature}'

    async def send_command_help(self, ctx: HideoutContext, command: commands.Command | commands.HybridCommand):
        formatted = await self.format_command(ctx, command)
        embed = discord.Embed(title=formatted, description=command.help)

        is_slash = formatted.startswith('[/]')

        try:
            can_run = await command.can_run(ctx)
        except commands.CommandError:
            can_run = False

        params = [f"**{param.name}** {param.description}" for param in command.params.values() if param.description]

        if params:
            embed.add_field(name='Parameters', value='\n'.join(params), inline=False)

        embed.set_footer(
            text=(
                f"This command is{' ' if is_slash else ' not '}a slash command."
                f"\nYou can{' ' if can_run else 'not '}run this command."
            )
        )
        await ctx.send(embed=embed)

    async def command_tree(
        self, ctx: HideoutContext, command: commands.Group | commands.Command, level: int = 0
    ) -> list[str]:
        lines = [' ' * level * self.indent + await self.format_command(ctx, command, x=True)]
        if isinstance(command, commands.Group):
            for command in await self.filter_commands(ctx, command.commands, verify_checks=False):
                lines.extend(await self.command_tree(ctx, command, level=level + 1))
        return lines

    async def send_group_help(self, ctx: HideoutContext, group: commands.Group | commands.HybridGroup):
        if not group.commands:
            return await self.send_command_help(ctx, group)

        formatted = await self.format_command(ctx, group)
        is_slash = formatted.startswith('[/]')

        try:
            can_run = await group.can_run(ctx)
        except commands.CommandError:
            can_run = False

        embed = discord.Embed(title=formatted, description=group.help)

        params = [f"**{param.name}** {param.description}" for param in group.params.values() if param.description]

        if params:
            embed.add_field(name='Parameters', value='\n'.join(params), inline=False)

        embed.add_field(
            name='Metadata',
            value=(
                f"This command is{' ' if is_slash else ' not '}a slash command."
                f"\nYou can{' ' if can_run else 'not '}run this command."
            ),
            inline=False,
        )

        embed.add_field(
            name='all sub-commands', value=cb('\n'.join(await self.command_tree(ctx, group)), lang=''), inline=False
        )
        embed.set_footer(
            text="\N{HEAVY MULTIPLICATION X} means you can't run that sub-command.\n[/] means that the subcommand is a slash command."
        )
        await ctx.send(embed=embed)

    async def send_cog_help(self, ctx: HideoutContext, cog: HideoutCog):
        embed = discord.Embed(title=cog.qualified_name, description=cog.description)

        lines = []
        for command in cog.get_commands():
            lines.extend(await self.command_tree(ctx, command))

        embed.add_field(name='all sub-commands', value=cb('\n'.join(lines), lang=''), inline=False)
        embed.set_footer(
            text="\N{HEAVY MULTIPLICATION X} means you can't run that sub-command.\n[/] means that the subcommand is a slash command."
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command()
    @app_commands.describe(entry='A valid command, category or topic.')
    async def help(self, ctx: HideoutContext, *, entry: Annotated[str, commands.clean_content] | None):
        """Sends help about a specific command, category or topic.

        You can use prefixes to narrow down your search. For example `!help command:<command>` will only search for commands.

        Valid prefixes are: `command:`, `category:` (or `cog:`) and `topic:`. If you don't include one of these, it will search any of the three, in order.
        """
        # Before we start, if nothing is passed, we send the onboarding page.
        if not entry:
            return await self.send_main_page(ctx)

        # The first thing to look for is a matching command. If one is found, we send the corresponding
        # help message. If one is not found, but the entry was prefixed, we send an error message.
        command = ctx.bot.get_command(entry)
        if entry.startswith('command:'):
            name = entry.removeprefix('command:').strip()
            command = ctx.bot.get_command(name)
            if not command:
                raise commands.BadArgument(f'Command not found: {name[:1000]!r}')
        if command:
            if isinstance(command, (commands.Group, commands.HybridGroup)):
                return await self.send_group_help(ctx, command)
            else:
                return await self.send_command_help(ctx, command)

        # Then, look for a matching cog. If one is found, we send the corresponding
        # help message. If it wasn't, but the entry was prefixed, we send an error message.
        cog_map = {name.lower().strip(): cog for name, cog in ctx.bot.cogs.items()}
        cog = cog_map.get(entry.lower(), None)
        if entry.startswith(('category:', 'cog:')):
            entry = re.sub('^(category:|cog:) *', '', entry)
            cog = cog_map.get(entry.lower(), None)
            if not cog:
                raise commands.BadArgument(f'Category not found: {entry[0:1000]!r}')
        if cog:
            return await self.send_cog_help(ctx, cog)

        # Then we look for a matching topic. Same deal, if not found but prefixed, we send an error.
        query = """
            SELECT array_agg(name) FROM tags 
            WHERE LOWER(name) LIKE 'topic:%' AND (guild_id = $1)
        """
        topics: list[str] = await self.bot.pool.fetchval(query, ctx.guild.id)
        topic_map = {topic.removeprefix('topic:').strip().lower(): topic for topic in topics}
        topic_name = topic_map.get(entry.lower(), None)
        topic = None
        if topic_name:
            try:
                topic = await self.tags.get_tag(topic_name, ctx.guild.id)
            except commands.BadArgument:
                pass
        elif entry.startswith('topic:'):
            stripped = entry.removeprefix('topic:').strip().lower()
            topic_name = topic_map.get(stripped, None)
            if not topic_name:
                raise commands.BadArgument(f'Topic not found: {stripped[0:1000]!r}')
            else:
                try:
                    topic = await self.tags.get_tag(topic_name, ctx.guild.id)
                except commands.BadArgument:
                    raise commands.BadArgument(f'Topic not found: {stripped[0:1000]!r}')
        if topic:
            return await self.send_topic_help(ctx, topic)

        # Alas, nothing matched <uh oh!>. Inform the user about that.
        raise commands.BadArgument(f'{entry[:1000]!r} is not a valid command, category or topic.')

    async def topic_choices(self, interaction: discord.Interaction, current: str) -> list[Choice]:
        query = """
            WITH selected AS (
                SELECT name FROM tags 
                WHERE name LIKE 'topic:%' AND (guild_id = $1)
                ORDER BY SIMILARITY(substr(name, 7), $2::TEXT)
                LIMIT 25
            )
            SELECT array_agg(name) FROM selected
        """
        topics: list[str] = await self.bot.pool.fetchval(
            query, interaction.guild.id if interaction.guild else 0, current.removeprefix('topic:').strip()
        )
        topic_choices = [app_commands.Choice(name=topic, value=topic) for topic in topics]
        return topic_choices

    async def category_choices(self, interaction: discord.Interaction, current: str) -> list[Choice]:
        category_choices = [
            app_commands.Choice(name=f'category: {name}', value=f'category: {name}')
            for name in sorted(
                self.bot.cogs,
                key=lambda x: difflib.SequenceMatcher(None, x, current.removeprefix('category:').strip()).quick_ratio(),
                reverse=True,
            )
        ]
        return category_choices

    async def command_choices(self, interaction: discord.Interaction, current: str) -> list[Choice]:
        command_choices = [
            app_commands.Choice(name=f'command: {cmd.name}', value=f'command: {cmd.name}')
            for cmd in sorted(
                filter(lambda c: not c.hidden, self.bot.commands),
                key=lambda x: difflib.SequenceMatcher(
                    None, x.qualified_name, current.removeprefix('command:').strip()
                ).quick_ratio(),
                reverse=True,
            )
        ]
        return command_choices

    @help.autocomplete('entry')
    async def entry_autocomplete(self, interaction: discord.Interaction, current: str) -> list[Choice]:

        if current.startswith('topic:'):
            return await self.topic_choices(interaction, current)

        if current.startswith('category:'):
            return await self.category_choices(interaction, current)

        if current.startswith('command:'):
            return await self.command_choices(interaction, current)

        return (
            await self.topic_choices(interaction, current)
            + await self.category_choices(interaction, current)
            + await self.command_choices(interaction, current)
        )[:25]
