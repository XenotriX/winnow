from typing import Any, Literal

from aioreactive import AsyncSubject

from jnav.filtering import (
    FilterGroup,
    Filter,
    FilterNode,
    build_expression,
)


class FilterProvider:
    on_change: AsyncSubject[None]

    def __init__(self) -> None:
        self._root = FilterGroup()
        self.on_change = AsyncSubject[None]()

    @property
    def root(self) -> FilterGroup:
        return self._root

    async def add_filter(
        self,
        expr: str,
        label: str | None = None,
        combine: Literal["and", "or"] = "and",
    ) -> None:
        """Add a new filter leaf to the root group."""
        existing = {
            leaf.expr
            for leaf in self._root.children
            if isinstance(leaf, Filter)
        }
        if expr not in existing:
            leaf = Filter(expr=expr, label=label)
            if combine == "or":
                self._root.children.append(
                    FilterGroup(operator="or", children=[leaf])
                )
            else:
                self._root.children.append(leaf)
            await self.on_change.asend(None)

    async def toggle_node(self, node: FilterNode) -> None:
        node.enabled = not node.enabled
        await self.on_change.asend(None)

    async def toggle_negated(self, node: FilterNode) -> None:
        node.negated = not node.negated
        await self.on_change.asend(None)

    async def add_group(
        self,
        parent: FilterGroup,
        index: int | None = None,
    ) -> None:
        op = "or" if parent.operator == "and" else "and"
        group = FilterGroup(operator=op)
        if index is not None:
            parent.children.insert(index + 1, group)
        else:
            parent.children.append(group)
        await self.on_change.asend(None)

    async def remove_node(self, node: FilterNode, parent: FilterGroup) -> None:
        parent.children.remove(node)
        await self.on_change.asend(None)

    async def set_node_operator(
        self,
        node: FilterNode,
        parent: FilterGroup,
    ) -> None:
        if isinstance(node, FilterGroup):
            node.operator = "or" if node.operator == "and" else "and"
        else:
            idx = parent.children.index(node)
            parent.children[idx] = FilterGroup(operator="or", children=[node])
        await self.on_change.asend(None)

    async def flatten_group(self, group: FilterGroup, parent: FilterGroup) -> None:
        """Replace a group with a single leaf containing its compiled expression."""
        expr = build_expression(
            FilterGroup(operator=group.operator, children=group.children)
        )
        if expr is None:
            return
        idx = parent.children.index(group)
        parent.children[idx] = Filter(expr=expr)
        await self.on_change.asend(None)

    async def edit_leaf(self, leaf: Filter, expr: str) -> None:
        leaf.expr = expr
        await self.on_change.asend(None)

    async def clear_filters(self) -> None:
        self._root.children.clear()
        await self.on_change.asend(None)

    def dump_root(self) -> dict[str, Any]:
        return self._root.model_dump()

    async def load_root(self, data: dict[str, Any]) -> None:
        self._root = FilterGroup.model_validate(data)
        await self.on_change.asend(None)
