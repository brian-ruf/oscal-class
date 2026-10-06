"""
Negative tests for OSCAL content loading and validation.

Covers:
  - File not found
  - Unsupported / unrecognized format (not XML, JSON, or YAML)
  - Non-UTF-8 encoded file
  - Malformed XML / JSON / YAML (well-formed check fails)
  - Well-formed but OSCAL schema-invalid content (each format)
"""
import json
import os
import tempfile

import pytest

from oscal import OSCAL, Catalog, Profile
from oscal.oscal_content import _constraint_conditions_met

# ---------------------------------------------------------------------------
# Fixtures — schema-valid structure but missing required fields
#
# These documents have the correct OSCAL root element and oscal-version so
# they pass model/version detection, but are missing required fields (e.g.
# catalog.uuid and metadata.last-modified) so schema validation fails.
# All use OSCAL v1.1.3, which is present in the test support database.
# ---------------------------------------------------------------------------

_XML_SCHEMA_INVALID = """\
<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="http://csrc.nist.gov/ns/oscal/1.0">
  <metadata>
    <title>Schema Invalid Catalog</title>
    <version>1.0</version>
    <oscal-version>1.1.3</oscal-version>
  </metadata>
</catalog>
"""

# Missing required catalog.uuid and metadata.last-modified
_JSON_SCHEMA_INVALID = """\
{
  "catalog": {
    "metadata": {
      "title": "Schema Invalid Catalog",
      "version": "1.0",
      "oscal-version": "1.1.3"
    }
  }
}
"""

_YAML_SCHEMA_INVALID = """\
catalog:
  metadata:
    title: Schema Invalid Catalog
    version: "1.0"
    oscal-version: "1.1.3"
"""


# ===========================================================================
# File not found
# ===========================================================================
class TestFileNotFound:
    def test_load_missing_file_returns_object(self):
        """load() on a nonexistent path must not raise — it returns an OSCAL instance."""
        obj = OSCAL.load("/nonexistent/path/missing.json")
        assert obj is not None

    def test_load_missing_file_is_not_valid(self):
        """load() on a nonexistent path produces is_valid=False."""
        obj = OSCAL.load("/nonexistent/path/missing.json")
        assert obj.is_valid is False

    def test_load_missing_file_has_no_model(self):
        """load() on a nonexistent path produces an empty model string."""
        obj = OSCAL.load("/nonexistent/path/missing.json")
        assert obj.model == ""


# ===========================================================================
# Unsupported / unrecognized format
# ===========================================================================
class TestUnsupportedFormat:
    def test_loads_csv_string_is_not_valid(self):
        """Content that is not XML, JSON, or YAML returns is_valid=False."""
        obj = OSCAL.loads("id,title,description\n1,Test,Row one\n2,Other,Row two\n")
        assert obj is not None
        assert obj.is_valid is False
        assert obj.model == ""

    def test_loads_empty_string_is_not_valid(self):
        """An empty string returns is_valid=False."""
        obj = OSCAL.loads("")
        assert obj is not None
        assert obj.is_valid is False

    def test_load_binary_file_is_not_valid(self):
        """A file containing arbitrary binary bytes must not raise and must return is_valid=False."""
        with tempfile.NamedTemporaryFile(suffix=".dat", delete=False) as fh:
            fh.write(b"\xff\xfe\x00\x01binary\xfe\xff" * 16)
            path = fh.name
        try:
            obj = OSCAL.load(path)
            assert obj is not None
            assert obj.is_valid is False
            assert obj.model == ""
        finally:
            os.unlink(path)

    def test_load_latin1_encoded_file_is_not_valid(self):
        """A file written in Latin-1 (not UTF-8) must not raise and must return is_valid=False."""
        latin1_bytes = "<?xml version='1.0'?><nota>\xe9\xe0\xfc</nota>".encode("latin-1")
        with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as fh:
            fh.write(latin1_bytes)
            path = fh.name
        try:
            obj = OSCAL.load(path)
            assert obj is not None
            assert obj.is_valid is False
        finally:
            os.unlink(path)


# ===========================================================================
# Malformed content — well-formed check fails before OSCAL validation
# ===========================================================================
class TestMalformedContent:
    def test_malformed_xml_does_not_raise(self):
        """Syntactically broken XML must not raise an exception."""
        OSCAL.loads("<catalog><metadata><title>Unclosed</metadata>")

    def test_malformed_xml_is_not_valid(self):
        """Syntactically broken XML returns is_valid=False."""
        obj = OSCAL.loads("<catalog><metadata><title>Unclosed</metadata>")
        assert obj.is_valid is False
        assert obj.model == ""

    def test_malformed_json_does_not_raise(self):
        """Syntactically broken JSON must not raise an exception."""
        OSCAL.loads('{"catalog": {"metadata": {"title": "Bad" missing_comma}}}')

    def test_malformed_json_is_not_valid(self):
        """Syntactically broken JSON returns is_valid=False."""
        obj = OSCAL.loads('{"catalog": {"metadata": {"title": "Bad" missing_comma}}}')
        assert obj.is_valid is False
        assert obj.model == ""

    def test_malformed_yaml_does_not_raise(self):
        """YAML with a parse error must not raise an exception."""
        OSCAL.loads("catalog:\n  metadata:\n    title: [unclosed bracket\n")

    def test_malformed_yaml_is_not_valid(self):
        """YAML with a parse error returns is_valid=False."""
        obj = OSCAL.loads("catalog:\n  metadata:\n    title: [unclosed bracket\n")
        assert obj.is_valid is False
        assert obj.model == ""


# ===========================================================================
# Well-formed and OSCAL-shaped, but schema-invalid
# ===========================================================================
class TestSchemaInvalidContent:
    """Content that passes format detection and model/version identification
    but fails OSCAL schema validation (e.g., missing required fields)."""

    def test_xml_schema_invalid_does_not_raise(self):
        """Well-formed OSCAL-shaped XML that is schema-invalid must not raise."""
        OSCAL.loads(_XML_SCHEMA_INVALID)

    def test_xml_schema_invalid_model_is_identified(self):
        """Even schema-invalid XML should identify its model before failing."""
        obj = OSCAL.loads(_XML_SCHEMA_INVALID)
        assert obj.model == "catalog"

    def test_xml_schema_invalid_is_not_valid(self):
        """Schema-invalid XML returns is_valid=False."""
        obj = OSCAL.loads(_XML_SCHEMA_INVALID)
        assert obj.is_valid is False

    def test_xml_schema_valid_flag_is_false(self):
        """Schema-invalid XML sets validation_status['structure'] to False."""
        obj = OSCAL.loads(_XML_SCHEMA_INVALID)
        assert obj.validation_status["structure"] is False

    def test_json_schema_invalid_does_not_raise(self):
        """Well-formed OSCAL-shaped JSON that is schema-invalid must not raise."""
        OSCAL.loads(_JSON_SCHEMA_INVALID)

    def test_json_schema_invalid_model_is_identified(self):
        """Even schema-invalid JSON should identify its model before failing."""
        obj = OSCAL.loads(_JSON_SCHEMA_INVALID)
        assert obj.model == "catalog"

    def test_json_schema_invalid_is_not_valid(self):
        """Schema-invalid JSON returns is_valid=False."""
        obj = OSCAL.loads(_JSON_SCHEMA_INVALID)
        assert obj.is_valid is False

    def test_json_schema_valid_flag_is_false(self):
        """Schema-invalid JSON sets validation_status['structure'] to False."""
        obj = OSCAL.loads(_JSON_SCHEMA_INVALID)
        assert obj.validation_status["structure"] is False

    def test_yaml_schema_invalid_does_not_raise(self):
        """Well-formed OSCAL-shaped YAML that is schema-invalid must not raise."""
        OSCAL.loads(_YAML_SCHEMA_INVALID)

    def test_yaml_schema_invalid_model_is_identified(self):
        """Even schema-invalid YAML should identify its model before failing."""
        obj = OSCAL.loads(_YAML_SCHEMA_INVALID)
        assert obj.model == "catalog"

    def test_yaml_schema_invalid_is_not_valid(self):
        """Schema-invalid YAML returns is_valid=False."""
        obj = OSCAL.loads(_YAML_SCHEMA_INVALID)
        assert obj.is_valid is False

    def test_yaml_schema_valid_flag_is_false(self):
        """Schema-invalid YAML sets validation_status['structure'] to False."""
        obj = OSCAL.loads(_YAML_SCHEMA_INVALID)
        assert obj.validation_status["structure"] is False


# ===========================================================================
# Choice directive — metaschema choice members are mutually exclusive
# ===========================================================================
class TestChoiceValidation:

    def test_validation_status_has_choice_key(self):
        p = Profile.new("Choice Test")
        p.validate()
        assert "choice" in p.validation_status

    def test_valid_choice_passes(self):
        p = Profile.new("Choice Test")
        p.set_merge(as_is=True)          # exactly one member -> valid
        p.validate()
        assert p.validation_status["choice"] is True
        assert p.is_valid

    def test_two_members_violate_choice(self):
        p = Profile.new("Choice Test")
        p._dict["profile"]["merge"] = {"flat": {}, "as-is": True}   # two members
        p.validate()
        assert p.validation_status["choice"] is False
        assert p.is_valid is False
        errs = [e for e in p.validation_errors if e["error-type"] == "choice"]
        assert errs
        assert errs[0]["location"] == "/profile/merge"
        assert set(errs[0]["field"]) == {"flat", "as-is"}

    def test_three_members_violate_choice(self):
        p = Profile.new("Choice Test")
        p._dict["profile"]["merge"] = {"flat": {}, "as-is": True, "custom": {}}
        p.validate()
        assert p.validation_status["choice"] is False

    def test_optional_choice_with_zero_members_ok(self):
        """A choice member set may be empty when the choice is optional — e.g. a
        param with neither 'values' nor 'select' must not be flagged."""
        c = Catalog.new("Choice Test")
        c.create_control("[root]", "ac-1", title="A", params=["ac-1_prm_1"])
        c.validate()
        assert c.validation_status["choice"] is True

    def test_single_member_choice_ok(self):
        p = Profile.new("Choice Test")
        p.set_merge(flat=True)
        p.validate()
        assert p.validation_status["choice"] is True


# ===========================================================================
# Choice cardinality — required/optional & bounded/unbounded driven by members
# ===========================================================================
class TestChoiceCardinality:

    def test_required_choice_missing_member_fails(self):
        """profile 'merge' is a required choice (flat|as-is|custom); none present -> error."""
        p = Profile.new("Card")
        p._dict["profile"]["merge"] = {"combine": {"method": "keep"}}  # no flat/as-is/custom
        p.validate()
        assert p.validation_status["choice"] is False
        assert p.is_valid is False
        errs = [e for e in p.validation_errors if e["error-type"] == "choice"]
        assert errs and errs[0]["location"] == "/profile/merge"
        assert errs[0]["expected"] == {"select-one-of": ["flat", "as-is", "custom"]}

    def test_required_choice_single_member_ok(self):
        p = Profile.new("Card")
        p.set_merge(custom={})
        p.validate()
        assert p.validation_status["choice"] is True

    def test_bounded_required_choice_rejects_two(self):
        p = Profile.new("Card")
        p._dict["profile"]["merge"] = {"as-is": True, "custom": {}}
        p.validate()
        assert p.validation_status["choice"] is False

    def test_optional_choice_empty_group_ok(self):
        """catalog group's (groups|controls) choice is optional -> empty group is valid."""
        c = Catalog.new("Card")
        c.create_control_group("[root]", "empty", title="Empty Group")
        c.validate()
        assert c.validation_status["choice"] is True
        assert c.is_valid

    def test_unbounded_choice_allows_many_members(self):
        """The (groups|controls) choice is unbounded — many controls is fine."""
        c = Catalog.new("Card")
        c.create_control_group("[root]", "g", title="G")
        c.create_control("g", "c-1", title="C1", statements=["S1."])
        c.create_control("g", "c-2", title="C2", statements=["S2."])
        c.validate()
        assert c.validation_status["choice"] is True
        assert c.is_valid

    def test_unbounded_choice_still_mutually_exclusive(self):
        """max-occurs=unbounded bounds items *within* a branch, not combining branches:
        a group holding BOTH groups and controls violates the (groups|controls) choice."""
        c = Catalog.new("Card")
        c._dict["catalog"]["groups"] = [{
            "id": "g", "title": "G",
            "groups": [{"id": "g-sub", "title": "Sub"}],
            "controls": [{"id": "c-1", "title": "C1"}],
        }]
        c.validate()
        assert c.validation_status["choice"] is False
        errs = [e for e in c.validation_errors if e["error-type"] == "choice"]
        assert any(set(e["field"]) == {"groups", "controls"} for e in errs)


# ===========================================================================
# Scoped allowed-values constraints — a constraint whose target predicate is
# translated into a `flag-in` / `flag-equals` condition must only apply where
# that flag matches. Regression: an unhandled `flag-in` condition was treated as
# always-satisfied ("fail-open"), so a constraint scoped to
# @type=('software','hardware','service') (allowing only `vendor-name`) fired on
# every inventory-item prop @name and produced false allowed-values errors — which
# marked an otherwise-valid SSP invalid and blocked import resolution.
# ===========================================================================
class TestConstraintConditionsMet:

    def test_flag_in_satisfied_when_flag_matches(self):
        cond = {"type": "flag-in", "flag": "type", "values": ["software", "hardware"]}
        assert _constraint_conditions_met({"conditions": [cond]}, {"type": "software"})

    def test_flag_in_not_satisfied_when_flag_differs(self):
        cond = {"type": "flag-in", "flag": "type", "values": ["software", "hardware"]}
        assert not _constraint_conditions_met({"conditions": [cond]}, {"type": "policy"})

    def test_flag_in_not_satisfied_when_flag_absent(self):
        # A prop has no `type` flag, so a @type-scoped constraint must not apply.
        cond = {"type": "flag-in", "flag": "type", "values": ["software", "hardware"]}
        assert not _constraint_conditions_met({"conditions": [cond]}, {"name": "asset-type"})

    def test_flag_equals_still_works(self):
        cond = {"type": "flag-equals", "flag": "type", "value": "software"}
        assert _constraint_conditions_met({"conditions": [cond]}, {"type": "software"})
        assert not _constraint_conditions_met({"conditions": [cond]}, {"type": "hardware"})

    def test_no_conditions_is_satisfied(self):
        assert _constraint_conditions_met({}, {"anything": "x"})


class TestScopedInventoryPropNames:
    """Prop names on components/inventory-items carry a general allowed-values plus a
    @type-scoped (`software`/`hardware`/`service`) `vendor-name` set. These targets are
    **L2-A** (a context-`@flag` gate over a native remainder), so the node is `valid` (L2)
    and the walk evaluates them with UNION semantics: the gate is resolved against the
    nearest enclosing object that owns `@type` (the component). A `software` component may
    therefore use `vendor-name` (via the type-gated set) *and* `asset-id` (via the general
    set) with no false positive, while a bad name — or `vendor-name` on a non-matching type
    — is correctly flagged at L2."""

    @staticmethod
    def _ssp_with_inventory_prop(name):
        return OSCAL.loads({
            "system-security-plan": {
                "uuid": "30000000-0000-4000-8000-000000000001",
                "metadata": {"title": "T", "last-modified": "2026-01-01T00:00:00Z",
                             "version": "1.0", "oscal-version": "1.1.3"},
                "system-implementation": {
                    "inventory-items": [
                        {"uuid": "40000000-0000-4000-8000-000000000001", "description": "d",
                         "props": [{"name": name, "value": "x"}]},
                    ],
                },
            }
        })

    @staticmethod
    def _ssp_with_component(ctype, name):
        return OSCAL.loads({
            "system-security-plan": {
                "uuid": "30000000-0000-4000-8000-000000000001",
                "metadata": {"title": "T", "last-modified": "2026-01-01T00:00:00Z",
                             "version": "1.0", "oscal-version": "1.1.3"},
                "system-implementation": {
                    "components": [
                        {"uuid": "10000000-0000-4000-8000-000000000003", "type": ctype,
                         "title": "C", "description": "d", "status": {"state": "operational"},
                         "props": [{"name": name, "value": "x"}]},
                    ],
                },
            }
        })

    @staticmethod
    def _av_errors(doc, loc_substr):
        return [e for e in doc.validation_errors
                if e["error-type"] == "allowed-values" and loc_substr in e["location"]]

    def test_legitimate_prop_name_not_flagged(self):
        # 'asset-type' is in the general inventory-item prop-name set -> L2 accepts it.
        doc = self._ssp_with_inventory_prop("asset-type")
        doc.validate()
        assert self._av_errors(doc, "inventory-items[0]/props[0]") == []

    def test_bogus_prop_name_flagged_at_l2(self):
        # The general set is now L2-enforced (L2-A made the node valid); a bad name fails.
        doc = self._ssp_with_inventory_prop("definitely-not-a-real-prop-name")
        doc.validate()
        assert self._av_errors(doc, "inventory-items[0]/props[0]")

    def test_component_vendor_name_allowed_for_software(self):
        # The crux: UNION + ancestor-resolved @type gate means a software component's
        # 'vendor-name' prop is NOT a false positive (the prior regression).
        doc = self._ssp_with_component("software", "vendor-name")
        doc.validate()
        assert self._av_errors(doc, "components[0]/props[0]") == []

    def test_component_general_name_allowed_for_software(self):
        doc = self._ssp_with_component("software", "asset-id")
        doc.validate()
        assert self._av_errors(doc, "components[0]/props[0]") == []

    def test_component_vendor_name_flagged_for_policy(self):
        # 'policy' is outside the type gate, so 'vendor-name' is not in the applicable union.
        doc = self._ssp_with_component("policy", "vendor-name")
        doc.validate()
        assert self._av_errors(doc, "components[0]/props[0]")

    def test_component_bogus_name_flagged_for_software(self):
        doc = self._ssp_with_component("software", "definitely-not-a-real-prop-name")
        doc.validate()
        assert self._av_errors(doc, "components[0]/props[0]")


# ===========================================================================
# Normalized validation errors — every error carries an `identifier` (uuid/id of
# the nearest enclosing identifiable object) alongside the JSON `location`.
# ===========================================================================
_SSP_UUID = "30000000-0000-4000-8000-000000000001"
_INV_UUID = "40000000-0000-4000-8000-000000000001"


# The bogus prop lives on an implemented-component (whose prop-name allowed-values is
# natively evaluable -> L2 / enforced by the automatic walk), not directly on the
# inventory-item (whose prop names are deferred to L3; see TestScopedInventoryPropNames).
# The implemented-component itself is not identifiable, so the nearest enclosing
# identifiable object remains the inventory-item uuid — the point of the identifier test.
def _ssp_with_inventory_prop_name(name):
    return OSCAL.loads({
        "system-security-plan": {
            "uuid": _SSP_UUID,
            "metadata": {"title": "T", "last-modified": "2026-01-01T00:00:00Z",
                         "version": "1.0", "oscal-version": "1.1.3"},
            "system-implementation": {
                "inventory-items": [
                    {"uuid": _INV_UUID, "description": "d",
                     "implemented-components": [
                         {"component-uuid": "50000000-0000-4000-8000-000000000001",
                          "props": [{"name": name, "value": "x"}]},
                     ]},
                ],
            },
        }
    })


class TestValidationErrorIdentifier:

    def test_error_has_identifier_of_nearest_item(self):
        # A prop has no id/uuid, so the error's identifier is the enclosing
        # inventory-item's uuid (the nearest identifiable ancestor).
        doc = _ssp_with_inventory_prop_name("definitely-not-a-real-prop-name")
        doc.validate()
        errs = [e for e in doc.validation_errors
                if e["error-type"] == "allowed-values" and "inventory-items" in e["location"]]
        assert errs
        assert errs[0]["identifier"] == _INV_UUID

    def test_error_core_shape_is_normalized(self):
        doc = _ssp_with_inventory_prop_name("definitely-not-a-real-prop-name")
        doc.validate()
        for e in doc.validation_errors:
            assert {"error-type", "location", "identifier", "field", "value"} <= set(e.keys())

    def test_identifier_falls_back_to_root_uuid(self):
        # A malformed metadata datetime -> invalid-type; metadata has no id/uuid, so the
        # nearest identifiable ancestor is the document root uuid.
        doc = OSCAL.loads({
            "system-security-plan": {
                "uuid": _SSP_UUID,
                "metadata": {"title": "T", "last-modified": "not-a-datetime",
                             "version": "1.0", "oscal-version": "1.1.3"},
                "system-implementation": {"components": []},
            }
        })
        doc.validate()
        dt_errs = [e for e in doc.validation_errors if e["error-type"] == "invalid-type"]
        assert dt_errs
        assert all(e["identifier"] == _SSP_UUID for e in dt_errs)


# ===========================================================================
# Import gating — non-blocking (allowed-values / invalid-type) errors do not stop
# import resolution; structural errors (missing-required / cardinality / choice) do.
# ===========================================================================
def _catalog_doc():
    return {"catalog": {
        "uuid": "10000000-0000-4000-8000-000000000001",
        "metadata": {"title": "Cat", "last-modified": "2026-01-01T00:00:00Z",
                     "version": "1.0", "oscal-version": "1.1.3"},
        "groups": [{"id": "ac", "title": "AC", "controls": [{"id": "ac-1", "title": "P"}]}],
    }}


def _ssp_importing(catalog_href, *, bogus_inventory=False, drop_required=False):
    root = {
        "uuid": _SSP_UUID,
        "metadata": {"title": "SSP", "last-modified": "2026-01-01T00:00:00Z",
                     "version": "1.0", "oscal-version": "1.1.3"},
        "import-profile": {"href": catalog_href},
        "system-characteristics": {
            "system-ids": [{"id": "s"}], "system-name": "S", "description": "d",
            "system-information": {"information-types": [{"title": "IT", "description": "d"}]},
            "security-sensitivity-level": "low",
            "security-impact-level": {"security-objective-confidentiality": "low",
                                      "security-objective-integrity": "low",
                                      "security-objective-availability": "low"},
            "status": {"state": "operational"},
            "authorization-boundary": {"description": "b"}},
        "system-implementation": {
            "users": [{"uuid": "60000000-0000-4000-8000-000000000001", "role-ids": ["admin"]}],
            "components": [{"uuid": "70000000-0000-4000-8000-000000000001", "type": "this-system",
                            "title": "This System", "description": "d",
                            "status": {"state": "operational"}}]},
        "control-implementation": {"description": "ci", "implemented-requirements": [
            {"uuid": "80000000-0000-4000-8000-000000000001", "control-id": "ac-1"}]},
    }
    if bogus_inventory:
        # Bogus name on an implemented-component prop (L2 / enforced) so it produces a
        # genuine non-blocking allowed-values error; a direct inventory-item prop name is
        # deferred to L3 and would not fail L2 validity.
        root["system-implementation"]["inventory-items"] = [
            {"uuid": _INV_UUID, "description": "d",
             "implemented-components": [
                 {"component-uuid": "50000000-0000-4000-8000-000000000001",
                  "props": [{"name": "definitely-not-a-real-prop-name", "value": "x"}]}]}]
    if drop_required:
        del root["system-characteristics"]   # required -> missing-required (blocking)
    return {"system-security-plan": root}


class TestImportBlockingErrorsProperty:

    def test_partitions_by_allow_list(self):
        doc = OSCAL.loads(_catalog_doc())  # any doc; we set errors directly
        doc.validation_errors = [
            {"error-type": "allowed-values", "location": "/x", "identifier": None,
             "field": "@name", "value": "z"},
            {"error-type": "missing-required", "location": "/y", "identifier": None,
             "field": "title", "value": None},
        ]
        blocking = doc.import_blocking_errors
        assert [e["error-type"] for e in blocking] == ["missing-required"]

    def test_only_nonblocking_yields_no_blocking(self):
        doc = OSCAL.loads(_catalog_doc())
        doc.validation_errors = [
            {"error-type": "allowed-values", "location": "/x", "identifier": None,
             "field": "@name", "value": "z"},
            {"error-type": "invalid-type", "location": "/y", "identifier": None,
             "field": "d", "value": "bad"},
        ]
        assert doc.import_blocking_errors == []

    def test_allow_list_is_tunable(self):
        doc = OSCAL.loads(_catalog_doc())
        doc.validation_errors = [
            {"error-type": "allowed-values", "location": "/x", "identifier": None,
             "field": "@name", "value": "z"}]
        # Narrow the allow-list so allowed-values now blocks.
        doc.import_nonblocking_error_types = frozenset({"invalid-type"})
        assert [e["error-type"] for e in doc.import_blocking_errors] == ["allowed-values"]


class TestImportGating:

    def _write(self, d, ssp_doc):
        with open(os.path.join(d, "catalog.json"), "w") as fh:
            json.dump(_catalog_doc(), fh)
        path = os.path.join(d, "ssp.json")
        with open(path, "w") as fh:
            json.dump(ssp_doc, fh)
        return path

    def test_valid_ssp_resolves_import(self):
        with tempfile.TemporaryDirectory() as d:
            doc = OSCAL.load(self._write(d, _ssp_importing("catalog.json")))
            assert doc.is_valid
            assert len(doc.import_list) == 1

    def test_nonblocking_error_still_resolves_import(self):
        with tempfile.TemporaryDirectory() as d:
            doc = OSCAL.load(self._write(d, _ssp_importing("catalog.json", bogus_inventory=True)))
            assert not doc.is_valid                     # allowed-values failure
            assert doc.import_blocking_errors == []     # but nothing blocking
            assert len(doc.import_list) == 1            # import still resolved
            assert not doc.imports_resolved             # not falsely marked valid/resolved

    def test_blocking_error_prevents_import(self):
        with tempfile.TemporaryDirectory() as d:
            doc = OSCAL.load(self._write(d, _ssp_importing("catalog.json", drop_required=True)))
            assert not doc.is_valid
            assert doc.import_blocking_errors          # missing-required blocks
            assert doc.import_list == []               # not auto-resolved


# ===========================================================================
# id/uuid indexes — built during the single validation walk (not a second pass).
# _id_index / _uuid_index map each value -> [{"value", "key", "path"}, ...]; a value
# with >1 record is a duplicate (foundation for the future uniqueness check).
# ===========================================================================
class TestIdentifierIndexes:

    @staticmethod
    def _cdef(components=None, capabilities=None, extra_meta=None):
        meta = {"title": "c", "last-modified": "2026-01-01T00:00:00Z",
                "version": "1.0", "oscal-version": "1.1.3"}
        if extra_meta:
            meta.update(extra_meta)
        root = {"uuid": "10000000-0000-4000-8000-000000000001", "metadata": meta}
        if components:
            root["components"] = components
        if capabilities:
            root["capabilities"] = capabilities
        return OSCAL.loads({"component-definition": root})

    def test_indexes_exist_after_init(self):
        cd = self._cdef()
        assert isinstance(cd._id_index, dict)
        assert isinstance(cd._uuid_index, dict)

    def test_uuid_indexed_with_value_key_and_path(self):
        cd = self._cdef(components=[
            {"uuid": "30000000-0000-4000-8000-000000000001", "type": "software",
             "title": "App", "description": "d"}])
        cd.validate()
        recs = cd._uuid_index["30000000-0000-4000-8000-000000000001"]
        assert recs == [{"value": "30000000-0000-4000-8000-000000000001",
                         "key": "components",
                         "path": "/component-definition/components[0]"}]

    def test_root_uuid_keyed_by_model(self):
        cd = self._cdef()
        cd.validate()
        rec = cd._uuid_index["10000000-0000-4000-8000-000000000001"][0]
        assert rec["key"] == "component-definition"
        assert rec["path"] == "/component-definition"

    def test_id_index_separate_from_uuid_index(self):
        cd = self._cdef(extra_meta={"roles": [{"id": "admin", "title": "Admin"}]})
        cd.validate()
        assert "admin" in cd._id_index
        assert cd._id_index["admin"][0]["key"] == "roles"
        assert "admin" not in cd._uuid_index

    def test_nested_parent_key_is_containing_collection(self):
        cd = self._cdef(components=[
            {"uuid": "30000000-0000-4000-8000-000000000001", "type": "software",
             "title": "App", "description": "d",
             "control-implementations": [
                 {"uuid": "40000000-0000-4000-8000-000000000001", "source": "#s",
                  "description": "d",
                  "implemented-requirements": [
                      {"uuid": "50000000-0000-4000-8000-000000000001",
                       "control-id": "ac-1", "description": "d"}]}]}])
        cd.validate()
        assert cd._uuid_index["40000000-0000-4000-8000-000000000001"][0]["key"] == \
            "control-implementations"
        assert cd._uuid_index["50000000-0000-4000-8000-000000000001"][0]["key"] == \
            "implemented-requirements"

    def test_duplicate_uuid_recorded_as_multiple_records(self):
        dup = "30000000-0000-4000-8000-000000000001"
        cd = self._cdef(components=[
            {"uuid": dup, "type": "software", "title": "A", "description": "d"},
            {"uuid": dup, "type": "software", "title": "B", "description": "d"}])
        cd.validate()
        recs = cd._uuid_index[dup]
        assert len(recs) == 2
        assert [r["path"] for r in recs] == ["/component-definition/components[0]",
                                             "/component-definition/components[1]"]

    def test_compound_reference_flags_not_indexed(self):
        # control-id / component-uuid are references, not defining identifiers.
        cd = self._cdef(components=[
            {"uuid": "30000000-0000-4000-8000-000000000001", "type": "software",
             "title": "App", "description": "d",
             "control-implementations": [
                 {"uuid": "40000000-0000-4000-8000-000000000001", "source": "#s",
                  "description": "d",
                  "implemented-requirements": [
                      {"uuid": "50000000-0000-4000-8000-000000000001",
                       "control-id": "ac-1", "description": "d"}]}]}])
        cd.validate()
        # "ac-1" is a control-id reference -> must not appear in the id index.
        assert "ac-1" not in cd._id_index

    def test_indexes_reset_on_each_validate(self):
        cd = self._cdef(components=[
            {"uuid": "30000000-0000-4000-8000-000000000001", "type": "software",
             "title": "App", "description": "d"}])
        cd.validate()
        first = dict(cd._uuid_index)
        cd.validate()
        assert cd._uuid_index == first   # rebuilt identically, not accumulated

    def test_catalog_top_level_controls_indexed(self):
        meta = {"title": "C", "last-modified": "2026-01-01T00:00:00Z",
                "version": "1.0", "oscal-version": "1.1.3"}
        cat = OSCAL.loads({"catalog": {
            "uuid": "10000000-0000-4000-8000-000000000001", "metadata": meta,
            "controls": [{"id": "ac-1", "title": "One"}, {"id": "ac-2", "title": "Two"}]}})
        cat.validate()
        assert cat._id_index["ac-1"][0]["key"] == "controls"
        assert cat._id_index["ac-2"][0]["path"] == "/catalog/controls[1]"


# ===========================================================================
# Walk descent — choice members and recursive self-references are validated
# (restores the post-metaschema-migration behavior). Structural errors found at
# any depth; value-quality (allowed-values) does not gate minimal validity.
# ===========================================================================
_CAT_META = {"last-modified": "2026-01-01T00:00:00Z", "version": "1.0", "oscal-version": "1.1.3"}


def _catalog(groups=None, controls=None):
    root = {"uuid": "10000000-0000-4000-8000-000000000001",
            "metadata": {"title": "C", **_CAT_META}}
    if groups is not None:
        root["groups"] = groups
    if controls is not None:
        root["controls"] = controls
    return OSCAL.loads({"catalog": root})


class TestChoiceAndRecursionDescent:

    def test_choice_member_content_is_validated(self):
        # A group's controls live inside a groups|controls *choice*; a nested control
        # missing its required title must be caught (walk descends into choice members).
        cat = _catalog(groups=[{"id": "ac", "title": "AC", "controls": [{"id": "ac-1"}]}])
        cat.validate()
        locs = [e["location"] for e in cat.validation_errors
                if e["error-type"] == "missing-required" and e["field"] == "title"]
        assert "/catalog/groups[0]/controls[0]" in locs

    def test_absent_choice_branch_is_not_missing_required(self):
        # The group chooses `controls` (not `groups`); the absent `groups` branch must
        # NOT raise missing-required — that's the choice's concern, not a required field.
        cat = _catalog(groups=[{"id": "ac", "title": "AC",
                                "controls": [{"id": "ac-1", "title": "One"}]}])
        cat.validate()
        assert cat.is_minimally_valid
        assert not any(e["error-type"] == "missing-required" and e["field"] == "groups"
                       for e in cat.validation_errors)

    def test_recursive_nesting_is_validated(self):
        # groups nest via a recursive self-reference; a deeply nested group (past the
        # index's concrete expansion) missing its required title must still be caught.
        cat = _catalog(groups=[{"id": "g1", "title": "G1", "groups": [
            {"id": "g2", "title": "G2", "groups": [
                {"id": "g3"}]}]}])   # g3 has no title
        cat.validate()
        locs = [e["location"] for e in cat.validation_errors
                if e["error-type"] == "missing-required" and e["field"] == "title"]
        assert "/catalog/groups[0]/groups[0]/groups[0]" in locs

    def test_recursive_control_enhancements_validated(self):
        cat = _catalog(controls=[{"id": "ac-1", "title": "One", "controls": [
            {"id": "ac-1.1", "title": "Enh", "controls": [
                {"id": "ac-1.1.1"}]}]}])   # deepest enhancement missing title
        cat.validate()
        locs = [e["location"] for e in cat.validation_errors
                if e["error-type"] == "missing-required" and e["field"] == "title"]
        assert "/catalog/controls[0]/controls[0]/controls[0]" in locs

    def test_deeply_nested_valid_hierarchy_is_minimally_valid(self):
        cat = _catalog(groups=[{"id": "g1", "title": "G1", "groups": [
            {"id": "g2", "title": "G2", "controls": [
                {"id": "ac-1", "title": "One", "controls": [
                    {"id": "ac-1.1", "title": "Enh"}]}]}]}])
        cat.validate()
        assert cat.is_minimally_valid


# ===========================================================================
# Minimal vs full validity tier
# ===========================================================================
class TestMinimalValidity:

    def test_structural_error_is_not_minimally_valid(self):
        cat = _catalog(groups=[{"id": "ac", "title": "AC", "controls": [{"id": "ac-1"}]}])
        cat.validate()
        assert not cat.is_valid
        assert not cat.is_minimally_valid          # missing-required is structural

    def test_allowed_values_only_is_minimally_valid(self):
        # A control part with an unknown @name is an allowed-values (value-quality) error;
        # the document is structurally complete, so it is minimally valid though not fully.
        cat = _catalog(controls=[{"id": "ac-1", "title": "One",
                                  "parts": [{"id": "p1", "name": "not-a-real-part-name"}]}])
        cat.validate()
        av = [e for e in cat.validation_errors if e["error-type"] == "allowed-values"]
        assert av                                   # the value-quality error is reported
        assert cat.is_minimally_valid               # ...but it does not block minimal validity
        assert not cat.is_valid                     # full validity still requires it

    def test_well_formed_but_structurally_invalid_not_minimal(self):
        # Missing required metadata/oscal-version -> not even well-formed.
        doc = OSCAL.loads({"catalog": {"uuid": "x"}})
        assert not doc.is_minimally_valid


# ===========================================================================
# matches (regex / datatype) family at L2
# ===========================================================================
class TestMatchesFamily:

    @staticmethod
    def _cat_with(hash_value="a" * 64, country="US"):
        return OSCAL.loads({"catalog": {
            "uuid": "10000000-0000-4000-8000-000000000001",
            "metadata": {"title": "C", "last-modified": "2026-01-01T00:00:00Z",
                         "version": "1.0", "oscal-version": "1.1.3",
                         "locations": [{"uuid": "20000000-0000-4000-8000-000000000002",
                                        "address": {"country": country}}]},
            "back-matter": {"resources": [{"uuid": "30000000-0000-4000-8000-000000000003",
                "rlinks": [{"href": "x", "hashes": [{"algorithm": "SHA-256", "value": hash_value}]}]}]},
        }})

    @staticmethod
    def _matches(doc, substr):
        return [e for e in doc.validation_errors
                if e["error-type"] == "matches" and substr in e["location"]]

    def test_valid_hash_and_country_not_flagged(self):
        doc = self._cat_with(hash_value="a" * 64, country="US")
        assert self._matches(doc, "hashes[0]") == []
        assert self._matches(doc, "country") == []

    def test_bad_hash_length_flagged(self):
        # SHA-256 digest must be 64 hex chars (matches regex, node-level on hash dict)
        doc = self._cat_with(hash_value="tooshort")
        errs = self._matches(doc, "hashes[0]")
        assert errs and errs[0]["expected"].get("regex")

    def test_bad_country_flagged(self):
        # country regex [A-Z]{2} on a bare-string field (scalar-child injection path)
        doc = self._cat_with(country="USA")
        assert self._matches(doc, "country")

    def test_hash_regex_only_applies_to_matching_algorithm(self):
        # the SHA-256 length regex is self-@algorithm-gated: a SHA-512 digest is not
        # flagged by the SHA-256 rule (its own 128-char rule applies instead)
        d = OSCAL.loads({"catalog": {
            "uuid": "10000000-0000-4000-8000-000000000001",
            "metadata": {"title": "C", "last-modified": "2026-01-01T00:00:00Z",
                         "version": "1.0", "oscal-version": "1.1.3"},
            "back-matter": {"resources": [{"uuid": "30000000-0000-4000-8000-000000000003",
                "rlinks": [{"href": "x", "hashes": [{"algorithm": "SHA-512", "value": "b" * 128}]}]}]},
        }})
        assert self._matches(d, "hashes[0]") == []


# ===========================================================================
# has-cardinality family at L2
# ===========================================================================
class TestHasCardinalityFamily:

    @staticmethod
    def _ap_with_objectives(count):
        return OSCAL.loads({"assessment-plan": {
            "uuid": "10000000-0000-4000-8000-000000000001",
            "metadata": {"title": "AP", "last-modified": "2026-01-01T00:00:00Z",
                         "version": "1.0", "oscal-version": "1.1.3"},
            "import-ssp": {"href": "#x"},
            "local-definitions": {"objectives-and-methods": [
                {"control-id": "ac-1", "parts": [{"name": "objective"}] * count}]},
            "reviewed-controls": {"control-selections": [{}]},
        }})

    @staticmethod
    def _hc(doc):
        return [e for e in doc.validation_errors if e["error-type"] == "has-cardinality"]

    def test_within_bound_not_flagged(self):
        # local-objective allows at most one 'objective' part
        assert self._hc(self._ap_with_objectives(1)) == []

    def test_over_max_flagged(self):
        errs = self._hc(self._ap_with_objectives(2))
        assert errs and errs[0]["value"] == 2 and errs[0]["max"] == 1

    def test_has_cardinality_is_non_blocking(self):
        # a constraint-level cardinality violation is value-quality: it must never be a
        # blocking error (only structural `cardinality` blocks imports / minimal validity)
        doc = self._ap_with_objectives(2)
        assert "has-cardinality" not in {e["error-type"] for e in doc.import_blocking_errors}
        from oscal.oscal_content import IMPORT_NONBLOCKING_ERROR_TYPES
        assert "has-cardinality" in IMPORT_NONBLOCKING_ERROR_TYPES


# ===========================================================================
# expect family at L2 (child-existence / value boolean tests)
# ===========================================================================
class TestExpectFamily:

    @staticmethod
    def _cv(doc):
        return [e for e in doc.validation_errors if e["error-type"] == "constraint-violation"]

    @staticmethod
    def _catalog(control, resources=None):
        root = {"uuid": "10000000-0000-4000-8000-000000000001",
                "metadata": {"title": "C", "last-modified": "2026-01-01T00:00:00Z",
                             "version": "1.0", "oscal-version": "1.1.3"},
                "controls": [control]}
        if resources is not None:
            root["back-matter"] = {"resources": resources}
        return OSCAL.loads({"catalog": root})

    def test_require_statement_violation(self):
        # a control with neither a statement part nor a withdrawn status is flagged
        doc = self._catalog({"id": "ac-1", "title": "One", "parts": [{"id": "g", "name": "guidance"}]})
        cv = [e for e in self._cv(doc) if "controls[0]" in e["location"]]
        assert cv

    def test_statement_present_ok(self):
        doc = self._catalog({"id": "ac-1", "title": "One", "parts": [{"id": "s", "name": "statement"}]})
        assert [e for e in self._cv(doc) if "controls[0]" in e["location"]] == []

    def test_withdrawn_control_exempt(self):
        # the `or` branch: a withdrawn control needs no statement part
        doc = self._catalog({"id": "ac-1", "title": "One",
                             "props": [{"name": "status", "value": "withdrawn"}]})
        assert [e for e in self._cv(doc) if "controls[0]" in e["location"]] == []

    def test_citation_requires_title(self):
        # target .[citation] applies only to resources that have a citation; then a title
        # is required (test='title')
        ctrl = {"id": "ac-1", "title": "One", "parts": [{"id": "s", "name": "statement"}]}
        doc = self._catalog(ctrl, resources=[{"uuid": "40000000-0000-4000-8000-000000000004",
                                              "citation": {"text": "c"}}])
        assert [e for e in self._cv(doc) if "resources[0]" in e["location"]]
        # a resource without a citation is not subject to the rule
        doc2 = self._catalog(ctrl, resources=[{"uuid": "40000000-0000-4000-8000-000000000004",
                                               "rlinks": [{"href": "x"}]}])
        assert [e for e in self._cv(doc2) if "resources[0]" in e["location"]] == []

    def test_constraint_violation_is_non_blocking(self):
        from oscal.oscal_content import IMPORT_NONBLOCKING_ERROR_TYPES
        assert "constraint-violation" in IMPORT_NONBLOCKING_ERROR_TYPES


# ===========================================================================
# L2 (valid) vs L3 (fully-compliant) tiers
#   * the automatic walk enforces only natively-evaluable (L2) allowed-values
#   * ancestor/cross-path-scoped (L3) allowed-values are deferred to validate_full
#   * is_fully_compliant is a tri-state: False (not L2-valid) / None (L3 not run) / bool
# ===========================================================================
_HERE = os.path.dirname(__file__)
_PUBLISHED_CATALOG = os.path.join(_HERE, "..", "test-data", "test", "800-53_catalog.json")


class TestValidationTiers:

    def test_l2_still_enforces_native_allowed_values(self):
        # A TOP-LEVEL control part name is a self-scoped (L2) allowed-values: still enforced.
        cat = _catalog(controls=[{"id": "ac-1", "title": "One",
                                  "parts": [{"id": "p1", "name": "not-a-real-part-name"}]}])
        cat.validate()
        av = [e for e in cat.validation_errors if e["error-type"] == "allowed-values"]
        assert av
        assert all(e.get("validation-level", "valid") == "valid" for e in av)

    def test_published_catalog_is_l2_valid(self):
        # A deeply-nested published catalog (nested part/@name='item' etc.) is L2-valid: its
        # only historical allowed-values noise came from L3 (ancestor-scoped) constraints,
        # now deferred. This is the regression the tier split fixes.
        cat = OSCAL.load(_PUBLISHED_CATALOG)
        assert cat.is_minimally_valid
        assert cat.is_valid
        assert [e for e in cat.validation_errors if e["error-type"] == "allowed-values"] == []

    def test_fully_compliant_unknown_until_full_run(self):
        # L2-valid but L3 not evaluated -> is_fully_compliant is None (unknown).
        cat = OSCAL.load(_PUBLISHED_CATALOG)
        assert cat.is_valid
        assert cat.is_fully_compliant is None

    def test_fully_compliant_false_when_not_valid(self):
        # Not even L2-valid -> cannot be fully compliant -> False (not None).
        cat = _catalog(groups=[{"id": "ac", "title": "AC", "controls": [{"id": "ac-1"}]}])
        cat.validate()
        assert not cat.is_valid
        assert cat.is_fully_compliant is False

    def test_validate_full_stub_contract(self):
        # The L3 engine is not yet implemented: validate_full leaves the tri-state unknown
        # on a valid doc, and reports False on an invalid one.
        cat = OSCAL.load(_PUBLISHED_CATALOG)
        assert cat.validate_full() is None
        assert cat.is_fully_compliant is None

        bad = _catalog(groups=[{"id": "ac", "title": "AC", "controls": [{"id": "ac-1"}]}])
        bad.validate()
        assert bad.validate_full() is False

    def test_revalidate_resets_l3_result(self):
        cat = OSCAL.load(_PUBLISHED_CATALOG)
        cat._fully_compliant = True       # simulate a prior L3 pass
        cat.validate()                    # a fresh L2 walk must invalidate it
        assert cat._fully_compliant is None
        assert cat.full_validation_errors == []
