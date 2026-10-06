"""
Support-DB staleness self-heal (docs/dev/SUPPORT_DB_STALENESS_FIX.md).

A runtime support DB whose stored processed indexes predate the current index schema (no
`validation-level` / `l2b-spec` / …) must NOT be silently trusted — that caused thousands
of false `allowed-values` errors on nested scoped `part/@name` values. The library now:

  * backfills NULL `index_version` rows to the pre-versioning sentinel (not the current
    version), so stale content can't masquerade as fresh;
  * in `get_metaschema_index`, trusts a stored index only when its embedded `index_version`
    is the same major AND not older than required — otherwise it rebuilds from raw
    metaschema or REFRESHES (delete-then-insert) that version from the bundle;
  * resolves the no-compatible-index case by replacing processed-bearing versions from the
    bundle, not an add-only merge.

Fixtures are built from the packaged bundled DB, so these tests are offline and independent
of the working directory.
"""
import json
import sqlite3
import zipfile
from importlib import resources

import pytest

import oscal.oscal_support as sm
from oscal.oscal_support import (
    OSCALSupport, METASCHEMA_INDEX_VERSION, PRE_VERSIONING_INDEX_SENTINEL,
)

_TIERING_KEYS = ("validation-level", "l2b-spec", "match-spec", "card-spec", "expect-spec")


def _extract_bundled(dest: str) -> str:
    with resources.files("oscal.data").joinpath("oscal_support.zip").open("rb") as f:
        with zipfile.ZipFile(f) as z:
            data = z.read("oscal_support.db")
    with open(dest, "wb") as out:
        out.write(data)
    return dest


def _strip_tiering(node: dict) -> None:
    for c in node.get("constraints", []) or []:
        for k in _TIERING_KEYS:
            c.pop(k, None)
    for ch in node.get("children", []) or []:
        _strip_tiering(ch)


@pytest.fixture
def stale_db(tmp_path):
    """A support DB whose v1.1.3 catalog index is pre-versioning: its processed JSON has the
    tiering keys + embedded index_version stripped, and its oscal_versions row is NULL."""
    path = _extract_bundled(str(tmp_path / "stale.db"))
    s = OSCALSupport(db_conn=path, db_init_mode="auto")
    idx = json.loads(s.get_asset("v1.1.3", "catalog", "processed"))
    idx.pop("index_version", None)
    nodes = idx["nodes"]
    (_strip_tiering(nodes) if isinstance(nodes, dict) else [_strip_tiering(n) for n in nodes])
    s.remove_asset(version="v1.1.3", model="catalog", asset_type="processed")
    s.add_asset("v1.1.3", "catalog", "processed", json.dumps(idx), filename="catalog.json")
    c = sqlite3.connect(path)
    c.execute("UPDATE oscal_versions SET index_version = NULL WHERE version = 'v1.1.3'")
    c.commit()
    c.close()
    return path


def _ivs(path):
    c = sqlite3.connect(path)
    try:
        return {str(r[0]) for r in c.execute("SELECT DISTINCT index_version FROM oscal_versions")}
    finally:
        c.close()


def _catalog_with_nested_item():
    # control -> 'statement' part -> 'item' sub-part: 'item' is only legal under a statement
    # part (ancestor-scoped). Correct validation requires the L2-B tiering data.
    return {"catalog": {
        "uuid": "10000000-0000-4000-8000-000000000001",
        "metadata": {"title": "C", "last-modified": "2026-01-01T00:00:00Z",
                     "version": "1.0", "oscal-version": "1.1.3"},
        "controls": [{"id": "ac-1", "title": "One", "parts": [
            {"id": "s", "name": "statement", "parts": [
                {"id": "s.1", "name": "item", "prose": "x"}]}]}],
    }}


class TestMigrationBackfill:

    def test_unindexed_versions_not_fabricated_to_current(self, tmp_path):
        # NULL every index_version (a fully pre-versioning DB), then open. A version with NO
        # processed content must land on the sentinel — never fabricated to the current
        # version — while versions that DO carry content are legitimately refreshed to
        # current by the resolve-time heal.
        path = _extract_bundled(str(tmp_path / "s.db"))
        c = sqlite3.connect(path)
        c.execute("UPDATE oscal_versions SET index_version = NULL")
        c.commit()
        c.close()
        OSCALSupport(db_conn=path, db_init_mode="auto")   # migrate + resolve (+ heal)
        c = sqlite3.connect(path)
        indexed = {r[0] for r in c.execute(
            "SELECT DISTINCT version FROM oscal_support WHERE type = 'processed'")}
        rows = dict(c.execute("SELECT version, index_version FROM oscal_versions"))
        c.close()
        unindexed = [v for v in rows if v not in indexed]
        assert unindexed, "fixture should include un-indexed versions (v1.0.x / v1.1.0)"
        assert all(rows[v] == PRE_VERSIONING_INDEX_SENTINEL for v in unindexed)
        assert all(rows[v] == METASCHEMA_INDEX_VERSION for v in indexed)


class TestSelfHeal:

    def test_stale_version_content_refreshed(self, stale_db):
        s = OSCALSupport(db_conn=stale_db, db_init_mode="auto")
        idx = s.get_metaschema_index("v1.1.3", "catalog")
        # the stripped stale content is replaced by the bundle's current content
        assert idx.get("index_version") == METASCHEMA_INDEX_VERSION
        assert "l2b-spec" in json.dumps(idx)

    def test_nested_item_validates_cleanly_after_heal(self, stale_db, monkeypatch):
        original = sm.support
        monkeypatch.setattr(sm, "support", OSCALSupport(db_conn=stale_db, db_init_mode="auto"))
        sm._metaschema_index_cache.clear()
        try:
            from oscal import OSCAL
            doc = OSCAL.loads(json.dumps(_catalog_with_nested_item()))
            av = [e for e in doc.validation_errors if e["error-type"] == "allowed-values"]
            assert av == []           # the nested 'item' over-report is gone
            assert doc.validation_status["allowed-values"] is True
        finally:
            sm.support = original
            sm._metaschema_index_cache.clear()

    def test_refresh_replaces_rather_than_ignores(self, stale_db):
        s = OSCALSupport(db_conn=stale_db, db_init_mode="auto")
        assert s._refresh_versions_from_bundle(["v1.1.3"]) is True
        refreshed = json.loads(s.get_asset("v1.1.3", "catalog", "processed"))
        assert refreshed.get("index_version") == METASCHEMA_INDEX_VERSION


class TestNoNeedlessWork:

    def test_current_db_not_refreshed_on_open(self, tmp_path, monkeypatch):
        # A pristine (current) bundled DB must not trigger any refresh/replace on open.
        path = _extract_bundled(str(tmp_path / "fresh.db"))
        calls = []
        orig = OSCALSupport._refresh_versions_from_bundle
        monkeypatch.setattr(OSCALSupport, "_refresh_versions_from_bundle",
                            lambda self, versions: calls.append(list(versions)) or orig(self, versions))
        s = OSCALSupport(db_conn=path, db_init_mode="auto")
        assert s.active_index_version == METASCHEMA_INDEX_VERSION
        assert calls == []            # no heal needed
