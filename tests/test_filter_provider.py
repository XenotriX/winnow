import pytest
import pytest_asyncio

from jnav.filter_provider import FilterProvider
from jnav.filtering import Filter, FilterGroup

from .conftest import make_signal_collector


@pytest_asyncio.fixture
async def fp() -> FilterProvider:
    return FilterProvider()


class TestInitialState:
    @pytest.mark.asyncio
    async def test_root_is_empty_and_group(self, fp: FilterProvider) -> None:
        assert isinstance(fp.root, FilterGroup)
        assert fp.root.operator == "and"
        assert fp.root.children == []


class TestAddFilter:
    @pytest.mark.asyncio
    async def test_add_filter_appends_leaf(self, fp: FilterProvider) -> None:
        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)

        await fp.add_filter('.level == "ERROR"')

        assert len(fp.root.children) == 1
        leaf = fp.root.children[0]
        assert isinstance(leaf, Filter)
        assert leaf.expr == '.level == "ERROR"'
        assert leaf.label is None
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_add_filter_with_label(self, fp: FilterProvider) -> None:
        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)

        await fp.add_filter(".x == 1", label="my-label")

        leaf = fp.root.children[0]
        assert isinstance(leaf, Filter)
        assert leaf.label == "my-label"
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_duplicate_expression_is_ignored(self, fp: FilterProvider) -> None:
        await fp.add_filter(".x == 1")

        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)
        await fp.add_filter(".x == 1")

        assert len(fp.root.children) == 1
        assert events == []

    @pytest.mark.asyncio
    async def test_combine_or_wraps_leaf_in_or_group(self, fp: FilterProvider) -> None:
        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)

        await fp.add_filter(".x == 1", combine="or")

        assert len(fp.root.children) == 1
        child = fp.root.children[0]
        assert isinstance(child, FilterGroup)
        assert child.operator == "or"
        assert len(child.children) == 1
        leaf = child.children[0]
        assert isinstance(leaf, Filter)
        assert leaf.expr == ".x == 1"
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_duplicate_check_only_considers_direct_leaf_children(
        self, fp: FilterProvider
    ) -> None:
        await fp.add_filter(".x == 1", combine="or")

        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)
        await fp.add_filter(".x == 1")

        assert len(fp.root.children) == 2
        assert len(events) == 1


class TestToggleNode:
    @pytest.mark.asyncio
    async def test_toggle_node_flips_enabled(self, fp: FilterProvider) -> None:
        await fp.add_filter(".x == 1")
        leaf = fp.root.children[0]
        assert leaf.enabled is True

        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)
        await fp.toggle_node(leaf)

        assert leaf.enabled is False
        assert len(events) == 1

        await fp.toggle_node(leaf)
        assert leaf.enabled is True


class TestToggleNegated:
    @pytest.mark.asyncio
    async def test_toggle_negated_on_leaf(self, fp: FilterProvider) -> None:
        await fp.add_filter(".x == 1")
        leaf = fp.root.children[0]
        assert leaf.negated is False

        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)
        await fp.toggle_negated(leaf)

        assert leaf.negated is True
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_toggle_negated_on_group(self, fp: FilterProvider) -> None:
        await fp.add_group(fp.root)
        group = fp.root.children[0]
        assert isinstance(group, FilterGroup)
        assert group.negated is False

        await fp.toggle_negated(group)

        assert group.negated is True


class TestAddGroup:
    @pytest.mark.asyncio
    async def test_added_group_uses_opposite_operator(self, fp: FilterProvider) -> None:
        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)
        await fp.add_group(fp.root)

        assert len(fp.root.children) == 1
        child = fp.root.children[0]
        assert isinstance(child, FilterGroup)
        assert child.operator == "or"
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_and_operator_inside_or_parent(self, fp: FilterProvider) -> None:
        await fp.add_group(fp.root)
        or_parent = fp.root.children[0]
        assert isinstance(or_parent, FilterGroup)
        assert or_parent.operator == "or"

        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)
        await fp.add_group(or_parent)

        nested = or_parent.children[0]
        assert isinstance(nested, FilterGroup)
        assert nested.operator == "and"
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_add_group_without_index_appends(self, fp: FilterProvider) -> None:
        await fp.add_filter(".a == 1")
        await fp.add_filter(".b == 2")

        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)
        await fp.add_group(fp.root)

        assert isinstance(fp.root.children[-1], FilterGroup)
        assert len(fp.root.children) == 3
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_add_group_with_index_inserts_after(self, fp: FilterProvider) -> None:
        await fp.add_filter(".a == 1")
        await fp.add_filter(".b == 2")
        await fp.add_filter(".c == 3")

        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)
        await fp.add_group(fp.root, index=0)

        assert isinstance(fp.root.children[1], FilterGroup)
        assert len(fp.root.children) == 4
        assert len(events) == 1


class TestRemoveNode:
    @pytest.mark.asyncio
    async def test_remove_node_from_root(self, fp: FilterProvider) -> None:
        await fp.add_filter(".a == 1")
        await fp.add_filter(".b == 2")
        leaf_a = fp.root.children[0]

        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)
        await fp.remove_node(leaf_a, fp.root)

        assert len(fp.root.children) == 1
        assert isinstance(fp.root.children[0], Filter)
        assert fp.root.children[0].expr == ".b == 2"
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_remove_node_from_nested_group(self, fp: FilterProvider) -> None:
        await fp.add_filter(".x == 1", combine="or")
        group = fp.root.children[0]
        assert isinstance(group, FilterGroup)
        inner = group.children[0]

        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)
        await fp.remove_node(inner, group)

        assert group.children == []
        assert len(events) == 1


class TestSetNodeOperator:
    @pytest.mark.asyncio
    async def test_set_node_operator_flips_group(self, fp: FilterProvider) -> None:
        await fp.add_group(fp.root)
        group = fp.root.children[0]
        assert isinstance(group, FilterGroup)
        starting_op = group.operator

        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)
        await fp.set_node_operator(group, fp.root)

        assert group.operator != starting_op
        assert len(events) == 1

        await fp.set_node_operator(group, fp.root)
        assert group.operator == starting_op

    @pytest.mark.asyncio
    async def test_leaf_is_wrapped_in_or_group_at_same_position(
        self, fp: FilterProvider
    ) -> None:
        await fp.add_filter(".a == 1")
        await fp.add_filter(".b == 2")
        leaf_b = fp.root.children[1]

        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)
        await fp.set_node_operator(leaf_b, fp.root)

        wrapper = fp.root.children[1]
        assert isinstance(wrapper, FilterGroup)
        assert wrapper.operator == "or"
        assert wrapper.children == [leaf_b]
        assert len(events) == 1


class TestFlattenGroup:
    @pytest.mark.asyncio
    async def test_or_group_flattened_with_or_joiner(self, fp: FilterProvider) -> None:
        group = FilterGroup(
            operator="or",
            children=[Filter(expr=".a == 1"), Filter(expr=".b == 2")],
        )
        fp.root.children.append(group)

        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)
        await fp.flatten_group(group, fp.root)

        assert len(fp.root.children) == 1
        leaf = fp.root.children[0]
        assert isinstance(leaf, Filter)
        assert leaf.expr == ".a == 1 or .b == 2"
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_and_group_flattened_with_and_joiner(
        self, fp: FilterProvider
    ) -> None:
        group = FilterGroup(
            operator="and",
            children=[Filter(expr=".a == 1"), Filter(expr=".b == 2")],
        )
        fp.root.children.append(group)

        await fp.flatten_group(group, fp.root)

        leaf = fp.root.children[0]
        assert isinstance(leaf, Filter)
        assert leaf.expr == ".a == 1 and .b == 2"

    @pytest.mark.asyncio
    async def test_flatten_preserves_position(self, fp: FilterProvider) -> None:
        await fp.add_filter(".first == 1")
        group = FilterGroup(children=[Filter(expr=".middle == 2")])
        fp.root.children.append(group)
        await fp.add_filter(".last == 9")

        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)
        await fp.flatten_group(group, fp.root)

        assert len(fp.root.children) == 3
        replaced = fp.root.children[1]
        assert isinstance(replaced, Filter)
        assert replaced.expr == ".middle == 2"
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_empty_group_is_not_flattened(self, fp: FilterProvider) -> None:
        group = FilterGroup()
        fp.root.children.append(group)

        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)
        await fp.flatten_group(group, fp.root)

        assert fp.root.children == [group]
        assert events == []

    @pytest.mark.asyncio
    async def test_group_with_only_disabled_children_is_not_flattened(
        self, fp: FilterProvider
    ) -> None:
        disabled = Filter(expr=".a == 1", enabled=False)
        group = FilterGroup(children=[disabled])
        fp.root.children.append(group)

        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)
        await fp.flatten_group(group, fp.root)

        assert fp.root.children == [group]
        assert events == []


class TestEditLeaf:
    @pytest.mark.asyncio
    async def test_edit_leaf_updates_expression(self, fp: FilterProvider) -> None:
        await fp.add_filter(".old == 1")
        leaf = fp.root.children[0]
        assert isinstance(leaf, Filter)

        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)
        await fp.edit_leaf(leaf, ".new == 2")

        assert leaf.expr == ".new == 2"
        assert len(events) == 1


class TestClearFilters:
    @pytest.mark.asyncio
    async def test_clear_removes_all_children(self, fp: FilterProvider) -> None:
        await fp.add_filter(".a == 1")
        await fp.add_filter(".b == 2")

        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)
        await fp.clear_filters()

        assert fp.root.children == []
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_clear_on_empty_still_emits(self, fp: FilterProvider) -> None:
        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)
        await fp.clear_filters()

        assert len(events) == 1


class TestSetRoot:
    @pytest.mark.asyncio
    async def test_root_captures_current_tree(self, fp: FilterProvider) -> None:
        await fp.add_filter(".a == 1", label="alpha")
        await fp.add_filter(".b == 2", combine="or")

        assert fp.root.operator == "and"
        assert len(fp.root.children) == 2

    @pytest.mark.asyncio
    async def test_set_root_round_trip_preserves_structure(
        self, fp: FilterProvider
    ) -> None:
        await fp.add_filter(".a == 1", label="alpha")
        await fp.add_filter(".b == 2", combine="or")
        original = fp.root

        fresh = FilterProvider()
        events, collect = make_signal_collector()
        await fresh.on_change.subscribe_async(collect)
        await fresh.set_root(original)

        assert fresh.root == original
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_set_root_replaces_existing_tree(self, fp: FilterProvider) -> None:
        await fp.add_filter(".stale == 1")

        replacement = FilterGroup(
            operator="or",
            children=[Filter(expr=".fresh == 1")],
        )

        events, collect = make_signal_collector()
        await fp.on_change.subscribe_async(collect)
        await fp.set_root(replacement)

        assert fp.root.operator == "or"
        assert len(fp.root.children) == 1
        leaf = fp.root.children[0]
        assert isinstance(leaf, Filter)
        assert leaf.expr == ".fresh == 1"
        stale = [
            c
            for c in fp.root.children
            if isinstance(c, Filter) and c.expr == ".stale == 1"
        ]
        assert stale == []
        assert len(events) == 1
