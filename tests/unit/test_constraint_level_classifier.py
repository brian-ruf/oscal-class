"""
Unit tests for the allowed-values native-evaluability classifier
(`_target_is_natively_evaluable`) — the crux of the L2/`valid` vs L3/`fully-compliant`
split. A target is natively evaluable (→ L2) only when whether it governs a node and
the node's allowed set depend solely on that node and its own flags (plus
`has-oscal-namespace`). Ancestor/descendant/absolute/cross-path/function scoping → L3.

Cases are the real targets observed in the metaschema index, including the ones that
caused the nested-allowed-values false positives.
"""
import pytest

from oscal.metaschema_parser import (
    _target_is_natively_evaluable,
    _target_is_l2_context_gated,
    _split_metapath_steps,
    _classify_allowed_values_levels,
    _CONSTRAINT_RULE_TAGS,
)


_FLAG_IN_TYPE = [{"type": "flag-in", "flag": "type", "values": ["software", "hardware", "service"]}]
_FLAG_EQ_SYSTEM = [{"type": "flag-equals", "flag": "system", "value": "http://csrc.nist.gov/ns/oscal"}]


# ---------------------------------------------------------------------------
# L2-A: context-@flag-gated targets (valid when a flag gate + native remainder)
# ---------------------------------------------------------------------------
class TestContextGatedL2:

    def test_type_gated_prop_name_is_l2(self):
        t = "(.)[@type=('software', 'hardware', 'service')]/prop[has-oscal-namespace('http://csrc.nist.gov/ns/oscal')]/@name"
        assert _target_is_l2_context_gated(t, _FLAG_IN_TYPE) is True

    def test_self_flag_gated_name_is_l2(self):
        t = "(.)[@system='http://csrc.nist.gov/ns/oscal']/@name"
        assert _target_is_l2_context_gated(t, _FLAG_EQ_SYSTEM) is True

    def test_requires_extracted_flag_condition(self):
        # Same shape but no machine-readable flag condition -> not L2-A.
        t = "(.)[@type='software']/prop/@name"
        assert _target_is_l2_context_gated(t, []) is False

    def test_non_flag_leading_predicate_rejected(self):
        t = "(.)[has-oscal-namespace('http://csrc.nist.gov/ns/oscal')]/@name"
        assert _target_is_l2_context_gated(t, _FLAG_EQ_SYSTEM) is False

    def test_element_name_gate_is_not_l2a(self):
        # L2-B element-@name gate (not a self context gate) stays out of L2-A.
        t = "part[has-oscal-namespace('http://csrc.nist.gov/ns/oscal') and @name='statement']//part/@name"
        assert _target_is_l2_context_gated(t, [{"type": "flag-equals", "flag": "name", "value": "statement"}]) is False

    def test_alternation_rejected(self):
        t = "(.|statement|.//by-component)/prop/@name"
        assert _target_is_l2_context_gated(t, _FLAG_IN_TYPE) is False


# ---------------------------------------------------------------------------
# L2-B: element-@name-gated targets (reverse-match spec)
# ---------------------------------------------------------------------------
from oscal.metaschema_parser import _parse_l2b_target, _target_is_l2_element_gated  # noqa: E402


class TestParseL2BTarget:

    def test_ancestor_statement_gate_descendant(self):
        t = ("part[has-oscal-namespace('http://csrc.nist.gov/ns/oscal') and @name='statement']"
             "//part[has-oscal-namespace('http://csrc.nist.gov/ns/oscal')]/@name")
        spec = _parse_l2b_target(t)
        assert spec == {"leaf": "name", "segments": [
            {"axis": "child", "elem": "part", "names": ["statement"]},
            {"axis": "descendant", "elem": "part", "names": None},
        ]}

    def test_immediate_parent_gate_child(self):
        t = ("part[has-oscal-namespace('http://csrc.nist.gov/ns/oscal') "
             "and @name=('assessment','assessment-method')]"
             "/part[has-oscal-namespace('http://csrc.nist.gov/ns/oscal')]/@name")
        spec = _parse_l2b_target(t)
        assert spec["leaf"] == "name"
        assert spec["segments"][0] == {"axis": "child", "elem": "part",
                                       "names": ["assessment", "assessment-method"]}
        assert spec["segments"][1] == {"axis": "child", "elem": "part", "names": None}

    def test_ungated_descendant(self):
        t = ".//part[has-oscal-namespace('http://csrc.nist.gov/ns/oscal')]/@name"
        spec = _parse_l2b_target(t)
        assert spec == {"leaf": "name",
                        "segments": [{"axis": "descendant", "elem": "part", "names": None}]}

    def test_value_leaf(self):
        t = ("part[has-oscal-namespace('http://csrc.nist.gov/ns/oscal') and @name='method']"
             "/prop[has-oscal-namespace('http://csrc.nist.gov/ns/oscal')]/@value")
        spec = _parse_l2b_target(t)
        assert spec is not None and spec["leaf"] == "value"

    @pytest.mark.parametrize("t", [
        "(.|statement|.//by-component)/prop/@name",            # alternation
        "(.)[@type='software']/prop/@name",                    # flag gate (that's L2-A, not B)
        "prop[starts-with(@name,'x')]/@name",                  # unsupported function
        "/catalog/metadata/prop/@name",                        # absolute
        "ancestor::control/@id",                               # axis
        "part[@class='x']/@name",                              # non-@name flag gate
    ])
    def test_non_l2b_targets(self, t):
        assert _target_is_l2_element_gated(t) is False


# ---------------------------------------------------------------------------
# matches target → value-resolution spec
# ---------------------------------------------------------------------------
from oscal.metaschema_parser import _parse_matches_target  # noqa: E402


class TestParseMatchesTarget:

    def test_own_flag(self):
        assert _parse_matches_target("@resource-fragment") == {"kind": "flag", "flag": "resource-fragment"}

    def test_self(self):
        assert _parse_matches_target(".") == {"kind": "self", "gate": []}

    def test_self_flag_gated(self):
        spec = _parse_matches_target(".[@algorithm=('SHA-256','SHA3-256')]")
        assert spec == {"kind": "self", "gate": [("algorithm", ["SHA-256", "SHA3-256"])]}

    def test_child_path_is_l2b_kind(self):
        spec = _parse_matches_target("prop[has-oscal-namespace('x') and @name='published']/@value")
        assert spec["kind"] == "l2b" and spec["spec"]["leaf"] == "value"

    @pytest.mark.parametrize("t", [
        ".[@rel=('reference') and starts-with(@href,'#')]/@href",   # function
        "link[@rel='x']/@href[not(starts-with(.,'#'))]",            # function
        "title|address|email-address",                              # alternation
    ])
    def test_function_or_alternation_rejected(self, t):
        assert _parse_matches_target(t) is None


# ---------------------------------------------------------------------------
# has-cardinality target → 1-level count spec
# ---------------------------------------------------------------------------
from oscal.metaschema_parser import _parse_cardinality_target  # noqa: E402


class TestParseCardinalityTarget:

    def test_child_name_gate(self):
        spec = _parse_cardinality_target(
            "part[has-oscal-namespace('x') and @name=('objective','assessment-objective')]")
        assert spec == {"self_gate": [],
                        "step": {"elem": "part", "names": ["assessment-objective", "objective"]}}

    def test_self_gated_child(self):
        spec = _parse_cardinality_target(".[@name='objective']/prop[@name='method']")
        assert spec == {"self_gate": [("name", ["objective"])],
                        "step": {"elem": "prop", "names": ["method"]}}

    @pytest.mark.parametrize("t", [
        "part[@name='a']/prop[@name='b']",   # two-level (deferred to L3)
        "title|address",                      # alternation
        ".//by-component",                    # descendant
        ".",                                  # self-only count
        "@id",                                # flag count
    ])
    def test_rejected(self, t):
        assert _parse_cardinality_target(t) is None


# ---------------------------------------------------------------------------
# expect target + boolean test → spec
# ---------------------------------------------------------------------------
from oscal.metaschema_parser import _parse_expect  # noqa: E402


class TestParseExpect:

    def test_or_of_value_set_and_child_existence(self):
        spec = _parse_expect(".", "prop[@name='status']/@value=('withdrawn','reserved') or part[@name='statement']")
        assert spec["applies"] is None
        assert spec["test"]["op"] == "or"
        ops = {a["op"] for a in spec["test"]["args"]}
        assert ops == {"eq", "exists"}

    def test_target_child_existence_predicate(self):
        spec = _parse_expect(".[citation]", "title")
        assert spec["applies"]["op"] == "exists"
        assert spec["test"]["op"] == "exists"

    def test_not_flag_equals(self):
        spec = _parse_expect(".", "not(@method='merge')")
        assert spec["test"] == {"op": "not", "arg": {"op": "eq",
               "path": [{"kind": "flag", "flag": "method"}], "values": ["merge"]}}

    def test_not_exists_flag(self):
        spec = _parse_expect(".", "not(exists(@depends-on))")
        assert spec["test"]["op"] == "not" and spec["test"]["arg"]["op"] == "exists"

    @pytest.mark.parametrize("target,test", [
        (".[starts-with(@href,'#')]", "not(exists(@media-type))"),   # function in target
        (".", "not(@start > @end)"),                                  # comparison
        (".", "count(prop) > 1"),                                     # unsupported function
        ("part[@name='x']", "prop"),                                  # element target (not . / .[..])
    ])
    def test_unsupported_stays_l3(self, target, test):
        assert _parse_expect(target, test) is None


# ---------------------------------------------------------------------------
# Native (L2 / valid): self or own-flag scoped
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("target", [
    ".",                                               # self
    "@name",                                           # own flag
    "./@name",                                         # own flag (explicit self)
    "@value",
    "prop[@name='type']/@value",                       # predicate on the governed prop itself
    "prop[has-oscal-namespace('http://csrc.nist.gov/ns/oscal')]/@name",   # ns only
    "prop[has-oscal-namespace('http://csrc.nist.gov/ns/oscal') and @name='marking']/@value",
    "rlink/hash/@algorithm",                           # forward path, no scoping predicate
])
def test_native_targets(target):
    assert _target_is_natively_evaluable(target) is True


# ---------------------------------------------------------------------------
# Not native (L3 / fully-compliant): needs ancestor / descendant / cross-path
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("target", [
    ".//part[has-oscal-namespace('http://csrc.nist.gov/ns/oscal')]/@name",          # descendant axis
    "part[has-oscal-namespace('http://csrc.nist.gov/ns/oscal') and @name='statement']"
        "//part[has-oscal-namespace('http://csrc.nist.gov/ns/oscal')]/@name",       # ancestor predicate + //
    "(.)[@type=('software','hardware','service')]/prop"
        "[has-oscal-namespace('http://csrc.nist.gov/ns/oscal')]/@name",             # @type on ancestor (context)
    "/catalog/metadata/prop/@name",                                                 # absolute
    "ancestor::control/@id",                                                         # explicit ancestor axis
    "../@id",                                                                        # parent axis
    "prop[starts-with(@name,'x')]/@value",                                           # unsupported function
    "(objective|statement)/@name",                                                   # alternation
])
def test_non_native_targets(target):
    assert _target_is_natively_evaluable(target) is False


# ---------------------------------------------------------------------------
# Step splitter respects predicates and quotes
# ---------------------------------------------------------------------------
class TestSplitSteps:

    def test_slash_inside_predicate_not_split(self):
        steps = _split_metapath_steps("a[@x='b/c']/d/@e")
        assert steps == ["a[@x='b/c']", "d", "@e"]

    def test_nested_brackets(self):
        steps = _split_metapath_steps("a[b[@x='1']]/c")
        assert steps == ["a[b[@x='1']]", "c"]

    def test_plain_path(self):
        assert _split_metapath_steps("prop/@name") == ["prop", "@name"]


# ---------------------------------------------------------------------------
# Per-node all-or-nothing promotion (_classify_allowed_values_levels)
# ---------------------------------------------------------------------------
def _av(target, **extra):
    c = {"type": "allowed-values", "target": target, "values": []}
    c.update(extra)
    return c


class TestClassifyLevels:

    def test_all_native_node_is_valid(self):
        node = {"constraints": [_av("@name"), _av("prop/@value")]}
        _classify_allowed_values_levels(node)
        assert [c["validation-level"] for c in node["constraints"]] == ["valid", "valid"]

    def test_one_non_native_demotes_whole_node(self):
        # A single genuinely-L3 target (alternation) drags every allowed-values to L3.
        node = {"constraints": [_av("@name"), _av("(objective|statement)/@name")]}
        _classify_allowed_values_levels(node)
        assert all(c["validation-level"] == "fully-compliant" for c in node["constraints"])

    def test_unresolved_target_is_treated_non_native(self):
        node = {"constraints": [_av("@name", **{"unresolved-target": "foo/bar"})]}
        _classify_allowed_values_levels(node)
        assert node["constraints"][0]["validation-level"] == "fully-compliant"

    def test_non_allowed_values_constraints_untouched(self):
        raw = {"type": "matches", "target": "@x", "handled": False,
               "validation-level": "fully-compliant", "raw": "<matches/>"}
        node = {"constraints": [_av("@name"), raw]}
        _classify_allowed_values_levels(node)
        assert node["constraints"][0]["validation-level"] == "valid"
        # the raw matches entry keeps its level and gains no allowed-values treatment
        assert raw["validation-level"] == "fully-compliant"

    def test_recurses_into_children_independently(self):
        tree = {
            "constraints": [_av("@name")],                 # native -> valid
            "children": [
                {"constraints": [_av("(a|b)/@y")]},          # alternation -> L3
                {"children": [{"constraints": [_av("@z")]}]},  # nested native -> valid
            ],
        }
        _classify_allowed_values_levels(tree)
        assert tree["constraints"][0]["validation-level"] == "valid"
        assert tree["children"][0]["constraints"][0]["validation-level"] == "fully-compliant"
        assert tree["children"][1]["children"][0]["constraints"][0]["validation-level"] == "valid"

    def test_cycle_guard_terminates(self):
        # Shared/recursive node references must not loop forever.
        node = {"constraints": [_av("@name")]}
        node["children"] = [node]  # self-reference
        _classify_allowed_values_levels(node)  # must return
        assert node["constraints"][0]["validation-level"] == "valid"

    def test_node_without_allowed_values_is_noop(self):
        node = {"constraints": [{"type": "expect", "target": ".", "handled": False}]}
        _classify_allowed_values_levels(node)
        assert "validation-level" not in [k for k in node["constraints"][0] if k == "validation-level"] \
            or node["constraints"][0].get("validation-level") == "fully-compliant"


class TestConstraintRuleTags:

    def test_known_rule_vocabulary(self):
        assert _CONSTRAINT_RULE_TAGS == {
            "allowed-values", "expect", "index-has-key", "matches",
            "is-unique", "has-cardinality", "index",
        }
