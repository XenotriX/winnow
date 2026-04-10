from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from jnav.filter_provider import FilterProvider
from jnav.filtering import (
    Filter,
    FilterGroup,
    FilterNode,
    build_expression,
    check_filter_warning,
)
from jnav.text_input_screen import TextInputScreen

if TYPE_CHECKING:
    from textual import getters
    from textual.app import App


@dataclass
class FilterTreeData:
    node: FilterNode
    parent: FilterGroup


class FilterTree(Tree[FilterTreeData]):
    if TYPE_CHECKING:
        app = getters.app(App[None])

    class Changed(Message):
        pass

    DEFAULT_CSS = """
    FilterTree {
        height: auto;
        max-height: 14;
        border: none;
        background: transparent;
    }
    """

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("a", "add_filter", "Add", show=False),
        Binding("e", "edit_filter", "Edit", show=False),
        Binding("d", "delete", "Delete", show=False),
        Binding("t", "toggle_item", "Toggle", show=False),
        Binding("o", "toggle_combine", "AND/OR", show=False),
        Binding("n", "toggle_negated", "Negate", show=False),
        Binding("g", "add_group", "Add group", show=False),
        Binding("p", "paste", "Paste", show=False),
        Binding("c", "flatten", "Flatten", show=False),
        Binding("y", "yank", "Yank", show=False),
        Binding("r", "rename", "Rename", show=False),
    ]

    def __init__(
        self,
        filter_provider: FilterProvider,
        *,
        id: str | None = None,
    ) -> None:
        super().__init__("Filters", id=id)
        self._fp = filter_provider
        self._clipboard: FilterNode | None = None

    @override
    def on_mount(self) -> None:
        self.rebuild()

    def on_tree_node_collapsed(self, event: Tree.NodeCollapsed[FilterTreeData]) -> None:
        data = event.node.data
        if data is None:
            return
        node = data.node
        if isinstance(node, FilterGroup):
            node.collapsed = True
            event.node.set_label(self._node_label(event.node))

    def on_tree_node_expanded(self, event: Tree.NodeExpanded[FilterTreeData]) -> None:
        data = event.node.data
        if data is None:
            return
        node = data.node
        if isinstance(node, FilterGroup):
            node.collapsed = False
            event.node.set_label(self._render_label(node))

    def rebuild(self) -> None:
        saved_line = self.cursor_line

        self.clear()
        self.root.set_label(self._render_label(self._fp.root))
        self.root.data = FilterTreeData(node=self._fp.root, parent=self._fp.root)
        self._populate(self.root, self._fp.root)
        self.root.expand()

        if self.cursor_line != saved_line:
            self.cursor_line = min(saved_line, self.last_line)
        self.post_message(self.Changed())

    def refresh_cursor_node(self) -> None:
        tree_node = self.cursor_node
        if tree_node is not None and tree_node.data is not None:
            tree_node.set_label(self._node_label(tree_node))
        self.post_message(self.Changed())

    def _node_label(self, tree_node: TreeNode[FilterTreeData]) -> Text:
        data = tree_node.data
        assert data is not None
        node = data.node
        if isinstance(node, FilterGroup) and not tree_node.is_expanded:
            style = "" if node.enabled else "dim strike"
            if node.label:
                return Text(node.label, style=style)
            preview = build_expression(
                FilterGroup(operator=node.operator, children=node.children)
            )
            if preview:
                return Text(preview, style=style)
        return self._render_label(node)

    def _populate(
        self,
        tree_parent: TreeNode[FilterTreeData],
        group: FilterGroup,
    ) -> None:
        for child in group.children:
            data = FilterTreeData(node=child, parent=group)
            label = self._render_label(child)
            if isinstance(child, FilterGroup):
                branch = tree_parent.add(label, data=data)
                self._populate(branch, child)
                if child.collapsed:
                    branch.collapse()
                    branch.set_label(self._node_label(branch))
                else:
                    branch.expand()
            else:
                tree_parent.add_leaf(label, data=data)

    def _render_label(self, node: FilterNode) -> Text:
        style = "" if node.enabled else "dim strike"
        if isinstance(node, FilterGroup):
            op = node.operator.upper()
            if node.negated:
                op = f"! {op}"
            if node.label:
                return Text.assemble((f"{op} ", style), (node.label, "dim"))
            return Text(op, style=style)

        display = node.label or node.expr
        icon = "\uf05e" if node.negated else "󱓜"
        return Text(f"{icon} {display}", style=style)

    def _cursor_data(self) -> FilterTreeData | None:
        node = self.cursor_node
        if node is None or node.data is None:
            return None
        return node.data

    def _insert_at_cursor(self) -> tuple[FilterGroup, int | None]:
        data = self._cursor_data()
        if data is not None:
            cursor_node = data.node
            parent = data.parent
            if isinstance(cursor_node, FilterGroup):
                return (cursor_node, None)
            return (parent, parent.children.index(cursor_node))
        return (self._fp.root, None)

    async def action_toggle_item(self) -> None:
        data = self._cursor_data()
        if data is None:
            return
        await self._fp.toggle_node(data.node)
        self.refresh_cursor_node()

    async def action_toggle_negated(self) -> None:
        data = self._cursor_data()
        if data is None:
            return
        await self._fp.toggle_negated(data.node)
        self.refresh_cursor_node()

    async def action_add_group(self) -> None:
        data = self._cursor_data()
        if data is None:
            return
        node = data.node
        parent = data.parent
        if isinstance(node, FilterGroup):
            await self._fp.add_group(node)
        else:
            idx = parent.children.index(node)
            await self._fp.add_group(parent, idx)
        self.rebuild()

    async def action_toggle_combine(self) -> None:
        data = self._cursor_data()
        if data is None:
            return
        if not isinstance(data.node, FilterGroup):
            return
        await self._fp.set_node_operator(data.node, data.parent)
        self.rebuild()

    def action_yank(self) -> None:
        data = self._cursor_data()
        if data is None:
            return
        node = data.node
        if node is self._fp.root:
            return
        self._clipboard = node.model_copy(deep=True)

    async def action_flatten(self) -> None:
        data = self._cursor_data()
        if data is None:
            return
        node = data.node
        if not isinstance(node, FilterGroup) or node is self._fp.root:
            return
        await self._fp.flatten_group(node, data.parent)
        self.rebuild()

    async def action_delete(self) -> None:
        data = self._cursor_data()
        if data is None:
            return
        node = data.node
        if node is self._fp.root:
            return
        self._clipboard = node
        await self._fp.remove_node(node, data.parent)
        self.rebuild()

    async def action_paste(self) -> None:
        if self._clipboard is None:
            return
        parent, idx = self._insert_at_cursor()
        if idx is not None:
            parent.children.insert(idx + 1, self._clipboard)
        else:
            parent.children.append(self._clipboard)
        self._clipboard = None
        await self._fp.on_change.asend(None)
        self.rebuild()

    def action_add_filter(self) -> None:
        target = self._insert_at_cursor()

        async def on_dismiss(expr: str | None) -> None:
            if not expr:
                return
            warning = check_filter_warning(expr)
            parent, idx = target
            leaf = Filter(expr=expr)
            if idx is not None:
                parent.children.insert(idx + 1, leaf)
            else:
                parent.children.append(leaf)
            await self._fp.on_change.asend(None)
            self.rebuild()
            if warning:
                self.app.notify(warning, severity="warning", timeout=3)

        self.app.push_screen(
            TextInputScreen("Add filter", placeholder="jq expression..."),
            on_dismiss,
        )

    def action_edit_filter(self) -> None:
        data = self._cursor_data()
        if data is None:
            return
        node = data.node
        if not isinstance(node, Filter):
            return

        async def on_dismiss(expr: str | None) -> None:
            if not expr:
                return
            warning = check_filter_warning(expr)
            await self._fp.edit_leaf(node, expr)
            self.rebuild()
            if warning:
                self.app.notify(warning, severity="warning", timeout=3)

        self.app.push_screen(
            TextInputScreen(
                "Edit filter",
                placeholder="jq expression...",
                initial_value=node.expr,
            ),
            on_dismiss,
        )

    def action_rename(self) -> None:
        data = self._cursor_data()
        if data is None:
            return
        node = data.node

        async def on_dismiss(label: str | None) -> None:
            node.label = label
            await self._fp.on_change.asend(None)
            self.rebuild()

        self.app.push_screen(
            TextInputScreen(
                "Rename",
                placeholder="label...",
                initial_value=node.label or "",
            ),
            on_dismiss,
        )
