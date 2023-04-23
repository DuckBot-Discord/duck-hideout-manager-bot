from logging import getLogger
from datetime import date, time, timezone
from pathlib import Path
from typing import Awaitable, Callable, Tuple, TypeAlias, Any

from discord.ext import tasks

from bot import HideoutManager
from utils import HideoutCog, DUCK_HIDEOUT
from utils.timed_guild_icons import EventsManager, EventNotFound, ICONS_FOLDER, DEFAULT_GUILD_ICON

DatePair: TypeAlias = Tuple[date, date]
CaseGetter: TypeAlias = Callable[[], Awaitable[DatePair] | DatePair]

log = getLogger(__name__)


class TimedEvents(HideoutCog):
    def __init__(self, bot: HideoutManager, *args: Any, **kwargs: Any) -> None:
        super().__init__(bot, *args, **kwargs)
        self.current_year: int = 0
        self.current_event_name: str = 'DEFAULT'
        self.events = EventsManager()

    @tasks.loop(time=time(hour=0, minute=0, second=0, tzinfo=timezone.utc))
    async def daily_task(self):
        guild = self.bot.get_guild(DUCK_HIDEOUT)

        if not guild:
            return log.critical('Could not find Duck Hideout guild.')

        today = date.today()
        if today.year != self.current_year:
            await self.events.populate_events_calendar()

        try:
            event = self.events.get_for(today)

            if event.name == self.current_event_name:
                return

            with event.file.open('rb') as fp:
                log.info('Editing guild icon for event %s', event.name)
                if not self.bot.no_automatic_features:
                    await guild.edit(icon=fp.read())

            self.current_event_name = event.name

        except EventNotFound:
            file = Path(ICONS_FOLDER + DEFAULT_GUILD_ICON)

            if file.stem == self.current_event_name:
                return

            with file.open('rb') as fp:
                log.info('Editing guild icon to DEFAULT')
                if not self.bot.no_automatic_features:
                    await guild.edit(icon=fp.read())

            self.current_event_name = file.stem

    async def cog_load(self) -> None:
        await self.events.populate_events_calendar()
        self.daily_task.start()
        return await super().cog_load()

    async def cog_unload(self) -> None:
        self.daily_task.cancel()
        return await super().cog_unload()


async def setup(bot: HideoutManager):
    bot.guilds[0].create_text_channel
    await bot.add_cog(TimedEvents(bot))
