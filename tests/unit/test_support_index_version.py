"""
Unit tests for metaschema-index versioning and the self-healing support database:

    * schema migration adds the oscal_versions.index_version column and backfills it
    * resolve_index_version() picks the lowest compatible index version, healing from the
      bundled DB when none is compatible
    * set_version_index_version() / rebuilt indexes carry METASCHEMA_INDEX_VERSION
    * ensure_version() acquires a missing OSCAL version from the bundled DB, substitutes the
      closest same-major version, or reports it unavailable (all exercised offline)
    * get_metaschema_index() keys on (version, model, index_version)
    * loaded OSCAL objects reflect version resolution via VersionSupport

The base database for each test is the library's own bundled copy (extracted to a temp
path), so the tests are independent of the working directory and the shared support DB.
"""
import os
import sqlite3
import zipfile
from importlib import resources

import pytest

import oscal.oscal_support as support_mod
from oscal.oscal_support import OSCALSupport, METASCHEMA_INDEX_VERSION


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------
def _extract_bundled_db(dest: str) -> str:
    """Write the packaged bundled support DB to *dest* and return it."""
    with resources.files("oscal.data").joinpath("oscal_support.zip").open("rb") as f:
        with zipfile.ZipFile(f) as z:
            data = z.read("oscal_support.db")
    with open(dest, "wb") as out:
        out.write(data)
    return dest


@pytest.fixture
def bundled_db_path(tmp_path):
    """Path to a fresh, writable copy of the bundled support database (pre-migration)."""
    return _extract_bundled_db(str(tmp_path / "oscal_support.db"))


@pytest.fixture
def support(bundled_db_path):
    """An OSCALSupport backed by a private copy of the bundled DB (startup already run)."""
    return OSCALSupport(db_conn=bundled_db_path, db_init_mode="auto")


def _columns(db_path, table):
    c = sqlite3.connect(db_path)
    try:
        return [r[1] for r in c.execute(f"PRAGMA table_info('{table}')")]
    finally:
        c.close()


def _distinct_index_versions(db_path):
    c = sqlite3.connect(db_path)
    try:
        return sorted(r[0] for r in c.execute("SELECT DISTINCT index_version FROM oscal_versions"))
    finally:
        c.close()


def _type_counts(db_path):
    c = sqlite3.connect(db_path)
    try:
        return {t: n for t, n in c.execute("SELECT type, count(*) FROM oscal_support GROUP BY type")}
    finally:
        c.close()


def _filecache_count(db_path):
    c = sqlite3.connect(db_path)
    try:
        return c.execute("SELECT count(*) FROM filecache").fetchone()[0]
    finally:
        c.close()


# ===========================================================================
# Schema migration
# ===========================================================================
class TestMigration:

    def test_bundled_db_lacks_column_until_migrated(self, bundled_db_path):
        # The shipped bundle predates the column; startup adds it.
        assert "index_version" not in _columns(bundled_db_path, "oscal_versions")
        OSCALSupport(db_conn=bundled_db_path, db_init_mode="auto")
        assert "index_version" in _columns(bundled_db_path, "oscal_versions")

    def test_existing_rows_backfilled(self, support):
        assert _distinct_index_versions(support.db_conn) == [METASCHEMA_INDEX_VERSION]

    def test_migration_is_idempotent(self, bundled_db_path):
        OSCALSupport(db_conn=bundled_db_path, db_init_mode="auto")
        # Re-opening must not error or change the backfilled values.
        OSCALSupport(db_conn=bundled_db_path, db_init_mode="auto")
        assert _distinct_index_versions(bundled_db_path) == [METASCHEMA_INDEX_VERSION]


# ===========================================================================
# resolve_index_version
# ===========================================================================
class TestResolveIndexVersion:

    def test_defaults_to_backfilled_value(self, support):
        assert support.active_index_version == METASCHEMA_INDEX_VERSION

    def test_picks_lowest_in_range(self, support):
        # Introduce a higher (still same-major) index version on some rows.
        c = sqlite3.connect(support.db_conn)
        c.execute("UPDATE oscal_versions SET index_version = '1.5.0' WHERE version = 'v1.2.3'")
        c.commit()
        c.close()
        assert support.resolve_index_version() == "1.0.0"   # lowest in [1.0.0, 2.0.0)

    def test_out_of_range_falls_back_to_target(self, support, caplog):
        # All rows a different major -> nothing in range -> heal attempt, then fall back.
        c = sqlite3.connect(support.db_conn)
        c.execute("UPDATE oscal_versions SET index_version = '2.0.0'")
        c.commit()
        c.close()
        with caplog.at_level("WARNING"):
            resolved = support.resolve_index_version()
        assert resolved == METASCHEMA_INDEX_VERSION
        assert any("no metaschema index compatible" in r.message.lower() for r in caplog.records)


# ===========================================================================
# Stamping
# ===========================================================================
class TestStamping:

    def test_set_version_index_version_records(self, support):
        assert support.set_version_index_version("v1.2.3", "9.9.9") is True
        c = sqlite3.connect(support.db_conn)
        val = c.execute("SELECT index_version FROM oscal_versions WHERE version = 'v1.2.3'").fetchone()[0]
        c.close()
        assert val == "9.9.9"
        assert support.versions["v1.2.3"]["index_version"] == "9.9.9"

    def test_rebuilt_index_is_stamped(self, support):
        from oscal.metaschema_parser import _rebuild_model_index
        fresh = _rebuild_model_index(support, "v1.2.3", "catalog")
        assert fresh is not None
        assert fresh.get("index_version") == METASCHEMA_INDEX_VERSION


# ===========================================================================
# ensure_version (offline)
# ===========================================================================
class TestEnsureVersion:

    def test_exact_when_present(self, support):
        assert support.ensure_version("v1.2.3") == ("v1.2.3", "exact")

    def test_merges_missing_version_from_bundle(self, support):
        # Remove a version, then have ensure_version restore it from the bundle.
        c = sqlite3.connect(support.db_conn)
        c.execute("DELETE FROM oscal_versions WHERE version = 'v1.2.3'")
        c.commit()
        c.close()
        support._OSCALSupport__load_versions()
        assert "v1.2.3" not in support.versions

        resolved, outcome = support.ensure_version("v1.2.3")
        assert (resolved, outcome) == ("v1.2.3", "exact")
        assert "v1.2.3" in support.versions

    def test_closest_match_when_unavailable(self, support, monkeypatch):
        # No network: a same-major but nonexistent version resolves to the closest one.
        monkeypatch.setattr(support, "update", lambda *a, **k: False)
        resolved, outcome = support.ensure_version("v1.2.99")
        assert outcome == "closest-match"
        assert resolved == "v1.2.3"          # highest available <= requested, same major

    def test_unavailable_when_no_same_major(self, support, monkeypatch):
        monkeypatch.setattr(support, "update", lambda *a, **k: False)
        assert support.ensure_version("v9.9.9") == (None, "unavailable")


# ===========================================================================
# _closest_same_major
# ===========================================================================
class TestClosestSameMajor:

    def _support(self, versions):
        obj = OSCALSupport.__new__(OSCALSupport)
        obj.versions = {v: {} for v in versions}
        return obj

    def test_prefers_highest_at_or_below(self):
        s = self._support(["v1.1.0", "v1.2.0", "v1.2.3", "v2.0.0"])
        assert s._closest_same_major("v1.2.2") == "v1.2.0"

    def test_falls_back_to_lowest_when_all_higher(self):
        s = self._support(["v1.3.0", "v1.4.0", "v2.0.0"])
        assert s._closest_same_major("v1.2.0") == "v1.3.0"

    def test_none_when_no_same_major(self):
        s = self._support(["v2.0.0", "v3.1.0"])
        assert s._closest_same_major("v1.2.0") is None


# ===========================================================================
# get_metaschema_index keyed by index version
# ===========================================================================
class TestIndexKeying:

    def setup_method(self):
        support_mod._metaschema_index_cache.clear()

    def test_cache_key_includes_index_version(self, support):
        support.get_metaschema_index("v1.2.3", "catalog")
        assert ("v1.2.3", "catalog", support.active_index_version) in support_mod._metaschema_index_cache

    def test_index_available(self, support):
        idx = support.get_metaschema_index("v1.2.3", "catalog")
        assert idx is not None and idx.get("nodes")


# ===========================================================================
# Loaded OSCAL object status (VersionSupport)
# ===========================================================================
class TestOSCALVersionSupport:

    @pytest.fixture
    def swapped_support(self, bundled_db_path, monkeypatch):
        """Point the shared support singleton at a private bundled DB for the duration
        of the test, restoring the original afterward."""
        original = support_mod.support
        support_mod.support = None
        support_mod._metaschema_index_cache.clear()
        inst = support_mod.configure_support(support_file=bundled_db_path)
        yield inst
        support_mod.support = original
        support_mod._metaschema_index_cache.clear()

    @staticmethod
    def _catalog_content(oscal_version="1.2.3"):
        raw = resources.files("oscal.data").joinpath("catalog.xml").read_text(encoding="utf-8")
        return raw.replace("<oscal-version>1.2.3</oscal-version>",
                           f"<oscal-version>{oscal_version}</oscal-version>")

    def test_exact_on_normal_load(self, swapped_support):
        from oscal import OSCAL
        from oscal.oscal_content import VersionSupport
        doc = OSCAL.loads(self._catalog_content("1.2.3"))
        assert doc.version_support is VersionSupport.EXACT
        assert doc.requested_oscal_version == "v1.2.3"
        assert doc.resolved_oscal_version == "v1.2.3"
        assert doc.is_valid

    def test_heals_missing_version_on_load(self, swapped_support):
        from oscal import OSCAL
        from oscal.oscal_content import VersionSupport
        # Drop v1.2.3 locally; loading v1.2.3 content re-acquires it from the bundle.
        c = sqlite3.connect(swapped_support.db_conn)
        c.execute("DELETE FROM oscal_versions WHERE version = 'v1.2.3'")
        c.commit()
        c.close()
        swapped_support._OSCALSupport__load_versions()
        doc = OSCAL.loads(self._catalog_content("1.2.3"))
        assert doc.version_support is VersionSupport.EXACT
        assert doc.is_valid

    def test_closest_match_on_load(self, swapped_support, monkeypatch):
        from oscal import OSCAL
        from oscal.oscal_content import VersionSupport
        monkeypatch.setattr(swapped_support, "update", lambda *a, **k: False)
        doc = OSCAL.loads(self._catalog_content("1.2.99"))
        assert doc.version_support is VersionSupport.CLOSEST_MATCH
        assert doc.requested_oscal_version == "v1.2.99"
        assert doc.resolved_oscal_version == "v1.2.3"

    def test_unsupported_on_load(self, swapped_support, monkeypatch):
        from oscal import OSCAL
        from oscal.oscal_content import VersionSupport, ContentState
        monkeypatch.setattr(swapped_support, "update", lambda *a, **k: False)
        doc = OSCAL.loads(self._catalog_content("9.9.9"))
        assert doc.version_support is VersionSupport.UNSUPPORTED
        assert doc.content_state == ContentState.ACQUIRED
        assert not doc.is_valid


# ===========================================================================
# remove_asset + prune-to-processed
# ===========================================================================
class TestRemoveAsset:

    def test_requires_a_criterion(self, support):
        assert support.remove_asset() == 0

    def test_no_match_returns_zero(self, support):
        assert support.remove_asset(version="v9.9.9") == 0

    def test_remove_by_type(self, support):
        removed = support.remove_asset(asset_type="metaschema")
        assert removed > 0
        assert "metaschema" not in _type_counts(support.db_conn)

    def test_remove_by_version_and_model(self, support):
        # catalog for v1.2.3 has three rows: metaschema, document-model, processed.
        removed = support.remove_asset(version="v1.2.3", model="catalog")
        assert removed == 3
        c = sqlite3.connect(support.db_conn)
        remaining = c.execute(
            "SELECT count(*) FROM oscal_support WHERE version='v1.2.3' AND model='catalog'"
        ).fetchone()[0]
        # a different version's catalog is untouched
        other = c.execute(
            "SELECT count(*) FROM oscal_support WHERE version='v1.2.2' AND model='catalog'"
        ).fetchone()[0]
        c.close()
        assert remaining == 0
        assert other > 0

    def test_filecache_orphan_safety(self, support):
        # metaschema and document-model rows share a filecache_uuid; removing only the
        # metaschema rows must NOT delete files still referenced by document-model rows.
        before = _filecache_count(support.db_conn)
        support.remove_asset(asset_type="metaschema")
        after_meta = _filecache_count(support.db_conn)
        # Some files survive (still referenced by document-model), so not everything is gone.
        c = sqlite3.connect(support.db_conn)
        dangling = c.execute(
            "SELECT count(*) FROM oscal_support WHERE filecache_uuid NOT IN (SELECT uuid FROM filecache)"
        ).fetchone()[0]
        c.close()
        assert dangling == 0            # no asset row left pointing at a deleted file
        assert after_meta < before      # some orphaned files were reclaimed

    def test_prune_to_processed_only(self, support):
        support.remove_asset(asset_type="metaschema")
        support.remove_asset(asset_type="document-model")
        assert set(_type_counts(support.db_conn)) == {"processed"}
        # every remaining asset row still has its backing file
        c = sqlite3.connect(support.db_conn)
        dangling = c.execute(
            "SELECT count(*) FROM oscal_support WHERE filecache_uuid NOT IN (SELECT uuid FROM filecache)"
        ).fetchone()[0]
        c.close()
        assert dangling == 0

    def test_list_models_from_processed_only(self, support):
        support.remove_asset(asset_type="metaschema")
        support.remove_asset(asset_type="document-model")
        support._cache.pop("models_per_version", None)  # ensure a fresh query
        models = set(support.list_models("v1.2.3"))
        assert {"catalog", "profile", "system-security-plan"} <= models
        assert "metadata" not in models     # shared module, not a document model

    def test_processed_only_db_still_validates(self, support, monkeypatch):
        # A processed-only support DB is sufficient for validation/conversion.
        support.remove_asset(asset_type="metaschema")
        support.remove_asset(asset_type="document-model")
        support.vacuum()

        import oscal.oscal_support as sm
        from importlib import resources
        original = sm.support
        monkeypatch.setattr(sm, "support", support)  # use this pruned instance directly
        sm._metaschema_index_cache.clear()
        try:
            from oscal import OSCAL
            raw = resources.files("oscal.data").joinpath("catalog.xml").read_text(encoding="utf-8")
            doc = OSCAL.loads(raw)
            assert doc.is_valid
        finally:
            sm.support = original
            sm._metaschema_index_cache.clear()
