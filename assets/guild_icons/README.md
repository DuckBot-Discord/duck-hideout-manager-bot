# How to Add Guild Icons?

Hey there! First of all thanks for wanting to contribute to the Duck Hideout server icons. I appreciate it.

If you want to contribute with an image for a certain event, you need to create a pull request that adds a gif or
a png to this folder. It must follow one of the following schemas:

> **Note** Use standard dates. Day before month. ``30-09`` not ``09-30``.

## Single Date

An event or time frame that lasts one day.

```
<day>-<month>-[<Event Name>].<Format [gif|png]>
```

> **Example** ``25-12-[The Day of Christmas].png``

## Date Lapse

An event that lasts multiple days, can span across multiple months.

```
<day start>-<month start>-<day end>-<month end>-[<Event Name>].<Format [gif|png]>
```

> **Example** ``01-01-31-01-[The Month of January].png``

## Single Month

An event that lasts for a month.

```
x-<month>-[<Event Name>].<Format [gif|png]>
```

> **Example** ``x-01-[The Month of January].png``

## Multi Month Lapse

An event that spans across multiple months.

```
x-<month start>-x-<month end>-[<Event Name>].<Format [gif|png]>
```

> **Example** ``x-01-x-12-[The Entire Year].png``

> **Note**
>
> You can use ``x`` in only the first of the pair to make it start at the beginning of the month, then to a single day.
>
> ``x-01-25-01`` from Jan 1st to Jan 25th.
>
> You can also use ``x`` in only the second pair to denote that it will be till the end of the month.
>
> ``10-01-x-01`` from Jan 10th to Jan 31st.
## Special Cases

Special cases are days or lapses that do not have a specific date, but change year by year. For example Easter.

For these, special handling is required for each, through the use of a callable from the [special_cases](./special_cases/)
folder. In it, you must define a function called parse which returns a pair of dates. See [TEMPLATE.py](./special_cases/TEMPLATE.py) for more info.

The file must be called the same as the identifier.

```
special_<Identifier [a-zA-z]{2}>-[<Event Name>].Format [gif|png]>
```

> **Example** ``special_EA-[Easter].png``
>
> And the file would be named ``EA.py``
> ```py
> from datetime import date
> 
> async def parse():
>     """A parser for Easter which retrieves this year's easter through an API"""
>     return date(...), date(...)
