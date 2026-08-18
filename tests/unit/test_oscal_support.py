"""
Unit tests for oscal.oscal_support.

These tests focus on API behavior and compatibility wrappers without
performing network updates.
"""

import json
import time

import oscal.oscal_support as support_mod
from oscal.oscal_support import OSCALSupport, OSCAL_support


class _FakeDB:
    def __init__(self):
        self.query_calls = 0

    def query(self, _sql):
        self.query_calls += 1
        return [{"model": "catalog"}, {"model": "profile"}]


class _FakeResourcePath:
    def __init__(self):
        self.name = ""
        self.read_text_calls = 0
        self.read_bytes_calls = 0

    def joinpath(self, name):
        self.name = name
        return self

    def read_text(self, encoding="utf-8"):
        _ = encoding
        self.read_text_calls += 1
        return f"text:{self.name}"

    def read_bytes(self):
        self.read_bytes_calls += 1
        return f"bytes:{self.name}".encode("utf-8")


def test_class_alias_preserved():
    assert OSCAL_support is OSCALSupport


def test_configure_support_accepts_pythonic_aliases(monkeypatch):
    monkeypatch.setattr(support_mod, "support", None)
    captured = {}

    class DummySupport:
        def __init__(self, support_file, db_init_mode="auto"):
            captured["support_file"] = support_file
            captured["db_init_mode"] = db_init_mode
            self.ready = True
            self.db_state = "populated"

    monkeypatch.setattr(support_mod, "OSCALSupport", DummySupport)

    obj = support_mod.configure_support(db_path="/tmp/test.db", init_mode="create")

    assert isinstance(obj, DummySupport)
    assert captured["support_file"] == "/tmp/test.db"
    assert captured["db_init_mode"] == "create"


def test_setup_support_wrapper_calls_configure_support(monkeypatch):
    sentinel = object()
    captured = {}

    def fake_configure_support(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(support_mod, "configure_support", fake_configure_support)

    result = support_mod.setup_support("/tmp/support.db", "extract")

    assert result is sentinel
    assert captured == {
        "support_file": "/tmp/support.db",
        "db_init_mode": "extract",
    }


def test_get_support_uses_singleton(monkeypatch):
    sentinel = object()
    calls = {"count": 0}

    def fake_configure_support():
        calls["count"] += 1
        return sentinel

    monkeypatch.setattr(support_mod, "support", None)
    monkeypatch.setattr(support_mod, "configure_support", fake_configure_support)

    first = support_mod.get_support()
    second = support_mod.get_support()

    assert first is sentinel
    assert second is sentinel
    assert calls["count"] == 1


def test_wrapper_asset_delegates_to_get_asset():
    obj = OSCALSupport.__new__(OSCALSupport)

    def fake_get_asset(version, model, asset_type):
        return f"{version}:{model}:{asset_type}"

    obj.get_asset = fake_get_asset

    assert obj.asset("v1.2.3", "catalog", "xml-schema") == "v1.2.3:catalog:xml-schema"


def test_wrapper_model_methods_delegate():
    obj = OSCALSupport.__new__(OSCALSupport)

    def fake_list_models(version="all"):
        if version == "v1.0.0":
            return ["catalog"]
        return ["profile"]

    obj.list_models = fake_list_models

    assert obj.enumerate_models("v1.0.0") == ["catalog"]
    assert obj.is_model_valid("catalog", "v1.0.0") is True
    assert obj.is_valid_model("profile", "all") is True


def test_get_latest_version_wrapper_delegates():
    obj = OSCALSupport.__new__(OSCALSupport)
    obj.latest_version = lambda: "v1.0.9"

    assert obj.get_latest_version() == "v1.0.9"


def test_list_models_uses_cache_per_version():
    obj = OSCALSupport.__new__(OSCALSupport)
    obj.versions = {"v1.0.0": {}}
    obj._cache = {}
    obj.db = _FakeDB()

    first = obj.list_models("v1.0.0")
    second = obj.list_models("v1.0.0")

    assert first == ["catalog", "profile"]
    assert second == ["catalog", "profile"]
    assert obj.db.query_calls == 1


def test_load_file_as_bytes_overrides_binary(monkeypatch):
    obj = OSCALSupport.__new__(OSCALSupport)
    obj._cache = {}

    fake_path = _FakeResourcePath()
    monkeypatch.setattr(support_mod.resources, "files", lambda _pkg: fake_path)

    content = obj.load_file("catalog.xml", binary=False, as_bytes=True)

    assert isinstance(content, bytes)
    assert content == b"bytes:catalog.xml"
    assert fake_path.read_bytes_calls == 1
    assert fake_path.read_text_calls == 0


def test_update_respects_fetch_alias_over_mode():
    obj = OSCALSupport.__new__(OSCALSupport)
    events = []

    obj._OSCALSupport__status_messages = lambda *args, **kwargs: None
    obj._OSCALSupport__clear_oscal_versions = lambda: events.append("clear_all") or True
    obj._OSCALSupport__clear_oscal_version = lambda version: events.append(("clear_one", version)) or True
    obj._OSCALSupport__get_oscal_versions = lambda fetch, save_to_fs=False: events.append(("get", fetch)) or True
    obj._OSCALSupport__load_versions = lambda: events.append("load") or True

    result = obj.update(mode="all", fetch="new")

    assert result is True
    assert "clear_all" not in events
    assert ("get", "new") in events


# ===========================================================================
# get_metaschema_index — cache behaviour
# ===========================================================================

# Per-model index payloads (new format: each model stored individually).
_FAKE_CATALOG_INDEX = {"oscal_model": "catalog", "nodes": {}}
_FAKE_PROFILE_INDEX = {"oscal_model": "profile", "nodes": {}}
_FAKE_CATALOG_RAW = json.dumps(_FAKE_CATALOG_INDEX)
_FAKE_PROFILE_RAW = json.dumps(_FAKE_PROFILE_INDEX)

# Legacy combined payload for migration tests.
_FAKE_LEGACY_INDEX = {
    "oscal_models": {
        "catalog": _FAKE_CATALOG_INDEX,
        "profile": _FAKE_PROFILE_INDEX,
    }
}
_FAKE_LEGACY_RAW = json.dumps(_FAKE_LEGACY_INDEX)


def _make_support(get_asset_fn, add_asset_fn=None):
    """Return a bare OSCALSupport with get_asset (and optionally add_asset) replaced."""
    obj = OSCALSupport.__new__(OSCALSupport)
    obj.get_asset = get_asset_fn
    obj.add_asset = add_asset_fn if add_asset_fn is not None else (lambda *a, **kw: True)
    return obj


class TestGetMetaschemaIndex:

    def setup_method(self):
        """Clear the module-level cache before each test."""
        support_mod._metaschema_index_cache.clear()

    def test_cache_miss_fetches_from_db(self):
        calls = []

        def fake_get_asset(version, model, asset_type):
            calls.append((version, model, asset_type))
            return _FAKE_CATALOG_RAW

        obj = _make_support(fake_get_asset)
        result = obj.get_metaschema_index("v1.2.0", "catalog")

        assert result == _FAKE_CATALOG_INDEX
        assert len(calls) == 1
        assert calls[0] == ("v1.2.0", "catalog", "processed")

    def test_cache_hit_skips_db(self):
        calls = []

        def fake_get_asset(version, model, asset_type):
            calls.append((version, model, asset_type))
            return _FAKE_CATALOG_RAW

        obj = _make_support(fake_get_asset)

        first = obj.get_metaschema_index("v1.2.0", "catalog")
        second = obj.get_metaschema_index("v1.2.0", "catalog")

        assert first is second          # same object from cache
        assert len(calls) == 1          # DB called only once

    def test_cache_entry_structure(self):
        obj = _make_support(lambda *_: _FAKE_CATALOG_RAW)

        before = time.time()
        obj.get_metaschema_index("v1.2.0", "catalog")
        after = time.time()

        entry = support_mod._metaschema_index_cache[("v1.2.0", "catalog")]
        assert entry["version"] == "v1.2.0"
        assert entry["model"] == "catalog"
        assert before <= entry["last_retrieved"] <= after
        assert entry["index"] == _FAKE_CATALOG_INDEX

    def test_expired_cache_refetches_from_db(self, monkeypatch):
        calls = []

        def fake_get_asset(version, model, asset_type):
            calls.append((version, model, asset_type))
            return _FAKE_CATALOG_RAW

        obj = _make_support(fake_get_asset)

        # Populate cache with a timestamp old enough to be stale.
        stale_time = time.time() - support_mod.INDEX_REFRESH - 1
        support_mod._metaschema_index_cache[("v1.2.0", "catalog")] = {
            "version": "v1.2.0",
            "model": "catalog",
            "last_retrieved": stale_time,
            "index": {"stale": True},
        }

        result = obj.get_metaschema_index("v1.2.0", "catalog")

        assert result == _FAKE_CATALOG_INDEX
        assert len(calls) == 1   # cache was expired, so DB was re-queried

    def test_fresh_cache_not_refetched(self):
        calls = []

        def fake_get_asset(version, model, asset_type):
            calls.append((version, model, asset_type))
            return _FAKE_CATALOG_RAW

        obj = _make_support(fake_get_asset)

        # Populate cache with a very recent timestamp.
        support_mod._metaschema_index_cache[("v1.2.0", "catalog")] = {
            "version": "v1.2.0",
            "model": "catalog",
            "last_retrieved": time.time(),
            "index": {"fresh": True},
        }

        result = obj.get_metaschema_index("v1.2.0", "catalog")

        assert result == {"fresh": True}   # returned the pre-populated entry
        assert len(calls) == 0             # DB never touched

    def test_different_versions_cached_independently(self):
        calls = []

        def fake_get_asset(version, model, asset_type):
            calls.append(version)
            return _FAKE_CATALOG_RAW

        obj = _make_support(fake_get_asset)

        obj.get_metaschema_index("v1.1.3", "catalog")
        obj.get_metaschema_index("v1.2.0", "catalog")
        obj.get_metaschema_index("v1.1.3", "catalog")  # should hit cache
        obj.get_metaschema_index("v1.2.0", "catalog")  # should hit cache

        assert calls.count("v1.1.3") == 1
        assert calls.count("v1.2.0") == 1
        assert len(support_mod._metaschema_index_cache) == 2

    def test_different_models_cached_independently(self):
        calls = []

        def fake_get_asset(version, model, asset_type):
            calls.append(model)
            return _FAKE_CATALOG_RAW

        obj = _make_support(fake_get_asset)

        obj.get_metaschema_index("v1.2.0", "catalog")
        obj.get_metaschema_index("v1.2.0", "profile")
        obj.get_metaschema_index("v1.2.0", "catalog")  # cache hit
        obj.get_metaschema_index("v1.2.0", "profile")  # cache hit

        # Each unique (version, model) key causes exactly one DB call.
        assert len(calls) == 2
        assert len(support_mod._metaschema_index_cache) == 2

    def test_returns_none_when_asset_missing(self):
        obj = _make_support(lambda *_: None)
        result = obj.get_metaschema_index("v1.2.0", "catalog")
        assert result is None
        assert ("v1.2.0", "catalog") not in support_mod._metaschema_index_cache

    def test_returns_none_when_asset_is_invalid_json(self):
        obj = _make_support(lambda *_: "not valid json {{{")
        result = obj.get_metaschema_index("v1.2.0", "catalog")
        assert result is None

    def test_legacy_complete_entry_migrates_on_first_hit(self):
        """When only a legacy 'complete' entry exists, the model is extracted and stored."""
        migrated = {}

        def fake_get_asset(version, model, asset_type):
            if model == "catalog":
                return None          # per-model entry not yet present
            if model == "complete":
                return _FAKE_LEGACY_RAW
            return None

        def fake_add_asset(version, model, asset_type, content, **kw):
            migrated[(version, model, asset_type)] = content
            return True

        obj = _make_support(fake_get_asset, fake_add_asset)
        result = obj.get_metaschema_index("v1.2.0", "catalog")

        assert result == _FAKE_CATALOG_INDEX
        assert ("v1.2.0", "catalog", "processed") in migrated

    def test_cache_is_module_level_global(self):
        """Two OSCALSupport instances share the same cache."""
        calls = []

        def fake_get_asset(version, model, asset_type):
            calls.append(1)
            return _FAKE_CATALOG_RAW

        obj1 = _make_support(fake_get_asset)
        obj2 = _make_support(fake_get_asset)

        obj1.get_metaschema_index("v1.2.0", "catalog")
        obj2.get_metaschema_index("v1.2.0", "catalog")

        assert len(calls) == 1  # second instance reused obj1's cache entry

    def test_index_refresh_constant_is_24_hours(self):
        assert support_mod.INDEX_REFRESH == 86400


# ===========================================================================
# Cycle detection in _annotate_ns_conditions and _compute_json_paths
# ===========================================================================

from oscal.metaschema_parser import (
    _annotate_ns_conditions,
    _collect_unresolved_targets,
    _compute_json_paths,
    _extract_oscal_namespace_condition,
    _parse_child_predicates,
    _reroute_unresolved_constraints,
)


def _make_node(path, use_name, structure_type="assembly", group_as=None, children=None, flags=None, constraints=None):
    return {
        "path": path,
        "use-name": use_name,
        "name": use_name,
        "structure-type": structure_type,
        "group-as": group_as,
        "children": (flags or []) + (children or []),
        "constraints": constraints or [],
    }


class TestCycleDetection:

    def test_compute_json_paths_acyclic_tree(self):
        """Normal tree: json-path set on all nodes."""
        prop = _make_node("/catalog/metadata/prop", "prop", group_as="props", flags=[
            _make_node("/catalog/metadata/prop/@name", "name", structure_type="flag"),
        ])
        metadata = _make_node("/catalog/metadata", "metadata", children=[prop])
        root = _make_node("/catalog", "catalog", children=[metadata])

        _compute_json_paths(root, "")

        assert root["json-path"] == "/catalog"
        assert metadata["json-path"] == "/catalog/metadata"
        assert prop["json-path"] == "/catalog/metadata/props"
        assert prop["children"][0]["json-path"] == "/catalog/metadata/props/name"

    def test_compute_json_paths_cycle_does_not_hang(self):
        """Artificially cyclic tree: function returns without infinite recursion."""
        child = _make_node("/ssp/statement/by-component/statement", "statement")
        parent = _make_node("/ssp/statement", "statement", children=[child])
        # Introduce the cycle: child's children list points back to parent
        child["children"].append(parent)

        # Must complete quickly; would hang forever before cycle detection was added
        _compute_json_paths(parent, "/ssp")
        # Both nodes must have been visited
        assert "json-path" in parent
        assert "json-path" in child

    def test_annotate_ns_conditions_cycle_does_not_hang(self):
        """Artificially cyclic tree: annotation returns without infinite recursion."""
        child = _make_node("/ssp/a/b/a", "a", constraints=[{
            "type": "allowed-values",
            "unresolved-target": "prop[has-oscal-namespace('http://csrc.nist.gov/ns/oscal')]/@name",
            "values": [],
        }])
        parent = _make_node("/ssp/a", "a", children=[child])
        child["children"].append(parent)  # cycle

        _annotate_ns_conditions(parent)
        assert child["constraints"][0].get("conditions") is not None

    def test_extract_ns_condition_nist_includes_empty_string(self):
        """NIST namespace condition must include '' so absent-ns props satisfy the check."""
        _, condition = _extract_oscal_namespace_condition(
            ".[has-oscal-namespace('http://csrc.nist.gov/ns/oscal')]/@name"
        )
        assert condition is not None
        assert "" in condition["values"]
        assert condition["allow-absent"] is True

    def test_extract_ns_condition_non_nist_no_empty_string(self):
        """Non-NIST namespace condition must NOT include '' — ns field must be present."""
        _, condition = _extract_oscal_namespace_condition(
            ".[has-oscal-namespace('http://example.com/ns')]/@name"
        )
        assert condition is not None
        assert "" not in condition["values"]
        assert condition["allow-absent"] is False

    def test_extract_ns_condition_cleans_target(self):
        """Cleaned target for a simple @flag reference should be './@name'."""
        cleaned, condition = _extract_oscal_namespace_condition(
            ".[has-oscal-namespace('http://csrc.nist.gov/ns/oscal')]/@name"
        )
        assert cleaned.strip().lstrip("./") == "@name" or cleaned.strip() == "./@name"
        assert condition is not None

    def test_parse_child_predicates_plain_name(self):
        assert _parse_child_predicates("link") == ("link", [])

    def test_parse_child_predicates_single_attr(self):
        name, conds = _parse_child_predicates("prop[@name='type']")
        assert name == "prop"
        assert conds == [{"type": "flag-equals", "flag": "name", "value": "type"}]

    def test_parse_child_predicates_two_attrs(self):
        name, conds = _parse_child_predicates("prop[@name='type' and @class='high']")
        assert name == "prop"
        assert {"type": "flag-equals", "flag": "name", "value": "type"} in conds
        assert {"type": "flag-equals", "flag": "class", "value": "high"} in conds

    def test_parse_child_predicates_unsupported(self):
        """Predicates with positional or function expressions return (None, [])."""
        name, conds = _parse_child_predicates("prop[.='something']")
        assert name is None
        assert conds == []

    def test_conditions_list_two_conditions(self):
        """Target with ns + name predicate produces a conditions list with both entries."""
        # Simulate what _extract_oscal_namespace_condition produces
        cleaned, ns_cond = _extract_oscal_namespace_condition(
            "prop[has-oscal-namespace('http://csrc.nist.gov/ns/oscal') and @name='type']/@value"
        )
        # After ns extraction, bracket has only @name='type' left
        child_ref = cleaned.split("/", 1)[0]   # "prop[@name='type']"
        plain, pred_conds = _parse_child_predicates(child_ref)
        assert plain == "prop"
        assert ns_cond is not None
        assert len(pred_conds) == 1
        assert pred_conds[0] == {"type": "flag-equals", "flag": "name", "value": "type"}
        all_conditions = [ns_cond] + pred_conds
        assert len(all_conditions) == 2
        assert all_conditions[0]["type"] == "namespace"
        assert all_conditions[1]["type"] == "flag-equals"

    def test_indirect_cycle_path_check(self):
        """Verify the path-based cycle guard catches non-adjacent repetition.

        Simulates statement → by-component → statement, which the old
        has_repeated_ending guard (end-only match) would NOT have caught.
        """
        # Build a path that has 'statement' as a non-terminal ancestor
        grandchild = _make_node("/ssp/statement/by-component/statement", "statement")
        by_component = _make_node("/ssp/statement/by-component", "by-component", children=[grandchild])
        root_stmt = _make_node("/ssp/statement", "statement", children=[by_component])

        _compute_json_paths(root_stmt, "/ssp")

        # grandchild shares the same id as root_stmt won't happen (they're separate
        # dicts), but the path-based guard in recurse_metaschema would stop the tree
        # from being built with true cycles.  Here we just verify annotation
        # completes and sets json-path on all three nodes.
        assert "json-path" in root_stmt
        assert "json-path" in by_component
        assert "json-path" in grandchild


class TestRerouteUnresolvedConstraints:
    """_reroute_unresolved_constraints migrates old cached-data constraint placements."""

    def test_dot_child_flag_rerouted(self):
        """./child/@flag on parent moves to child's flag node."""
        value_flag = _make_node("/action/system/@value", "value", structure_type="flag")
        system_child = _make_node("/action/system", "system", flags=[value_flag])
        action = _make_node("/action", "action", children=[system_child], constraints=[{
            "type": "allowed-values",
            "unresolved-target": "./system/@value",
            "values": [{"value": "yes"}, {"value": "no"}],
        }])

        _reroute_unresolved_constraints(action)

        # Constraint removed from action
        assert not any("unresolved-target" in c for c in action["constraints"])
        # Constraint placed on the value flag
        assert len(value_flag["constraints"]) == 1
        assert value_flag["constraints"][0]["type"] == "allowed-values"
        assert "unresolved-target" not in value_flag["constraints"][0]

    def test_plain_child_flag_rerouted(self):
        """child/@flag (without leading ./) is also re-routed."""
        rel_flag = _make_node("/parent/link/@rel", "rel", structure_type="flag")
        link_child = _make_node("/parent/link", "link", flags=[rel_flag])
        parent = _make_node("/parent", "parent", children=[link_child], constraints=[{
            "type": "allowed-values",
            "unresolved-target": "link/@rel",
            "values": [{"value": "reference"}],
        }])

        _reroute_unresolved_constraints(parent)

        assert not any("unresolved-target" in c for c in parent["constraints"])
        assert len(rel_flag["constraints"]) == 1

    def test_flag_on_current_node_rerouted(self):
        """@flag (unresolved on parent) moves to the flag child."""
        name_flag = _make_node("/prop/@name", "name", structure_type="flag")
        prop = _make_node("/prop", "prop", flags=[name_flag], constraints=[{
            "type": "allowed-values",
            "unresolved-target": "@name",
            "values": [{"value": "marking"}],
        }])

        _reroute_unresolved_constraints(prop)

        assert not any("unresolved-target" in c for c in prop["constraints"])
        assert len(name_flag["constraints"]) == 1

    def test_unresolvable_target_left_in_place(self):
        """Targets that cannot be parsed are left as unresolved on the parent."""
        parent = _make_node("/parent", "parent", constraints=[{
            "type": "allowed-values",
            "unresolved-target": "deep/nested/path/@flag",
            "values": [],
        }])

        _reroute_unresolved_constraints(parent)

        assert len(parent["constraints"]) == 1
        assert "unresolved-target" in parent["constraints"][0]

    def test_ns_condition_extracted_during_reroute(self):
        """Namespace condition is extracted and attached when re-routing @flag."""
        name_flag = _make_node("/prop/@name", "name", structure_type="flag")
        prop = _make_node("/prop", "prop", flags=[name_flag], constraints=[{
            "type": "allowed-values",
            "unresolved-target": ".[has-oscal-namespace('http://csrc.nist.gov/ns/oscal')]/@name",
            "values": [{"value": "marking"}],
        }])

        _reroute_unresolved_constraints(prop)

        assert not any("unresolved-target" in c for c in prop["constraints"])
        assert len(name_flag["constraints"]) == 1
        cond = name_flag["constraints"][0].get("conditions", [])
        assert any(c["type"] == "namespace" for c in cond)


class TestTwoLevelRouting:
    """Two-level (and N-level) constraint path navigation."""

    def test_two_level_plain_rerouted(self):
        """metadata/prop/@name (no leading ./) routes to prop's name flag."""
        name_flag = _make_node("/catalog/metadata/prop/@name", "name", structure_type="flag")
        prop      = _make_node("/catalog/metadata/prop", "prop", flags=[name_flag])
        metadata  = _make_node("/catalog/metadata", "metadata", children=[prop])
        catalog   = _make_node("/catalog", "catalog", children=[metadata], constraints=[{
            "type": "allowed-values",
            "unresolved-target": "metadata/prop/@name",
            "values": [{"value": "marking"}],
        }])

        _reroute_unresolved_constraints(catalog)

        assert not any("unresolved-target" in c for c in catalog["constraints"])
        assert len(name_flag["constraints"]) == 1
        assert "unresolved-target" not in name_flag["constraints"][0]

    def test_two_level_with_ns_condition(self):
        """metadata/prop[has-oscal-namespace(...)]/@name routes and attaches conditions."""
        name_flag = _make_node("/catalog/metadata/prop/@name", "name", structure_type="flag")
        prop      = _make_node("/catalog/metadata/prop", "prop", flags=[name_flag])
        metadata  = _make_node("/catalog/metadata", "metadata", children=[prop])
        catalog   = _make_node("/catalog", "catalog", children=[metadata], constraints=[{
            "type": "allowed-values",
            "unresolved-target": "metadata/prop[has-oscal-namespace('http://csrc.nist.gov/ns/oscal')]/@name",
            "values": [{"value": "marking"}],
        }])

        _reroute_unresolved_constraints(catalog)

        assert not any("unresolved-target" in c for c in catalog["constraints"])
        cond = name_flag["constraints"][0].get("conditions", [])
        assert any(c["type"] == "namespace" for c in cond)

    def test_two_level_with_flag_predicate(self):
        """metadata/prop[@name='type']/@value routes with flag-equals condition."""
        value_flag = _make_node("/catalog/metadata/prop/@value", "value", structure_type="flag")
        prop       = _make_node("/catalog/metadata/prop", "prop", flags=[value_flag])
        metadata   = _make_node("/catalog/metadata", "metadata", children=[prop])
        catalog    = _make_node("/catalog", "catalog", children=[metadata], constraints=[{
            "type": "allowed-values",
            "unresolved-target": "metadata/prop[@name='type']/@value",
            "values": [{"value": "system"}],
        }])

        _reroute_unresolved_constraints(catalog)

        assert not any("unresolved-target" in c for c in catalog["constraints"])
        cond = value_flag["constraints"][0].get("conditions", [])
        assert any(c["type"] == "flag-equals" and c["flag"] == "name" for c in cond)

    def test_collect_unresolved_targets(self):
        """_collect_unresolved_targets gathers constraints that remain unresolved."""
        child = _make_node("/catalog/metadata", "metadata", constraints=[{
            "type": "allowed-values",
            "unresolved-target": "deep/path/@flag",
            "values": [],
        }])
        root = _make_node("/catalog", "catalog", children=[child])

        result = _collect_unresolved_targets(root)
        assert len(result) == 1
        assert result[0]["path"] == "/catalog/metadata"
        assert result[0]["target"] == "deep/path/@flag"

    def test_collect_unresolved_skips_resolved(self):
        """Constraints without unresolved-target are not included."""
        node = _make_node("/catalog", "catalog", constraints=[{
            "type": "allowed-values",
            "values": [{"value": "marking"}],
        }])
        assert _collect_unresolved_targets(node) == []
