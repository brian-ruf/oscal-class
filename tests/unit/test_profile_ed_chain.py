"""
Integration test for the ED multi-profile overlay chain (private test data):

  ed-high-baseline-privacy-profile  (as-is, use-first)
    ├── ed-high-baseline-profile
    └── ed-privacy-overlay-profile

Both branches import ed-tailoring-profile (-> remote NIST 800-53) and the ED overlay
catalog. The expected result is every high-baseline control plus the privacy-overlay
controls not already present. Skips when the remote 800-53 catalog cannot be fetched.
"""
import os

import pytest

from oscal import OSCAL, Profile

_HERE = os.path.dirname(__file__)
_ED = os.path.join(_HERE, "..", "test-data", "private", "ed")
_TOP = os.path.join(_ED, "ed-high-baseline-privacy-profile.json")


def _control_ids(prof):
    def allc(nodes):
        out = []
        for n in nodes:
            if not n["group"]:
                out.append(n["id"])
            out += allc(n["children"])
        return out
    return set(allc(prof.controls_tree))


@pytest.fixture(scope="module")
def top():
    if not os.path.exists(_TOP):
        pytest.skip("ED private test data not present")
    prof = OSCAL.load(_TOP)
    # Skip when the remote 800-53 import didn't resolve (offline CI).
    if not _control_ids(prof):
        pytest.skip("ED chain imports did not resolve (likely offline)")
    return prof


class TestEdOverlayChain:

    def test_no_uuid_collisions_in_content(self):
        import glob
        import json
        seen = {}
        for f in glob.glob(os.path.join(_ED, "*.json")):
            try:
                doc = json.load(open(f))
                root = next(iter(doc.values()))
                seen.setdefault(root.get("uuid"), []).append(os.path.basename(f))
            except Exception:
                pass
        collisions = {u: v for u, v in seen.items() if u and len(v) > 1}
        assert collisions == {}, f"UUID collisions in ED content: {collisions}"

    def test_expected_control_count(self, top):
        ids = _control_ids(top)
        assert len(ids) == 527

    def test_no_duplicate_or_renamed_controls(self, top):
        # use-first + group-merge => clean ids, no __uuid renames
        ids = _control_ids(top)
        assert not any("__" in i for i in ids)

    def test_families_merged_not_duplicated(self, top):
        # all top-level nodes are family groups; none renamed
        top_ids = [n["id"] for n in top.controls_tree]
        assert all("__" not in i for i in top_ids)

    def test_privacy_enhancements_of_baseline_parents_kept(self, top):
        # these privacy enhancements have parents already in the baseline; use-first
        # must keep them (not drop with the duplicate parent)
        ids = _control_ids(top)
        assert {"at-3.5", "ca-7.4", "ir-2.3", "pm-20.1",
                "si-12.1", "si-12.2", "si-12.3"} <= ids

    def test_resolves_to_valid_catalog(self, top):
        top.resolve()
        assert top.catalog is not None and top.catalog.is_valid
        assert len(top.catalog) == 527
