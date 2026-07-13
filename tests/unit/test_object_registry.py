"""
Unit + integration tests for the in-memory object registry (identity map).

Covers:
    ObjectRegistry:
        - register/get by content-identity key and by canonical href
        - alias_href, clear, __len__ (distinct objects)
        - stale entries (is_cache_expired) are treated as misses and dropped
        - weak-reference lifetime (entry clears when the object is GC'd)
    Integration (real OSCAL objects):
        - loaded content exposes uuid and a composite _identity
        - two separate parents importing the same file share one object
        - format-variant dedup: xml + json of the same content resolve to one object
        - distinct content stays distinct
"""
import gc
import os

import pytest

from oscal import OSCAL, Catalog, CacheDirective
from oscal.oscal_registry import ObjectRegistry, get_registry


_IMPORTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "test-data", "xml", "imports",
)
_CATALOG = os.path.join(_IMPORTS, "test_catalog.xml")
_PROFILE = os.path.join(_IMPORTS, "test_profile_direct.xml")


@pytest.fixture(autouse=True)
def _clean_registry():
    """Isolate tests from shared global-registry state."""
    get_registry().clear()
    yield
    get_registry().clear()


# ===========================================================================
# ObjectRegistry unit tests (stub values)
# ===========================================================================
class _Stub:
    """Minimal weak-referenceable stand-in with a controllable freshness flag."""
    def __init__(self, expired=False):
        self.is_cache_expired = expired


class TestObjectRegistryUnit:

    def test_register_and_get_by_key(self):
        reg = ObjectRegistry()
        obj = _Stub()
        reg.register(obj, key=("u", "lm", "pub"))
        assert reg.get(key=("u", "lm", "pub")) is obj

    def test_register_and_get_by_href(self):
        reg = ObjectRegistry()
        obj = _Stub()
        reg.register(obj, href="/abs/catalog.xml")
        assert reg.get(href="/abs/catalog.xml") is obj

    def test_get_miss_returns_none(self):
        reg = ObjectRegistry()
        assert reg.get(key=("x",)) is None
        assert reg.get(href="/nope") is None

    def test_href_checked_before_key(self):
        reg = ObjectRegistry()
        a, b = _Stub(), _Stub()
        reg.register(a, key=("k",))
        reg.register(b, href="/h")
        assert reg.get(key=("k",), href="/h") is b  # href wins

    def test_alias_href(self):
        reg = ObjectRegistry()
        obj = _Stub()
        reg.register(obj, key=("k",), href="/a.xml")
        reg.alias_href("/a.json", obj)
        assert reg.get(href="/a.json") is obj

    def test_stale_entry_is_missed_and_dropped(self):
        reg = ObjectRegistry()
        obj = _Stub(expired=True)
        reg.register(obj, key=("k",), href="/h")
        assert reg.get(href="/h") is None      # stale -> miss
        assert reg.get(key=("k",)) is None      # and forgotten from both maps

    def test_clear(self):
        reg = ObjectRegistry()
        reg.register(_Stub(), key=("k",), href="/h")
        reg.clear()
        assert len(reg) == 0
        assert reg.get(href="/h") is None

    def test_len_counts_distinct_objects(self):
        reg = ObjectRegistry()
        obj = _Stub()
        reg.register(obj, key=("k",), href="/a")
        reg.alias_href("/b", obj)   # same object, second href
        assert len(reg) == 1

    def test_weakref_lifetime(self):
        reg = ObjectRegistry()
        obj = _Stub()
        reg.register(obj, key=("k",), href="/h")
        assert reg.get(href="/h") is obj
        del obj
        gc.collect()
        assert reg.get(href="/h") is None   # GC'd -> entry gone


# ===========================================================================
# Identity extraction
# ===========================================================================
class TestIdentityExtraction:

    def test_loaded_catalog_has_uuid(self):
        c = OSCAL.load(_CATALOG)
        assert c.uuid
        assert c.is_valid

    def test_loaded_catalog_has_identity_key(self):
        c = OSCAL.load(_CATALOG)
        key = c._identity_key()
        assert key is not None
        assert key[0] == c.uuid

    def test_object_is_weak_referenceable(self):
        import weakref
        c = OSCAL.load(_CATALOG)
        assert weakref.ref(c)() is c


# ===========================================================================
# Cross-object dedup via resolve_imports
# ===========================================================================
class TestCrossObjectDedup:

    def test_two_parents_share_one_imported_object(self):
        p1 = OSCAL.load(_PROFILE); p1.resolve_imports()
        p2 = OSCAL.load(_PROFILE); p2.resolve_imports()
        o1 = [e["object"] for e in p1.import_list if e["object"] is not None]
        o2 = [e["object"] for e in p2.import_list if e["object"] is not None]
        assert o1 and o2
        assert o1[0] is o2[0]                 # same shared instance

    def test_registry_holds_single_catalog(self):
        p1 = OSCAL.load(_PROFILE); p1.resolve_imports()
        p2 = OSCAL.load(_PROFILE); p2.resolve_imports()
        assert len(get_registry()) == 1


# ===========================================================================
# Cache directives bypass the in-memory registry (refresh / never)
# ===========================================================================
class TestRegistryBypass:

    def test_default_reuses_registry(self):
        p1 = OSCAL.load(_PROFILE); p1.resolve_imports()
        p2 = OSCAL.load(_PROFILE); p2.resolve_imports()
        assert p2.import_list[0]["object"] is p1.import_list[0]["object"]

    def test_refresh_forces_fresh_object(self):
        p1 = OSCAL.load(_PROFILE); p1.resolve_imports()
        p2 = OSCAL.load(_PROFILE)
        p2.resolve_imports(cache_directive=CacheDirective.refresh_now())
        cat2 = p2.import_list[0]["object"]
        assert cat2 is not p1.import_list[0]["object"]   # registry bypassed
        assert cat2.is_valid

    def test_never_forces_fresh_object(self):
        p1 = OSCAL.load(_PROFILE); p1.resolve_imports()
        p2 = OSCAL.load(_PROFILE)
        p2.resolve_imports(cache_directive=CacheDirective.never())
        assert p2.import_list[0]["object"] is not p1.import_list[0]["object"]


# ===========================================================================
# Format-variant identity dedup (same content, xml vs json)
# ===========================================================================
class TestFormatVariantDedup:

    @pytest.fixture
    def json_variant(self, tmp_path):
        """A JSON serialization of the XML test catalog — same content identity."""
        c = OSCAL.load(_CATALOG)
        path = tmp_path / "test_catalog.json"
        path.write_text(c.dumps(format="json"))
        return str(path)

    def test_xml_then_json_resolve_to_one_object(self, json_variant):
        parent = Catalog.new("holder")
        first = parent._acquire_shared(_CATALOG)
        second = parent._acquire_shared(json_variant)
        assert first.is_valid and second.is_valid
        assert second is first                # deduped by content identity

    def test_registry_has_one_object_after_variant(self, json_variant):
        parent = Catalog.new("holder")
        a = parent._acquire_shared(_CATALOG)          # keep strong refs so the
        b = parent._acquire_shared(json_variant)      # weakref entries survive
        assert a is b
        assert len(get_registry()) == 1

    def test_same_identity_key(self, json_variant):
        parent = Catalog.new("holder")
        a = parent._acquire_shared(_CATALOG)
        # loading the json directly yields the same identity tuple
        b = OSCAL.load(json_variant)
        assert a._identity_key() == b._identity_key()
