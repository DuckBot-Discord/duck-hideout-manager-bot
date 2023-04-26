from datetime import date, timedelta
from dateutil.easter import easter


async def parse() -> tuple[date, date]:
    """#TODO: create an easter image"""
    easter_date = easter(date.today().year)
    return easter_date - timedelta(days=3), easter_date + timedelta(days=1)
