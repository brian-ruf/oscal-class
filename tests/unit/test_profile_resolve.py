"""
Unit tests for the tree-driven Profile resolution model (Phases C & D):

  - controls_tree is built on load/directive-change (scope + organization + origin);
  - .catalog stays None until resolve(); resolve() materializes a fresh catalog;
  - read-only getters materialize from source when unresolved, from .catalog when resolved,
    and agree (parity);
  - combine/duplicates rename node ids in the tree, full internal ids at resolve;
  - metadata & back-matter carry-forward; manual duplicate resolution.

Source catalogs are written to real files and imported — nothing is mocked.
"""
import json
import os

import pytest

from oscal import Profile, Catalog
from oscal.oscal_controls import ResolutionStatus


# ===========================================================================
# Helpers / fixtures
# ===========================================================================
def _source_catalog(uuid="11111111-1111-4111-8111-111111111111",
                    title="Source Catalog",
                    last_modified="2026-01-01T00:00:00Z"):
    return {
        "catalog": {
            "uuid": uuid,
            "metadata": {
                "title": title,
                "last-modified": last_modified,
                "version": "1.0",
                "oscal-version": "1.1.3",
                "links": [{"href": "https://example.test/src", "rel": "canonical"}],
                "props": [{"name": "keywords", "value": "source"}],
            },
            "groups": [
                {"id": "ac", "class": "family", "title": "Access Control", "controls": [
                    {"id": "ac-1", "title": "Policy and Procedures",
                     "params": [{"id": "ac-1_prm_1", "label": "personnel"}],
                     "parts": [{"id": "ac-1_smt", "name": "statement",
                                "prose": "Develop {{ insert: param, ac-1_prm_1 }}."}],
                     "links": [{"href": "#res-1", "rel": "reference"}],
                     "controls": [{"id": "ac-1.1", "title": "Enhancement"}]},
                    {"id": "ac-2", "title": "Account Management"},
                ]},
                {"id": "au", "class": "family", "title": "Audit", "controls": [
                    {"id": "au-1", "title": "Audit Policy"},
                    {"id": "au-2", "title": "Audit Events"},
                ]},
            ],
            "back-matter": {"resources": [
                {"uuid": "res-1-uuid-placeholder", "title": "Cited Doc"},
            ]},
        }
    }


def _write(tmp_path, name, doc):
    res = doc["catalog"]["back-matter"]["resources"][0]
    res["uuid"] = "27847491-5ce1-4f6a-a1e4-9e483782f0ef"
    doc["catalog"]["groups"][0]["controls"][0]["links"][0]["href"] = f"#{res['uuid']}"
    path = os.path.join(str(tmp_path), name)
    with open(path, "w") as fh:
        json.dump(doc, fh)
    return path


@pytest.fixture
def src_path(tmp_path):
    return _write(tmp_path, "src.json", _source_catalog())


def _baseline(src_path, merge_kwargs=None, title="My Baseline"):
    p = Profile.new(title)
    p.set_metadata({"title": title})
    p.add_import(src_path, include_all=True)
    p.set_merge(**(merge_kwargs or {"as_is": True, "combine": "keep"}))
    return p


@pytest.fixture
def prof(src_path):
    return _baseline(src_path)


@pytest.fixture
def resolved(prof):
    prof.resolve()
    return prof


# ===========================================================================
# Lazy model: tree on load, catalog on resolve
# ===========================================================================
class TestLazyModel:

    def test_catalog_none_until_resolve(self, prof):
        assert prof.catalog is None
        assert prof.resolution_status == ResolutionStatus.UNRESOLVED

    def test_controls_tree_built_from_directives(self, prof):
        top_ids = {n["id"] for n in prof.controls_tree}
        assert top_ids == {"ac", "au"}

    def test_tree_nodes_carry_origin(self, prof):
        ac = next(n for n in prof.controls_tree if n["id"] == "ac")
        ac1 = next(c for c in ac["children"] if c["id"] == "ac-1")
        assert ac1["origin"]["source_id"] == "ac-1"
        assert ac1["origin"]["object_uuid"] == "11111111-1111-4111-8111-111111111111"

    def test_resolve_builds_catalog(self, prof):
        assert prof.resolve() == ResolutionStatus.RESOLVED
        assert isinstance(prof.catalog, Catalog)
        assert prof.catalog.is_valid

    def test_resolve_replaces_prior_catalog(self, prof):
        prof.resolve()
        first = prof.catalog
        prof.resolve()
        assert prof.catalog is not first


# ===========================================================================
# Unresolved read path materializes from source (parity with resolved)
# ===========================================================================
class TestUnresolvedReads:

    def test_get_control_materialized(self, prof):
        c = prof.get_control_by_id("ac-1")
        assert c is not None and c["id"] == "ac-1"
        assert c["params"][0]["id"] == "ac-1_prm_1"
        assert "{{ insert: param, ac-1_prm_1 }}" in c["parts"][0]["prose"]

    def test_get_control_enhancement_nested(self, prof):
        c = prof.get_control_by_id("ac-1")
        assert c["controls"][0]["id"] == "ac-1.1"

    def test_depth_zero_omits_enhancements(self, prof):
        assert "controls" not in prof.get_control_by_id("ac-1", depth=0)

    def test_get_group_materialized(self, prof):
        g = prof.get_group_by_id("ac", depth=0)
        assert g["id"] == "ac" and "controls" not in g

    def test_control_list_counts_all(self, prof):
        ids = {c["id"] for c in prof.get_control_list()}
        assert ids == {"ac-1", "ac-1.1", "ac-2", "au-1", "au-2"}

    def test_parity_unresolved_vs_resolved(self, prof):
        before = prof.get_control_by_id("ac-1")
        prof.resolve()
        after = prof.get_control_by_id("ac-1")
        assert before == after

    def test_absent_returns_none(self, prof):
        assert prof.get_control_by_id("zz-9") is None
        assert prof.get_group_by_id("zz") is None

    def test_safe_copy(self, prof):
        c = prof.get_control_by_id("ac-1")
        c["title"] = "MUT"
        assert prof.get_control_by_id("ac-1")["title"] != "MUT"


# ===========================================================================
# Resolved catalog structure & metadata
# ===========================================================================
class TestResolvedCatalog:

    def test_control_count(self, resolved):
        assert len(resolved.catalog) == 5

    def test_groups_preserved_as_is(self, resolved):
        assert resolved.get_group_by_id("ac") is not None
        assert resolved.get_group_by_id("au") is not None

    def test_param_insert_intact(self, resolved):
        ac1 = resolved.get_control_by_id("ac-1")
        assert "{{ insert: param, ac-1_prm_1 }}" in ac1["parts"][0]["prose"]

    def test_title_from_profile(self, resolved):
        assert resolved.catalog._dict["catalog"]["metadata"]["title"] == "My Baseline"

    def test_fresh_uuid(self, resolved):
        assert resolved.catalog._dict["catalog"]["uuid"] != "11111111-1111-4111-8111-111111111111"

    def test_last_modified_newest(self, tmp_path):
        older = _write(tmp_path, "old.json", _source_catalog(last_modified="2020-01-01T00:00:00Z"))
        p = _baseline(older)
        p.set_metadata({"last-modified": "2027-05-05T00:00:00Z"})
        p.resolve()
        assert p.catalog._dict["catalog"]["metadata"]["last-modified"] == "2027-05-05T00:00:00Z"

    def test_links_and_props_carried(self, resolved):
        meta = resolved.catalog._dict["catalog"]["metadata"]
        assert any(ln.get("href") == "https://example.test/src" for ln in meta.get("links", []))
        assert any(p.get("value") == "source" for p in meta.get("props", []))

    def test_referenced_resource_carried_with_uuid(self, resolved):
        resources = resolved.catalog._dict["catalog"].get("back-matter", {}).get("resources", [])
        assert "27847491-5ce1-4f6a-a1e4-9e483782f0ef" in {r["uuid"] for r in resources}


# ===========================================================================
# flat
# ===========================================================================
class TestFlat:

    def test_flat_no_groups(self, src_path):
        p = _baseline(src_path, {"flat": True})
        p.resolve()
        assert "groups" not in p.catalog._dict["catalog"]
        assert p.catalog.is_valid

    def test_flat_controls_at_root(self, src_path):
        p = _baseline(src_path, {"flat": True})
        p.resolve()
        root_ids = {c["id"] for c in p.catalog._dict["catalog"].get("controls", [])}
        assert {"ac-1", "ac-2", "au-1", "au-2"} <= root_ids


# ===========================================================================
# selection via include/exclude
# ===========================================================================
class TestSelection:

    def _with_include(self, src_path, include, exclude=None):
        p = Profile.new("Sel")
        p.add_import(src_path)
        imp = p._dict["profile"]["imports"][0]
        imp.pop("include-all", None)
        imp["include-controls"] = include
        if exclude:
            imp["exclude-controls"] = exclude
        p.set_merge(as_is=True)   # triggers tree rebuild with the edited directives
        return p

    def test_include_specific(self, src_path):
        p = self._with_include(src_path, [{"with-ids": ["ac-1"]}])
        assert {c["id"] for c in p.get_control_list()} == {"ac-1"}

    def test_with_child_controls_yes(self, src_path):
        p = self._with_include(src_path, [{"with-ids": ["ac-1"], "with-child-controls": "yes"}])
        assert {c["id"] for c in p.get_control_list()} == {"ac-1", "ac-1.1"}

    def test_matching_glob(self, src_path):
        p = self._with_include(src_path, [{"matching": [{"pattern": "au-*"}]}])
        assert {c["id"] for c in p.get_control_list()} == {"au-1", "au-2"}

    def test_exclude(self, src_path):
        p = self._with_include(src_path, [{"matching": [{"pattern": "au-*"}]}],
                               exclude=[{"with-ids": ["au-2"]}])
        assert {c["id"] for c in p.get_control_list()} == {"au-1"}

    def test_empty_groups_pruned(self, src_path):
        p = self._with_include(src_path, [{"matching": [{"pattern": "au-*"}]}])
        assert p.get_group_by_id("ac") is None
        assert p.get_group_by_id("au") is not None


# ===========================================================================
# combine / duplicates
# ===========================================================================
class TestDuplicates:

    def _two(self, tmp_path, combine):
        a = _write(tmp_path, "a.json", _source_catalog())
        b = _write(tmp_path, "b.json", _source_catalog())
        p = Profile.new("Dup")
        p.add_import(a, include_all=True)
        p.add_import(b, include_all=True)
        p.set_merge(as_is=True, combine=combine)
        return p

    def test_keep_tracked_in_tree(self, tmp_path):
        p = self._two(tmp_path, "keep")
        # duplicates recorded at tree-build time (before resolve)
        assert "ac-1" in p.duplicates["controls"]
        assert p.duplicates["controls"]["ac-1"][0]["new_id"].startswith("ac-1__")
        assert "ac" in p.duplicates["groups"]

    def test_keep_renamed_control_resolves_with_internal_ids(self, tmp_path):
        p = self._two(tmp_path, "keep")
        new_id = p.duplicates["controls"]["ac-1"][0]["new_id"]
        p.resolve()
        assert p.catalog.is_valid
        renamed = p.get_control_by_id(new_id)
        assert renamed is not None
        # internal ids were suffixed at resolve, and the insert follows the rename
        assert renamed["params"][0]["id"].startswith("ac-1_prm_1__")
        assert renamed["params"][0]["id"] in renamed["parts"][0]["prose"]

    def test_use_first_drops(self, tmp_path):
        p = self._two(tmp_path, "use-first")
        p.resolve()
        assert len(p.catalog) == 5
        assert p.duplicates["controls"]["ac-1"][0].get("dropped") is True


# ===========================================================================
# modes & blocking
# ===========================================================================
class TestModesAndBlocking:

    def test_custom_falls_back_to_asis(self, src_path):
        p = Profile.new("Custom")
        p.set_metadata({"title": "Custom"})
        p.add_import(src_path, include_all=True)
        p.set_merge(custom={"groups": [{"id": "x", "title": "X"}]})
        assert p.resolve() == ResolutionStatus.RESOLVED
        assert p.get_group_by_id("ac") is not None

    def test_unresolved_import_blocks(self, tmp_path):
        p = Profile.new("Bad")
        p.add_import(os.path.join(str(tmp_path), "nope.json"), include_all=True)
        assert p.resolve() == ResolutionStatus.BLOCKED


# ===========================================================================
# manual duplicate resolution
# ===========================================================================
class TestResolveDuplicate:

    def _dup(self, tmp_path):
        a = _write(tmp_path, "a.json", _source_catalog())
        b = _write(tmp_path, "b.json", _source_catalog())
        p = Profile.new("Dup")
        p.add_import(a, include_all=True)
        p.add_import(b, include_all=True)
        p.set_merge(as_is=True, combine="keep")
        p.resolve()
        return p

    def test_keep_original(self, tmp_path):
        p = self._dup(tmp_path)
        renamed = p.duplicates["controls"]["ac-1"][0]["new_id"]
        survived = p.resolve_duplicate("ac-1")
        assert survived["id"] == "ac-1"
        assert p.get_control_by_id(renamed) is None
        assert "ac-1" not in p.duplicates["controls"]

    def test_keep_variant(self, tmp_path):
        p = self._dup(tmp_path)
        renamed = p.duplicates["controls"]["ac-1"][0]["new_id"]
        survived = p.resolve_duplicate("ac-1", keep=renamed)
        assert survived["id"] == renamed
        assert p.get_control_by_id("ac-1") is None

    def test_replacement(self, tmp_path):
        p = self._dup(tmp_path)
        res = p.resolve_duplicate("ac-1", replacement={"id": "ac-1", "title": "MERGED"})
        assert res["title"] == "MERGED"
        ids = [c["id"] for c in p.get_control_list()]
        assert ids.count("ac-1") == 1 and not any(i.startswith("ac-1__") for i in ids)

    def test_relocate(self, tmp_path):
        p = self._dup(tmp_path)
        p.resolve_duplicate("ac-2", parent_id="au")
        assert p.catalog._find_parent_and_obj("ac-2")[0].get("id") == "au"

    def test_bad_keep(self, tmp_path):
        p = self._dup(tmp_path)
        assert p.resolve_duplicate("ac-1", keep="nope") is None

    def test_gated_before_resolve(self, src_path):
        p = _baseline(src_path)  # not resolved
        assert p.resolve_duplicate("ac-1") is None

    def test_resolve_duplicate_group(self, tmp_path):
        p = self._dup(tmp_path)
        renamed = p.duplicates["groups"]["ac"][0]["new_id"]
        survived = p.resolve_duplicate_group("ac")
        assert survived["id"] == "ac"
        assert p.get_group_by_id(renamed) is None


# ===========================================================================
# Multi-import: controls must not be lost when imports mix root controls & groups
# ===========================================================================
class TestMultiImport:

    def _cat(self, tmp_path, name, uuid, groups=None, root_controls=None, title="C"):
        doc = {"catalog": {"uuid": uuid,
               "metadata": {"title": title, "last-modified": "2026-01-01T00:00:00Z",
                            "version": "1", "oscal-version": "1.1.3"}}}
        if groups:
            doc["catalog"]["groups"] = [{"id": g, "title": g.upper(),
                                         "controls": [{"id": c, "title": c} for c in cs]}
                                        for g, cs in groups]
        if root_controls:
            doc["catalog"]["controls"] = [{"id": c, "title": c} for c in root_controls]
        path = os.path.join(str(tmp_path), name)
        with open(path, "w") as fh:
            json.dump(doc, fh)
        return path

    def test_root_controls_wrapped_when_groups_present(self, tmp_path):
        a = self._cat(tmp_path, "a.json", "33333333-3333-4333-8333-333333333333",
                      root_controls=["x1", "x2"])
        b = self._cat(tmp_path, "b.json", "44444444-4444-4444-8444-444444444444",
                      groups=[("g", ["y1", "y2"])])
        p = Profile.new("Multi")
        p.add_import(a, include_all=True)
        p.add_import(b, include_all=True)
        p.set_merge(as_is=True)
        # Root controls are wrapped into a synthetic "ROOT CONTROLS" group, inserted
        # first; the tree top is now all groups (no controls/groups mixing).
        top = p.controls_tree
        assert all(n["group"] for n in top)
        assert top[0]["title"] == "ROOT CONTROLS"
        assert {c["id"] for c in top[0]["children"]} == {"x1", "x2"}
        assert top[1]["id"] == "g"

        p.resolve()
        assert p.catalog.is_valid   # no root mixing -> valid
        assert {c["id"] for c in p.get_control_list()} == {"x1", "x2", "y1", "y2"}
        # the wrapper group carries the specified props
        wrapper = p.catalog._dict["catalog"]["groups"][0]
        assert wrapper["title"] == "ROOT CONTROLS"
        props = {pr["name"]: pr["value"] for pr in wrapper.get("props", [])}
        assert props.get("sort-id") == "0" and props.get("label") == "/"

    def test_no_wrapper_when_all_grouped(self, tmp_path):
        a = self._cat(tmp_path, "a.json", "77777777-7777-4777-8777-777777777777",
                      groups=[("ac", ["ac-1"])])
        b = self._cat(tmp_path, "b.json", "88888888-8888-4888-8888-888888888888",
                      groups=[("au", ["au-1"])])
        p = Profile.new("Multi")
        p.add_import(a, include_all=True)
        p.add_import(b, include_all=True)
        p.set_merge(as_is=True)
        assert all(not n.get("title") == "ROOT CONTROLS" for n in p.controls_tree)

    def test_flat_no_wrapper(self, tmp_path):
        a = self._cat(tmp_path, "a.json", "aaaaaaaa-7777-4777-8777-777777777777",
                      root_controls=["x1"])
        b = self._cat(tmp_path, "b.json", "bbbbbbbb-8888-4888-8888-888888888888",
                      groups=[("g", ["y1"])])
        p = Profile.new("Multi")
        p.add_import(a, include_all=True)
        p.add_import(b, include_all=True)
        p.set_merge(flat=True)
        p.resolve()
        # flat -> everything at root as controls, no groups, no wrapper
        assert "groups" not in p.catalog._dict["catalog"]
        assert {c["id"] for c in p.get_control_list()} == {"x1", "y1"}

    def test_two_distinct_catalogs_all_controls_present(self, tmp_path):
        a = self._cat(tmp_path, "a.json", "55555555-5555-4555-8555-555555555555",
                      groups=[("ac", ["ac-1", "ac-2"])])
        b = self._cat(tmp_path, "b.json", "66666666-6666-4666-8666-666666666666",
                      groups=[("au", ["au-1", "au-2"])])
        p = Profile.new("Multi")
        p.add_import(a, include_all=True)
        p.add_import(b, include_all=True)
        p.set_merge(as_is=True)
        p.resolve()
        assert {c["id"] for c in p.get_control_list()} == {"ac-1", "ac-2", "au-1", "au-2"}
        assert p.get_group_by_id("ac") is not None
        assert p.get_group_by_id("au") is not None


# ===========================================================================
# Combine semantics: use-first merges, keep renames (controls AND groups)
# ===========================================================================
class TestCombineSemantics:

    def _cat(self, tmp_path, name, uuid, groups):
        doc = {"catalog": {"uuid": uuid,
               "metadata": {"title": name, "last-modified": "2026-01-01T00:00:00Z",
                            "version": "1", "oscal-version": "1.1.3"},
               "groups": [{"id": g, "title": g.upper(),
                           "controls": ctrls} for g, ctrls in groups]}}
        path = os.path.join(str(tmp_path), name)
        with open(path, "w") as fh:
            json.dump(doc, fh)
        return path

    def _ids(self, prof):
        def allc(nodes):
            out = []
            for n in nodes:
                if not n["group"]:
                    out.append(n["id"])
                out += allc(n["children"])
            return out
        return allc(prof.controls_tree)

    def _two(self, tmp_path, combine):
        # both catalogs have family group 'ac'; ac-2 overlaps; ac-2.1 is a NEW
        # enhancement of the (duplicated) ac-2 introduced by the second import.
        a = self._cat(tmp_path, "a.json", "11111111-1111-4111-8111-111111111111",
                      [("ac", [{"id": "ac-1", "title": "ac-1"},
                               {"id": "ac-2", "title": "ac-2"}])])
        b = self._cat(tmp_path, "b.json", "22222222-2222-4222-8222-222222222222",
                      [("ac", [{"id": "ac-2", "title": "ac-2",
                                "controls": [{"id": "ac-2.1", "title": "ac-2.1"}]},
                               {"id": "ac-3", "title": "ac-3"}])])
        p = Profile.new("C")
        p.add_import(a, include_all=True)
        p.add_import(b, include_all=True)
        p.set_merge(as_is=True, combine=combine)
        return p

    def test_use_first_merges_groups(self, tmp_path):
        p = self._two(tmp_path, "use-first")
        # single merged 'ac' group, no rename
        assert [n["id"] for n in p.controls_tree] == ["ac"]
        assert not p.duplicates["groups"]

    def test_use_first_keeps_new_enhancement_of_duplicate_parent(self, tmp_path):
        p = self._two(tmp_path, "use-first")
        ids = set(self._ids(p))
        # ac-2 (duplicate) dropped-as-first-wins, but its NEW child ac-2.1 is kept
        assert {"ac-1", "ac-2", "ac-3", "ac-2.1"} == ids
        # ac-2.1 nested under the kept ac-2
        ac = p.controls_tree[0]
        ac2 = next(c for c in ac["children"] if c["id"] == "ac-2")
        assert any(ch["id"] == "ac-2.1" for ch in ac2["children"])

    def test_use_first_drops_true_duplicate(self, tmp_path):
        p = self._two(tmp_path, "use-first")
        assert p.duplicates["controls"].get("ac-2", [{}])[0].get("dropped") is True

    def test_keep_renames_groups_and_controls(self, tmp_path):
        p = self._two(tmp_path, "keep")
        top = [n["id"] for n in p.controls_tree]
        assert top[0] == "ac" and top[1].startswith("ac__")     # duplicate group renamed
        assert "ac" in p.duplicates["groups"]
        assert "ac-2" in p.duplicates["controls"]               # duplicate control renamed
        ids = set(self._ids(p))
        assert "ac-1" in ids and "ac-3" in ids
        assert any(i.startswith("ac-2__") for i in ids)


# ===========================================================================
# Defensive root-UUID-collision handling
# ===========================================================================
class TestUuidCollision:

    def _cat(self, tmp_path, name, uuid, ctrls, version, lm="2026-02-27T03:29:33Z",
             title="Shared"):
        doc = {"catalog": {"uuid": uuid,
               "metadata": {"title": title, "last-modified": lm, "version": version,
                            "oscal-version": "1.1.3"},
               "groups": [{"id": "g", "title": "G",
                           "controls": [{"id": c, "title": c} for c in ctrls]}]}}
        path = os.path.join(str(tmp_path), name)
        with open(path, "w") as fh:
            json.dump(doc, fh)
        return path

    def test_collision_reassigned_and_all_controls_kept(self, tmp_path, caplog):
        U = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        # same uuid + last-modified, DIFFERENT version -> genuine collision
        a = self._cat(tmp_path, "a.json", U, ["x1", "x2"], version="1.0.0")
        b = self._cat(tmp_path, "b.json", U, ["y1", "y2"], version="2.0.0")
        p = Profile.new("Coll")
        p.add_import(a, include_all=True)
        p.add_import(b, include_all=True)
        p.set_merge(as_is=True, combine="use-first")
        objs = [e.get("object").uuid for e in p.import_list if e.get("object")]
        assert objs[0] != objs[1]        # subsequent doc reassigned a new uuid

        def allc(nodes):
            out = []
            for n in nodes:
                if not n["group"]:
                    out.append(n["id"])
                out += allc(n["children"])
            return out
        assert set(allc(p.controls_tree)) == {"x1", "x2", "y1", "y2"}

    def test_identical_documents_dedup_to_one_instance(self, tmp_path):
        U = "cccccccc-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        a = self._cat(tmp_path, "a.json", U, ["x1"], version="1.0.0")
        b = self._cat(tmp_path, "b.json", U, ["x1"], version="1.0.0")  # identical signature
        p = Profile.new("Dup")
        p.add_import(a, include_all=True)
        p.add_import(b, include_all=True)
        p.set_merge(as_is=True)
        # same identity + signature -> reused, both imports resolve to one instance
        assert p.import_list[0].get("object") is p.import_list[1].get("object")


# ===========================================================================
# dump_catalog / dumps_catalog — pass-throughs to the resolved catalog
# ===========================================================================
class TestDumpCatalog:

    def test_dumps_catalog_json_roundtrips(self, resolved):
        s = resolved.dumps_catalog(format="json")
        assert s and isinstance(s, str)
        reloaded = Catalog.loads(s)
        assert {c["id"] for c in reloaded.get_control_list()} == \
            {c["id"] for c in resolved.get_control_list()}

    def test_dumps_catalog_matches_catalog_dumps(self, resolved):
        assert resolved.dumps_catalog(format="json") == \
            resolved.catalog.dumps(format="json")

    def test_dump_catalog_writes_file(self, resolved, tmp_path):
        out = os.path.join(str(tmp_path), "resolved.json")
        assert resolved.dump_catalog(filename=out, format="json") is True
        assert os.path.exists(out)
        reloaded = Catalog.load(out)
        assert len(reloaded.get_control_list()) == len(resolved.get_control_list())

    def test_dumps_catalog_unresolved_returns_empty(self, prof):
        assert prof.catalog is None
        assert prof.dumps_catalog(format="json") == ""

    def test_dump_catalog_unresolved_returns_false(self, prof, tmp_path):
        out = os.path.join(str(tmp_path), "nope.json")
        assert prof.dump_catalog(filename=out, format="json") is False
        assert not os.path.exists(out)


# ===========================================================================
# resolve_and_dump_catalog / resolve_and_dumps_catalog — one-shot convenience
# ===========================================================================
class TestResolveAndDump:

    def test_resolve_and_dumps_from_unresolved(self, prof):
        assert prof.catalog is None
        s = prof.resolve_and_dumps_catalog(format="json")
        assert s and Catalog.loads(s).get_control_by_id("ac-1") is not None
        assert prof.resolution_status == ResolutionStatus.RESOLVED   # it resolved

    def test_resolve_and_dumps_equals_dump_of_resolved(self, prof):
        # resolve_and_dumps == serializing the catalog it just produced (each resolve
        # assigns a fresh catalog uuid, so this compares the same resolved instance).
        one_shot = prof.resolve_and_dumps_catalog(format="json")
        assert one_shot == prof.dumps_catalog(format="json")

    def test_resolve_and_dump_writes_file(self, prof, tmp_path):
        out = os.path.join(str(tmp_path), "resolved.json")
        assert prof.resolve_and_dump_catalog(filename=out, format="json") is True
        assert os.path.exists(out)
        assert len(Catalog.load(out).get_control_list()) == len(prof.get_control_list())

    def test_blocked_profile_returns_falsy(self, tmp_path):
        p = Profile.new("Bad")
        p.add_import(os.path.join(str(tmp_path), "does-not-exist.json"), include_all=True)
        assert p.resolve_and_dumps_catalog(format="json") == ""
        assert p.resolve_and_dump_catalog(
            filename=os.path.join(str(tmp_path), "x.json"), format="json") is False
        assert p.resolution_status == ResolutionStatus.BLOCKED


# ===========================================================================
# Content mutation invalidates a resolved catalog (resets to UNRESOLVED)
# ===========================================================================
class TestResolutionInvalidation:

    def test_set_merge_invalidates(self, resolved):
        assert resolved.resolution_status == ResolutionStatus.RESOLVED
        resolved.set_merge(as_is=True, combine="use-first")
        assert resolved.resolution_status == ResolutionStatus.UNRESOLVED
        assert resolved.catalog is None

    def test_set_metadata_invalidates(self, resolved):
        resolved.set_metadata({"title": "Edited Title"})
        assert resolved.resolution_status == ResolutionStatus.UNRESOLVED
        assert resolved.catalog is None

    def test_add_import_invalidates(self, resolved, tmp_path):
        extra = _write(tmp_path, "extra.json",
                       _source_catalog(uuid="99999999-9999-4999-8999-999999999999"))
        resolved.add_import(extra, include_all=True)
        assert resolved.resolution_status == ResolutionStatus.UNRESOLVED
        assert resolved.catalog is None

    def test_put_invalidates(self, resolved):
        resolved.put("metadata/version", "9.9.9")
        assert resolved.resolution_status == ResolutionStatus.UNRESOLVED
        assert resolved.catalog is None

    def test_reresolve_after_edit_reflects_change(self, resolved):
        resolved.set_metadata({"title": "New Title"})
        resolved.resolve()
        assert resolved.catalog._dict["catalog"]["metadata"]["title"] == "New Title"

    def test_editing_catalog_directly_keeps_profile_resolved(self, resolved):
        # A Catalog-level edit (as manual duplicate resolution does) must NOT flip the
        # profile back to unresolved — that hook is Catalog's no-op, not the Profile's.
        resolved.catalog.set_metadata({"version": "2"})
        assert resolved.resolution_status == ResolutionStatus.RESOLVED
        assert resolved.catalog is not None

    def test_resolve_duplicate_keeps_resolved(self, tmp_path):
        a = _write(tmp_path, "a.json", _source_catalog())
        b = _write(tmp_path, "b.json", _source_catalog())
        p = Profile.new("Dup")
        p.add_import(a, include_all=True)
        p.add_import(b, include_all=True)
        p.set_merge(as_is=True, combine="keep")
        p.resolve()
        assert p.resolution_status == ResolutionStatus.RESOLVED
        p.resolve_duplicate("ac-1")                       # edits .catalog in place
        assert p.resolution_status == ResolutionStatus.RESOLVED
        assert p.catalog is not None
