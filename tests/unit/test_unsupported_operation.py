"""
Unit tests for the cross-model operation guard on the OSCAL base class:
    - OSCAL.__getattr__ (turns missing members into UnsupportedModelOperation)
    - OSCAL.supports()
    - OSCALError / UnsupportedModelOperation exception behavior

These cover the scenario where a method valid for one OSCAL model is applied to a
model that does not define it, and the typo scenario where no model defines it.
"""
import copy

import pytest

from oscal import (
    Catalog,
    Profile,
    SSP,
    OSCALError,
    UnsupportedModelOperation,
)
from oscal.oscal_content import _MODEL_REGISTRY


# ===========================================================================
# Fixtures
# ===========================================================================
@pytest.fixture
def cat():
    """Fresh writable catalog."""
    return Catalog.new("Guard Test Catalog")


def _method_only_on(model_name):
    """Return the name of a public method defined on ``model_name``'s class but
    not on Catalog, or None if the model exposes no such distinct method."""
    cls = _MODEL_REGISTRY[model_name]
    catalog_attrs = set(dir(Catalog))
    for attr in vars(cls):
        if attr.startswith("_"):
            continue
        if attr in catalog_attrs:
            continue
        if callable(getattr(cls, attr)):
            return attr
    return None


# ===========================================================================
# supports()
# ===========================================================================
class TestSupports:
    def test_true_for_own_method(self, cat):
        assert cat.supports("create_control") is True

    def test_false_for_foreign_method(self, cat):
        # 'resolve' is a Profile operation, not a Catalog one.
        assert cat.supports("resolve") is False

    def test_false_for_nonexistent(self, cat):
        assert cat.supports("definitely_not_a_method") is False

    def test_ignores_instance_attributes(self, cat):
        # Per-instance state must not count as a supported model capability.
        cat.__dict__["ad_hoc_flag"] = True
        assert cat.supports("ad_hoc_flag") is False


# ===========================================================================
# hasattr / getattr semantics must be preserved
# ===========================================================================
class TestAttributeErrorSemantics:
    def test_hasattr_returns_false_not_raises(self, cat):
        # Because UnsupportedModelOperation subclasses AttributeError, hasattr
        # must return False rather than propagating.
        assert hasattr(cat, "resolve") is False

    def test_getattr_default_returned(self, cat):
        assert getattr(cat, "resolve", "SENTINEL") == "SENTINEL"

    def test_is_attribute_error(self, cat):
        with pytest.raises(AttributeError):
            cat.resolve()


# ===========================================================================
# Wrong-model operation
# ===========================================================================
class TestWrongModelOperation:
    def test_raises_unsupported_model_operation(self, cat):
        with pytest.raises(UnsupportedModelOperation):
            cat.resolve()

    def test_catchable_as_oscal_error(self, cat):
        with pytest.raises(OSCALError):
            cat.resolve()

    def test_reports_valid_models(self, cat):
        with pytest.raises(UnsupportedModelOperation) as exc:
            cat.resolve()
        err = exc.value
        assert err.method == "resolve"
        assert err.model == "catalog"
        assert "profile" in err.valid_on
        assert "profile" in err.developer_message
        assert "resolve" in err.developer_message

    def test_ssp_method_on_catalog(self, cat):
        method = _method_only_on("system-security-plan")
        assert method is not None, "expected an SSP-only method to exist"
        with pytest.raises(UnsupportedModelOperation) as exc:
            getattr(cat, method)()
        assert "system-security-plan" in exc.value.valid_on

    def test_user_message_hides_internal_detail(self, cat):
        with pytest.raises(UnsupportedModelOperation) as exc:
            cat.resolve()
        # user_message must be safe/generic; must not leak the method name.
        assert "resolve" not in exc.value.user_message
        assert exc.value.user_message == UnsupportedModelOperation.default_user_message


# ===========================================================================
# Typo (no model defines the name)
# ===========================================================================
class TestTypoOperation:
    def test_raises_with_empty_valid_on(self, cat):
        with pytest.raises(UnsupportedModelOperation) as exc:
            cat.craete_control("id")  # deliberate typo
        assert exc.value.valid_on == []
        assert "typo" in exc.value.developer_message


# ===========================================================================
# Error is captured for developer inspection
# ===========================================================================
class TestErrorCapture:
    def test_recorded_on_instance(self, cat):
        try:
            cat.resolve()
        except UnsupportedModelOperation:
            pass
        recorded = cat.errors.get("unsupported_operations")
        assert recorded, "expected the failed operation to be recorded on .errors"
        entry = recorded[-1]
        assert entry["method"] == "resolve"
        assert entry["model"] == "catalog"
        assert "profile" in entry["valid_on"]

    def test_multiple_failures_accumulate(self, cat):
        for name in ("resolve", "craete_control"):
            try:
                getattr(cat, name)()
            except UnsupportedModelOperation:
                pass
        recorded = cat.errors.get("unsupported_operations")
        assert len(recorded) == 2


# ===========================================================================
# Dunder / protocol probing must not be intercepted
# ===========================================================================
class TestDunderGuard:
    @pytest.mark.parametrize("dunder", ["__deepcopy__", "__wrapped__", "__nonexistent_dunder__"])
    def test_missing_dunder_raises_plain_attribute_error(self, cat, dunder):
        with pytest.raises(AttributeError) as exc:
            getattr(cat, dunder)
        # Must be a plain AttributeError, NOT our UnsupportedModelOperation.
        assert not isinstance(exc.value, UnsupportedModelOperation)

    def test_deepcopy_of_dict_fragment(self, cat):
        # The library relies on deepcopy for safe-copy getters; the dunder guard
        # must not interfere with copying plain dict fragments.
        fragment = {"id": "ac-1", "props": [{"name": "label", "value": "AC-1"}]}
        assert copy.deepcopy(fragment) == fragment


# ===========================================================================
# Valid operations are unaffected (no overhead path)
# ===========================================================================
class TestValidOperationsUnaffected:
    def test_normal_method_still_works(self, cat):
        grp = cat.create_control_group("", "ac", title="Access Control")
        assert grp is not None
        assert cat.supports("create_control_group")
