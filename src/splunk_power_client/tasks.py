import asyncio
from contextvars import Context
from typing import Any, TypeVar

_T = TypeVar


class BoundedTaskGroup(asyncio.TaskGroup):
    """_summary_

    Args:
        asyncio (_type_): _description_
    """

    def __init__(self, *args, max_parallelism=1, **kwargs) -> None:
        super().__init__(*args)
        if max_parallelism:
            self._sem = asyncio.Semaphore(max_parallelism)
        else:
            self._sem = None

    def create_task(
        self,
        coro: asyncio.Coroutine[Any, Any, _T],
        *,
        name: str | None = None,
        context: Context | None = None,
    ) -> asyncio.Task[_T]:
        if self._sem:

            async def _wrapped_coro(sem, coro):
                async with sem:
                    return await coro

            coro = _wrapped_coro(self._sem, coro)
        return super().create_task(coro, name=name, context=context)
