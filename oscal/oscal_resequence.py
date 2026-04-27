#!/usr/bin/env python3
"""
oscal_resequence.py

Resequences keys in OSCAL JSON and YAML files to match the canonical order
defined in NIST OSCAL syntax documentation. Data and parent/child
relationships are preserved exactly; only key ordering changes.

Supports all 8 OSCAL models:
  - Catalog
  - Profile
  - Mapping Collection
  - Component Definition
  - System Security Plan (SSP)
  - System Assessment Plan (SAP)
  - System Assessment Results (SAR)
  - Plan of Action and Milestones (POA&M)

Usage:
    python oscal_resequence.py <input_file> [output_file]

    If output_file is omitted, the resequenced content is written back to
    input_file (in-place).

Function for inclusion in oscal-class library:
    from oscal_resequence import resequence_oscal_file
    resequence_oscal_file("ssp.json")
    resequence_oscal_file("catalog.yaml", "catalog_ordered.yaml")
"""

import json
import sys
from pathlib import Path
from typing import List, Optional, Union

try:
    import yaml

    class _OscalLoader(yaml.SafeLoader):
        """SafeLoader variant that preserves datetime strings as plain strings.

        PyYAML's default SafeLoader maps ISO 8601 timestamps to Python
        datetime objects, which yaml.dump then serializes in a different
        format (e.g. '2025-02-28 00:00:00+00:00') that is not valid per the
        OSCAL date-time-with-timezone pattern.  Removing the implicit
        resolver for the 'tag:yaml.org,2002:timestamp' tag prevents that
        conversion so the original string is round-tripped unchanged.
        """

    # Remove the timestamp resolver from our custom loader only.
    _OscalLoader.yaml_implicit_resolvers = {
        key: [(tag, regexp) for tag, regexp in resolvers
              if tag != "tag:yaml.org,2002:timestamp"]
        for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    _OscalLoader = None # type: ignore


# ---------------------------------------------------------------------------
# OSCAL 1.2.0 canonical key orderings
#
# Each entry is a list of keys in the order they appear in the NIST schema
# documentation.  Keys not present in a given list fall through to the end
# in their original order (preserves forward-compatibility for unknown keys).
# ---------------------------------------------------------------------------

# ── Shared / common structures ──────────────────────────────────────────────

COMMON_METADATA_KEYS = [
    "title", "published", "last-modified", "version", "oscal-version",
    "revisions", "document-ids", "props", "links", "roles", "locations",
    "parties", "responsible-parties", "remarks",
]

COMMON_BACK_MATTER_KEYS = [
    "resources",
]

COMMON_RESOURCE_KEYS = [
    "uuid", "title", "description", "props", "document-ids",
    "citation", "rlinks", "base64", "remarks",
]

COMMON_CITATION_KEYS = ["text", "props", "links"]

COMMON_RLINK_KEYS = ["href", "media-type", "hashes"]

COMMON_BASE64_KEYS = ["filename", "media-type", "value"]

COMMON_REVISION_KEYS = [
    "title", "published", "last-modified", "version", "oscal-version",
    "props", "links", "remarks",
]

COMMON_ROLE_KEYS = [
    "id", "title", "short-name", "description", "props", "links", "remarks",
]

COMMON_LOCATION_KEYS = [
    "uuid", "title", "address", "email-addresses", "telephone-numbers",
    "urls", "props", "links", "remarks",
]

COMMON_ADDRESS_KEYS = [
    "type", "addr-lines", "city", "state", "postal-code", "country",
]

COMMON_PARTY_KEYS = [
    "uuid", "type", "name", "short-name", "external-ids", "props", "links",
    "email-addresses", "telephone-numbers", "addresses", "location-uuids",
    "member-of-organizations", "remarks",
]

COMMON_RESPONSIBLE_PARTY_KEYS = [
    "role-id", "party-uuids", "props", "links", "remarks",
]

COMMON_PROP_KEYS = ["name", "uuid", "ns", "value", "class", "group", "remarks"]

COMMON_LINK_KEYS = ["href", "rel", "media-type", "resource-fragment", "text"]

COMMON_HASH_KEYS = ["algorithm", "value"]

COMMON_DOCUMENT_ID_KEYS = ["scheme", "identifier"]

COMMON_EXTERNAL_ID_KEYS = ["scheme", "id"]

COMMON_TELEPHONE_KEYS = ["type", "number"]

# ── Catalog ─────────────────────────────────────────────────────────────────

CATALOG_ROOT_KEYS = [
    "uuid", "metadata", "params", "controls", "groups", "back-matter",
]

CATALOG_GROUP_KEYS = [
    "id", "class", "title", "params", "props", "links", "parts", "groups",
    "controls",
]

CATALOG_CONTROL_KEYS = [
    "id", "class", "title", "params", "props", "links", "parts",
    "controls",
]

CATALOG_PARAM_KEYS = [
    "id", "class", "depends-on", "props", "links", "label", "usage",
    "constraints", "guidelines", "values", "select", "remarks",
]

CATALOG_PART_KEYS = [
    "id", "name", "ns", "class", "title", "props", "prose", "parts", "links",
]

CATALOG_CONSTRAINT_KEYS = ["description", "tests"]

CATALOG_CONSTRAINT_TEST_KEYS = ["expression", "remarks"]

CATALOG_GUIDELINE_KEYS = ["prose"]

CATALOG_SELECT_KEYS = ["how-many", "choice"]

# ── Profile ──────────────────────────────────────────────────────────────────

PROFILE_ROOT_KEYS = [
    "uuid", "metadata", "imports", "merge", "modify", "back-matter",
]

PROFILE_IMPORT_KEYS = [
    "href", "include-all", "include-controls", "exclude-controls",
]

PROFILE_MERGE_KEYS = ["combine", "flat", "as-is", "custom"]

PROFILE_COMBINE_KEYS = ["method"]

PROFILE_CUSTOM_KEYS = ["groups", "insert-controls"]

PROFILE_CUSTOM_GROUP_KEYS = [
    "id", "class", "title", "params", "props", "links", "parts", "groups",
    "insert-controls",
]

PROFILE_INSERT_CONTROLS_KEYS = [
    "order", "include-all", "include-controls", "exclude-controls",
]

PROFILE_MODIFY_KEYS = ["set-parameters", "alters"]

PROFILE_SET_PARAM_KEYS = [
    "param-id", "class", "depends-on", "props", "links", "label", "usage",
    "constraints", "guidelines", "values", "select", "remarks",
]

PROFILE_ALTER_KEYS = [
    "control-id", "removes", "adds",
]

PROFILE_REMOVE_KEYS = [
    "by-name", "by-class", "by-id", "by-item-name", "by-ns",
]

PROFILE_ADD_KEYS = [
    "position", "by-id", "title", "params", "props", "links", "parts",
]

PROFILE_INCLUDE_CONTROLS_KEYS = [
    "with-ids", "matching",
]

PROFILE_MATCHING_KEYS = ["pattern"]

# ── Component Definition ─────────────────────────────────────────────────────

COMPONENT_DEF_ROOT_KEYS = [
    "uuid", "metadata", "import-component-definitions", "components",
    "capabilities", "back-matter",
]

COMPONENT_DEF_IMPORT_KEYS = ["href"]

COMPONENT_DEF_COMPONENT_KEYS = [
    "uuid", "type", "title", "description", "purpose", "props", "links",
    "responsible-roles", "protocols", "control-implementations", "remarks",
]

COMPONENT_DEF_CAPABILITY_KEYS = [
    "uuid", "name", "description", "props", "links",
    "incorporates-components", "control-implementations", "remarks",
]

COMPONENT_DEF_INCORPORATES_KEYS = [
    "component-uuid", "description",
]

COMPONENT_DEF_CONTROL_IMPL_KEYS = [
    "uuid", "source", "description", "props", "links", "set-parameters",
    "implemented-requirements",
]

COMPONENT_DEF_IMPL_REQ_KEYS = [
    "uuid", "control-id", "description", "props", "links", "set-parameters",
    "responsible-roles", "statements", "remarks",
]

COMPONENT_DEF_STATEMENT_KEYS = [
    "statement-id", "uuid", "description", "props", "links",
    "responsible-roles", "remarks",
]

COMPONENT_DEF_PROTOCOL_KEYS = [
    "uuid", "name", "title", "port-ranges",
]

COMPONENT_DEF_PORT_RANGE_KEYS = [
    "start", "end", "transport",
]

COMPONENT_DEF_RESPONSIBLE_ROLE_KEYS = [
    "role-id", "props", "links", "party-uuids", "remarks",
]

COMPONENT_DEF_SET_PARAM_KEYS = [
    "param-id", "values", "remarks",
]

# ── System Security Plan (SSP) ───────────────────────────────────────────────

SSP_ROOT_KEYS = [
    "uuid", "metadata", "import-profile", "system-characteristics",
    "system-implementation", "control-implementation", "back-matter",
]

SSP_IMPORT_PROFILE_KEYS = ["href", "remarks"]

SSP_SYSTEM_CHARACTERISTICS_KEYS = [
    "system-ids", "system-name", "system-name-short", "description",
    "props", "links", "date-authorized", "security-sensitivity-level",
    "system-information", "security-impact-level", "status",
    "authorization-boundary", "network-architecture", "data-flow", "remarks",
]

SSP_SYSTEM_ID_KEYS = ["identifier-type", "id"]

SSP_SYSTEM_INFO_KEYS = [
    "props", "links", "information-types",
]

SSP_INFO_TYPE_KEYS = [
    "uuid", "title", "description", "categorizations", "props", "links",
    "confidentiality-impact", "integrity-impact", "availability-impact",
]

SSP_CATEGORIZATION_KEYS = ["system", "information-type-ids"]

SSP_IMPACT_KEYS = [
    "props", "links", "base", "selected", "adjustment-justification",
]

SSP_SECURITY_IMPACT_LEVEL_KEYS = [
    "security-objective-confidentiality",
    "security-objective-integrity",
    "security-objective-availability",
]

SSP_STATUS_KEYS = ["state", "remarks"]

SSP_AUTH_BOUNDARY_KEYS = [
    "description", "props", "links", "diagrams", "remarks",
]

SSP_DIAGRAM_KEYS = [
    "uuid", "description", "props", "links", "caption", "remarks",
]

SSP_NETWORK_ARCH_KEYS = [
    "description", "props", "links", "diagrams", "remarks",
]

SSP_DATA_FLOW_KEYS = [
    "description", "props", "links", "diagrams", "remarks",
]

SSP_SYSTEM_IMPL_KEYS = [
    "props", "links", "leveraged-authorizations", "users", "components",
    "inventory-items", "remarks",
]

SSP_LEVERAGED_AUTH_KEYS = [
    "uuid", "title", "props", "links", "party-uuid", "date-authorized",
    "remarks",
]

SSP_USER_KEYS = [
    "uuid", "title", "short-name", "description", "props", "links",
    "role-ids", "authorized-privileges", "remarks",
]

SSP_PRIVILEGE_KEYS = [
    "title", "description", "functions-performed",
]

SSP_COMPONENT_KEYS = [
    "uuid", "type", "title", "description", "purpose", "props", "links",
    "status", "responsible-roles", "protocols", "remarks",
]

SSP_INVENTORY_ITEM_KEYS = [
    "uuid", "description", "props", "links", "responsible-parties",
    "implemented-components", "remarks",
]

SSP_IMPL_COMPONENT_KEYS = [
    "component-uuid", "props", "links", "responsible-parties", "remarks",
]

SSP_CONTROL_IMPL_KEYS = [
    "description", "set-parameters", "implemented-requirements",
]

SSP_IMPL_REQ_KEYS = [
    "uuid", "control-id", "props", "links", "set-parameters",
    "responsible-roles", "statements", "by-components", "remarks",
]

SSP_STATEMENT_KEYS = [
    "statement-id", "uuid", "props", "links", "responsible-roles",
    "by-components", "remarks",
]

SSP_BY_COMPONENT_KEYS = [
    "component-uuid", "uuid", "description", "props", "links",
    "set-parameters", "implementation-status", "export", "inherited",
    "satisfied", "responsible-roles", "remarks",
]

SSP_IMPL_STATUS_KEYS = ["state", "remarks"]

SSP_EXPORT_KEYS = [
    "description", "props", "links", "provided", "responsibilities", "remarks",
]

SSP_PROVIDED_KEYS = [
    "uuid", "description", "props", "links", "responsible-roles", "remarks",
]

SSP_RESPONSIBILITY_KEYS = [
    "uuid", "provided-uuid", "description", "props", "links",
    "responsible-roles", "remarks",
]

SSP_INHERITED_KEYS = [
    "uuid", "provided-uuid", "description", "props", "links",
    "responsible-roles",
]

SSP_SATISFIED_KEYS = [
    "uuid", "responsibility-uuid", "description", "props", "links",
    "responsible-roles", "remarks",
]

# ── Assessment Plan (SAP) ────────────────────────────────────────────────────

SAP_ROOT_KEYS = [
    "uuid", "metadata", "import-ssp", "local-definitions",
    "terms-and-conditions", "reviewed-controls", "assessment-subjects",
    "assessment-assets", "tasks", "back-matter",
]

SAP_IMPORT_SSP_KEYS = ["href", "remarks"]

SAP_LOCAL_DEFS_KEYS = [
    "objectives-and-methods", "activities", "remarks",
]

SAP_OBJ_METHOD_KEYS = [
    "uuid", "control-id", "description", "props", "links", "parts", "remarks",
]

SAP_ACTIVITY_KEYS = [
    "uuid", "title", "description", "props", "links", "steps",
    "related-controls", "responsible-roles", "remarks",
]

SAP_STEP_KEYS = [
    "uuid", "title", "description", "props", "links", "reviewed-controls",
    "responsible-roles", "remarks",
]

SAP_TERMS_CONDS_KEYS = ["parts"]

SAP_REVIEWED_CONTROLS_KEYS = [
    "description", "props", "links", "control-objective-selections",
    "control-selections", "remarks",
]

SAP_CONTROL_SELECTION_KEYS = [
    "description", "props", "links", "include-all", "include-controls",
    "exclude-controls", "remarks",
]

SAP_CONTROL_OBJECTIVE_SELECTION_KEYS = [
    "description", "props", "links", "include-all", "include-objectives",
    "exclude-objectives", "remarks",
]

SAP_INCLUDE_CONTROL_KEYS = ["control-id", "statement-ids"]

SAP_INCLUDE_OBJECTIVE_KEYS = ["control-id"]

SAP_ASSESSMENT_SUBJECT_KEYS = [
    "type", "description", "props", "links", "include-all",
    "include-subjects", "exclude-subjects", "remarks",
]

SAP_SUBJECT_REFERENCE_KEYS = [
    "subject-uuid", "type", "title", "props", "links", "remarks",
]

SAP_ASSESSMENT_ASSETS_KEYS = [
    "components", "assessment-platforms",
]

SAP_ASSESSMENT_PLATFORM_KEYS = [
    "uuid", "title", "props", "links", "uses-components", "remarks",
]

SAP_USES_COMPONENT_KEYS = [
    "component-uuid", "props", "links", "remarks",
]

SAP_TASK_KEYS = [
    "uuid", "type", "title", "description", "props", "links", "timing",
    "dependencies", "tasks", "responsible-roles", "subjects",
    "associated-activities", "remarks",
]

SAP_TIMING_KEYS = [
    "on-date", "within-date-range", "at-frequency",
]

SAP_ON_DATE_KEYS = ["date"]

SAP_DATE_RANGE_KEYS = ["start", "end"]

SAP_AT_FREQUENCY_KEYS = ["period", "unit"]

SAP_DEPENDENCY_KEYS = ["task-uuid", "remarks"]

SAP_ASSOCIATED_ACTIVITY_KEYS = [
    "activity-uuid", "props", "links", "responsible-roles", "subjects",
    "remarks",
]

# ── Assessment Results (SAR) ─────────────────────────────────────────────────

SAR_ROOT_KEYS = [
    "uuid", "metadata", "import-ap", "local-definitions", "results",
    "back-matter",
]

SAR_IMPORT_AP_KEYS = ["href", "remarks"]

SAR_LOCAL_DEFS_KEYS = [
    "objectives-and-methods", "activities", "remarks",
]

SAR_RESULT_KEYS = [
    "uuid", "title", "description", "start", "end", "props", "links",
    "local-definitions", "reviewed-controls", "attestations",
    "assessment-log", "observations", "risks", "findings", "remarks",
]

SAR_RESULT_LOCAL_DEFS_KEYS = [
    "objectives-and-methods", "components", "inventory-items", "users",
    "assessment-assets", "tasks", "remarks",
]

SAR_ATTESTATION_KEYS = [
    "responsible-parties", "parts",
]

SAR_ASSESSMENT_LOG_KEYS = ["entries"]

SAR_LOG_ENTRY_KEYS = [
    "uuid", "title", "description", "start", "end", "props", "links",
    "logged-by", "related-tasks", "remarks",
]

SAR_LOGGED_BY_KEYS = ["party-uuid", "role-id"]

SAR_RELATED_TASK_KEYS = [
    "task-uuid", "props", "links", "responsible-parties",
    "subjects", "identified-subject", "remarks",
]

SAR_IDENTIFIED_SUBJECT_KEYS = [
    "subject-placeholder-uuid", "subjects",
]

SAR_OBSERVATION_KEYS = [
    "uuid", "title", "description", "props", "links", "methods", "types",
    "origins", "subjects", "relevant-evidence", "collected", "expires",
    "remarks",
]

SAR_ORIGIN_KEYS = ["actors", "related-tasks"]

SAR_ORIGIN_ACTOR_KEYS = [
    "type", "actor-uuid", "role-id", "props", "links",
]

SAR_RELEVANT_EVIDENCE_KEYS = [
    "href", "description", "props", "links", "remarks",
]

SAR_RISK_KEYS = [
    "uuid", "title", "description", "statement", "props", "links",
    "status", "origins", "threat-ids", "characterizations",
    "mitigating-factors", "deadline", "remediations", "risk-log",
    "related-observations", "remarks",
]

SAR_THREAT_ID_KEYS = ["system", "href", "id"]

SAR_CHARACTERIZATION_KEYS = ["props", "links", "origin", "facets"]

SAR_FACET_KEYS = [
    "name", "system", "value", "props", "links", "remarks",
]

SAR_MITIGATING_FACTOR_KEYS = [
    "uuid", "implementation-uuid", "description", "props", "links",
    "subjects",
]

SAR_REMEDIATION_KEYS = [
    "uuid", "lifecycle", "title", "description", "props", "links", "origins",
    "required-assets", "tasks", "remarks",
]

SAR_REQUIRED_ASSET_KEYS = [
    "uuid", "subjects", "title", "description", "props", "links", "remarks",
]

SAR_RISK_LOG_KEYS = ["entries"]

SAR_RISK_LOG_ENTRY_KEYS = [
    "uuid", "title", "description", "start", "end", "props", "links",
    "logged-by", "status-change", "related-responses", "remarks",
]

SAR_RELATED_RESPONSE_KEYS = [
    "response-uuid", "props", "links", "related-tasks", "remarks",
]

SAR_FINDING_KEYS = [
    "uuid", "title", "description", "props", "links", "origins", "target",
    "implementation-statement-uuid", "related-observations", "related-risks",
    "remarks",
]

SAR_FINDING_TARGET_KEYS = [
    "type", "target-id", "title", "description", "props", "links", "status",
    "implementation-status", "remarks",
]

SAR_FINDING_TARGET_STATUS_KEYS = ["state", "reason", "remarks"]

SAR_RELATED_OBS_KEYS = ["observation-uuid"]

SAR_RELATED_RISK_KEYS = ["risk-uuid"]

# ── POA&M ────────────────────────────────────────────────────────────────────

POAM_ROOT_KEYS = [
    "uuid", "metadata", "import-ssp", "system-id", "local-definitions",
    "observations", "risks", "findings", "poam-items", "back-matter",
]

POAM_LOCAL_DEFS_KEYS = [
    "components", "inventory-items", "remarks",
]

POAM_ITEM_KEYS = [
    "uuid", "title", "description", "props", "links", "origins",
    "related-findings", "related-observations", "related-risks", "remarks",
]

POAM_RELATED_FINDING_KEYS = ["finding-uuid"]

# ── Mapping Collection ───────────────────────────────────────────────────────

MAPPING_COLLECTION_ROOT_KEYS = [
    "uuid", "metadata", "provenance", "mappings", "back-matter",
]

MAPPING_PROVENANCE_KEYS = [
    "method", "matching-rationale", "status", "confidence-score",
    "coverage", "mapping-description", "responsible-parties", "props",
    "links", "remarks",
]

MAPPING_KEYS = [
    "uuid", "method", "matching-rationale", "status", "source-resource",
    "target-resource", "maps", "props", "links", "remarks",
    "mapping-description", "source-gap-summary", "target-gap-summary",
    "confidence-score", "coverage",
]

MAPPING_MAP_ENTRY_KEYS = [
    "uuid", "ns", "matching-rationale", "relationship", "sources",
    "targets", "qualifiers", "confidence-score", "coverage", "props",
    "links", "remarks",
]

MAPPING_ITEM_KEYS = [
    "type", "id-ref", "props", "links", "remarks",
]

MAPPING_RESOURCE_REFERENCE_KEYS = [
    "ns", "type", "href", "props", "links", "remarks",
]

MAPPING_QUALIFIER_KEYS = [
    "subject", "predicate", "category", "description", "remarks",
]

MAPPING_GAP_SUMMARY_KEYS = [
    "uuid", "unmapped-controls",
]

MAPPING_CONFIDENCE_SCORE_KEYS = ["category", "percentage"]

MAPPING_COVERAGE_KEYS = ["generation-method", "target-coverage"]

MAPPING_SELECT_CONTROL_KEYS = [
    "with-child-controls", "with-ids", "matching",
]

# ── Master dispatch table ────────────────────────────────────────────────────
# Maps (context_path_tuple, key_name) → ordered_key_list.
# A context path of ("*",) acts as a wildcard for objects matched anywhere
# under that parent key name, and ("**",) matches the key regardless of depth.
#
# For simplicity we use a flat name-based dispatch: when ordering an object
# whose parent key is <parent>, look up ORDERING_BY_PARENT[parent].

ORDERING_BY_PARENT: dict[str, list[str]] = {
    # ── Root model objects ──────────────────────────────────────────────────
    "catalog":                      CATALOG_ROOT_KEYS,
    "profile":                      PROFILE_ROOT_KEYS,
    "mapping":                      MAPPING_COLLECTION_ROOT_KEYS,
    "mapping-collection":           MAPPING_COLLECTION_ROOT_KEYS,
    "component-definition":         COMPONENT_DEF_ROOT_KEYS,
    "system-security-plan":         SSP_ROOT_KEYS,
    "assessment-plan":              SAP_ROOT_KEYS,
    "assessment-results":           SAR_ROOT_KEYS,
    "plan-of-action-and-milestones": POAM_ROOT_KEYS,

    # ── Common / shared ─────────────────────────────────────────────────────
    "metadata":                     COMMON_METADATA_KEYS,
    "back-matter":                  COMMON_BACK_MATTER_KEYS,
    "resources":                    COMMON_RESOURCE_KEYS,
    "citation":                     COMMON_CITATION_KEYS,
    "rlinks":                       COMMON_RLINK_KEYS,
    "base64":                       COMMON_BASE64_KEYS,
    "revisions":                    COMMON_REVISION_KEYS,
    "roles":                        COMMON_ROLE_KEYS,
    "locations":                    COMMON_LOCATION_KEYS,
    "address":                      COMMON_ADDRESS_KEYS,
    "parties":                      COMMON_PARTY_KEYS,
    "responsible-parties":          COMMON_RESPONSIBLE_PARTY_KEYS,
    "responsible-party":            COMMON_RESPONSIBLE_PARTY_KEYS,
    "props":                        COMMON_PROP_KEYS,
    "links":                        COMMON_LINK_KEYS,
    "hashes":                       COMMON_HASH_KEYS,
    "document-ids":                 COMMON_DOCUMENT_ID_KEYS,
    "external-ids":                 COMMON_EXTERNAL_ID_KEYS,
    "telephone-numbers":            COMMON_TELEPHONE_KEYS,

    # ── Catalog ─────────────────────────────────────────────────────────────
    "groups":                       CATALOG_GROUP_KEYS,
    "controls":                     CATALOG_CONTROL_KEYS,
    "params":                       CATALOG_PARAM_KEYS,
    "parts":                        CATALOG_PART_KEYS,
    "constraints":                  CATALOG_CONSTRAINT_KEYS,
    "tests":                        CATALOG_CONSTRAINT_TEST_KEYS,
    "guidelines":                   CATALOG_GUIDELINE_KEYS,
    "select":                       CATALOG_SELECT_KEYS,

    # ── Profile ─────────────────────────────────────────────────────────────
    "imports":                      PROFILE_IMPORT_KEYS,
    "merge":                        PROFILE_MERGE_KEYS,
    "combine":                      PROFILE_COMBINE_KEYS,
    "custom":                       PROFILE_CUSTOM_KEYS,
    "insert-controls":              PROFILE_INSERT_CONTROLS_KEYS,
    "modify":                       PROFILE_MODIFY_KEYS,
    "set-parameters":               PROFILE_SET_PARAM_KEYS,
    "alters":                       PROFILE_ALTER_KEYS,
    "removes":                      PROFILE_REMOVE_KEYS,
    "adds":                         PROFILE_ADD_KEYS,
    "include-controls":             PROFILE_INCLUDE_CONTROLS_KEYS,
    "matching":                     PROFILE_MATCHING_KEYS,

    # ── Component Definition ─────────────────────────────────────────────────
    "import-component-definitions": COMPONENT_DEF_IMPORT_KEYS,
    "components":                   COMPONENT_DEF_COMPONENT_KEYS,
    "capabilities":                 COMPONENT_DEF_CAPABILITY_KEYS,
    "incorporates-components":      COMPONENT_DEF_INCORPORATES_KEYS,
    "control-implementations":      COMPONENT_DEF_CONTROL_IMPL_KEYS,
    "implemented-requirements":     COMPONENT_DEF_IMPL_REQ_KEYS,
    "statements":                   COMPONENT_DEF_STATEMENT_KEYS,
    "protocols":                    COMPONENT_DEF_PROTOCOL_KEYS,
    "port-ranges":                  COMPONENT_DEF_PORT_RANGE_KEYS,
    "responsible-roles":            COMPONENT_DEF_RESPONSIBLE_ROLE_KEYS,
    "responsible-role":             COMPONENT_DEF_RESPONSIBLE_ROLE_KEYS,

    # ── SSP ─────────────────────────────────────────────────────────────────
    "import-profile":               SSP_IMPORT_PROFILE_KEYS,
    "system-characteristics":       SSP_SYSTEM_CHARACTERISTICS_KEYS,
    "system-ids":                   SSP_SYSTEM_ID_KEYS,
    "system-information":           SSP_SYSTEM_INFO_KEYS,
    "information-types":            SSP_INFO_TYPE_KEYS,
    "categorizations":              SSP_CATEGORIZATION_KEYS,
    "confidentiality-impact":       SSP_IMPACT_KEYS,
    "integrity-impact":             SSP_IMPACT_KEYS,
    "availability-impact":          SSP_IMPACT_KEYS,
    "security-impact-level":        SSP_SECURITY_IMPACT_LEVEL_KEYS,
    "status":                       SSP_STATUS_KEYS,
    "authorization-boundary":       SSP_AUTH_BOUNDARY_KEYS,
    "diagrams":                     SSP_DIAGRAM_KEYS,
    "network-architecture":         SSP_NETWORK_ARCH_KEYS,
    "data-flow":                    SSP_DATA_FLOW_KEYS,
    "system-implementation":        SSP_SYSTEM_IMPL_KEYS,
    "leveraged-authorizations":     SSP_LEVERAGED_AUTH_KEYS,
    "users":                        SSP_USER_KEYS,
    "authorized-privileges":        SSP_PRIVILEGE_KEYS,
    "inventory-items":              SSP_INVENTORY_ITEM_KEYS,
    "implemented-components":       SSP_IMPL_COMPONENT_KEYS,
    "control-implementation":       SSP_CONTROL_IMPL_KEYS,
    "by-components":                SSP_BY_COMPONENT_KEYS,
    "implementation-status":        SSP_IMPL_STATUS_KEYS,
    "export":                       SSP_EXPORT_KEYS,
    "provided":                     SSP_PROVIDED_KEYS,
    "responsibilities":             SSP_RESPONSIBILITY_KEYS,
    "inherited":                    SSP_INHERITED_KEYS,
    "satisfied":                    SSP_SATISFIED_KEYS,

    # ── SAP ─────────────────────────────────────────────────────────────────
    "import-ssp":                   SAP_IMPORT_SSP_KEYS,
    "local-definitions":            SAP_LOCAL_DEFS_KEYS,   # overridden in SAR
    "objectives-and-methods":       SAP_OBJ_METHOD_KEYS,
    "activities":                   SAP_ACTIVITY_KEYS,
    "steps":                        SAP_STEP_KEYS,
    "terms-and-conditions":         SAP_TERMS_CONDS_KEYS,
    "reviewed-controls":            SAP_REVIEWED_CONTROLS_KEYS,
    "control-selections":           SAP_CONTROL_SELECTION_KEYS,
    "control-objective-selections": SAP_CONTROL_OBJECTIVE_SELECTION_KEYS,
    "include-objectives":           SAP_INCLUDE_OBJECTIVE_KEYS,
    "assessment-subjects":          SAP_ASSESSMENT_SUBJECT_KEYS,
    "include-subjects":             SAP_SUBJECT_REFERENCE_KEYS,
    "exclude-subjects":             SAP_SUBJECT_REFERENCE_KEYS,
    "assessment-assets":            SAP_ASSESSMENT_ASSETS_KEYS,
    "assessment-platforms":         SAP_ASSESSMENT_PLATFORM_KEYS,
    "uses-components":              SAP_USES_COMPONENT_KEYS,
    "tasks":                        SAP_TASK_KEYS,
    "timing":                       SAP_TIMING_KEYS,
    "on-date":                      SAP_ON_DATE_KEYS,
    "within-date-range":            SAP_DATE_RANGE_KEYS,
    "at-frequency":                 SAP_AT_FREQUENCY_KEYS,
    "dependencies":                 SAP_DEPENDENCY_KEYS,
    "associated-activities":        SAP_ASSOCIATED_ACTIVITY_KEYS,

    # ── SAR ─────────────────────────────────────────────────────────────────
    "import-ap":                    SAR_IMPORT_AP_KEYS,
    "results":                      SAR_RESULT_KEYS,
    "attestations":                 SAR_ATTESTATION_KEYS,
    "assessment-log":               SAR_ASSESSMENT_LOG_KEYS,
    "entries":                      SAR_LOG_ENTRY_KEYS,
    "logged-by":                    SAR_LOGGED_BY_KEYS,
    "related-tasks":                SAR_RELATED_TASK_KEYS,
    "identified-subject":           SAR_IDENTIFIED_SUBJECT_KEYS,
    "observations":                 SAR_OBSERVATION_KEYS,
    "origins":                      SAR_ORIGIN_KEYS,
    "actors":                       SAR_ORIGIN_ACTOR_KEYS,
    "relevant-evidence":            SAR_RELEVANT_EVIDENCE_KEYS,
    "risks":                        SAR_RISK_KEYS,
    "threat-ids":                   SAR_THREAT_ID_KEYS,
    "characterizations":            SAR_CHARACTERIZATION_KEYS,
    "facets":                       SAR_FACET_KEYS,
    "mitigating-factors":           SAR_MITIGATING_FACTOR_KEYS,
    "remediations":                 SAR_REMEDIATION_KEYS,
    "required-assets":              SAR_REQUIRED_ASSET_KEYS,
    "risk-log":                     SAR_RISK_LOG_KEYS,
    "related-responses":            SAR_RELATED_RESPONSE_KEYS,
    "findings":                     SAR_FINDING_KEYS,
    "target":                       SAR_FINDING_TARGET_KEYS,
    "related-observations":         SAR_RELATED_OBS_KEYS,
    "related-risks":                SAR_RELATED_RISK_KEYS,

    # ── POA&M ────────────────────────────────────────────────────────────────
    "plan-of-action-and-milestones.local-definitions": POAM_LOCAL_DEFS_KEYS,
    "poam-items":                   POAM_ITEM_KEYS,
    "related-findings":             POAM_RELATED_FINDING_KEYS,

    # ── Mapping Collection ─────────────────────────────────────────────────
    "provenance":                   MAPPING_PROVENANCE_KEYS,
    "mappings":                     MAPPING_KEYS,
    "maps":                         MAPPING_MAP_ENTRY_KEYS,
    "source-resource":              MAPPING_RESOURCE_REFERENCE_KEYS,
    "target-resource":              MAPPING_RESOURCE_REFERENCE_KEYS,
    "sources":                      MAPPING_ITEM_KEYS,
    "targets":                      MAPPING_ITEM_KEYS,
    "qualifiers":                   MAPPING_QUALIFIER_KEYS,
    "source-gap-summary":           MAPPING_GAP_SUMMARY_KEYS,
    "target-gap-summary":           MAPPING_GAP_SUMMARY_KEYS,
    "confidence-score":             MAPPING_CONFIDENCE_SCORE_KEYS,
    "coverage":                     MAPPING_COVERAGE_KEYS,
    "unmapped-controls":            MAPPING_SELECT_CONTROL_KEYS,
}


def _canonical_key_order(parent_key: Optional[str], model_root_key: Optional[str]) -> Optional[List[str]]:
    """
    Return the canonical key list for an object whose parent field name is
    *parent_key* within the given *model_root_key* (e.g. "system-security-plan").

    Returns None when no ordering rule is known (object is left as-is).
    """
    if parent_key is None:
        return None

    # Check for model-qualified override first (e.g. POA&M local-definitions)
    if model_root_key:
        qualified = f"{model_root_key}.{parent_key}"
        if qualified in ORDERING_BY_PARENT:
            return ORDERING_BY_PARENT[qualified]

    return ORDERING_BY_PARENT.get(parent_key)


def _reorder_dict(d: dict, ordered_keys: List[str]) -> dict:
    """
    Return a new dict with keys from *ordered_keys* first (in that order),
    followed by any remaining keys not in *ordered_keys* (preserving their
    original relative order).
    """
    result: dict = {}
    for k in ordered_keys:
        if k in d:
            result[k] = d[k]
    for k in d:
        if k not in result:
            result[k] = d[k]
    return result


def _resequence_value(value, parent_key: Optional[str], model_root_key: Optional[str]):
    """
    Recursively resequence *value*. Returns the resequenced value.
    """
    if isinstance(value, dict):
        # Determine if this dict itself should be reordered based on parent_key
        ordered_keys = _canonical_key_order(parent_key, model_root_key)
        if ordered_keys:
            value = _reorder_dict(value, ordered_keys)

        # Now recurse into each child value
        return {
            k: _resequence_value(v, parent_key=k, model_root_key=model_root_key)
            for k, v in value.items()
        }

    elif isinstance(value, list):
        return [
            _resequence_value(item, parent_key=parent_key, model_root_key=model_root_key)
            for item in value
        ]

    else:
        # Scalar — nothing to reorder
        return value


def _detect_model_root_key(data: dict) -> Optional[str]:
    """Identify which OSCAL model root key is present in the document."""
    known_roots = [
        "catalog",
        "profile",
        "mapping",
        "mapping-collection",
        "component-definition",
        "system-security-plan",
        "assessment-plan",
        "assessment-results",
        "plan-of-action-and-milestones",
    ]
    for root in known_roots:
        if root in data:
            return root
    return None


def resequence_oscal(data: dict) -> dict:
    """
    Resequence all keys in an OSCAL document dict to match NIST 1.2.0
    canonical ordering.  The document root itself is also reordered so that
    the single model root key comes first.

    Args:
        data: Parsed OSCAL document as a Python dict.

    Returns:
        New dict with keys in canonical order (same data, new ordering).
    """
    model_root_key = _detect_model_root_key(data)

    # Resequence from the top level; pass parent_key=None for the outermost
    # wrapper (the file may have a single root key like "catalog": {...})
    result: dict = {}
    if model_root_key and model_root_key in data:
        # Put the known root key first, then any unknowns (e.g. "$schema")
        for k, v in data.items():
            if k != model_root_key:
                result[k] = _resequence_value(v, parent_key=k, model_root_key=model_root_key)
        # Now place the root model object, fully resequenced
        root_obj = data[model_root_key]
        root_obj = _resequence_value(root_obj, parent_key=model_root_key, model_root_key=model_root_key)
        final: dict = {model_root_key: root_obj}
        final.update(result)   # any extra top-level keys after
        return final
    else:
        # Unknown or no root key — still recurse to resequence what we can
        return {
            k: _resequence_value(v, parent_key=k, model_root_key=model_root_key)
            for k, v in data.items()
        }


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def _detect_format(path: Path) -> str:
    """Return 'json' or 'yaml' based on file extension."""
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    elif suffix in (".yaml", ".yml"):
        return "yaml"
    else:
        # Try sniffing the first non-whitespace character
        try:
            text = path.read_text(encoding="utf-8").lstrip()
            if text.startswith("{") or text.startswith("["):
                return "json"
        except OSError:
            pass
        return "yaml"  # default fallback


def _load_file(path: Path, fmt: str) -> dict:
    text = path.read_text(encoding="utf-8")
    if fmt == "json":
        return json.loads(text)
    else:
        if not YAML_AVAILABLE:
            raise ImportError(
                "PyYAML is not installed. Install it with: pip install pyyaml"
            )
        return yaml.load(text, Loader=_OscalLoader) # type: ignore


def _dump_file(data: dict, path: Path, fmt: str) -> None:
    if fmt == "json":
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    else:
        if not YAML_AVAILABLE:
            raise ImportError(
                "PyYAML is not installed. Install it with: pip install pyyaml"
            )
        text = yaml.dump( # type: ignore
            data,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,    # preserve our manually-imposed ordering
            indent=2,
            width=120,
        )
    path.write_text(text, encoding="utf-8")


def resequence_oscal_file(
    input_path: Union[str, Path],
    output_path: Union[str, Path, None] = None,
) -> Path:
    """
    Load an OSCAL JSON or YAML file, resequence all keys to match the NIST
    OSCAL 1.2.0 canonical ordering, and write the result.

    Args:
        input_path:  Path to the source OSCAL file.
        output_path: Destination path.  If None, the input file is overwritten
                     in-place.

    Returns:
        The Path object of the written output file.
    """
    input_path = Path(input_path)
    if output_path is None:
        output_path = input_path
    output_path = Path(output_path)

    fmt = _detect_format(input_path)
    data = _load_file(input_path, fmt)
    ordered = resequence_oscal(data)

    # Use the output file's extension to determine output format (allows
    # implicit JSON→YAML or YAML→JSON conversion if extensions differ).
    out_fmt = _detect_format(output_path)
    _dump_file(ordered, output_path, out_fmt)

    return output_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else None

    if not input_path.exists():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    out = resequence_oscal_file(input_path, output_path)
    action = "resequenced in-place" if output_path is None or output_path == input_path else f"written to {out}"
    model = _detect_model_root_key(_load_file(input_path, _detect_format(input_path))) or "unknown model"
    print(f"✓ [{model}] {input_path.name} — {action}")


if __name__ == "__main__":
    main()
