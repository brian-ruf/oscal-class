"""
Unit tests for OSCAL duplicate import detection and resolution actions.

Covers:
    - Two imports that resolve to the same file → second is DUPLICATE
    - DUPLICATE entry shape (status, object, failure, href_valid)
    - DUPLICATE does not appear in failed_imports
    - DUPLICATE does not block content_state from reaching IMPORTS_RESOLVED
    - Three imports where the second and third both duplicate the first
    - Fragment / back-matter imports that resolve to the same file
    - retry_import: DUPLICATE with different valid path → READY
    - retry_import: DUPLICATE/INVALID with already-loaded path → INVALID / ALREADY_IMPORTED
    - ignore_import: entry becomes IGNORED, does not block IMPORTS_RESOLVED
    - ignore_import: returns False for unknown href
    - ignore_import: INVALID entry → IGNORED, unblocks IMPORTS_RESOLVED
    - remove_import: entry is removed from import_list entirely
    - remove_import: returns False for unknown href
    - remove_import: INVALID entry removed → unblocks IMPORTS_RESOLVED
    - remove_import: DUPLICATE removed → list shorter, still resolved
    - import_tree reflects IGNORED and post-remove state
"""

import os
import pytest

from oscal import OSCAL
from oscal.oscal_content import (
    ContentState,
    ImportFailure,
    ImportFailureCode,
    ImportState,
)

_IMPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "test-data", "xml", "imports",
)
_CATALOG_A = os.path.join(_IMPORTS_DIR, "test_catalog.xml")
# A second distinct catalog so we have two different valid files in tests.
# test_profile_direct.xml imports test_catalog.xml, so it makes a valid second file.
_PROFILE_B  = os.path.join(_IMPORTS_DIR, "test_profile_direct.xml")


# ---------------------------------------------------------------------------
# XML builders
# ---------------------------------------------------------------------------

def _profile_xml(*hrefs: str) -> str:
    """Profile with one <import> per href supplied."""
    imports = "\n  ".join(
        f'<import href="{h}"><include-all/></import>' for h in hrefs
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<profile xmlns="http://csrc.nist.gov/ns/oscal/1.0" uuid="aabbccdd-0000-4000-a000-000000000020">
  <metadata>
    <title>Duplicate Detection Test Profile</title>
    <last-modified>2026-06-06T00:00:00Z</last-modified>
    <version>1.0</version>
    <oscal-version>1.2.1</oscal-version>
  </metadata>
  {imports}
  <merge><combine method="keep"/><as-is>true</as-is></merge>
</profile>"""


def _profile_with_backmatter(*rlinks_per_import) -> str:
    """Profile where each import is a fragment → back-matter resource → rlink.

    rlinks_per_import: sequence of (uuid_suffix, rlink_href) tuples, one per import.
    """
    uuid_base = "aabbccdd-0000-4000-a000-00000000"
    imports   = ""
    resources = ""
    for i, (suffix, rlink) in enumerate(rlinks_per_import, start=30):
        uuid = f"{uuid_base}{i:04d}"
        imports   += f'\n  <import href="#{uuid}"><include-all/></import>'
        resources += (
            f'\n    <resource uuid="{uuid}">'
            f'\n      <rlink href="{rlink}"/>'
            f'\n    </resource>'
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<profile xmlns="http://csrc.nist.gov/ns/oscal/1.0" uuid="aabbccdd-0000-4000-a000-000000000021">
  <metadata>
    <title>Fragment Duplicate Test Profile</title>
    <last-modified>2026-06-06T00:00:00Z</last-modified>
    <version>1.0</version>
    <oscal-version>1.2.1</oscal-version>
  </metadata>
  {imports}
  <merge><combine method="keep"/><as-is>true</as-is></merge>
  <back-matter>{resources}
  </back-matter>
</profile>"""


# ===========================================================================
# TestDuplicateDetection — initial resolve_imports pass
# ===========================================================================

class TestDuplicateDetection:
    """Two direct imports that resolve to the same file."""

    @pytest.fixture
    def two_same(self):
        return OSCAL.loads(_profile_xml(_CATALOG_A, _CATALOG_A))

    def test_import_list_has_two_entries(self, two_same):
        assert len(two_same.import_list) == 2

    def test_first_import_is_ready(self, two_same):
        assert two_same.import_list[0]["status"] == ImportState.READY

    def test_second_import_is_duplicate(self, two_same):
        assert two_same.import_list[1]["status"] == ImportState.DUPLICATE

    def test_duplicate_object_is_none(self, two_same):
        """DUPLICATE entries must not hold a second object reference."""
        assert two_same.import_list[1]["object"] is None

    def test_duplicate_failure_is_none(self, two_same):
        """DUPLICATE is not a failure — failure field must be None."""
        assert two_same.import_list[1]["failure"] is None

    def test_duplicate_href_valid_set(self, two_same):
        """href_valid is populated so the caller knows which file was the duplicate."""
        assert two_same.import_list[1]["href_valid"] != ""

    def test_duplicate_href_valid_matches_first(self, two_same):
        """The DUPLICATE href_valid must equal the READY entry's href_valid."""
        assert (
            two_same.import_list[0]["href_valid"]
            == two_same.import_list[1]["href_valid"]
        )

    def test_duplicate_not_in_failed_imports(self, two_same):
        assert all(e["failure"] is None for e in two_same.import_list)
        assert two_same.failed_imports == []

    def test_content_state_imports_resolved(self, two_same):
        """DUPLICATE must not block IMPORTS_RESOLVED when no genuine failures exist."""
        assert two_same.content_state == ContentState.IMPORTS_RESOLVED

    def test_imports_resolved_property_true(self, two_same):
        assert two_same.imports_resolved is True


class TestThreeSameImports:
    """First import loads; second and third are DUPLICATE."""

    @pytest.fixture
    def three_same(self):
        return OSCAL.loads(_profile_xml(_CATALOG_A, _CATALOG_A, _CATALOG_A))

    def test_import_list_has_three_entries(self, three_same):
        assert len(three_same.import_list) == 3

    def test_only_first_is_ready(self, three_same):
        assert three_same.import_list[0]["status"] == ImportState.READY

    def test_second_is_duplicate(self, three_same):
        assert three_same.import_list[1]["status"] == ImportState.DUPLICATE

    def test_third_is_duplicate(self, three_same):
        assert three_same.import_list[2]["status"] == ImportState.DUPLICATE

    def test_still_fully_resolved(self, three_same):
        assert three_same.content_state == ContentState.IMPORTS_RESOLVED


class TestMixedDuplicateAndValid:
    """Two distinct valid imports followed by a duplicate of the first."""

    @pytest.fixture
    def mixed(self):
        return OSCAL.loads(_profile_xml(_CATALOG_A, _PROFILE_B, _CATALOG_A))

    def test_three_entries(self, mixed):
        assert len(mixed.import_list) == 3

    def test_first_ready(self, mixed):
        assert mixed.import_list[0]["status"] == ImportState.READY

    def test_second_ready(self, mixed):
        assert mixed.import_list[1]["status"] == ImportState.READY

    def test_third_duplicate(self, mixed):
        assert mixed.import_list[2]["status"] == ImportState.DUPLICATE

    def test_fully_resolved(self, mixed):
        assert mixed.content_state == ContentState.IMPORTS_RESOLVED

    def test_no_failed_imports(self, mixed):
        assert mixed.failed_imports == []


class TestDuplicateWithFailure:
    """One valid import, one failed import, one duplicate — must NOT reach IMPORTS_RESOLVED."""

    @pytest.fixture
    def with_failure(self):
        return OSCAL.loads(
            _profile_xml(_CATALOG_A, "/tmp/_oscal_dup_fail_nonexistent.xml", _CATALOG_A)
        )

    def test_three_entries(self, with_failure):
        assert len(with_failure.import_list) == 3

    def test_first_ready(self, with_failure):
        assert with_failure.import_list[0]["status"] == ImportState.READY

    def test_second_invalid(self, with_failure):
        assert with_failure.import_list[1]["status"] == ImportState.INVALID

    def test_third_duplicate(self, with_failure):
        assert with_failure.import_list[2]["status"] == ImportState.DUPLICATE

    def test_not_fully_resolved(self, with_failure):
        assert with_failure.content_state == ContentState.VALID
        assert with_failure.imports_resolved is False

    def test_only_the_failure_in_failed_imports(self, with_failure):
        assert len(with_failure.failed_imports) == 1
        assert with_failure.failed_imports[0]["failure"].code == ImportFailureCode.LOCAL_NOT_FOUND


class TestFragmentDuplicate:
    """Two back-matter resources whose rlinks point to the same catalog file."""

    @pytest.fixture
    def fragment_dup(self):
        xml = _profile_with_backmatter(
            ("30", _CATALOG_A),
            ("31", _CATALOG_A),
        )
        return OSCAL.loads(xml)

    def test_two_entries(self, fragment_dup):
        assert len(fragment_dup.import_list) == 2

    def test_first_ready(self, fragment_dup):
        assert fragment_dup.import_list[0]["status"] == ImportState.READY

    def test_second_duplicate(self, fragment_dup):
        assert fragment_dup.import_list[1]["status"] == ImportState.DUPLICATE

    def test_fully_resolved(self, fragment_dup):
        assert fragment_dup.imports_resolved is True


# ===========================================================================
# TestDuplicateImportTree — tree reflects DUPLICATE nodes
# ===========================================================================

class TestDuplicateImportTree:
    @pytest.fixture
    def two_same(self):
        return OSCAL.loads(_profile_xml(_CATALOG_A, _CATALOG_A))

    def test_tree_has_two_nodes(self, two_same):
        assert len(two_same.import_tree["imports"]) == 2

    def test_first_tree_node_ready(self, two_same):
        assert two_same.import_tree["imports"][0]["status"] == ImportState.READY

    def test_second_tree_node_duplicate(self, two_same):
        assert two_same.import_tree["imports"][1]["status"] == ImportState.DUPLICATE

    def test_duplicate_tree_node_no_object(self, two_same):
        assert two_same.import_tree["imports"][1]["object_uuid"] is None

    def test_duplicate_tree_node_empty_imports(self, two_same):
        """Cannot recurse into a DUPLICATE — it holds no object."""
        assert two_same.import_tree["imports"][1]["imports"] == []

    def test_duplicate_tree_node_failure_none(self, two_same):
        assert two_same.import_tree["imports"][1]["failure"] is None


# ===========================================================================
# TestRetryDuplicate — retrying a DUPLICATE entry
# ===========================================================================

class TestRetryDuplicate:
    """The user supplies a different, valid replacement for a DUPLICATE import."""

    @pytest.fixture
    def two_same(self):
        return OSCAL.loads(_profile_xml(_CATALOG_A, _CATALOG_A))

    def test_retry_duplicate_with_different_file_returns_true(self, two_same):
        result = two_same.retry_import(
            two_same.import_list[1]["href_original"],
            _PROFILE_B,
        )
        assert result is True

    def test_retry_duplicate_with_different_file_status_ready(self, two_same):
        two_same.retry_import(two_same.import_list[1]["href_original"], _PROFILE_B)
        assert two_same.import_list[1]["status"] == ImportState.READY

    def test_retry_duplicate_with_different_file_clears_failure(self, two_same):
        two_same.retry_import(two_same.import_list[1]["href_original"], _PROFILE_B)
        assert two_same.import_list[1]["failure"] is None

    def test_retry_duplicate_with_different_file_populates_object(self, two_same):
        two_same.retry_import(two_same.import_list[1]["href_original"], _PROFILE_B)
        assert two_same.import_list[1]["object"] is not None

    def test_retry_duplicate_with_different_file_stays_resolved(self, two_same):
        """Was already IMPORTS_RESOLVED; must stay so after successful retry."""
        assert two_same.imports_resolved is True
        two_same.retry_import(two_same.import_list[1]["href_original"], _PROFILE_B)
        assert two_same.imports_resolved is True

    def test_retry_duplicate_tree_reflects_ready(self, two_same):
        two_same.retry_import(two_same.import_list[1]["href_original"], _PROFILE_B)
        assert two_same.import_tree["imports"][1]["status"] == ImportState.READY

    def test_retry_duplicate_with_same_file_returns_false(self, two_same):
        """Retrying the DUPLICATE with the already-loaded file must fail."""
        result = two_same.retry_import(
            two_same.import_list[1]["href_original"],
            _CATALOG_A,
        )
        assert result is False

    def test_retry_duplicate_with_same_file_status_invalid(self, two_same):
        two_same.retry_import(two_same.import_list[1]["href_original"], _CATALOG_A)
        assert two_same.import_list[1]["status"] == ImportState.INVALID

    def test_retry_duplicate_with_same_file_code_already_imported(self, two_same):
        two_same.retry_import(two_same.import_list[1]["href_original"], _CATALOG_A)
        failure = two_same.import_list[1]["failure"]
        assert failure is not None
        assert failure.code == ImportFailureCode.ALREADY_IMPORTED

    def test_retry_duplicate_with_same_file_reverts_content_state(self, two_same):
        """ALREADY_IMPORTED on a previously-resolved profile must revert content_state."""
        assert two_same.imports_resolved is True
        two_same.retry_import(two_same.import_list[1]["href_original"], _CATALOG_A)
        assert two_same.content_state == ContentState.VALID
        assert two_same.imports_resolved is False


# ===========================================================================
# TestRetryAlreadyImported — retrying a FAILED import with an already-loaded path
# ===========================================================================

class TestRetryAlreadyImported:
    """The user supplies a replacement for a genuinely failed import, but the
    replacement resolves to a file already loaded by a different READY import."""

    @pytest.fixture
    def one_ready_one_failed(self):
        return OSCAL.loads(
            _profile_xml(_CATALOG_A, "/tmp/_oscal_already_imported_test.xml")
        )

    def test_initial_state(self, one_ready_one_failed):
        assert one_ready_one_failed.import_list[0]["status"] == ImportState.READY
        assert one_ready_one_failed.import_list[1]["status"] == ImportState.INVALID

    def test_retry_with_already_loaded_returns_false(self, one_ready_one_failed):
        result = one_ready_one_failed.retry_import(
            "/tmp/_oscal_already_imported_test.xml",
            _CATALOG_A,
        )
        assert result is False

    def test_retry_with_already_loaded_status_invalid(self, one_ready_one_failed):
        one_ready_one_failed.retry_import("/tmp/_oscal_already_imported_test.xml", _CATALOG_A)
        assert one_ready_one_failed.import_list[1]["status"] == ImportState.INVALID

    def test_retry_with_already_loaded_code_already_imported(self, one_ready_one_failed):
        one_ready_one_failed.retry_import("/tmp/_oscal_already_imported_test.xml", _CATALOG_A)
        failure = one_ready_one_failed.import_list[1]["failure"]
        assert failure is not None
        assert failure.code == ImportFailureCode.ALREADY_IMPORTED

    def test_retry_with_already_loaded_uri_in_failure(self, one_ready_one_failed):
        one_ready_one_failed.retry_import("/tmp/_oscal_already_imported_test.xml", _CATALOG_A)
        failure = one_ready_one_failed.import_list[1]["failure"]
        assert failure.uri != ""

    def test_retry_with_already_loaded_href_list_appended(self, one_ready_one_failed):
        """The rejected replacement must still appear in href_list for audit trail."""
        before = len(one_ready_one_failed.import_list[1]["href_list"])
        one_ready_one_failed.retry_import("/tmp/_oscal_already_imported_test.xml", _CATALOG_A)
        after = len(one_ready_one_failed.import_list[1]["href_list"])
        assert after == before + 1

    def test_retry_with_already_loaded_does_not_advance_state(self, one_ready_one_failed):
        """ALREADY_IMPORTED must not advance content_state to IMPORTS_RESOLVED."""
        one_ready_one_failed.retry_import("/tmp/_oscal_already_imported_test.xml", _CATALOG_A)
        assert one_ready_one_failed.content_state == ContentState.VALID
        assert one_ready_one_failed.imports_resolved is False

    def test_retry_with_different_valid_file_succeeds(self, one_ready_one_failed):
        """Confirm the failure is specific to the duplicate — a different file works."""
        result = one_ready_one_failed.retry_import(
            "/tmp/_oscal_already_imported_test.xml",
            _PROFILE_B,
        )
        assert result is True
        assert one_ready_one_failed.imports_resolved is True

    def test_retry_tree_shows_already_imported_failure(self, one_ready_one_failed):
        one_ready_one_failed.retry_import("/tmp/_oscal_already_imported_test.xml", _CATALOG_A)
        tree_entry = one_ready_one_failed.import_tree["imports"][1]
        assert tree_entry["status"] == ImportState.INVALID
        assert tree_entry["failure"].code == ImportFailureCode.ALREADY_IMPORTED


# ===========================================================================
# TestIgnoreImport — ignore_import() method
# ===========================================================================

class TestIgnoreImport:
    """ignore_import() marks an entry IGNORED without removing it."""

    @pytest.fixture
    def two_same(self):
        return OSCAL.loads(_profile_xml(_CATALOG_A, _CATALOG_A))

    @pytest.fixture
    def one_ready_one_failed(self):
        return OSCAL.loads(_profile_xml(_CATALOG_A, "/tmp/_oscal_ignore_test_nonexistent.xml"))

    # --- basic mechanics ---

    def test_ignore_duplicate_returns_true(self, two_same):
        result = two_same.ignore_import(two_same.import_list[1]["href_original"])
        assert result is True

    def test_ignore_sets_status_ignored(self, two_same):
        two_same.ignore_import(two_same.import_list[1]["href_original"])
        assert two_same.import_list[1]["status"] == ImportState.IGNORED

    def test_ignore_clears_failure(self, two_same):
        two_same.ignore_import(two_same.import_list[1]["href_original"])
        assert two_same.import_list[1]["failure"] is None

    def test_ignore_entry_stays_in_list(self, two_same):
        two_same.ignore_import(two_same.import_list[1]["href_original"])
        assert len(two_same.import_list) == 2

    def test_ignore_preserves_href_valid(self, two_same):
        href_valid_before = two_same.import_list[1]["href_valid"]
        two_same.ignore_import(two_same.import_list[1]["href_original"])
        assert two_same.import_list[1]["href_valid"] == href_valid_before

    # --- resolution state ---

    def test_ignored_does_not_block_imports_resolved(self, two_same):
        """DUPLICATE was already non-blocking; IGNORED must also be non-blocking."""
        assert two_same.imports_resolved is True
        two_same.ignore_import(two_same.import_list[1]["href_original"])
        assert two_same.imports_resolved is True

    def test_ignore_invalid_entry_unblocks_resolution(self, one_ready_one_failed):
        """Ignoring a failed import must advance content_state to IMPORTS_RESOLVED."""
        assert one_ready_one_failed.imports_resolved is False
        one_ready_one_failed.ignore_import("/tmp/_oscal_ignore_test_nonexistent.xml")
        assert one_ready_one_failed.imports_resolved is True
        assert one_ready_one_failed.content_state == ContentState.IMPORTS_RESOLVED

    def test_ignore_invalid_entry_status_ignored(self, one_ready_one_failed):
        one_ready_one_failed.ignore_import("/tmp/_oscal_ignore_test_nonexistent.xml")
        assert one_ready_one_failed.import_list[1]["status"] == ImportState.IGNORED

    def test_ignore_not_in_failed_imports(self, two_same):
        two_same.ignore_import(two_same.import_list[1]["href_original"])
        assert two_same.failed_imports == []

    def test_ignore_unknown_href_returns_false(self, two_same):
        result = two_same.ignore_import("/tmp/_oscal_completely_unknown_href.xml")
        assert result is False

    def test_ignore_unknown_href_does_not_mutate_list(self, two_same):
        statuses_before = [e["status"] for e in two_same.import_list]
        two_same.ignore_import("/tmp/_oscal_completely_unknown_href.xml")
        assert [e["status"] for e in two_same.import_list] == statuses_before

    # --- partial ignore (one of two failures) ---

    def test_ignore_one_of_two_failures_does_not_resolve(self):
        """Ignoring one of two failed imports must not advance to IMPORTS_RESOLVED."""
        doc = OSCAL.loads(_profile_xml(
            "/tmp/_oscal_ignore_partial_a.xml",
            "/tmp/_oscal_ignore_partial_b.xml",
        ))
        assert doc.imports_resolved is False
        doc.ignore_import("/tmp/_oscal_ignore_partial_a.xml")
        # One import is still INVALID
        assert doc.imports_resolved is False

    def test_ignore_both_failures_resolves(self):
        """Ignoring all failed imports must advance to IMPORTS_RESOLVED."""
        doc = OSCAL.loads(_profile_xml(
            "/tmp/_oscal_ignore_both_a.xml",
            "/tmp/_oscal_ignore_both_b.xml",
        ))
        doc.ignore_import("/tmp/_oscal_ignore_both_a.xml")
        doc.ignore_import("/tmp/_oscal_ignore_both_b.xml")
        assert doc.imports_resolved is True

    # --- import_tree reflects IGNORED ---

    def test_tree_reflects_ignored_status(self, two_same):
        two_same.ignore_import(two_same.import_list[1]["href_original"])
        assert two_same.import_tree["imports"][1]["status"] == ImportState.IGNORED

    def test_tree_updated_in_place_after_ignore(self, two_same):
        """The cached tree is updated in-place, so the next (copied) access reflects it."""
        _ = two_same.import_tree  # prime cache
        two_same.ignore_import(two_same.import_list[1]["href_original"])
        assert two_same.import_tree["imports"][1]["status"] == ImportState.IGNORED


# ===========================================================================
# TestRemoveImport — remove_import() method
# ===========================================================================

class TestRemoveImport:
    """remove_import() deletes an entry from import_list and from self._dict."""

    @pytest.fixture
    def two_same(self):
        return OSCAL.loads(_profile_xml(_CATALOG_A, _CATALOG_A))

    @pytest.fixture
    def one_ready_one_failed(self):
        return OSCAL.loads(_profile_xml(_CATALOG_A, "/tmp/_oscal_remove_test_nonexistent.xml"))

    # --- basic mechanics ---

    def test_remove_duplicate_returns_true(self, two_same):
        result = two_same.remove_import(two_same.import_list[1]["href_original"])
        assert result is True

    def test_remove_decreases_list_length(self, two_same):
        two_same.remove_import(two_same.import_list[1]["href_original"])
        assert len(two_same.import_list) == 1

    def test_removed_entry_not_in_list(self, two_same):
        href = two_same.import_list[1]["href_original"]
        two_same.remove_import(href)
        assert all(e["href_original"] != href or e["status"] == ImportState.READY
                   for e in two_same.import_list)

    def test_remove_unknown_href_returns_false(self, two_same):
        result = two_same.remove_import("/tmp/_oscal_remove_unknown.xml")
        assert result is False

    def test_remove_unknown_href_does_not_mutate_list(self, two_same):
        length_before = len(two_same.import_list)
        two_same.remove_import("/tmp/_oscal_remove_unknown.xml")
        assert len(two_same.import_list) == length_before

    # --- dict removal ---

    def test_remove_deletes_import_from_dict(self, two_same):
        """The import statement must be removed from self._dict.imports."""
        imports_before = len(two_same._dict["profile"]["imports"])
        two_same.remove_import(two_same.import_list[1]["href_original"])
        assert len(two_same._dict["profile"]["imports"]) == imports_before - 1

    def test_remove_leaves_one_import_in_dict(self, two_same):
        two_same.remove_import(two_same.import_list[1]["href_original"])
        assert len(two_same._dict["profile"]["imports"]) == 1

    def test_remove_preserves_first_import_in_dict(self, two_same):
        """The READY import statement must remain; only the duplicate is deleted."""
        href = two_same.import_list[0]["href_original"]
        two_same.remove_import(two_same.import_list[1]["href_original"])
        remaining = two_same._dict["profile"]["imports"]
        assert len(remaining) == 1
        assert remaining[0]["href"] == href

    def test_remove_marks_content_unsaved(self, two_same):
        """Modifying the dict must set is_unsaved."""
        two_same.is_unsaved = False  # reset to ensure the flag is set by remove
        two_same.remove_import(two_same.import_list[1]["href_original"])
        assert two_same.is_unsaved is True

    def test_remove_unknown_href_does_not_mark_unsaved(self, two_same):
        two_same.is_unsaved = False
        two_same.remove_import("/tmp/_oscal_remove_unknown.xml")
        assert two_same.is_unsaved is False

    # --- back-matter preservation ---

    def test_remove_preserves_back_matter_resource(self):
        """Removing a fragment-based import must NOT delete the back-matter resource."""
        doc = OSCAL.loads(_profile_with_backmatter(("30", _CATALOG_A), ("31", _CATALOG_A)))
        resources_before = len(
            doc._dict["profile"].get("back-matter", {}).get("resources", [])
        )
        doc.remove_import(doc.import_list[1]["href_original"])
        resources_after = len(
            doc._dict["profile"].get("back-matter", {}).get("resources", [])
        )
        assert resources_after == resources_before

    # --- read-only guard ---

    def test_remove_on_read_only_returns_false(self, two_same):
        two_same.is_read_only = True
        result = two_same.remove_import(two_same.import_list[1]["href_original"])
        assert result is False

    def test_remove_on_read_only_does_not_mutate_dict(self, two_same):
        two_same.is_read_only = True
        imports_before = len(two_same._dict["profile"]["imports"])
        two_same.remove_import(two_same.import_list[1]["href_original"])
        assert len(two_same._dict["profile"]["imports"]) == imports_before

    # --- resolution state ---

    def test_remove_duplicate_stays_resolved(self, two_same):
        assert two_same.imports_resolved is True
        two_same.remove_import(two_same.import_list[1]["href_original"])
        assert two_same.imports_resolved is True

    def test_remove_invalid_entry_unblocks_resolution(self, one_ready_one_failed):
        assert one_ready_one_failed.imports_resolved is False
        one_ready_one_failed.remove_import("/tmp/_oscal_remove_test_nonexistent.xml")
        assert one_ready_one_failed.imports_resolved is True
        assert one_ready_one_failed.content_state == ContentState.IMPORTS_RESOLVED

    def test_remove_one_of_two_failures_does_not_resolve(self):
        doc = OSCAL.loads(_profile_xml(
            "/tmp/_oscal_remove_partial_a.xml",
            "/tmp/_oscal_remove_partial_b.xml",
        ))
        doc.remove_import("/tmp/_oscal_remove_partial_a.xml")
        assert doc.imports_resolved is False

    def test_cannot_remove_last_import(self):
        """A profile requires at least one import, so the second removal is refused
        (leaving one import) — its cardinality minimum is enforced."""
        doc = OSCAL.loads(_profile_xml(
            "/tmp/_oscal_remove_both_a.xml",
            "/tmp/_oscal_remove_both_b.xml",
        ))
        assert doc.remove_import("/tmp/_oscal_remove_both_a.xml") is True
        # Only one import remains; removing it would drop below the minimum of 1.
        assert doc.remove_import("/tmp/_oscal_remove_both_b.xml") is False
        assert len(doc._dict["profile"]["imports"]) == 1

    # --- import_tree after removal ---

    def test_tree_has_one_node_after_remove(self, two_same):
        two_same.remove_import(two_same.import_list[1]["href_original"])
        assert len(two_same.import_tree["imports"]) == 1

    def test_tree_updated_in_place_after_remove(self, two_same):
        _ = two_same.import_tree  # prime cache
        two_same.remove_import(two_same.import_list[1]["href_original"])
        assert len(two_same.import_tree["imports"]) == 1

    # --- prefers DUPLICATE over READY when hrefs match ---

    def test_remove_targets_duplicate_not_ready(self, two_same):
        """DUPLICATE entry is removed; READY entry stays in both list and dict."""
        two_same.remove_import(two_same.import_list[1]["href_original"])
        assert len(two_same.import_list) == 1
        assert two_same.import_list[0]["status"] == ImportState.READY
        assert len(two_same._dict["profile"]["imports"]) == 1


# ===========================================================================
# TestEnumMembership — all new enum values
# ===========================================================================

class TestEnumMembership:
    def test_already_imported_in_enum(self):
        assert ImportFailureCode.ALREADY_IMPORTED is not None

    def test_already_imported_value(self):
        assert ImportFailureCode.ALREADY_IMPORTED.value == "already-imported"

    def test_duplicate_in_import_state_enum(self):
        assert ImportState.DUPLICATE is not None

    def test_duplicate_value(self):
        assert ImportState.DUPLICATE.value == "duplicate"

    def test_ignored_in_import_state_enum(self):
        assert ImportState.IGNORED is not None

    def test_ignored_value(self):
        assert ImportState.IGNORED.value == "ignored"


# ===========================================================================
# TestImportSignalProperties — failed_imports / duplicate_imports / unresolved_imports
# ===========================================================================

class TestImportSignalProperties:
    """The three list properties a UI uses to drive import-resolution affordances."""

    @pytest.fixture
    def failed_and_dup(self):
        """One failed import, one READY, one DUPLICATE of the READY one."""
        return OSCAL.loads(_profile_xml(
            "/tmp/_oscal_signal_nonexistent.xml",  # INVALID
            _CATALOG_A,                            # READY
            _CATALOG_A,                            # DUPLICATE
        ))

    # --- duplicate_imports ---

    def test_duplicate_imports_returns_only_duplicates(self, failed_and_dup):
        dups = failed_and_dup.duplicate_imports
        assert len(dups) == 1
        assert all(e["status"] == ImportState.DUPLICATE for e in dups)

    def test_duplicate_imports_empty_when_none(self):
        doc = OSCAL.loads(_profile_xml(_CATALOG_A, _PROFILE_B))
        assert doc.duplicate_imports == []

    def test_failed_imports_excludes_duplicates(self, failed_and_dup):
        """Duplicates have failure=None, so they must not appear in failed_imports."""
        assert len(failed_and_dup.failed_imports) == 1
        assert all(e["status"] == ImportState.INVALID for e in failed_and_dup.failed_imports)

    # --- unresolved_imports ---

    def test_unresolved_imports_includes_failed_and_duplicate(self, failed_and_dup):
        assert len(failed_and_dup.unresolved_imports) == 2
        statuses = {e["status"] for e in failed_and_dup.unresolved_imports}
        assert statuses == {ImportState.INVALID, ImportState.DUPLICATE}

    def test_unresolved_imports_empty_when_all_ready(self):
        doc = OSCAL.loads(_profile_xml(_CATALOG_A, _PROFILE_B))
        assert doc.unresolved_imports == []

    def test_unresolved_imports_excludes_ready(self, failed_and_dup):
        assert all(e["status"] != ImportState.READY for e in failed_and_dup.unresolved_imports)

    def test_unresolved_imports_excludes_ignored(self, failed_and_dup):
        """An IGNORED entry is dismissed and must drop out of unresolved_imports."""
        failed_and_dup.ignore_import(failed_and_dup.import_list[2]["href_original"])
        assert all(e["status"] != ImportState.IGNORED for e in failed_and_dup.unresolved_imports)

    # --- the exact GUI regression sequence ---

    def test_resolving_failure_keeps_duplicate_unresolved(self, failed_and_dup):
        """After the failed import is fixed, the duplicate must remain in
        unresolved_imports even though imports_resolved becomes True — so the UI
        keeps its resolution affordances visible."""
        failed_and_dup.retry_import("/tmp/_oscal_signal_nonexistent.xml", _PROFILE_B)
        assert failed_and_dup.imports_resolved is True       # duplicate is non-blocking
        assert len(failed_and_dup.unresolved_imports) == 1   # but still actionable
        assert failed_and_dup.unresolved_imports[0]["status"] == ImportState.DUPLICATE

    def test_skipping_duplicate_clears_unresolved(self, failed_and_dup):
        """After the failure is fixed AND the duplicate is skipped, nothing remains
        for the user to act on — the resolution UI can close."""
        failed_and_dup.retry_import("/tmp/_oscal_signal_nonexistent.xml", _PROFILE_B)
        failed_and_dup.ignore_import(failed_and_dup.import_list[2]["href_original"])
        assert failed_and_dup.unresolved_imports == []
        assert failed_and_dup.imports_resolved is True

    def test_removing_duplicate_clears_unresolved(self, failed_and_dup):
        """remove_import on the duplicate also clears it from unresolved_imports."""
        failed_and_dup.retry_import("/tmp/_oscal_signal_nonexistent.xml", _PROFILE_B)
        failed_and_dup.remove_import(failed_and_dup.import_list[2]["href_original"])
        assert failed_and_dup.unresolved_imports == []
