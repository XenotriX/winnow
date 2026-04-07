from collections.abc import Sequence
from typing import Generic, Protocol, TypeVar

from aioreactive import AsyncObservable

T = TypeVar("T", covariant=True)


class Model(Protocol, Generic[T]):
    @property
    def on_append(self) -> AsyncObservable[Sequence[T]]: ...

    def get(self, pos: int) -> T: ...
    def count(self) -> int: ...
    def is_empty(self) -> bool: ...
