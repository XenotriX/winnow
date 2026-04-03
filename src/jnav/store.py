from dataclasses import dataclass

from aioreactive import AsyncSubject

from jnav.parsing import ParsedEntry

LogEntry = ParsedEntry


@dataclass(frozen=True)
class IndexedEntry:
    index: int
    entry: LogEntry


class Store:
    entries: list[LogEntry]
    on_append: AsyncSubject[list[IndexedEntry]]

    def __init__(self) -> None:
        self.entries = []
        self.on_append = AsyncSubject[list[IndexedEntry]]()

    async def append_entries(self, new_entries: list[LogEntry]) -> None:
        start = len(self.entries)
        self.entries.extend(new_entries)
        indexed = [IndexedEntry(start + i, e) for i, e in enumerate(new_entries)]
        await self.on_append.asend(indexed)

    def get(self, index: int) -> IndexedEntry:
        return IndexedEntry(index, self.entries[index])

    def all(self) -> list[IndexedEntry]:
        return [IndexedEntry(i, e) for i, e in enumerate(self.entries)]

    def __len__(self) -> int:
        return len(self.entries)
