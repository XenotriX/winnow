from typing import override
import aioreactive as rx
from aioreactive import AsyncSubject, pipe

from jnav.filter_provider import FilterProvider
from jnav.filtering import apply_combined_filters
from jnav.store import IndexedEntry, Store
from jnav.model import Model


class LogModel(Model[IndexedEntry]):
    _on_append: AsyncSubject[list[IndexedEntry]]
    on_will_rebuild: AsyncSubject[None]
    on_rebuild: AsyncSubject[None]
    _filtering_enabled: bool
    _view: list[int]

    def __init__(
        self,
        store: Store,
        filter_provider: FilterProvider,
    ):
        self._store = store
        self._filter_provider = filter_provider
        self._on_append = AsyncSubject[list[IndexedEntry]]()
        self.on_will_rebuild = AsyncSubject[None]()
        self.on_rebuild = AsyncSubject[None]()
        self._filtering_enabled = True
        self._view = []

    @property
    @override
    def on_append(self) -> AsyncSubject[list[IndexedEntry]]:
        return self._on_append

    async def start(self) -> None:
        await self._filter_provider.on_change.subscribe_async(self.refilter)
        filtered_append = pipe(
            self._store.on_append,
            rx.map(self._filter_batch),
            rx.filter(lambda batch: len(batch) > 0),
        )
        await filtered_append.subscribe_async(self._append_to_view)

    async def _append_to_view(self, batch: list[IndexedEntry]) -> None:
        self._view.extend(ie.index for ie in batch)
        await self._on_append.asend(batch)

    def _filter_batch(self, batch: list[IndexedEntry]) -> list[IndexedEntry]:
        return [i for i in batch if self._apply_filters(i)]

    def _apply_filters(self, indexed_entry: IndexedEntry) -> bool:
        if not self._filtering_enabled:
            return True
        filters = self._filter_provider.get_filters()
        matched, error = apply_combined_filters(filters, [indexed_entry.entry.expanded])
        return error is not None or len(matched) > 0

    def _rebuild_view(self) -> None:
        if not self._filtering_enabled:
            self._view = list(range(len(self._store)))
        else:
            filters = self._filter_provider.get_filters()
            entries = [e.entry.expanded for e in self._store.all()]
            matched, _error = apply_combined_filters(filters, entries)
            self._view = matched

    def total_count(self) -> int:
        return len(self._store)

    @override
    def count(self) -> int:
        return len(self._view)

    def all(self) -> list[IndexedEntry]:
        return self._store.all()

    @override
    def is_empty(self) -> bool:
        return len(self._view) == 0

    @override
    def get(self, pos: int) -> IndexedEntry:
        return self._store.get(self._view[pos])

    @property
    def visible_entries(self) -> list[IndexedEntry]:
        return [self._store.get(i) for i in self._view]

    @property
    def visible_indices(self) -> list[int]:
        return list(self._view)

    @property
    def filtering_enabled(self) -> bool:
        return self._filtering_enabled

    async def set_filtering_enabled(self, value: bool) -> None:
        await self.on_will_rebuild.asend(None)
        self._filtering_enabled = value
        self._rebuild_view()
        await self.on_rebuild.asend(None)

    async def pause_filtering(self) -> None:
        await self.set_filtering_enabled(False)

    async def resume_filtering(self) -> None:
        await self.set_filtering_enabled(True)

    async def refilter(self, _: None) -> None:
        await self.on_will_rebuild.asend(None)
        self._rebuild_view()
        await self.on_rebuild.asend(None)
