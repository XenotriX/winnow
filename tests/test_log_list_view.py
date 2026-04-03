from jnav.parsing import ParsedEntry
from jnav.store import IndexedEntry

from jnav.log_list_view import LogListView


def _ie(store_idx: int) -> IndexedEntry:
    return IndexedEntry(
        store_idx, ParsedEntry(raw={}, expanded={}, expanded_paths=set())
    )


def _make_list_view_with_items(store_indices: list[int]) -> LogListView:
    lv = LogListView.__new__(LogListView)
    lv._items = [_ie(i) for i in store_indices]
    return lv


def test_exact_match():
    lv = _make_list_view_with_items([0, 2, 5, 8])
    assert lv._closest_list_index(5) == 2


def test_closest_rounds_down():
    lv = _make_list_view_with_items([0, 3, 7, 10])
    assert lv._closest_list_index(4) == 1


def test_closest_rounds_up():
    lv = _make_list_view_with_items([0, 3, 7, 10])
    assert lv._closest_list_index(6) == 2


def test_before_first():
    lv = _make_list_view_with_items([5, 10, 15])
    assert lv._closest_list_index(0) == 0


def test_after_last():
    lv = _make_list_view_with_items([5, 10, 15])
    assert lv._closest_list_index(100) == 2


def test_single_item():
    lv = _make_list_view_with_items([42])
    assert lv._closest_list_index(0) == 0
    assert lv._closest_list_index(42) == 0
    assert lv._closest_list_index(100) == 0


def test_equidistant_prefers_earlier():
    lv = _make_list_view_with_items([0, 4, 8])
    # store_idx=2 is equidistant from 0 and 4; first match (0) wins since < not <=
    assert lv._closest_list_index(2) == 0
