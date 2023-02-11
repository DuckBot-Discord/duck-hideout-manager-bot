from __future__ import annotations

import io
import time
from typing import List, Annotated, TYPE_CHECKING

from discord import File
from discord.ext import commands

from tabulate import tabulate

from utils import HideoutCog, HideoutContext, UntilFlag

if not TYPE_CHECKING:
    from import_expression import eval


def cleanup_code(content: str):
    """Automatically removes code blocks from the code."""
    content = content.strip()
    # remove ```py\n```
    if content.startswith('```') and content.endswith('```'):
        return '\n'.join(content.split('\n')[1:-1])

    # remove `foo`
    return content.strip('` \n')


class plural:
    def __init__(self, value: int):
        self.value = value

    def __format__(self, format_spec: str):
        v = self.value
        singular, _, plural = format_spec.partition('|')
        plural = plural or f'{singular}s'
        if abs(v) != 1:
            return f'{v} {plural}'
        return f'{v} {singular}'


class EvaluatedArg(commands.Converter[str]):
    async def convert(self, ctx: HideoutContext, argument: str) -> str:  # pyright: reportIncompatibleMethodOverride=false
        return eval(cleanup_code(argument), {'bot': ctx.bot, 'ctx': ctx})


class SqlCommandFlags(commands.FlagConverter, prefix="--", delimiter=" ", case_insensitive=True):
    args: List[str] = commands.flag(name='argument', aliases=['a', 'arg'], default=[])


class SQLCommands(HideoutCog):
    @commands.command()
    async def sql(self, ctx: HideoutContext, *, query: UntilFlag[Annotated[str, cleanup_code], SqlCommandFlags]):
        """Executes an SQL query."""
        is_multistatement = query.value.count(';') > 1
        if is_multistatement:
            # fetch does not support multiple statements
            strategy = ctx.bot.pool.execute
        else:
            strategy = ctx.bot.pool.fetch

        try:
            start = time.perf_counter()
            results = await strategy(query.value, *query.flags.args)
            dt = (time.perf_counter() - start) * 1000.0
        except Exception as e:
            return await ctx.send(f'{type(e).__name__}: {e}')

        rows = len(results)
        if rows == 0 or isinstance(results, str):
            result = 'Query returned o rows\n' if rows == 0 else str(results)
            await ctx.send(result + f'*Ran in {dt:.2f}ms*')

        else:
            table = tabulate(results, headers='keys', tablefmt='orgtbl')

            fmt = f'```\n{table}\n```*Returned {plural(rows):row} in {dt:.2f}ms*'
            if len(fmt) > 2000:
                fp = io.BytesIO(table.encode('utf-8'))
                await ctx.send(
                    f'*Too many results...\nReturned {plural(rows):row} in {dt:.2f}ms*', file=File(fp, 'output.txt')
                )
            else:
                await ctx.send(fmt)
