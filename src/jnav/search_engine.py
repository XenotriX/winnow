from typing import Any, cast

from aioreactive import AsyncSubject

from jnav.log_model import LogModel
from jnav.store import IndexedEntry


def entry_matches_search(entry: dict[str, Any], term_lower: str) -> bool:
    def _check(obj: object) -> bool:
        if isinstance(obj, str):
            return term_lower in obj.lower()
        if isinstance(obj, dict):
            obj = cast(dict[str, Any], obj)
            return any(_check(v) for v in obj.values())
        if isinstance(obj, list):
            obj = cast(list[Any], obj)
            return any(_check(item) for item in obj)
        return term_lower in str(obj).lower()

    return _check(entry)


class SearchEngine:
    on_change: AsyncSubject[None]

    def __init__(self, model: LogModel) -> None:
        self._model = model
        self._term: str = ""
        self._matches: list[int] = []
        self.on_change = AsyncSubject[None]()

    @property
    def term(self) -> str:
        return self._term

    @property
    def matches(self) -> list[int]:
        return self._matches

    @property
    def active(self) -> bool:
        return bool(self._term)

    async def start(self) -> None:
        await self._model.on_rebuild.subscribe_async(self._on_rebuild)
        await self._model.on_append.subscribe_async(self._on_append)

    async def set_term(self, term: str) -> None:
        self._term = term
        self._recompute_all()
        await self.on_change.asend(None)

    async def clear(self) -> None:
        self._term = ""
        self._matches = []
        await self.on_change.asend(None)

    def _recompute_all(self) -> None:
        if not self._term:
            self._matches = []
            return
        term_lower = self._term.lower()
        self._matches = [
            ie.index
            for ie in self._model.all()
            if entry_matches_search(ie.entry.expanded, term_lower)
        ]

    async def _on_rebuild(self, _: None) -> None:
        if not self._term:
            return
        self._recompute_all()
        await self.on_change.asend(None)

    async def _on_append(self, new_entries: list[IndexedEntry]) -> None:
        if not self._term:
            return
        term_lower = self._term.lower()
        new_matches = [
            ie.index
            for ie in new_entries
            if entry_matches_search(ie.entry.expanded, term_lower)
        ]
        if new_matches:
            self._matches.extend(new_matches)
            await self.on_change.asend(None)
