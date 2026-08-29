"""
Integration tests for Profile.resolve() against real FedRAMP rev5 baselines.

Each FedRAMP baseline profile imports a FedRAMP tailoring *profile*, which in turn
imports the NIST SP 800-53 rev5 catalog. Under the tree-driven model the parent
consumes the child profile's *load-time* controls_tree and lazy getters, so the child
does NOT need to be resolved first — a plain load + resolve() suffices. The resulting
control set is compared, id-for-id, against FedRAMP's own published resolved catalog —
the authoritative oracle for correctness.
"""
import os
import re

import pytest

from oscal import OSCAL, Catalog, Profile
from oscal.oscal_controls import ResolutionStatus


# Normalize away representation differences that are NOT modify concerns:
#   * out-of-scope cross-references. This library REMOVES a structured ``link`` to an
#     out-of-scope control; the official resolver rewrites the href to an absolute source
#     URI (``file:...#id``) — which is actually schema-invalid OSCAL, since a ``related``
#     link's href must be a catalog-local fragment (a blind spot in the long-"draft" Profile
#     Resolution spec). Both are normalized away here so the comparison focuses on modify
#     (add/remove/set-parameter) content: official ``link`` entries with a ``file:`` href are
#     dropped (matching the library's removal), while ``file:...#`` inside prose markdown is
#     collapsed back to ``#`` (the library still rewrites inline prose).
#   * markdown bracket escaping (``\[`` vs ``[``).
_FILE_REF = re.compile(r"file:[^\s)#]*#")


def _norm(x):
    if isinstance(x, dict):
        out = {}
        for k, v in sorted(x.items()):
            if k == "links" and isinstance(v, list):
                # Drop out-of-scope cross-reference links (official: file: source URIs);
                # omit an entirely-empty links list to match the library removing it.
                v = [ln for ln in v
                     if not (isinstance(ln, dict) and str(ln.get("href", "")).startswith("file:"))]
                if not v:
                    continue
            out[k] = _norm(v)
        return out
    if isinstance(x, list):
        import json
        return sorted((_norm(i) for i in x), key=lambda e: json.dumps(e, sort_keys=True))
    if isinstance(x, str):
        return _FILE_REF.sub("#", x).replace("\\[", "[").replace("\\]", "]")
    return x


_HERE = os.path.dirname(__file__)
_JSON = os.path.join(_HERE, "..", "test-data", "json")

# (baseline name, expected resolved control count)
_BASELINES = [
    ("LOW", 156),
    ("MODERATE", 323),
    ("HIGH", 410),
    ("LI-SaaS", 156),
]


def _resolve_baseline(name):
    """Load a FedRAMP baseline profile and resolve it (no child pre-resolution)."""
    prof = OSCAL.load(os.path.join(_JSON, f"FedRAMP_rev5_{name}-baseline_profile.json"))
    assert isinstance(prof, Profile)
    status = prof.resolve()
    return prof, status


def _official_ids(name):
    cat = Catalog.load(os.path.join(
        _JSON, f"FedRAMP_rev5_{name}-baseline-resolved-profile_catalog.json"))
    return {c["id"] for c in cat.get_control_list()}


@pytest.mark.parametrize("name,expected_count", _BASELINES)
class TestFedrampBaselines:

    def test_resolves(self, name, expected_count):
        prof, status = _resolve_baseline(name)
        assert status == ResolutionStatus.RESOLVED
        assert prof.catalog.is_valid

    def test_control_set_matches_official(self, name, expected_count):
        prof, _ = _resolve_baseline(name)
        mine = {c["id"] for c in prof.get_control_list()}
        theirs = _official_ids(name)
        assert mine == theirs, (
            f"{name}: only-official={sorted(theirs - mine)[:10]}, "
            f"only-mine={sorted(mine - theirs)[:10]}"
        )

    def test_expected_count(self, name, expected_count):
        prof, _ = _resolve_baseline(name)
        assert len(prof.get_control_list()) == expected_count

    def test_no_unexpected_duplicates(self, name, expected_count):
        # A single 800-53 source means no cross-import id collisions.
        prof, _ = _resolve_baseline(name)
        assert prof.duplicates == {"controls": {}, "groups": {}}

    def test_unresolved_fetch_through_chain(self, name, expected_count):
        # Without resolve(), a control is materialized on demand by recursing through
        # the imported (unresolved) tailoring profile down to the 800-53 catalog.
        prof = OSCAL.load(os.path.join(_JSON, f"FedRAMP_rev5_{name}-baseline_profile.json"))
        assert prof.catalog is None
        c = prof.get_control_by_id("ac-1")
        assert c is not None and c["id"] == "ac-1"
        assert prof.catalog is None  # fetching did not trigger a full resolve


# ===========================================================================
# Content oracle: modify (removes/adds/set-parameters) vs. official resolution
# ===========================================================================
@pytest.fixture(scope="module")
def resolved_low():
    prof = OSCAL.load(os.path.join(_JSON, "FedRAMP_rev5_LOW-baseline_profile.json"))
    prof.resolve()
    return prof


@pytest.fixture(scope="module")
def official_low():
    return Catalog.load(os.path.join(
        _JSON, "FedRAMP_rev5_LOW-baseline-resolved-profile_catalog.json"))


class TestModifyContentOracle:
    """Compare resolved control *content* against FedRAMP's published resolved catalog
    for a curated set of controls that exercise adds, removes, and set-parameters. These
    match exactly once the two non-modify representation differences are normalized."""

    # controls exercising: nested-part prop adds, control-level prop add, remove+re-add,
    # and set-parameter constraint/value application.
    CURATED = ["ac-1", "ac-2", "ca-8", "au-2", "au-3", "cm-6"]

    @pytest.mark.parametrize("cid", CURATED)
    def test_content_matches_official(self, resolved_low, official_low, cid):
        mine = resolved_low.get_control_by_id(cid, depth=0)
        theirs = official_low.get_control_by_id(cid, depth=0)
        assert theirs is not None
        assert _norm(mine) == _norm(theirs)

    def test_add_by_control_id_applied(self, resolved_low):
        # child alter: add {name: CORE} prop with by-id == the control itself
        ac2 = resolved_low.get_control_by_id("ac-2", depth=0)
        assert any(p.get("name") == "CORE" for p in ac2.get("props", []))

    def test_add_into_nested_part_applied(self, resolved_low):
        # child alter: add FedRAMP props "starting" into a nested objective part
        ac1 = resolved_low.get_control_by_id("ac-1", depth=0)
        import json
        assert "response-point" in json.dumps(ac1)

    def test_remove_then_readd_applied(self, resolved_low, official_low):
        # parent alter on ca-8: removes by-id ca-8_fr, then re-adds it after ca-8_gdn
        assert _norm(resolved_low.get_control_by_id("ca-8", 0)) == \
            _norm(official_low.get_control_by_id("ca-8", 0))

    def test_unresolved_modify_parity(self, official_low):
        # JIT (unresolved) fetch applies the same modify as resolve()
        prof = OSCAL.load(os.path.join(_JSON, "FedRAMP_rev5_LOW-baseline_profile.json"))
        jit = prof.get_control_by_id("ac-2", depth=0)
        assert any(p.get("name") == "CORE" for p in jit.get("props", []))
