import asyncio

import click

from utils.launcher import run_bot


@click.command()
@click.option('--verbose', is_flag=True, help='Makes logs more verbose.')
def run(verbose: bool):
    """Options to run the bot."""
    asyncio.run(run_bot(verbose=verbose))


if __name__ == '__main__':
    run()
