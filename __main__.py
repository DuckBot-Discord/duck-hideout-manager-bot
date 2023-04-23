import asyncio

import click


@click.command()
@click.option('--verbose', is_flag=True, help='Makes logs more verbose.')
@click.option('--verify-dates', is_flag=True, help='Verify the TGI dates.')
def run(verbose: bool, verify_dates: bool):
    """Options to run the bot."""
    if verify_dates:
        from cogs.tgi_event_manager import run_TGI_checks

        asyncio.run(run_TGI_checks(verbose=verbose))
    else:
        from utils.bot_bases.launcher import run_bot

        asyncio.run(run_bot(verbose=verbose))


if __name__ == '__main__':
    run()
