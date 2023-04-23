import asyncio
import calendar
import re
from datetime import date, timedelta
from logging import getLogger, basicConfig, INFO, DEBUG
from pathlib import Path
from typing import Awaitable, Callable, NamedTuple, Tuple, TypeAlias
from types import ModuleType

__all__ = (
    'EventsManager',
    'FileInfo',
    'FileNameParsingFailure',
    'EventNotFound',
)

DatePair: TypeAlias = Tuple[date, date]
CaseGetter: TypeAlias = Callable[[], Awaitable[DatePair] | DatePair]

SPECIAL_CASES: dict[str, CaseGetter] = {}
ICONS_FOLDER = 'assets/guild_icons/'
DEFAULT_GUILD_ICON = 'DEFAULT.gif'
IGNORED_FILES = ['DEFAULT.gif', 'README.md']

log = getLogger(__name__)


class FileInfo(NamedTuple):
    file: Path
    name: str
    start: date
    end: date


class FileNameParsingFailure(Exception):
    """Raised when parsing a file name fails."""


class EventNotFound(Exception):
    """Raised when an event is not found."""

    def __init__(self, the_date: date) -> None:
        super().__init__(f"No event found for date {the_date!r}")


class EventsManager:
    def __init__(self) -> None:
        self.events: dict[date, FileInfo] = {}

    def handle_parsed_data(self, day: str | int, month: str | int, start: date | None) -> date:
        month = int(month)
        if day == 'x':
            if start:
                _, day = calendar.monthrange(start.year, start.month)
                return date.today().replace(day=day, month=month)

            else:
                return date.today().replace(day=1, month=month)
        else:
            day = int(day)
            return date.today().replace(day=day, month=month)

    async def parse_filename(self, file: Path) -> FileInfo | None:
        """|coro|
        Parses a file name and returns it's corresponding FileInfo.

        Returns
        -------
        Optional[FileInfo]
            The information about this file. Returns None for README.md and DEFAULT.gif

        01-04-[April Fools].gif      # A specific day (1st of April)
        01-12-23-12-[Advent].gif     # A range of dates (1st of December to 23rd of December)
        special_EA-[Easter].gif      # A specific event with a variable date (requires callable to acquire this date each year *(somehow?) idk)
        x-06-[Pride Month].gif       # An entire month (June)
        x-06-x-07-[Not Sure].gif     # Two months (From the start of June to the end of July)
        """
        filename = file.name
        try:
            SINGLE_PERIOD_PATTERN = re.compile(
                r"^(?P<DAY>[0-3][0-9]|x)-(?P<MONTH>[0-1][0-9])-\[(?P<EVENT>.+)\].(?P<EXT>gif|png)$"
            )
            COMPOSITE_PERIOD_PATTERN = re.compile(
                r"^(?P<DAY1>[0-3][0-9]|x)-(?P<MONTH1>[0-1][0-9])-(?P<DAY2>[0-3][0-9]|x)-(?P<MONTH2>[0-1][0-9])-\[(?P<EVENT>.+)\].(?P<EXT>gif|png)$"
            )
            SPECIAL_CASE_PATTERN = re.compile(r"^special_(?P<CID>[a-zA-Z]{2})-\[(?P<EVENT>.+)\].(?P<EXT>gif|png)$")

            if match := SINGLE_PERIOD_PATTERN.fullmatch(filename):
                # This is the match that can either correspond to a full day or a full month.
                log.debug('Parsing single-period file %s', filename)

                month = int(match.group('MONTH'))
                day = match.group('DAY')

                start = self.handle_parsed_data(day=day, month=month, start=None)
                end = self.handle_parsed_data(day=day, month=month, start=start)

            elif match := COMPOSITE_PERIOD_PATTERN.fullmatch(filename):
                # The event is for a lapse of time between two dates.
                log.debug('Parsing composite-period file %s', filename)

                start = self.handle_parsed_data(
                    day=match.group('DAY1'),
                    month=match.group('MONTH1'),
                    start=None,
                )

                end = self.handle_parsed_data(
                    day=match.group('DAY2'),
                    month=match.group('MONTH2'),
                    start=start,
                )

            elif match := SPECIAL_CASE_PATTERN.fullmatch(filename):
                # Special-cased callables that require custom state.

                special_case_id: str = match.group('CID')
                log.debug('Parsing special-case file %s (CID: %s)', filename, special_case_id)

                module: ModuleType = __import__(f'assets.guild_icons.special_cases.{special_case_id}')
                log.debug('Found module for parser at %s', module.__name__)

                if not hasattr(module, 'parse'):
                    raise FileNameParsingFailure(f'Could not find special case file for {filename}')

                if not asyncio.iscoroutinefunction(module.parse):
                    raise FileNameParsingFailure(f"'parse()' method of {module} must be a coroutine function.")

                start, end = await module.parse()

            elif filename in IGNORED_FILES:
                return None

            else:
                raise FileNameParsingFailure(f'Invalid filename format for file {filename!r}.')

        except FileNameParsingFailure as e:
            raise e
        except Exception as e:
            # Mostly when invalid dates are provided. Propagate the exception raised by datetime.date
            raise FileNameParsingFailure(f'Encountered an error while parsing {filename!r}: {type(e).__name__} {e}') from e

        event_name = match.group('EVENT')

        return FileInfo(name=event_name, start=start, end=end, file=file)

    def date_range(self, start: date, end: date):
        today = start
        end = end + timedelta(days=1)
        while today < end:
            yield today
            today = today + timedelta(days=1)

    async def populate_events_calendar(self):
        self.events = {}

        for file in Path(ICONS_FOLDER).glob('*.*'):
            file_data = await self.parse_filename(file=file)

            if not file_data:
                continue

            for date in self.date_range(file_data.start, file_data.end):
                if date in self.events:
                    raise RuntimeError(f'Date {date!r} already in cache for event {file_data.name}')
                log.debug('Populating event %s for date %s', file_data.name, date)
                self.events[date] = file_data

    def get_for(self, the_date: date) -> FileInfo:
        try:
            return self.events[the_date]
        except KeyError:
            raise EventNotFound(the_date)


async def run_TGI_checks(verbose: bool = False):
    basicConfig(level=DEBUG if verbose else INFO)
    manager = EventsManager()
    await manager.populate_events_calendar()
