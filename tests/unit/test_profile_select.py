"""
Unit tests for profile-resolution selection over controls_tree (Phase A) — the pure
helpers that compute which control ids an import selects from a source controls_tree,
plus the tree-navigation/pruning helpers.
"""
import pytest

from oscal.oscal_controls import (
    _index_tree_controls, _tree_descendant_control_ids, _match_select_entries_tree,
    _selected_tree_ids, _find_tree_node, _all_tree_control_nodes,
    _prune_empty_group_nodes, _tree_has_control,
)


# ===========================================================================
# controls_tree fixture (nodes: id/title/group/children)
# ===========================================================================
def _ctl(cid, children=None):
    return {"id": cid, "title": cid, "group": False, "children": children or []}


def _grp(gid, children):
    return {"id": gid, "title": gid, "group": True, "children": children}


def _tree():
    return [
        _grp("ac", [
            _ctl("ac-1"),
            _ctl("ac-2", [
                _ctl("ac-2.1", [_ctl("ac-2.1.1")]),
                _ctl("ac-2.2"),
            ]),
        ]),
        _grp("au", [_ctl("au-1"), _ctl("au-2")]),
    ]


# ===========================================================================
# Indexing helpers
# ===========================================================================
class TestIndexing:

    def test_index_all_control_ids(self):
        ids = set(_index_tree_controls(_tree()).keys())
        assert ids == {"ac-1", "ac-2", "ac-2.1", "ac-2.1.1", "ac-2.2", "au-1", "au-2"}

    def test_index_excludes_groups(self):
        assert "ac" not in _index_tree_controls(_tree())
        assert "au" not in _index_tree_controls(_tree())

    def test_descendant_control_ids(self):
        ac2 = _index_tree_controls(_tree())["ac-2"]
        assert set(_tree_descendant_control_ids(ac2)) == {"ac-2.1", "ac-2.1.1", "ac-2.2"}

    def test_descendant_leaf_empty(self):
        ac1 = _index_tree_controls(_tree())["ac-1"]
        assert _tree_descendant_control_ids(ac1) == []


# ===========================================================================
# select-control-by-id resolution
# ===========================================================================
class TestMatchSelectEntries:

    def _map(self):
        return _index_tree_controls(_tree())

    def test_with_ids_exact(self):
        assert _match_select_entries_tree([{"with-ids": ["ac-1", "au-2"]}], self._map()) == {"ac-1", "au-2"}

    def test_with_ids_absent_skipped(self):
        assert _match_select_entries_tree([{"with-ids": ["ac-1", "nope"]}], self._map()) == {"ac-1"}

    def test_matching_glob(self):
        got = _match_select_entries_tree([{"matching": [{"pattern": "ac-*"}]}], self._map())
        assert got == {"ac-1", "ac-2", "ac-2.1", "ac-2.1.1", "ac-2.2"}

    def test_matching_question_mark(self):
        got = _match_select_entries_tree([{"matching": [{"pattern": "au-?"}]}], self._map())
        assert got == {"au-1", "au-2"}

    def test_with_child_controls_default_no(self):
        assert _match_select_entries_tree([{"with-ids": ["ac-2"]}], self._map()) == {"ac-2"}

    def test_with_child_controls_yes_all_descendants(self):
        got = _match_select_entries_tree(
            [{"with-ids": ["ac-2"], "with-child-controls": "yes"}], self._map())
        assert got == {"ac-2", "ac-2.1", "ac-2.1.1", "ac-2.2"}

    def test_union_across_entries(self):
        got = _match_select_entries_tree([{"with-ids": ["ac-1"]}, {"with-ids": ["au-1"]}], self._map())
        assert got == {"ac-1", "au-1"}

    def test_empty(self):
        assert _match_select_entries_tree([], self._map()) == set()


# ===========================================================================
# _selected_tree_ids — include/exclude composition
# ===========================================================================
class TestSelectedTreeIds:

    def test_include_all(self):
        sel, warn = _selected_tree_ids({"include-all": {}}, _tree())
        assert sel == set(_index_tree_controls(_tree()).keys())
        assert warn == []

    def test_include_all_minus_exclude(self):
        sel, _ = _selected_tree_ids(
            {"include-all": {}, "exclude-controls": [{"with-ids": ["au-1", "au-2"]}]}, _tree())
        assert "au-1" not in sel and "au-2" not in sel and "ac-1" in sel

    def test_exclude_parent_with_children(self):
        sel, _ = _selected_tree_ids(
            {"include-all": {},
             "exclude-controls": [{"with-ids": ["ac-2"], "with-child-controls": "yes"}]}, _tree())
        assert not ({"ac-2", "ac-2.1", "ac-2.1.1", "ac-2.2"} & sel)
        assert "ac-1" in sel

    def test_include_controls(self):
        sel, warn = _selected_tree_ids({"include-controls": [{"with-ids": ["ac-1", "ac-2"]}]}, _tree())
        assert sel == {"ac-1", "ac-2"} and warn == []

    def test_exclude_not_included_warns(self):
        sel, warn = _selected_tree_ids(
            {"include-controls": [{"with-ids": ["ac-1"]}],
             "exclude-controls": [{"with-ids": ["au-1"]}]}, _tree())
        assert sel == {"ac-1"} and any("not included" in w for w in warn)

    def test_no_selection_root_warns(self):
        sel, warn = _selected_tree_ids({}, _tree())
        assert sel == set() and any("neither include-all nor include-controls" in w for w in warn)


# ===========================================================================
# tree navigation / pruning
# ===========================================================================
class TestTreeNav:

    def test_find_control_node(self):
        n = _find_tree_node(_tree(), "ac-2.1", want_group=False)
        assert n is not None and n["id"] == "ac-2.1"

    def test_find_group_node(self):
        n = _find_tree_node(_tree(), "au", want_group=True)
        assert n is not None and n["group"] is True

    def test_find_wrong_kind_returns_none(self):
        assert _find_tree_node(_tree(), "ac", want_group=False) is None  # 'ac' is a group

    def test_all_control_nodes(self):
        ids = {n["id"] for n in _all_tree_control_nodes(_tree())}
        assert ids == {"ac-1", "ac-2", "ac-2.1", "ac-2.1.1", "ac-2.2", "au-1", "au-2"}

    def test_has_control(self):
        assert _tree_has_control(_grp("g", [_ctl("x")])) is True
        assert _tree_has_control(_grp("g", [_grp("h", [])])) is False

    def test_prune_empty_groups(self):
        tree = [
            _grp("empty", [_grp("also_empty", [])]),
            _grp("ac", [_ctl("ac-1")]),
        ]
        pruned = _prune_empty_group_nodes(tree)
        ids = {n["id"] for n in pruned}
        assert ids == {"ac"}

    def test_prune_keeps_nested_nonempty(self):
        tree = [_grp("ac", [_grp("sub", [_ctl("ac-1")]), _grp("empty", [])])]
        pruned = _prune_empty_group_nodes(tree)
        sub_ids = {g["id"] for g in pruned[0]["children"]}
        assert sub_ids == {"sub"}
