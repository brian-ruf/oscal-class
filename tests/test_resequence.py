"""
Unit tests for oscal.oscal_resequence
"""
import sys
from pathlib import Path

import pytest

# Import directly from the module file to avoid triggering oscal/__init__.py,
# which requires ruf_common (a heavy dependency not needed for these tests.
sys.path.insert(0, "oscal")
from oscal_resequence import (
    _detect_format,
    _detect_model_root_key,
    resequence_oscal,
)


class TestDetectModelRootKey:
    def test_catalog(self):
        assert _detect_model_root_key({"catalog": {}}) == "catalog"

    def test_profile(self):
        assert _detect_model_root_key({"profile": {}}) == "profile"

    def test_system_security_plan(self):
        assert _detect_model_root_key({"system-security-plan": {}}) == "system-security-plan"

    def test_assessment_plan(self):
        assert _detect_model_root_key({"assessment-plan": {}}) == "assessment-plan"

    def test_assessment_results(self):
        assert _detect_model_root_key({"assessment-results": {}}) == "assessment-results"

    def test_poam(self):
        assert _detect_model_root_key(
            {"plan-of-action-and-milestones": {}}
        ) == "plan-of-action-and-milestones"

    def test_component_definition(self):
        assert _detect_model_root_key({"component-definition": {}}) == "component-definition"

    def test_unknown_returns_none(self):
        assert _detect_model_root_key({"not-oscal": {}}) is None

    def test_empty_dict_returns_none(self):
        assert _detect_model_root_key({}) is None


class TestDetectFormat:
    def test_json_extension(self):
        assert _detect_format(Path("document.json")) == "json"

    def test_yaml_extension(self):
        assert _detect_format(Path("document.yaml")) == "yaml"

    def test_yml_extension(self):
        assert _detect_format(Path("document.yml")) == "yaml"

    def test_uppercase_json(self):
        assert _detect_format(Path("document.JSON")) == "json"

    def test_uppercase_yaml(self):
        assert _detect_format(Path("document.YAML")) == "yaml"


class TestResequenceOscal:
    def test_catalog_root_key_comes_first(self):
        data = {
            "$schema": "http://example.com/schema",
            "catalog": {"uuid": "abc", "metadata": {}, "groups": []},
        }
        result = resequence_oscal(data)
        keys = list(result.keys())
        assert keys[0] == "catalog"

    def test_metadata_before_other_keys_in_catalog(self):
        data = {
            "catalog": {
                "groups": [],
                "back-matter": {},
                "metadata": {"title": "Test Catalog"},
                "uuid": "test-uuid",
            }
        }
        result = resequence_oscal(data)
        catalog_keys = list(result["catalog"].keys())
        assert "uuid" in catalog_keys
        assert "metadata" in catalog_keys
        # uuid should appear before metadata per OSCAL canonical order
        assert catalog_keys.index("uuid") < catalog_keys.index("metadata")
        # metadata should appear before groups
        assert catalog_keys.index("metadata") < catalog_keys.index("groups")

    def test_data_preserved_after_resequence(self):
        data = {
            "catalog": {
                "groups": [{"id": "g1"}],
                "metadata": {"title": "My Catalog"},
                "uuid": "test-uuid-1234",
            }
        }
        result = resequence_oscal(data)
        assert result["catalog"]["uuid"] == "test-uuid-1234"
        assert result["catalog"]["metadata"]["title"] == "My Catalog"
        assert result["catalog"]["groups"] == [{"id": "g1"}]

    def test_unknown_root_key_passthrough(self):
        data = {"unknown-model": {"key": "value"}}
        result = resequence_oscal(data)
        assert result["unknown-model"]["key"] == "value"

    def test_empty_catalog(self):
        data = {"catalog": {}}
        result = resequence_oscal(data)
        assert result == {"catalog": {}}

    def test_nested_metadata_keys_resequenced(self):
        # OSCAL canonical order for metadata (from COMMON_METADATA_KEYS):
        # title, published, last-modified, version, oscal-version, ...
        # So: title < last-modified < version
        data = {
            "catalog": {
                "uuid": "test-uuid",
                "metadata": {
                    "remarks": "Some remarks",
                    "version": "1.0",
                    "title": "Test",
                    "last-modified": "2025-01-01T00:00:00Z",
                },
            }
        }
        result = resequence_oscal(data)
        metadata_keys = list(result["catalog"]["metadata"].keys())
        if "title" in metadata_keys and "last-modified" in metadata_keys:
            assert metadata_keys.index("title") < metadata_keys.index("last-modified")
        if "last-modified" in metadata_keys and "version" in metadata_keys:
            assert metadata_keys.index("last-modified") < metadata_keys.index("version")
