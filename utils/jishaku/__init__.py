from __future__ import annotations

import contextlib
import io
import itertools
import time
import traceback
from typing import TYPE_CHECKING, Annotated, Any, Optional, TypeVar

import discord
from jishaku.codeblocks import Codeblock, codeblock_converter
from jishaku.cog import OPTIONAL_FEATURES, STANDARD_FEATURES
from jishaku.exception_handling import ReplResponseReactor
from jishaku.features.baseclass import Feature
from jishaku.features.management import ManagementFeature
from jishaku.features.python import PythonFeature
from jishaku.flags import Flags
from jishaku.functools import AsyncSender
from jishaku.modules import ExtensionConverter
from jishaku.paginators import PaginatorInterface, WrappedPaginator, use_file_check
from jishaku.repl import AsyncCodeExecutor, Scope
from jishaku.repl.repl_builtins import get_var_dict_from_ctx

from utils.context import HideoutContext

from .. import HideoutCog, add_logging


if TYPE_CHECKING:
    from bot import HideoutManager

T = TypeVar("T")


class OverwrittenManagementFeature(ManagementFeature):
    @Feature.Command(parent="jsk", name="load", aliases=["reload"])
    async def jsk_load(self, ctx: HideoutContext, *extensions: Annotated[list[str], ExtensionConverter]):
        """
        Loads or reloads the given extension names.

        Reports any extensions that failed to load.
        """
        paginator = WrappedPaginator(prefix="", suffix="")

        # 'jsk reload' on its own just reloads jishaku
        if ctx.invoked_with == "reload" and not extensions:
            extensions = (["utils.jishaku"],)

        for extension in itertools.chain(*extensions):
            method, icon = (
                (
                    self.bot.reload_extension,
                    "\N{CLOCKWISE RIGHTWARDS AND LEFTWARDS OPEN CIRCLE ARROWS}",
                )
                if extension in self.bot.extensions
                else (self.bot.load_extension, "\N{INBOX TRAY}")
            )

            try:
                await discord.utils.maybe_coroutine(method, extension)
            except Exception as exc:  # pylint: disable=broad-except
                traceback_data = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__, 1))

                paginator.add_line(
                    f"{icon}\N{WARNING SIGN} `{extension}`\n```py\n{traceback_data}\n```",
                    empty=True,
                )
            else:
                paginator.add_line(f"{icon} `{extension}`", empty=True)

        for page in paginator.pages:
            await ctx.send(page)


class HideoutManagerJishaku(
    HideoutCog,
    OverwrittenManagementFeature,
    *STANDARD_FEATURES,  # type: ignore
    *OPTIONAL_FEATURES,  # type: ignore
):
    """
    The main frontend class for JIshaku.

    This implements all Features and is the main entry point for Jishaku.

    Attributes
    ----------
    bot: :class:`HideoutManager`
        The bot instance this frontend is attached to.
    """

    __is_jishaku__: bool = True

    async def jsk_python_result_handling(
        self,
        ctx: HideoutContext,
        result: Any,
        *,
        start_time: Optional[float] = None,
        redirect_stdout: Optional[str] = None,
    ):
        if isinstance(result, discord.Message):
            return await ctx.send(f"<Message <{result.jump_url}>>")

        elif isinstance(result, discord.File):
            return await ctx.send(file=result)

        elif isinstance(result, PaginatorInterface):
            return await result.send_to(ctx)

        elif isinstance(result, discord.Embed):
            return await ctx.send(embed=result)

        if not isinstance(result, str):
            result = repr(result)

        stripper = "**Redirected stdout**:\n{}"
        total = 2000
        if redirect_stdout:
            total -= len(f"{stripper.format(redirect_stdout)}\n")

        if len(result) <= total:
            if result.strip == "":
                result = "\u200b"

            if redirect_stdout:
                result = f"{stripper.format(redirect_stdout)}\n{result}"

            return await ctx.send(result.replace(self.bot.http.token or "", "[token omitted]"))

        if use_file_check(ctx, len(result)):  # File "full content" preview limit
            # Discord's desktop and web client now supports an interactive file content
            #  display for files encoded in UTF-8.
            # Since this avoids escape issues and is more intuitive than pagination for
            #  long results, it will now be prioritized over PaginatorInterface if the
            #  resultant content is below the filesize threshold
            return await ctx.send(file=discord.File(filename="output.py", fp=io.BytesIO(result.encode("utf-8"))))

        # inconsistency here, results get wrapped in codeblocks when they are too large
        #  but don't if they're not. probably not that bad, but noting for later review
        paginator = WrappedPaginator(prefix="```py", suffix="```", max_size=1985)

        if redirect_stdout:
            for chunk in self.bot.chunker(f'{stripper.format(redirect_stdout).replace("**", "")}\n', size=1975):
                paginator.add_line(chunk)

        for chunk in self.bot.chunker(result, size=1975):
            paginator.add_line(chunk)

        interface = PaginatorInterface(ctx.bot, paginator, owner=ctx.author)
        return await interface.send_to(ctx)

    @discord.utils.copy_doc(PythonFeature.jsk_python)  # type: ignore
    @Feature.Command(parent="jsk", name="py", aliases=["python"])
    async def jsk_python(self, ctx: HideoutContext, *, argument: Annotated[Codeblock, codeblock_converter]) -> None:
        """|coro|

        The subclassed jsk python command to implement some more functionality and features.

        Added
        -----
        - :meth:`contextlib.redirect_stdout` to allow for print statements.
        - :meth:`utils.add_logging` and `self` to the scope.

        Parameters
        ----------
        argument: :class:`str`
            The code block to evaluate and return.
        """

        arg_dict = get_var_dict_from_ctx(ctx, Flags.SCOPE_PREFIX)
        arg_dict.update(
            add_logging=add_logging,
            self=self,
            _=self.last_result,
            _r=getattr(ctx.message.reference, 'resolved', None),
            _a=ctx.author,
            _m=ctx.message,
            _now=discord.utils.utcnow,
            _g=ctx.guild,
        )

        scope: Scope = self.scope  # type: ignore
        printed = io.StringIO()

        try:
            async with ReplResponseReactor(ctx.message):
                with self.submit(ctx):
                    with contextlib.redirect_stdout(printed):
                        executor = AsyncCodeExecutor(argument.content, scope, arg_dict=arg_dict)
                        start = time.perf_counter()

                        # Absolutely a garbage lib that I have to fix jesus christ.
                        # I have to rewrite this lib holy jesus its so bad.
                        async for send, result in AsyncSender(executor):  # type: ignore
                            self.last_result: Any = result

                            value = printed.getvalue()
                            send(
                                await self.jsk_python_result_handling(
                                    ctx,
                                    result,
                                    start_time=start,
                                    redirect_stdout=None if value == "" else value,
                                )
                            )

        finally:
            scope.clear_intersection(arg_dict)


async def setup(bot: HideoutManager) -> None:
    return await bot.add_cog(HideoutManagerJishaku(bot=bot))
