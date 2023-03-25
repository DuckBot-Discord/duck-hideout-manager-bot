from __future__ import annotations

import asyncio
import logging
from abc import ABCMeta
from contextlib import suppress
from typing import Any, Callable, Coroutine, Generator, MutableSet, Optional, overload, Self
from weakref import WeakSet

__all__: tuple[str, ...] = ("AsyncInstance",)


_log: logging.Logger = logging.getLogger(__name__)
CloseableType = Callable[[], Any | Coroutine[Any, Any, Any]]


class Task:
    """A custom task store for asyncio tasks and futures.

    Parameters
    ----------
    loop: :class:`asyncio.AbstractEventLoop`
        The event loop to use for creating tasks and futures.

    Attributes
    ----------
    tasks: :class:`set`
        A set of all tasks created by this store.
    futures: :class:`set`
        A set of all futures created by this store.
    children: :class:`set`
        A set of all child stores created by this store.
    close_callbacks: :class:`set`
        A set of all close callbacks added to this store.
    is_closed: :class:`bool`
        Whether or not this store is closed.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.tasks: MutableSet[asyncio.Task[Any]] = WeakSet()
        self.futures: MutableSet[asyncio.Future[Any]] = WeakSet()
        self.children: MutableSet[Task] = WeakSet()
        self.close_callbacks: set[CloseableType] = set()
        self.__loop: asyncio.AbstractEventLoop = loop
        self.__closing: asyncio.Future[bool] = self.__loop.create_future()

    def get_child(self) -> Task:
        # This is a bit of a hacky to get around the task that
        # but it's the best way I can think of to do it.
        store = self.__class__(self.__loop)
        self.children.add(store)
        return store

    def add_close_callback(self, func: CloseableType) -> None:
        self.close_callbacks.add(func)

    def compose_task(self, *args: Any, **kwargs: Any) -> asyncio.Task[Any]:
        task = self.__loop.create_task(*args, **kwargs)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.remove)
        return task

    def compose_future(self) -> asyncio.Future[Any]:
        future = self.__loop.create_future()
        self.futures.add(future)
        future.add_done_callback(self.futures.remove)
        return future

    @property
    def is_closed(self) -> bool:
        return self.__closing.done()

    async def close(self, exc: Optional[Exception] = None) -> None:
        if self.__closing.done():
            return

        if exc is None:
            self.__closing.set_result(True)
        else:
            self.__closing.set_exception(exc)

        for future in self.futures:
            if future.done():
                continue

            future.set_exception(
                exc or asyncio.CancelledError("Object %r closed" % self),
            )

        tasks: list[asyncio.Task[Any] | Coroutine[Any, Any, Any]] = []

        for func in self.close_callbacks:
            try:
                result: Any | Coroutine[Any, Any, Any] = func()
            except BaseException:
                # Something gone bad happened while trying to close
                # the object. We need to log this and continue.
                _log.exception(
                    (
                        "Error while trying to close %r. "
                        "The exception was not retrieved due to an error in "
                        "asyncio's exception handler. ",
                        func,
                    ),
                    self,
                )
                continue

            if asyncio.iscoroutine(result) or isinstance(result, asyncio.Future):
                # Simply add our coros to the list of tasks to wait on.
                tasks.append(result)  # type: ignore

        for task in self.tasks:
            if task.done():
                continue

            task.cancel()
            tasks.append(task)

        for store in self.children:
            tasks.append(store.close())

        await asyncio.gather(*tasks, return_exceptions=True)


class AsyncABCMeta(ABCMeta):
    """
    This metaclass ensures that the ``__ainit__`` method is a coroutine.
    """
    def __new__(
        cls,
        clsname: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
    ) -> AsyncABCMeta:
        instance = super(AsyncABCMeta, cls).__new__(
            cls,
            clsname,
            bases,
            namespace,
        )

        if not asyncio.iscoroutinefunction(instance.__ainit__):  # type: ignore
            raise TypeError("__ainit__ must be coroutine")

        return instance


class AsyncInstanceType(metaclass=AsyncABCMeta):
    """
    Parameters
    ----------
    *args: Any
        The arguments to pass to ``__ainit__``.
    **kwargs: Any
        The keyword arguments to pass to ``__ainit__``.

    Attributes
    ----------
    loop: :class:`asyncio.AbstractEventLoop`
        The event loop to use for creating tasks and futures.
    """
    __slots__: tuple[str, ...] = ("_args", "_kwargs")
    _args: tuple[Any, ...]
    _kwargs: dict[str, Any]

    def __new__(
        cls,
        *args: Any,
        **kwargs: Any,
    ) -> AsyncInstanceType:
        instance = super().__new__(cls)
        instance._args = args
        instance._kwargs = kwargs
        return instance

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return asyncio.get_running_loop()

    def __await__(self) -> Generator[Any, None, AsyncInstanceType]:
        yield from self.__ainit__(*self._args, **self._kwargs).__await__()

        # blep :<
        return self

    async def __ainit__(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        ...


class AsyncInstance(AsyncInstanceType):
    """A base class for creating async classes.

    This class is designed to be used as a base class for creating
    async classes. It provides a ``__await__`` method which calls
    ``__ainit__`` and returns the instance.
    """
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.__closed = False
        self._async_class_task_store: Task

    @property
    def __tasks__(self) -> Task:
        return self._async_class_task_store

    @property
    def is_closed(self) -> bool:
        return self.__closed

    def compose_task(self, *args: Any, **kwargs: Any) -> asyncio.Task[Any]:
        return self.__tasks__.compose_task(*args, **kwargs)

    def compose_future(self) -> asyncio.Future[Any]:
        return self.__tasks__.compose_future()

    async def __adel__(self) -> None:
        pass

    def __await__(self) -> Generator[Any, None, Self]:
        if not hasattr(self, "_async_class_task_store"):
            self._async_class_task_store = Task(self.loop)

        yield from self.compose_task(
            self.__ainit__(*self._args, **self._kwargs),
        ).__await__()  # cursed
        return self

    def __del__(self) -> None:
        if self.__closed:
            return

        with suppress(BaseException):
            self.loop.create_task(self.close())

    async def close(self, exc: Optional[Exception] = None) -> None:
        if self.__closed:
            return

        tasks: list[asyncio.Task[Any] | Coroutine[Any, Any, Any]] = []

        if hasattr(self, "_async_class_task_store"):
            # Allows for graceful closing of the task manager.
            tasks.append(self.__adel__())
            tasks.append(self.__tasks__.close(exc))
            self.__closed = True

        if not tasks:
            return

        # Gather all the tasks and wait for them to finish.
        # Could use the new syntax but I am not sure if every contributor
        # is using 3.11 yet. Changable in the future.
        await asyncio.gather(*tasks, return_exceptions=True)

    # I just looked up the overload docs and I am still confused
    # hope this works, as plannend :p
    @overload
    async def __ainit__(self) -> None:
        ...

    @overload
    async def __ainit__(self, *args: Any, **kwargs: Any) -> None:
        ...

    async def __ainit__(self, *args: Any, **kwargs: Any) -> None:
        ...

    def __init_subclass__(cls, **kwargs: Any) -> None:
        # We don't want to allow overriding __await__ as it is used
        if cls.__await__ is not AsyncInstance.__await__:
            raise TypeError(
                f"{cls.__name__} cannot override __await__",
            )


if __name__ == "__main__":
    # NOTE: DELETE THIS BEFORE MERGING
    async def compose_test_instance() -> None:
        class Test(AsyncInstance):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, **kwargs)

            async def __ainit__(self, *args: Any, **kwargs: Any) -> None:
                print("Test.__ainit__", args, kwargs)
                await asyncio.sleep(1)
                print("Test.__ainit__ done")

            async def __adel__(self) -> None:
                print("Test.__adel__")
                await asyncio.sleep(1)
                print("Test.__adel__ done")

        test = await Test(1, 2, 3, a=4, b=5, c=6)
        print("Test.__await__ done")
        await test.close()

        try:
            class FailOverride(AsyncInstance):  # type: ignore # reportUnusedClass
                def __init__(self, *args: Any, **kwargs: Any) -> None:
                    super().__init__(*args, **kwargs)

                # This case is not allowed and should raise a TypeError
                async def __await__(self) -> Generator[Any, None, AsyncInstance]:  # type: ignore
                    ...
            
            print("This should not print")
        except TypeError as e:
            print(e)

    # Test.__ainit__ (1, 2, 3) {'a': 4, 'b': 5, 'c': 6}
    # Test.__ainit__ done
    # Test.__await__ done
    # Test.__adel__
    # Test.__adel__ done
    # FailOverride cannot override __await__

    asyncio.run(compose_test_instance())
