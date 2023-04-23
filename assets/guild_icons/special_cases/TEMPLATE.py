from datetime import date


async def parse() -> tuple[date, date]:
    """|coro|
    A hook used to get a special-case date for an event. Aka events that don't have a set time and change year by year.
    This hook function is not passed any parameters, since it is specific for the event. You must return 2 date objects.
    """
    ...
