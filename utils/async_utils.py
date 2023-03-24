import inspect
from abc import ABCMeta
from typing import Any, Callable, Dict, Tuple, Type, TypeVar

__all__: tuple[str, ...] = ("AsyncInstance",)


_T = TypeVar("_T")


class AsyncABCMeta(ABCMeta):
    def __init__(cls, name: str, bases: Tuple[Type[Any], ...], methods: Dict[str, Any]) -> None:
        coros: Dict[str, Callable[..., Any]] = {}
        for base in reversed(cls.__mro__):
            coros.update((name, val) for name, val in vars(base).items() if inspect.iscoroutinefunction(val))

        for name, val in vars(cls).items():
            if name in coros and not inspect.iscoroutinefunction(val):
                raise TypeError('Must use async def %s%s' % (name, inspect.signature(val)))
        super().__init__(name, bases, methods)


class AsyncABC(metaclass=AsyncABCMeta):
    pass


class AsyncInstanceType(AsyncABCMeta):
    @staticmethod
    def __new__(cls: Type[_T], clsname: str, bases: Tuple[Type[Any], ...], attributes: Dict[str, Any]) -> _T:  # type: ignore
        if '__init__' in attributes and not inspect.iscoroutinefunction(attributes['__init__']):
            raise TypeError('__init__ must be a coroutine')
        return super().__new__(cls, clsname, bases, attributes)

    async def __call__(cls: Type[_T], *args: Any, **kwargs: Any) -> _T:
        self = cls.__new__(cls, *args, **kwargs)

        await self.__init__(*args, **kwargs)  # type: ignore
        return self


class AsyncInstance(metaclass=AsyncInstanceType):
    """A class that creates asynchronous instances.

    Its a base class for classes that need to be asynchronous.

    Example
    -------

    >>> import asyncio
    >>> from utils import AsyncInstance
    ...
    >>> class TestClass(AsyncInstance):
    ...     # Note creating this constructor with `def` will raise an error.
    ...     async def __init__(self, name: str):
    ...         self.name = name
    ...
    ...
    >>> async def main():
    ...     test = await TestClass("test")
    ...     print(test.name)
    ...     await asyncio.get_running_loop().shutdown_asyncgens()
    ...
    >>> asyncio.run(main())
    """
    pass
