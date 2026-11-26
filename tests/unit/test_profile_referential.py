"""
Referential (hierarchy-reconstructing) profile merge — MergeStrategy.

Covers the ``as-is`` case where two imports select a parent control and its
enhancement respectively, from a common source catalog, via different import
branches.

Public fixtures reproduce the private ``ed`` overlay-chain scenario:

    top-profile (as-is, use-first)
      ├── branch-a-profile  -> catalog, includes ac-3        (parent)
      └── branch-b-profile  -> catalog, includes ac-3.14     (child only)

In the source catalog ac-3.14 is an enhancement of ac-3. Per the OSCAL
profile-resolution rule that an explicitly-selected child control implicitly
selects its ancestor controls, branch-b's selection of ac-3.14 pulls ac-3 into
scope, so the enhancement nests under its parent in BOTH merge strategies for this
nested source. The REFERENTIAL-vs-POSITIONAL distinction (REFERENTIAL reconstructs
control→control containment; POSITIONAL keeps the immediate-import structure)
therefore now only diverges for flat/dotted sources where the parent is not an
ancestor of the child in the source tree.
"""

import json
import os

import pytest

from oscal import Profile
from oscal.oscal_controls import MergeStrategy, ResolutionStatus


# ---------------------------------------------------------------------------
# Fixtures: a mini catalog + two branch profiles + a top overlay profile
# ---------------------------------------------------------------------------
def _catalog():
    return {
        "catalog": {
            "uuid": "aaaaaaaa-0000-4000-8000-000000000001",
            "metadata": {
                "title": "Mini Source Catalog",
                "last-modified": "2026-01-01T00:00:00Z",
                "version": "1.0",
                "oscal-version": "1.1.2",
            },
            "groups": [
                {"id": "ac", "class": "family", "title": "Access Control", "controls": [
                    {"id": "ac-1", "title": "Policy and Procedures"},
                    {"id": "ac-3", "title": "Access Enforcement", "controls": [
                        {"id": "ac-3.14", "title": "Individual Access"},
                    ]},
                ]},
            ],
        }
    }


def _branch_profile(uuid, cat_href, ids):
    return {
        "profile": {
            "uuid": uuid,
            "metadata": {
                "title": f"Branch {uuid[-1]}",
                "last-modified": "2026-01-01T00:00:00Z",
                "version": "1.0",
                "oscal-version": "1.1.2",
            },
            "imports": [
                {"href": cat_href, "include-controls": [{"with-ids": ids}]},
            ],
            "merge": {"as-is": True, "combine": {"method": "use-first"}},
        }
    }


def _top_profile(uuid, a_href, b_href):
    return {
        "profile": {
            "uuid": uuid,
            "metadata": {
                "title": "Top Overlay",
                "last-modified": "2026-01-01T00:00:00Z",
                "version": "1.0",
                "oscal-version": "1.1.2",
            },
            "imports": [
                {"href": a_href, "include-all": {}},
                {"href": b_href, "include-all": {}},
            ],
            "merge": {"as-is": True, "combine": {"method": "use-first"}},
        }
    }


def _write(tmp_path, name, doc):
    path = os.path.join(str(tmp_path), name)
    with open(path, "w") as fh:
        json.dump(doc, fh)
    return path


@pytest.fixture
def top(tmp_path):
    cat = _write(tmp_path, "catalog.json", _catalog())
    a = _write(tmp_path, "branch-a.json",
               _branch_profile("bbbbbbbb-0000-4000-8000-00000000000a", cat, ["ac-3"]))
    b = _write(tmp_path, "branch-b.json",
               _branch_profile("cccccccc-0000-4000-8000-00000000000b", cat, ["ac-3.14"]))
    top_path = _write(tmp_path, "top.json",
                      _top_profile("dddddddd-0000-4000-8000-00000000000c", a, b))
    return Profile.load(top_path)


def _path_to(nodes, tid, path=()):
    for n in nodes:
        if n["id"] == tid:
            return path + (n["id"],)
        r = _path_to(n.get("children", []), tid, path + (n["id"],))
        if r:
            return r
    return None


def _count_controls(nodes):
    total = 0
    for n in nodes:
        if not n["group"]:
            total += 1
        total += _count_controls(n.get("children", []))
    return total


# ===========================================================================
# Default strategy + the peer-vs-nest distinction
# ===========================================================================
class TestReferentialDefault:

    def test_default_is_referential(self, top):
        assert top.merge_strategy == MergeStrategy.REFERENTIAL

    def test_referential_nests_enhancement_under_parent(self, top):
        # ac-3.14 nests under ac-3 (which itself sits under group ac).
        assert _path_to(top.controls_tree, "ac-3.14") == ("ac", "ac-3", "ac-3.14")
        assert _path_to(top.controls_tree, "ac-3") == ("ac", "ac-3")

    def test_positional_also_nests_via_implicit_ancestor(self, top):
        # Ancestor inclusion puts ac-3 in branch-b's scope, so the source nesting is
        # preserved under POSITIONAL too (no orphan peer for a nested source).
        top.merge_strategy = MergeStrategy.POSITIONAL
        assert _path_to(top.controls_tree, "ac-3.14") == ("ac", "ac-3", "ac-3.14")
        assert _path_to(top.controls_tree, "ac-3") == ("ac", "ac-3")

    def test_strategy_preserves_control_set(self, top):
        ref_n = _count_controls(top.controls_tree)
        top.merge_strategy = MergeStrategy.POSITIONAL
        pos_n = _count_controls(top.controls_tree)
        assert ref_n == pos_n == 2   # ac-3, ac-3.14 (ac-1 selected by neither branch)


# ===========================================================================
# Strategy switch invalidates resolution and rebuilds the tree
# ===========================================================================
class TestStrategySwitch:

    def test_switch_invalidates_resolution(self, top):
        assert top.resolve() == ResolutionStatus.RESOLVED
        assert top.catalog is not None
        top.merge_strategy = MergeStrategy.POSITIONAL
        assert top.resolution_status == ResolutionStatus.UNRESOLVED
        assert top.catalog is None

    def test_switch_rebuilds_tree_immediately(self, top):
        # No explicit resolve()/getter call between the switch and the read: the tree is
        # rebuilt on access. (For this nested source both strategies nest ac-3.14 under
        # ac-3 because ancestor inclusion pulls ac-3 into scope.)
        assert _path_to(top.controls_tree, "ac-3.14") == ("ac", "ac-3", "ac-3.14")
        top.merge_strategy = MergeStrategy.POSITIONAL
        assert _path_to(top.controls_tree, "ac-3.14") == ("ac", "ac-3", "ac-3.14")

    def test_setting_same_strategy_is_noop(self, top):
        top.resolve()
        cat = top.catalog
        top.merge_strategy = MergeStrategy.REFERENTIAL   # unchanged default
        assert top.catalog is cat                        # resolution not dropped

    def test_referential_resolve_makes_true_enhancement(self, top):
        top.resolve()
        ac3 = top.catalog.get_control_by_id("ac-3")
        assert "ac-3.14" in [c.get("id") for c in ac3.get("controls", [])]

    def test_positional_resolve_nests_via_ancestor(self, top):
        # ac-3 is implicitly in scope (ancestor of the selected ac-3.14), so the resolved
        # catalog nests the enhancement under its parent even under POSITIONAL.
        top.merge_strategy = MergeStrategy.POSITIONAL
        top.resolve()
        ac3 = top.catalog.get_control_by_id("ac-3")
        assert "ac-3.14" in [c.get("id") for c in ac3.get("controls", [])]
        assert top.catalog.get_control_by_id("ac-3.14") is not None


# ===========================================================================
# Real ED overlay-chain dataset (private; skipped when absent, e.g. in CI)
# ===========================================================================
_ED = os.path.join(os.path.dirname(__file__), "..", "test-data", "private", "ed",
                   "ed-high-baseline-privacy-profile.json")


@pytest.mark.skipif(not os.path.exists(_ED), reason="private ED dataset not present")
class TestEdOverlayChain:

    def test_referential_nests_ac_3_14_under_ac_3(self):
        p = Profile.load(_ED)
        assert _path_to(p.controls_tree, "ac-3.14") == ("ac", "ac-3", "ac-3.14")

    def test_positional_also_nests_ac_3_14_via_ancestor(self):
        # The source nests ac-3.14 under ac-3; ancestor inclusion keeps ac-3 in scope, so
        # the enhancement nests under its parent under POSITIONAL too.
        p = Profile.load(_ED)
        p.merge_strategy = MergeStrategy.POSITIONAL
        assert _path_to(p.controls_tree, "ac-3.14") == ("ac", "ac-3", "ac-3.14")

    def test_strategy_preserves_ed_control_count(self):
        p = Profile.load(_ED)
        ref_n = _count_controls(p.controls_tree)
        p.merge_strategy = MergeStrategy.POSITIONAL
        assert _count_controls(p.controls_tree) == ref_n
