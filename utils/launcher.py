from __future__ import annotations

import logging
import os
import aiohttp
import asyncio

from bot import DuckBot
from dotenv import load_dotenv
from utils.helpers import col

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

logging.basicConfig(
    level=logging.INFO,
    format=f'{col()}[{col(7)}%(asctime)s{col()} | {col(4)}%(name)s{col()}:{col(3)}%(levelname)s{col()}] %(message)s{col()}',
)

log = logging.getLogger('DuckBot.launcher')


async def run_bot(verbose: bool = False) -> None:
    async with aiohttp.ClientSession() as session, DuckBot.temporary_pool(uri=URI) as pool, DuckBot(
        session=session, pool=pool, error_wh=ERROR_WH, prefix=PREFIX
    ) as duck:
        await duck.start(TOKEN, reconnect=True, verbose=verbose)


if __name__ == '__main__':
    asyncio.run(run_bot())
