# pyright: reportPrivateUsage=false, reportAttributeAccessIssue=false, reportUninitializedInstanceVariable=false, reportUnknownMemberType=false

from collections.abc import Awaitable, Callable
from typing import cast, override
from unittest.mock import Mock

import pytest
import pytest_asyncio
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets.tree import TreeNode

from jnav.filter_provider import FilterProvider
from jnav.filter_tree import FilterTree, FilterTreeData
from jnav.filtering import Filter, FilterGroup
from jnav.text_input_screen import TextInputScreen


@pytest_asyncio.fixture
async def fp() -> FilterProvider:
    return FilterProvider()


class _StubFilterTree(FilterTree):
    _stub_cursor_node: TreeNode[FilterTreeData] | None = None
    _stub_app: Mock

    @property
    @override
    def cursor_node(self) -> TreeNode[FilterTreeData] | None:
        return self._stub_cursor_node

    @property
    @override
    def app(self) -> App[None]:  # pyright: ignore[reportIncompatibleUnannotatedOverride]
        return cast(App[None], self._stub_app)


def _make_tree_stub(
    fp: FilterProvider,
    *,
    cursor_data: FilterTreeData | None = None,
) -> _StubFilterTree:
    tree = _StubFilterTree.__new__(_StubFilterTree)
    tree._fp = fp
    tree._clipboard = None
    if cursor_data is None:
        tree._stub_cursor_node = None
    else:
        cursor_node = Mock()
        cursor_node.data = cursor_data
        tree._stub_cursor_node = cursor_node
    tree.rebuild = Mock()  # type: ignore[method-assign]
    tree.refresh_cursor_node = Mock()  # type: ignore[method-assign]
    tree.post_message = Mock()  # type: ignore[method-assign]
    mock_app = Mock()
    mock_app.push_screen = Mock()
    mock_app.notify = Mock()
    tree._stub_app = mock_app
    return tree


def _last_on_dismiss(
    tree: _StubFilterTree,
) -> Callable[[str | None], Awaitable[None]]:
    call = tree._stub_app.push_screen.call_args
    return cast(Callable[[str | None], Awaitable[None]], call.args[1])


def _last_screen(tree: _StubFilterTree) -> TextInputScreen:
    return cast(TextInputScreen, tree._stub_app.push_screen.call_args.args[0])


class TestCursorData:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_cursor(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        assert tree._cursor_data() is None

    @pytest.mark.asyncio
    async def test_returns_data_when_cursor_set(self, fp: FilterProvider) -> None:
        leaf = Filter(expr=".a")
        data = FilterTreeData(node=leaf, parent=fp.root)
        tree = _make_tree_stub(fp, cursor_data=data)
        assert tree._cursor_data() is data

    @pytest.mark.asyncio
    async def test_returns_none_when_cursor_has_no_data(
        self, fp: FilterProvider
    ) -> None:
        tree = _make_tree_stub(fp)
        node = Mock()
        node.data = None
        tree._stub_cursor_node = node
        assert tree._cursor_data() is None


class TestInsertAtCursor:
    @pytest.mark.asyncio
    async def test_no_cursor_returns_root_append(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        parent, idx = tree._insert_at_cursor()
        assert parent is fp.root
        assert idx is None

    @pytest.mark.asyncio
    async def test_cursor_on_group_returns_that_group(self, fp: FilterProvider) -> None:
        group = FilterGroup(operator="or")
        fp.root.children.append(group)
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=group, parent=fp.root),
        )
        parent, idx = tree._insert_at_cursor()
        assert parent is group
        assert idx is None

    @pytest.mark.asyncio
    async def test_cursor_on_leaf_returns_parent_and_index(
        self, fp: FilterProvider
    ) -> None:
        leaf_a = Filter(expr=".a")
        leaf_b = Filter(expr=".b")
        fp.root.children.extend([leaf_a, leaf_b])
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=leaf_b, parent=fp.root),
        )
        parent, idx = tree._insert_at_cursor()
        assert parent is fp.root
        assert idx == 1


class TestActionToggleItem:
    @pytest.mark.asyncio
    async def test_noop_when_no_cursor(self, fp: FilterProvider) -> None:
        await fp.add_filter(".a")
        tree = _make_tree_stub(fp)
        await tree.action_toggle_item()
        leaf = fp.root.children[0]
        assert leaf.enabled is True

    @pytest.mark.asyncio
    async def test_toggles_node_and_refreshes(self, fp: FilterProvider) -> None:
        await fp.add_filter(".a")
        leaf = fp.root.children[0]
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=leaf, parent=fp.root),
        )
        await tree.action_toggle_item()
        assert leaf.enabled is False
        cast(Mock, tree.refresh_cursor_node).assert_called_once()


class TestActionToggleNegated:
    @pytest.mark.asyncio
    async def test_noop_when_no_cursor(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        await tree.action_toggle_negated()

    @pytest.mark.asyncio
    async def test_toggles_negated_and_refreshes(self, fp: FilterProvider) -> None:
        await fp.add_filter(".a")
        leaf = fp.root.children[0]
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=leaf, parent=fp.root),
        )
        await tree.action_toggle_negated()
        assert leaf.negated is True
        cast(Mock, tree.refresh_cursor_node).assert_called_once()


class TestActionAddGroup:
    @pytest.mark.asyncio
    async def test_noop_when_no_cursor(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        await tree.action_add_group()
        assert fp.root.children == []

    @pytest.mark.asyncio
    async def test_adds_nested_group_when_cursor_on_group(
        self, fp: FilterProvider
    ) -> None:
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=fp.root, parent=fp.root),
        )
        await tree.action_add_group()
        assert len(fp.root.children) == 1
        new_group = fp.root.children[0]
        assert isinstance(new_group, FilterGroup)
        assert new_group.operator == "or"
        cast(Mock, tree.rebuild).assert_called_once()

    @pytest.mark.asyncio
    async def test_inserts_after_cursor_when_cursor_on_leaf(
        self, fp: FilterProvider
    ) -> None:
        await fp.add_filter(".a")
        await fp.add_filter(".b")
        leaf_a = fp.root.children[0]
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=leaf_a, parent=fp.root),
        )
        await tree.action_add_group()
        assert len(fp.root.children) == 3
        assert isinstance(fp.root.children[1], FilterGroup)
        cast(Mock, tree.rebuild).assert_called_once()


class TestActionToggleCombine:
    @pytest.mark.asyncio
    async def test_noop_when_no_cursor(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        await tree.action_toggle_combine()
        cast(Mock, tree.rebuild).assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_when_cursor_on_leaf(self, fp: FilterProvider) -> None:
        await fp.add_filter(".a")
        leaf = fp.root.children[0]
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=leaf, parent=fp.root),
        )
        await tree.action_toggle_combine()
        cast(Mock, tree.rebuild).assert_not_called()

    @pytest.mark.asyncio
    async def test_flips_group_operator(self, fp: FilterProvider) -> None:
        group = FilterGroup(operator="and")
        fp.root.children.append(group)
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=group, parent=fp.root),
        )
        await tree.action_toggle_combine()
        assert group.operator == "or"
        cast(Mock, tree.rebuild).assert_called_once()


class TestActionYank:
    @pytest.mark.asyncio
    async def test_noop_when_no_cursor(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        tree.action_yank()
        assert tree._clipboard is None

    @pytest.mark.asyncio
    async def test_noop_when_cursor_on_root(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=fp.root, parent=fp.root),
        )
        tree.action_yank()
        assert tree._clipboard is None

    @pytest.mark.asyncio
    async def test_yank_deep_copies_leaf(self, fp: FilterProvider) -> None:
        await fp.add_filter(".a", label="alpha")
        leaf = fp.root.children[0]
        assert isinstance(leaf, Filter)
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=leaf, parent=fp.root),
        )
        tree.action_yank()
        assert tree._clipboard is not leaf
        assert isinstance(tree._clipboard, Filter)
        assert tree._clipboard.expr == ".a"
        assert tree._clipboard.label == "alpha"

    @pytest.mark.asyncio
    async def test_yank_group_deep_copies_children(self, fp: FilterProvider) -> None:
        inner = Filter(expr=".inner")
        group = FilterGroup(operator="or", children=[inner])
        fp.root.children.append(group)
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=group, parent=fp.root),
        )
        tree.action_yank()
        assert isinstance(tree._clipboard, FilterGroup)
        assert tree._clipboard is not group
        assert tree._clipboard.children[0] is not inner


class TestActionFlatten:
    @pytest.mark.asyncio
    async def test_noop_when_no_cursor(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        await tree.action_flatten()
        cast(Mock, tree.rebuild).assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_when_cursor_on_leaf(self, fp: FilterProvider) -> None:
        await fp.add_filter(".a")
        leaf = fp.root.children[0]
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=leaf, parent=fp.root),
        )
        await tree.action_flatten()
        cast(Mock, tree.rebuild).assert_not_called()
        assert fp.root.children == [leaf]

    @pytest.mark.asyncio
    async def test_noop_when_cursor_on_root(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=fp.root, parent=fp.root),
        )
        await tree.action_flatten()
        cast(Mock, tree.rebuild).assert_not_called()

    @pytest.mark.asyncio
    async def test_flattens_group_into_single_leaf(self, fp: FilterProvider) -> None:
        group = FilterGroup(
            operator="or",
            children=[Filter(expr=".a"), Filter(expr=".b")],
        )
        fp.root.children.append(group)
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=group, parent=fp.root),
        )
        await tree.action_flatten()
        assert len(fp.root.children) == 1
        new_leaf = fp.root.children[0]
        assert isinstance(new_leaf, Filter)
        assert new_leaf.expr == ".a or .b"
        cast(Mock, tree.rebuild).assert_called_once()


class TestActionDelete:
    @pytest.mark.asyncio
    async def test_noop_when_no_cursor(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        await tree.action_delete()
        cast(Mock, tree.rebuild).assert_not_called()
        assert tree._clipboard is None

    @pytest.mark.asyncio
    async def test_noop_when_cursor_on_root(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=fp.root, parent=fp.root),
        )
        await tree.action_delete()
        cast(Mock, tree.rebuild).assert_not_called()
        assert tree._clipboard is None

    @pytest.mark.asyncio
    async def test_removes_node_and_copies_to_clipboard(
        self, fp: FilterProvider
    ) -> None:
        await fp.add_filter(".a")
        await fp.add_filter(".b")
        leaf_a = fp.root.children[0]
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=leaf_a, parent=fp.root),
        )
        await tree.action_delete()
        assert tree._clipboard is leaf_a
        assert leaf_a not in fp.root.children
        assert len(fp.root.children) == 1
        cast(Mock, tree.rebuild).assert_called_once()


class TestActionPaste:
    @pytest.mark.asyncio
    async def test_noop_when_clipboard_empty(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        await tree.action_paste()
        cast(Mock, tree.rebuild).assert_not_called()
        assert fp.root.children == []

    @pytest.mark.asyncio
    async def test_paste_at_no_cursor_is_noop(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        leaf = Filter(expr=".pasted")
        tree._clipboard = leaf
        await tree.action_paste()
        assert fp.root.children == []
        assert tree._clipboard is leaf
        cast(Mock, tree.rebuild).assert_not_called()

    @pytest.mark.asyncio
    async def test_paste_at_leaf_inserts_after(self, fp: FilterProvider) -> None:
        await fp.add_filter(".a")
        await fp.add_filter(".b")
        leaf_a = fp.root.children[0]
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=leaf_a, parent=fp.root),
        )
        new_leaf = Filter(expr=".pasted")
        tree._clipboard = new_leaf
        await tree.action_paste()
        assert fp.root.children[1] == new_leaf
        assert fp.root.children[1] is not new_leaf
        assert tree._clipboard is new_leaf

    @pytest.mark.asyncio
    async def test_paste_at_expanded_group_inserts_as_first_child(
        self, fp: FilterProvider
    ) -> None:
        existing = Filter(expr=".existing")
        group = FilterGroup(operator="or", collapsed=False, children=[existing])
        fp.root.children.append(group)
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=group, parent=fp.root),
        )
        new_leaf = Filter(expr=".pasted")
        tree._clipboard = new_leaf
        await tree.action_paste()
        assert group.children == [new_leaf, existing]
        assert tree._clipboard is new_leaf

    @pytest.mark.asyncio
    async def test_paste_at_collapsed_group_inserts_after_as_sibling(
        self, fp: FilterProvider
    ) -> None:
        group = FilterGroup(operator="or", collapsed=True)
        trailing = Filter(expr=".trailing")
        fp.root.children.extend([group, trailing])
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=group, parent=fp.root),
        )
        new_leaf = Filter(expr=".pasted")
        tree._clipboard = new_leaf
        await tree.action_paste()
        assert fp.root.children == [group, new_leaf, trailing]
        assert group.children == []
        assert tree._clipboard is new_leaf

    @pytest.mark.asyncio
    async def test_paste_at_root_inserts_as_first_child(
        self, fp: FilterProvider
    ) -> None:
        existing = Filter(expr=".existing")
        fp.root.children.append(existing)
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=fp.root, parent=fp.root),
        )
        new_leaf = Filter(expr=".pasted")
        tree._clipboard = new_leaf
        await tree.action_paste()
        assert fp.root.children == [new_leaf, existing]
        assert tree._clipboard is new_leaf


class TestActionPasteAbove:
    @pytest.mark.asyncio
    async def test_noop_when_clipboard_empty(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        await tree.action_paste_above()
        cast(Mock, tree.rebuild).assert_not_called()
        assert fp.root.children == []

    @pytest.mark.asyncio
    async def test_paste_above_at_no_cursor_is_noop(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        leaf = Filter(expr=".pasted")
        tree._clipboard = leaf
        await tree.action_paste_above()
        assert fp.root.children == []
        assert tree._clipboard is leaf
        cast(Mock, tree.rebuild).assert_not_called()

    @pytest.mark.asyncio
    async def test_paste_above_at_leaf_inserts_before(self, fp: FilterProvider) -> None:
        await fp.add_filter(".a")
        await fp.add_filter(".b")
        leaf_b = fp.root.children[1]
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=leaf_b, parent=fp.root),
        )
        new_leaf = Filter(expr=".pasted")
        tree._clipboard = new_leaf
        await tree.action_paste_above()
        assert fp.root.children[1] == new_leaf
        assert fp.root.children[1] is not new_leaf
        assert fp.root.children[2] is leaf_b
        assert tree._clipboard is new_leaf

    @pytest.mark.asyncio
    async def test_paste_above_at_expanded_group_inserts_before_as_sibling(
        self, fp: FilterProvider
    ) -> None:
        leading = Filter(expr=".leading")
        existing = Filter(expr=".existing")
        group = FilterGroup(operator="or", collapsed=False, children=[existing])
        fp.root.children.extend([leading, group])
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=group, parent=fp.root),
        )
        new_leaf = Filter(expr=".pasted")
        tree._clipboard = new_leaf
        await tree.action_paste_above()
        assert fp.root.children == [leading, new_leaf, group]
        assert group.children == [existing]
        assert tree._clipboard is new_leaf

    @pytest.mark.asyncio
    async def test_paste_above_at_collapsed_group_inserts_before_as_sibling(
        self, fp: FilterProvider
    ) -> None:
        leading = Filter(expr=".leading")
        group = FilterGroup(operator="or", collapsed=True)
        fp.root.children.extend([leading, group])
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=group, parent=fp.root),
        )
        new_leaf = Filter(expr=".pasted")
        tree._clipboard = new_leaf
        await tree.action_paste_above()
        assert fp.root.children == [leading, new_leaf, group]
        assert tree._clipboard is new_leaf

    @pytest.mark.asyncio
    async def test_paste_above_at_root_is_noop(self, fp: FilterProvider) -> None:
        existing = Filter(expr=".existing")
        fp.root.children.append(existing)
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=fp.root, parent=fp.root),
        )
        new_leaf = Filter(expr=".pasted")
        tree._clipboard = new_leaf
        await tree.action_paste_above()
        assert fp.root.children == [existing]
        assert tree._clipboard is new_leaf
        cast(Mock, tree.rebuild).assert_not_called()


class TestActionAddFilter:
    @pytest.mark.asyncio
    async def test_pushes_text_input_screen(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        tree.action_add_filter()
        tree._stub_app.push_screen.assert_called_once()
        screen = _last_screen(tree)
        assert isinstance(screen, TextInputScreen)

    @pytest.mark.asyncio
    async def test_dismiss_with_empty_does_nothing(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        tree.action_add_filter()
        await _last_on_dismiss(tree)(None)
        assert fp.root.children == []
        cast(Mock, tree.rebuild).assert_not_called()

    @pytest.mark.asyncio
    async def test_dismiss_with_empty_string_does_nothing(
        self, fp: FilterProvider
    ) -> None:
        tree = _make_tree_stub(fp)
        tree.action_add_filter()
        await _last_on_dismiss(tree)("")
        assert fp.root.children == []

    @pytest.mark.asyncio
    async def test_dismiss_with_expr_appends_leaf_at_root(
        self, fp: FilterProvider
    ) -> None:
        tree = _make_tree_stub(fp)
        tree.action_add_filter()
        await _last_on_dismiss(tree)('.level == "ERROR"')
        assert len(fp.root.children) == 1
        leaf = fp.root.children[0]
        assert isinstance(leaf, Filter)
        assert leaf.expr == '.level == "ERROR"'
        cast(Mock, tree.rebuild).assert_called_once()

    @pytest.mark.asyncio
    async def test_dismiss_with_expr_inserts_after_cursor_leaf(
        self, fp: FilterProvider
    ) -> None:
        await fp.add_filter(".a")
        leaf_a = fp.root.children[0]
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=leaf_a, parent=fp.root),
        )
        tree.action_add_filter()
        await _last_on_dismiss(tree)(".b")
        assert len(fp.root.children) == 2
        inserted = fp.root.children[1]
        assert isinstance(inserted, Filter)
        assert inserted.expr == ".b"

    @pytest.mark.asyncio
    async def test_warning_notification_shown_for_assignment(
        self, fp: FilterProvider
    ) -> None:
        tree = _make_tree_stub(fp)
        tree.action_add_filter()
        await _last_on_dismiss(tree)('.level = "ERROR"')
        tree._stub_app.notify.assert_called_once()
        _, kwargs = tree._stub_app.notify.call_args
        assert kwargs.get("severity") == "warning"


class TestActionEditFilter:
    @pytest.mark.asyncio
    async def test_noop_when_no_cursor(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        tree.action_edit_filter()
        tree._stub_app.push_screen.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_when_cursor_on_group(self, fp: FilterProvider) -> None:
        group = FilterGroup()
        fp.root.children.append(group)
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=group, parent=fp.root),
        )
        tree.action_edit_filter()
        tree._stub_app.push_screen.assert_not_called()

    @pytest.mark.asyncio
    async def test_pushes_screen_with_initial_value(self, fp: FilterProvider) -> None:
        await fp.add_filter(".orig")
        leaf = fp.root.children[0]
        assert isinstance(leaf, Filter)
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=leaf, parent=fp.root),
        )
        tree.action_edit_filter()
        screen = _last_screen(tree)
        assert isinstance(screen, TextInputScreen)
        assert screen._initial_value == ".orig"

    @pytest.mark.asyncio
    async def test_dismiss_with_empty_does_nothing(self, fp: FilterProvider) -> None:
        await fp.add_filter(".a")
        leaf = fp.root.children[0]
        assert isinstance(leaf, Filter)
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=leaf, parent=fp.root),
        )
        tree.action_edit_filter()
        await _last_on_dismiss(tree)(None)
        assert leaf.expr == ".a"
        cast(Mock, tree.rebuild).assert_not_called()

    @pytest.mark.asyncio
    async def test_dismiss_updates_expr_and_rebuilds(self, fp: FilterProvider) -> None:
        await fp.add_filter(".old")
        leaf = fp.root.children[0]
        assert isinstance(leaf, Filter)
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=leaf, parent=fp.root),
        )
        tree.action_edit_filter()
        await _last_on_dismiss(tree)(".new")
        assert leaf.expr == ".new"
        cast(Mock, tree.rebuild).assert_called_once()

    @pytest.mark.asyncio
    async def test_warning_notification_shown_for_assignment(
        self, fp: FilterProvider
    ) -> None:
        await fp.add_filter(".a")
        leaf = fp.root.children[0]
        assert isinstance(leaf, Filter)
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=leaf, parent=fp.root),
        )
        tree.action_edit_filter()
        await _last_on_dismiss(tree)(".x = 1")
        tree._stub_app.notify.assert_called_once()


class TestActionRename:
    @pytest.mark.asyncio
    async def test_noop_when_no_cursor(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        tree.action_rename()
        tree._stub_app.push_screen.assert_not_called()

    @pytest.mark.asyncio
    async def test_pushes_screen_with_existing_label(self, fp: FilterProvider) -> None:
        leaf = Filter(expr=".a", label="alpha")
        fp.root.children.append(leaf)
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=leaf, parent=fp.root),
        )
        tree.action_rename()
        screen = _last_screen(tree)
        assert isinstance(screen, TextInputScreen)
        assert screen._initial_value == "alpha"

    @pytest.mark.asyncio
    async def test_pushes_screen_with_empty_label_when_none(
        self, fp: FilterProvider
    ) -> None:
        leaf = Filter(expr=".a")
        fp.root.children.append(leaf)
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=leaf, parent=fp.root),
        )
        tree.action_rename()
        screen = _last_screen(tree)
        assert screen._initial_value == ""

    @pytest.mark.asyncio
    async def test_dismiss_sets_label(self, fp: FilterProvider) -> None:
        leaf = Filter(expr=".a")
        fp.root.children.append(leaf)
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=leaf, parent=fp.root),
        )
        tree.action_rename()
        await _last_on_dismiss(tree)("new-label")
        assert leaf.label == "new-label"
        cast(Mock, tree.rebuild).assert_called_once()

    @pytest.mark.asyncio
    async def test_dismiss_with_none_clears_label(self, fp: FilterProvider) -> None:
        leaf = Filter(expr=".a", label="existing")
        fp.root.children.append(leaf)
        tree = _make_tree_stub(
            fp,
            cursor_data=FilterTreeData(node=leaf, parent=fp.root),
        )
        tree.action_rename()
        await _last_on_dismiss(tree)(None)
        assert leaf.label is None
        cast(Mock, tree.rebuild).assert_called_once()


class TestRenderLabel:
    @pytest.mark.asyncio
    async def test_leaf_uses_expr_when_no_label(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        leaf = Filter(expr=".level")
        text = tree._render_label(leaf)
        assert ".level" in text.plain

    @pytest.mark.asyncio
    async def test_leaf_uses_label_when_present(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        leaf = Filter(expr=".level", label="my-label")
        text = tree._render_label(leaf)
        assert "my-label" in text.plain
        assert ".level" not in text.plain

    @pytest.mark.asyncio
    async def test_disabled_leaf_gets_strike_style(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        leaf = Filter(expr=".a", enabled=False)
        text = tree._render_label(leaf)
        assert any("strike" in str(s) for s in text.spans) or "strike" in str(
            text.style
        )

    @pytest.mark.asyncio
    async def test_group_renders_operator_upper(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        group = FilterGroup(operator="or")
        text = tree._render_label(group)
        assert "OR" in text.plain

    @pytest.mark.asyncio
    async def test_negated_group_shows_nand(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        group = FilterGroup(operator="and", negated=True)
        text = tree._render_label(group)
        assert text.plain == "NAND"

    @pytest.mark.asyncio
    async def test_group_with_label_includes_label(self, fp: FilterProvider) -> None:
        tree = _make_tree_stub(fp)
        group = FilterGroup(operator="and", label="my-group")
        text = tree._render_label(group)
        assert "my-group" in text.plain
        assert "AND" in text.plain


class TestTreeBuilding:
    @pytest.mark.asyncio
    async def test_rebuild_creates_nodes_for_root_children(
        self, fp: FilterProvider
    ) -> None:
        await fp.add_filter(".a")
        await fp.add_filter(".b")

        class _TestApp(App[None]):
            @override
            def compose(self) -> ComposeResult:
                yield FilterTree(filter_provider=fp)

        app = _TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(FilterTree)
            children = list(tree.root.children)
            assert len(children) == 2
            exprs = [
                c.data.node.expr
                for c in children
                if c.data is not None and isinstance(c.data.node, Filter)
            ]
            assert exprs == [".a", ".b"]

    @pytest.mark.asyncio
    async def test_rebuild_creates_nested_group_nodes(self, fp: FilterProvider) -> None:
        inner_leaf = Filter(expr=".inner")
        group = FilterGroup(operator="or", children=[inner_leaf])
        fp.root.children.append(group)

        class _TestApp(App[None]):
            @override
            def compose(self) -> ComposeResult:
                yield FilterTree(filter_provider=fp)

        app = _TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(FilterTree)
            [group_node] = list(tree.root.children)
            assert group_node.data is not None
            assert group_node.data.node is group
            [inner_node] = list(group_node.children)
            assert inner_node.data is not None
            assert inner_node.data.node is inner_leaf

    @pytest.mark.asyncio
    async def test_rebuild_respects_collapsed_flag(self, fp: FilterProvider) -> None:
        group = FilterGroup(
            operator="or",
            collapsed=True,
            children=[Filter(expr=".x")],
        )
        fp.root.children.append(group)

        class _TestApp(App[None]):
            @override
            def compose(self) -> ComposeResult:
                yield FilterTree(filter_provider=fp)

        app = _TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(FilterTree)
            [group_node] = list(tree.root.children)
            assert group_node.is_expanded is False

    @pytest.mark.asyncio
    async def test_rebuild_posts_changed_message(self, fp: FilterProvider) -> None:
        changed: list[FilterTree.Changed] = []

        class _TestApp(App[None]):
            @override
            def compose(self) -> ComposeResult:
                yield FilterTree(filter_provider=fp)

            def on_filter_tree_changed(self, event: FilterTree.Changed) -> None:
                changed.append(event)

        app = _TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert len(changed) >= 1


class TestNodeLabel:
    @pytest.mark.asyncio
    async def test_collapsed_group_with_label_shows_label(
        self, fp: FilterProvider
    ) -> None:
        group = FilterGroup(
            operator="or",
            label="my-group",
            collapsed=True,
            children=[Filter(expr=".x")],
        )
        fp.root.children.append(group)

        class _TestApp(App[None]):
            @override
            def compose(self) -> ComposeResult:
                yield FilterTree(filter_provider=fp)

        app = _TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(FilterTree)
            [group_node] = list(tree.root.children)
            label = tree._node_label(group_node)
            assert "my-group" in label.plain

    @pytest.mark.asyncio
    async def test_collapsed_unlabelled_group_shows_expression_preview(
        self, fp: FilterProvider
    ) -> None:
        group = FilterGroup(
            operator="or",
            collapsed=True,
            children=[Filter(expr=".a"), Filter(expr=".b")],
        )
        fp.root.children.append(group)

        class _TestApp(App[None]):
            @override
            def compose(self) -> ComposeResult:
                yield FilterTree(filter_provider=fp)

        app = _TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(FilterTree)
            [group_node] = list(tree.root.children)
            label = tree._node_label(group_node)
            assert ".a" in label.plain
            assert ".b" in label.plain

    @pytest.mark.asyncio
    async def test_expanded_group_falls_back_to_render_label(
        self, fp: FilterProvider
    ) -> None:
        group = FilterGroup(operator="or", children=[Filter(expr=".a")])
        fp.root.children.append(group)

        class _TestApp(App[None]):
            @override
            def compose(self) -> ComposeResult:
                yield FilterTree(filter_provider=fp)

        app = _TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(FilterTree)
            [group_node] = list(tree.root.children)
            assert group_node.is_expanded
            label = tree._node_label(group_node)
            assert "OR" in label.plain


class TestCollapsedExpandedEvents:
    @pytest.mark.asyncio
    async def test_collapse_event_updates_group_state(self, fp: FilterProvider) -> None:
        group = FilterGroup(operator="or", children=[Filter(expr=".x")])
        fp.root.children.append(group)

        class _TestApp(App[None]):
            @override
            def compose(self) -> ComposeResult:
                yield FilterTree(filter_provider=fp)

        app = _TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(FilterTree)
            [group_node] = list(tree.root.children)
            group_node.collapse()
            await pilot.pause()
            assert group.collapsed is True

    @pytest.mark.asyncio
    async def test_expand_event_updates_group_state(self, fp: FilterProvider) -> None:
        group = FilterGroup(
            operator="or",
            collapsed=True,
            children=[Filter(expr=".x")],
        )
        fp.root.children.append(group)

        class _TestApp(App[None]):
            @override
            def compose(self) -> ComposeResult:
                yield FilterTree(filter_provider=fp)

        app = _TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(FilterTree)
            [group_node] = list(tree.root.children)
            assert group.collapsed is True
            group_node.expand()
            await pilot.pause()
            assert group.collapsed is False


class TestRefreshCursorNode:
    @pytest.mark.asyncio
    async def test_updates_label_for_current_cursor(self, fp: FilterProvider) -> None:
        await fp.add_filter(".a")
        leaf = fp.root.children[0]
        assert isinstance(leaf, Filter)

        class _TestApp(App[None]):
            @override
            def compose(self) -> ComposeResult:
                yield FilterTree(filter_provider=fp)

        app = _TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(FilterTree)
            [leaf_node] = list(tree.root.children)
            tree.cursor_line = 1
            leaf.label = "renamed"
            tree.refresh_cursor_node()
            assert isinstance(leaf_node.label, Text)
            assert "renamed" in leaf_node.label.plain


class TestPilotKeyBindings:
    @pytest.mark.asyncio
    async def test_t_key_toggles_enabled_on_cursor(self, fp: FilterProvider) -> None:
        await fp.add_filter(".a")

        class _TestApp(App[None]):
            @override
            def compose(self) -> ComposeResult:
                yield FilterTree(filter_provider=fp)

        app = _TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(FilterTree)
            tree.focus()
            tree.cursor_line = 1
            await pilot.pause()
            await pilot.press("t")
            await pilot.pause()
            leaf = fp.root.children[0]
            assert leaf.enabled is False

    @pytest.mark.asyncio
    async def test_y_key_yanks_cursor_node(self, fp: FilterProvider) -> None:
        await fp.add_filter(".a")

        class _TestApp(App[None]):
            @override
            def compose(self) -> ComposeResult:
                yield FilterTree(filter_provider=fp)

        app = _TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(FilterTree)
            tree.focus()
            tree.cursor_line = 1
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            assert isinstance(tree._clipboard, Filter)
            assert tree._clipboard.expr == ".a"

    @pytest.mark.asyncio
    async def test_g_key_adds_group(self, fp: FilterProvider) -> None:
        class _TestApp(App[None]):
            @override
            def compose(self) -> ComposeResult:
                yield FilterTree(filter_provider=fp)

        app = _TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(FilterTree)
            tree.focus()
            await pilot.press("g")
            await pilot.pause()
            assert len(fp.root.children) == 1
            assert isinstance(fp.root.children[0], FilterGroup)

    @pytest.mark.asyncio
    async def test_d_key_deletes_cursor_node(self, fp: FilterProvider) -> None:
        await fp.add_filter(".a")

        class _TestApp(App[None]):
            @override
            def compose(self) -> ComposeResult:
                yield FilterTree(filter_provider=fp)

        app = _TestApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tree = app.query_one(FilterTree)
            tree.focus()
            tree.cursor_line = 1
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()
            assert fp.root.children == []
            assert tree._clipboard is not None
