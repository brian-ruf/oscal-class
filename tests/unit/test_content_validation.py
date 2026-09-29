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
        c.create_control("g", "c-1", title="C1")
        c.create_control("g", "c-2", title="C2")
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
    """An inventory-item prop with a legitimate (but non-`vendor-name`) name must not
    trip the @type-scoped `vendor-name`-only allowed-values constraint."""

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
    def _inventory_av_errors(doc):
        return [e for e in doc.validation_errors
                if e["error-type"] == "allowed-values" and "inventory-items" in e["location"]]

    def test_legitimate_prop_name_not_flagged(self):
        doc = self._ssp_with_inventory_prop("asset-type")
        doc.validate()
        assert self._inventory_av_errors(doc) == []

    def test_bogus_prop_name_still_flagged(self):
        # The general (unscoped) allowed-values constraint is still enforced.
        doc = self._ssp_with_inventory_prop("definitely-not-a-real-prop-name")
        doc.validate()
        assert self._inventory_av_errors(doc)


# ===========================================================================
# Normalized validation errors — every error carries an `identifier` (uuid/id of
# the nearest enclosing identifiable object) alongside the JSON `location`.
# ===========================================================================
_SSP_UUID = "30000000-0000-4000-8000-000000000001"
_INV_UUID = "40000000-0000-4000-8000-000000000001"


def _ssp_with_inventory_prop_name(name):
    return OSCAL.loads({
        "system-security-plan": {
            "uuid": _SSP_UUID,
            "metadata": {"title": "T", "last-modified": "2026-01-01T00:00:00Z",
                         "version": "1.0", "oscal-version": "1.1.3"},
            "system-implementation": {
                "inventory-items": [
                    {"uuid": _INV_UUID, "description": "d",
                     "props": [{"name": name, "value": "x"}]},
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
        root["system-implementation"]["inventory-items"] = [
            {"uuid": _INV_UUID, "description": "d",
             "props": [{"name": "definitely-not-a-real-prop-name", "value": "x"}]}]
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
