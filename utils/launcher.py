from __future__ import annotations

import asyncio
import os
import logging

import aiohttp
from dotenv import load_dotenv
import discord

from utils import github
from bot import HideoutManager

load_dotenv('utils/.env')
# (jsk flags are now in the .env)


def _get_or_fail(env_var: str) -> str:
    val = os.environ.get(env_var)
    if not val:
        raise RuntimeError(f'{env_var!r} not set in .env file. Set it.')
    return val


TOKEN = _get_or_fail('TOKEN')
URI = _get_or_fail('POSTGRES')
ERROR_WH = _get_or_fail('ERROR_WEBHOOK_URL')
PREFIX = _get_or_fail('PREFIX')
GH_TOKEN = _get_or_fail('GITHUB_ORG_TOKEN')


async def run_bot(verbose: bool = False) -> None:
    async with (
        aiohttp.ClientSession() as session,
        HideoutManager.temporary_pool(uri=URI) as pool,
        github.create_client(GH_TOKEN) as gh_client,
        HideoutManager(
            session=session,
            pool=pool,
            github_client=gh_client,
            error_wh=ERROR_WH,
            prefix=PREFIX,
        ) as bot,
    ):
        discord.utils.setup_logging(level=logging.DEBUG)
        await bot.start(TOKEN, reconnect=True, verbose=verbose)


if __name__ == '__main__':
    asyncio.run(run_bot())
