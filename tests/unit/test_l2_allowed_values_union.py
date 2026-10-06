"""
Prototype tests for the L2 allowed-values UNION evaluator (step-2 Phase 1).

A single flag can be governed by several allowed-values constraints — a general set plus
context-scoped sets (e.g. a component's props accept `vendor-name` only when the component
`@type` is software/hardware/service). The correct L2 rule is the UNION of the in-scope
sets, with `allow-other` as a least-restrictive shortcut. These tests pin that semantics
(including the real SSP metaschema constraints) before it is wired into the validation
walk — the previous naive "union" attempt regressed freeform props, so the contract is
locked down here first.
"""
import pytest

from oscal.oscal_content import (
    _partition_conditions,
    _context_gates_met,
    _target_filters_met,
    _resolve_flag_allowed_values,
    _flag_value_allowed,
    _l2b_in_scope,
)
from oscal.oscal_support import get_support


# ---------------------------------------------------------------------------
# L2-B reverse-match evaluator (_l2b_in_scope)
# ---------------------------------------------------------------------------
def _part(name):
    return ("part", {"name": name})


_SPEC_STATEMENT_ITEM = {"leaf": "name", "segments": [
    {"axis": "child", "elem": "part", "names": {"statement"}},
    {"axis": "descendant", "elem": "part", "names": None},
]}
_SPEC_ASSESSMENT_CHILD = {"leaf": "name", "segments": [
    {"axis": "child", "elem": "part", "names": {"assessment", "assessment-method"}},
    {"axis": "child", "elem": "part", "names": None},
]}
_SPEC_ANY_DESCENDANT = {"leaf": "name",
                        "segments": [{"axis": "descendant", "elem": "part", "names": None}]}


# governed element carries its own @name predicate (prop[@name='method']/@value)
_SPEC_METHOD_VALUE = {"leaf": "value", "segments": [
    {"axis": "child", "elem": "part", "names": ["assessment", "assessment-method"]},
    {"axis": "child", "elem": "prop", "names": ["method"]},
]}


class TestL2BInScope:

    def test_descendant_gate_matches_any_ancestor(self):
        # a part somewhere beneath a 'statement' part
        chain = [_part("objective"), _part("statement"), ("control", {"id": "ac-1"})]
        assert _l2b_in_scope(_SPEC_STATEMENT_ITEM, "part", {"name": "objective"}, chain) is True

    def test_descendant_gate_absent_statement(self):
        chain = [_part("objective"), _part("guidance"), ("control", {"id": "ac-1"})]
        assert _l2b_in_scope(_SPEC_STATEMENT_ITEM, "part", {"name": "x"}, chain) is False

    def test_child_gate_requires_immediate_parent(self):
        assert _l2b_in_scope(_SPEC_ASSESSMENT_CHILD, "part", {}, [_part("assessment")]) is True

    def test_child_gate_not_satisfied_by_grandparent(self):
        # assessment is the grandparent, not the immediate parent -> out of scope
        chain = [_part("objective"), _part("assessment")]
        assert _l2b_in_scope(_SPEC_ASSESSMENT_CHILD, "part", {}, chain) is False

    def test_ungated_descendant_always_in_scope(self):
        assert _l2b_in_scope(_SPEC_ANY_DESCENDANT, "part", {}, [("control", {})]) is True
        assert _l2b_in_scope(_SPEC_ANY_DESCENDANT, "part", {}, []) is True

    def test_governed_element_mismatch(self):
        # the governed element is 'part'; a 'prop' leaf is never in scope
        assert _l2b_in_scope(_SPEC_ANY_DESCENDANT, "prop", {}, [_part("statement")]) is False

    def test_governed_name_predicate_scopes_the_prop(self):
        # prop[@name='method']/@value governs ONLY props named 'method'
        parent = [_part("assessment")]
        assert _l2b_in_scope(_SPEC_METHOD_VALUE, "prop", {"name": "method"}, parent) is True
        # a differently-named prop under the same assessment part is NOT governed
        assert _l2b_in_scope(_SPEC_METHOD_VALUE, "prop", {"name": "label"}, parent) is False

_OSCAL_NS = "http://csrc.nist.gov/ns/oscal"


def _av(values, *, allow_other=False, conditions=None, cid="c"):
    return {
        "type": "allowed-values",
        "id": cid,
        "allow-other": allow_other,
        "values": [{"value": v} for v in values],
        "conditions": conditions or [],
    }


def _ns_filter():
    return {"type": "namespace", "values": [_OSCAL_NS, ""], "allow-absent": True}


def _type_gate(values):
    return {"type": "flag-in", "flag": "type", "values": list(values)}


# ---------------------------------------------------------------------------
# Condition partitioning
# ---------------------------------------------------------------------------
class TestPartitionConditions:

    def test_flag_conditions_are_context_gates(self):
        con = _av(["x"], conditions=[_type_gate(["software"]), _ns_filter()])
        gates, filters = _partition_conditions(con)
        assert [g["type"] for g in gates] == ["flag-in"]
        assert [f["type"] for f in filters] == ["namespace"]

    def test_flag_equals_is_a_gate(self):
        con = _av(["x"], conditions=[{"type": "flag-equals", "flag": "type", "value": "software"}])
        gates, filters = _partition_conditions(con)
        assert len(gates) == 1 and filters == []

    def test_no_conditions(self):
        assert _partition_conditions(_av(["x"])) == ([], [])


# ---------------------------------------------------------------------------
# Context gates / target filters
# ---------------------------------------------------------------------------
class TestGatesAndFilters:

    def test_gate_flag_in_match(self):
        assert _context_gates_met([_type_gate(["software", "hardware"])], {"type": "hardware"})

    def test_gate_flag_in_miss(self):
        assert not _context_gates_met([_type_gate(["software"])], {"type": "policy"})

    def test_gate_absent_flag_never_matches(self):
        assert not _context_gates_met([_type_gate(["software"])], {"description": "no type"})

    def test_empty_gates_always_met(self):
        assert _context_gates_met([], {"anything": 1})

    def test_namespace_filter_absent_ns_is_oscal(self):
        assert _target_filters_met([_ns_filter()], {"name": "x"})          # no ns -> OSCAL default

    def test_namespace_filter_vendor_ns_excluded(self):
        assert not _target_filters_met([_ns_filter()], {"name": "x", "ns": "https://vendor.example/ns"})


# ---------------------------------------------------------------------------
# Union resolution + value check
# ---------------------------------------------------------------------------
class TestUnionResolution:

    def test_single_set_in_and_out(self):
        r = _resolve_flag_allowed_values([_av(["a", "b"])], {"name": "a"})
        assert r["governed"] and not r["allow_other"]
        assert _flag_value_allowed("a", r)
        assert not _flag_value_allowed("z", r)

    def test_union_of_two_sets(self):
        cons = [_av(["a"], cid="g"), _av(["b"], cid="h")]
        r = _resolve_flag_allowed_values(cons, {"name": "b"})
        assert r["allowed"] == {"a", "b"}
        assert _flag_value_allowed("a", r) and _flag_value_allowed("b", r)
        assert not _flag_value_allowed("c", r)

    def test_no_governing_constraint_is_no_opinion(self):
        # All out of scope -> not governed -> any value passes (deferred, not an error).
        cons = [_av(["vendor-name"], conditions=[_type_gate(["software"])], cid="v")]
        r = _resolve_flag_allowed_values(cons, {"type": "policy"})
        assert not r["governed"]
        assert _flag_value_allowed("anything", r)

    def test_allow_other_shortcut(self):
        r = _resolve_flag_allowed_values([_av(["a"], allow_other=True)], {"name": "a"})
        assert r["allow_other"]
        assert _flag_value_allowed("literally-anything", r)

    def test_allow_other_is_least_restrictive_across_sets(self):
        # One in-scope set is closed, another permits others -> others allowed.
        cons = [_av(["a"], cid="closed"), _av(["b"], allow_other=True, cid="open")]
        r = _resolve_flag_allowed_values(cons, {"name": "x"})
        assert r["allow_other"]
        assert _flag_value_allowed("x", r)


# ---------------------------------------------------------------------------
# The motivating case: component @type gates `vendor-name`
# ---------------------------------------------------------------------------
class TestTypeScopedPropNames:

    def _cons(self):
        general = _av(["asset-id", "asset-type"], conditions=[_ns_filter()], cid="general")
        vendor = _av(["vendor-name"], conditions=[_type_gate(["software", "hardware", "service"]),
                                                  _ns_filter()], cid="vendor")
        return [general, vendor]

    def test_vendor_name_allowed_for_software(self):
        r = _resolve_flag_allowed_values(self._cons(), {"type": "software"}, leaf_obj={"name": "vendor-name"})
        assert _flag_value_allowed("vendor-name", r)   # via the type-gated set
        assert _flag_value_allowed("asset-id", r)      # via the general set (union)

    def test_vendor_name_rejected_for_policy(self):
        r = _resolve_flag_allowed_values(self._cons(), {"type": "policy"}, leaf_obj={"name": "vendor-name"})
        assert not _flag_value_allowed("vendor-name", r)   # type-gated set out of scope
        assert _flag_value_allowed("asset-id", r)          # general set still applies

    def test_bogus_name_rejected_for_software(self):
        r = _resolve_flag_allowed_values(self._cons(), {"type": "software"}, leaf_obj={"name": "nope"})
        assert not _flag_value_allowed("nope", r)


# ---------------------------------------------------------------------------
# Same semantics against the REAL SSP metaschema constraints
# ---------------------------------------------------------------------------
class TestAgainstRealIndex:

    @staticmethod
    def _component_name_constraints():
        idx = get_support().get_metaschema_index("v1.2.3", "system-security-plan")
        assert idx is not None
        seen, found = set(), []

        def walk(n, path=""):
            if id(n) in seen:
                return
            seen.add(id(n))
            nm = n.get("name") or n.get("use-name")
            p = f"{path}/{nm}"
            if p.endswith("system-component/property"):
                for ch in n.get("children", []) or []:
                    if (ch.get("name") or ch.get("use-name")) == "name":
                        avs = [c for c in ch.get("constraints", []) if c.get("type") == "allowed-values"]
                        if any("vendor-name" in {v["value"] for v in c.get("values", [])} for c in avs):
                            found.append(avs)
            for ch in n.get("children", []) or []:
                walk(ch, p)

        nd = idx["nodes"]
        walk(nd) if isinstance(nd, dict) else [walk(x) for x in nd]
        assert found, "expected a component property/name node with a vendor-name set"
        return found[0]

    def test_real_union_allows_vendor_name_for_software(self):
        cons = self._component_name_constraints()
        r = _resolve_flag_allowed_values(cons, {"type": "software"}, leaf_obj={"name": "vendor-name"})
        assert r["governed"]
        assert _flag_value_allowed("vendor-name", r)

    def test_real_union_rejects_vendor_name_for_plan(self):
        cons = self._component_name_constraints()
        r = _resolve_flag_allowed_values(cons, {"type": "plan"}, leaf_obj={"name": "vendor-name"})
        # 'plan' is not in the software/hardware/service gate -> vendor-name not permitted.
        assert not _flag_value_allowed("vendor-name", r)

    def test_real_union_rejects_bogus_name(self):
        cons = self._component_name_constraints()
        r = _resolve_flag_allowed_values(cons, {"type": "software"}, leaf_obj={"name": "definitely-bogus"})
        assert not _flag_value_allowed("definitely-bogus", r)
