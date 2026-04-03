import aioreactive as rx
from aioreactive import AsyncSubject, pipe

from jnav.filter_provider import FilterProvider
from jnav.filtering import apply_combined_filters
from jnav.store import IndexedEntry, Store


class LogModel:
    on_append: AsyncSubject[list[IndexedEntry]]
    on_rebuild: AsyncSubject[None]
    _filtering_enabled: bool

    def __init__(
        self,
        store: Store,
        filter_provider: FilterProvider,
    ):
        self._store = store
        self._filter_provider = filter_provider
        self.on_append = AsyncSubject[list[IndexedEntry]]()
        self.on_rebuild = AsyncSubject[None]()
        self._filtering_enabled = True

    async def start(self) -> None:
        await self._filter_provider.on_change.subscribe_async(self.refilter)
        filtered_append = pipe(
            self._store.on_append,
            rx.map(self._filter_batch),
            rx.filter(lambda batch: len(batch) > 0),
        )
        await filtered_append.subscribe_async(self.on_append.asend)

    def _filter_batch(self, batch: list[IndexedEntry]) -> list[IndexedEntry]:
        return [i for i in batch if self._apply_filters(i)]

    def _apply_filters(self, indexed_entry: IndexedEntry) -> bool:
        if not self._filtering_enabled:
            return True
        filters = self._filter_provider.get_filters()
        matched, error = apply_combined_filters(filters, [indexed_entry.entry.expanded])
        return error is not None or len(matched) > 0

    def count(self) -> int:
        return len(self._store)

    def all(self) -> list[IndexedEntry]:
        return self._store.all()

    def is_empty(self) -> bool:
        return self.count() == 0

    def get(self, index: int) -> IndexedEntry:
        return self._store.get(index)

    @property
    def visible_entries(self) -> list[IndexedEntry]:
        if not self._filtering_enabled:
            return self.all()
        indices = self.visible_indices
        return [self._store.get(i) for i in indices]

    @property
    def visible_indices(self) -> list[int]:
        if not self._filtering_enabled:
            return list(range(self.count()))
        filters = self._filter_provider.get_filters()
        entries = [e.entry.expanded for e in self.all()]
        indices = apply_combined_filters(filters, entries)
        return indices[0]

    @property
    def filtering_enabled(self) -> bool:
        return self._filtering_enabled

    async def set_filtering_enabled(self, value: bool) -> None:
        self._filtering_enabled = value
        await self.on_rebuild.asend(None)

    async def pause_filtering(self) -> None:
        await self.set_filtering_enabled(False)

    async def resume_filtering(self) -> None:
        await self.set_filtering_enabled(True)

    async def refilter(self, _: None) -> None:
        await self.on_rebuild.asend(None)
