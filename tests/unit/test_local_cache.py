"""
Unit tests for the on-disk remote-content cache (oscal_cache.LocalCache) and its
integration with load_source().

Covers:
    LocalCache:
        - database is created lazily (first use), beside a given path
        - miss -> put -> hit round trip
        - entries expire after LOCAL_CACHE_TTL (stale -> miss)
        - refresh updates in place (single row, TTL reset)
        - clear empties the cache
        - empty url / empty content are no-ops
    load_source integration (no network — download is faked):
        - first load fetches and populates the cache
        - second load is served from the cache (no second download)
"""
import os
import time

import pytest

from oscal.oscal_cache import (
    LocalCache, LOCAL_CACHE_TTL, LOCAL_CACHE_FILENAME,
    CacheDirective, CACHE_FOREVER, CACHE_NEVER,
)


def _age(cache, seconds):
    """Backdate the single cached entry so it appears `seconds` old."""
    cache._ensure_db().db_execute(f"UPDATE filecache SET acquired = {time.time() - seconds}")


@pytest.fixture
def cache(tmp_path):
    return LocalCache(db_path=str(tmp_path / LOCAL_CACHE_FILENAME))


_URL = "https://example.com/baselines/catalog.json?v=1"
_CONTENT = '{"catalog": {"uuid": "11111111-1111-4111-8111-111111111111"}}'


# ===========================================================================
# LocalCache
# ===========================================================================
class TestLocalCache:

    def test_db_created_lazily(self, cache, tmp_path):
        assert cache._db is None
        assert not (tmp_path / LOCAL_CACHE_FILENAME).exists()
        cache.get(_URL)  # first use
        assert (tmp_path / LOCAL_CACHE_FILENAME).exists()

    def test_miss_returns_none(self, cache):
        assert cache.get(_URL) is None

    def test_put_then_get(self, cache):
        assert cache.put(_URL, _CONTENT) is True
        assert cache.get(_URL) == _CONTENT

    def test_stale_entry_is_missed(self, cache):
        cache.put(_URL, _CONTENT)
        cache._ensure_db().db_execute("UPDATE filecache SET acquired = 0")  # far in the past
        assert cache.get(_URL) is None

    def test_within_ttl_is_served(self, cache):
        cache.put(_URL, _CONTENT)
        recent = time.time() - (LOCAL_CACHE_TTL - 100)
        cache._ensure_db().db_execute(f"UPDATE filecache SET acquired = {recent}")
        assert cache.get(_URL) == _CONTENT

    def test_refresh_updates_in_place(self, cache):
        cache.put(_URL, _CONTENT)
        cache.put(_URL, '{"catalog": {"v": 2}}')
        rows = cache._ensure_db().query("SELECT count(*) AS n FROM filecache")
        assert rows[0]["n"] == 1                     # single row per url
        assert cache.get(_URL) == '{"catalog": {"v": 2}}'

    def test_clear(self, cache):
        cache.put(_URL, _CONTENT)
        cache.clear()
        assert cache.get(_URL) is None

    def test_empty_url_is_noop(self, cache):
        assert cache.get("") is None
        assert cache.put("", _CONTENT) is False

    def test_empty_content_not_stored(self, cache):
        assert cache.put(_URL, "") is False
        assert cache.get(_URL) is None

    def test_default_path_resolves_beside_support(self):
        c = LocalCache()  # no explicit path
        resolved = c._resolve_path()
        assert resolved.endswith(LOCAL_CACHE_FILENAME)


# ===========================================================================
# load_source integration (download faked — no network)
# ===========================================================================
class TestLoadSourceIntegration:

    def test_second_load_served_from_cache(self, tmp_path, monkeypatch):
        import oscal.oscal_source as oc  # load_source resolves download_file/get_local_cache here
        from oscal.oscal_content import OscalRef, classify_source, load_source

        calls = {"n": 0}

        def fake_download(url, name):
            calls["n"] += 1
            return _CONTENT.encode("utf-8")

        test_cache = LocalCache(db_path=str(tmp_path / LOCAL_CACHE_FILENAME))
        monkeypatch.setattr(oc, "download_file", fake_download)
        monkeypatch.setattr(oc, "get_local_cache", lambda: test_cache)

        ref = OscalRef(href="https://example.com/remote/catalog.json")
        classify_source(ref)

        first = load_source(ref)
        second = load_source(ref)

        assert calls["n"] == 1              # downloaded once, second served from cache
        assert first == second == _CONTENT


# ===========================================================================
# CacheDirective semantics
# ===========================================================================
class TestCacheDirectives:

    def test_constructors(self):
        assert CacheDirective().ttl == LOCAL_CACHE_TTL
        assert CacheDirective.of(60).ttl == 60
        assert CacheDirective.forever().ttl == CACHE_FOREVER
        assert CacheDirective.never().ttl == CACHE_NEVER
        assert CacheDirective.refresh_now().refresh is True

    def test_ttl_override_still_fresh(self, cache):
        """Fetched 6h ago; re-checking with a 12h TTL keeps it fresh."""
        cache.put(_URL, _CONTENT)
        _age(cache, 6 * 3600)
        assert cache.get(_URL, CacheDirective.of(12 * 3600)) == _CONTENT

    def test_ttl_override_now_stale(self, cache):
        """Fetched 6h ago; a 3h TTL now makes it stale."""
        cache.put(_URL, _CONTENT)
        _age(cache, 6 * 3600)
        assert cache.get(_URL, CacheDirective.of(3 * 3600)) is None

    def test_never_purges_and_misses(self, cache):
        cache.put(_URL, _CONTENT)
        assert cache.get(_URL, CacheDirective.never()) is None
        assert cache._row_for(_URL) is None          # purged

    def test_never_does_not_store(self, cache):
        assert cache.put(_URL, _CONTENT, CacheDirective.never()) is False
        assert cache._row_for(_URL) is None

    def test_forever_reuses_any_age(self, cache):
        cache.put(_URL, _CONTENT)
        _age(cache, 100 * 24 * 3600)                  # 100 days old
        assert cache.get(_URL, CacheDirective.forever()) == _CONTENT
        assert cache.get(_URL) is None                # default TTL: stale

    def test_refresh_forces_miss(self, cache):
        cache.put(_URL, _CONTENT)
        assert cache.get(_URL, CacheDirective.refresh_now()) is None  # even though fresh
        assert cache._row_for(_URL) is not None       # entry kept until put() replaces it

    def test_purge(self, cache):
        cache.put(_URL, _CONTENT)
        cache.purge(_URL)
        assert cache.get(_URL) is None


# ===========================================================================
# Directive integration through load_source
# ===========================================================================
class TestDirectiveIntegration:

    def _setup(self, tmp_path, monkeypatch):
        import oscal.oscal_source as oc  # load_source resolves download_file/get_local_cache here
        from oscal.oscal_content import OscalRef, classify_source

        calls = {"n": 0}

        def fake_download(url, name):
            calls["n"] += 1
            return _CONTENT.encode("utf-8")

        test_cache = LocalCache(db_path=str(tmp_path / LOCAL_CACHE_FILENAME))
        monkeypatch.setattr(oc, "download_file", fake_download)
        monkeypatch.setattr(oc, "get_local_cache", lambda: test_cache)
        ref = OscalRef(href="https://example.com/remote/catalog.json")
        classify_source(ref)
        return calls, ref

    def test_never_always_downloads(self, tmp_path, monkeypatch):
        from oscal.oscal_content import load_source
        calls, ref = self._setup(tmp_path, monkeypatch)
        load_source(ref, CacheDirective.never())
        load_source(ref, CacheDirective.never())
        assert calls["n"] == 2               # never served from cache

    def test_refresh_forces_second_download(self, tmp_path, monkeypatch):
        from oscal.oscal_content import load_source
        calls, ref = self._setup(tmp_path, monkeypatch)
        load_source(ref)                                  # downloads + caches
        load_source(ref, CacheDirective.refresh_now())    # forced refetch
        assert calls["n"] == 2

    def test_default_uses_cache(self, tmp_path, monkeypatch):
        from oscal.oscal_content import load_source
        calls, ref = self._setup(tmp_path, monkeypatch)
        load_source(ref)
        load_source(ref)
        assert calls["n"] == 1
