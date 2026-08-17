"""
Integration test for a multi-profile overlay chain (fully self-contained fixtures):

  combined-profile        (as-is, use-first)
    ├── baseline-profile   ── base-catalog + overlay-catalog
    └── overlay-profile    ── base-catalog + overlay-catalog

This mirrors a real-world "apply a privacy overlay onto a high baseline" composition.
The expected result is every baseline control plus the overlay controls not already
present — with identical duplicates dropped by ``use-first``, same-id family groups
merged, and a NEW enhancement of a duplicated parent kept (merged under the kept
parent). All fixtures live in the repo (no external or private data).
"""
import glob
import json
import os

import pytest

from oscal import OSCAL, Profile


_HERE = os.path.dirname(__file__)
_DIR = os.path.join(_HERE, "..", "test-data", "overlay-chain")


def _control_ids(prof):
    def walk(nodes):
        out = []
        for n in nodes:
            if not n["group"]:
                out.append(n["id"])
            out += walk(n["children"])
        return out
    return set(walk(prof.controls_tree))


@pytest.fixture(scope="module")
def combined():
    return OSCAL.load(os.path.join(_DIR, "combined-profile.json"))


class TestOverlayChain:

    def test_fixtures_have_unique_uuids(self):
        seen = {}
        for f in glob.glob(os.path.join(_DIR, "*.json")):
            root = next(iter(json.load(open(f)).values()))
            seen.setdefault(root.get("uuid"), []).append(os.path.basename(f))
        collisions = {u: v for u, v in seen.items() if u and len(v) > 1}
        assert collisions == {}, f"UUID collisions in fixtures: {collisions}"

    def test_top_is_a_profile_that_resolves(self, combined):
        assert isinstance(combined, Profile)
        assert combined.controls_tree, "controls_tree should build from the sub-profiles"

    def test_expected_control_set(self, combined):
        # baseline (11) + overlay controls not already present (4): ac-2.2, pt-2, pt-2.1, sa-1_ov
        assert _control_ids(combined) == {
            "ac-1", "ac-2", "ac-2.1", "ac-2.2", "ac-3", "ac-4",
            "ac-1_ov", "ac-2_ov", "au-1", "au-2", "au-3",
            "pt-1", "pt-2", "pt-2.1", "sa-1_ov",
        }

    def test_use_first_drops_identical_duplicates(self, combined):
        # ac-1, ac-2, pt-1 are in both profiles -> the overlay copies are dropped
        dropped = combined.duplicates["controls"]
        for cid in ("ac-1", "ac-2", "pt-1"):
            assert dropped.get(cid, [{}])[0].get("dropped") is True

    def test_new_enhancement_of_duplicated_parent_kept(self, combined):
        # ac-2 is a duplicate (dropped from overlay), but its NEW child ac-2.2 must be
        # kept and nested under the kept ac-2 (alongside baseline's ac-2.1).
        ac = next(n for n in combined.controls_tree if n["id"] == "ac")
        ac2 = next(c for c in ac["children"] if c["id"] == "ac-2")
        assert {c["id"] for c in ac2["children"]} == {"ac-2.1", "ac-2.2"}

    def test_family_groups_merged_not_duplicated(self, combined):
        top = [n["id"] for n in combined.controls_tree]
        assert top == ["ac", "au", "pt", "sa"]        # merged families, in first-seen order
        assert all("__" not in i for i in _control_ids(combined))   # no renames under use-first

    def test_unresolved_fetch_through_chain(self):
        # Without resolve(), a control materializes on demand through the imported
        # (unresolved) sub-profiles down to the base catalog.
        prof = OSCAL.load(os.path.join(_DIR, "combined-profile.json"))
        assert prof.catalog is None
        ac1 = prof.get_control_by_id("ac-1")
        assert ac1 is not None and ac1["id"] == "ac-1"
        assert "{{ insert: param, ac-1_prm_1 }}" in ac1["parts"][0]["prose"]
        assert prof.catalog is None      # JIT fetch did not force a full resolve

    def test_resolves_to_valid_catalog(self, combined):
        combined.resolve()
        assert combined.catalog is not None and combined.catalog.is_valid
        assert len(combined.catalog) == 15
