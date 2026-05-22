# OSCAL JSON Schema Errors

## Summary

Analysis of the NIST-published OSCAL profile JSON schemas stored in the support database for the five most recent OSCAL versions reveals a regression introduced in v1.2.0 that persists through v1.2.2.

## Versions Checked

| Version | `combine.method` present | Status |
|---------|--------------------------|--------|
| v1.2.2  | No | ❌ Broken |
| v1.2.1  | No | ❌ Broken |
| v1.2.0  | No | ❌ Broken |
| v1.1.3  | Yes | ✅ Correct |
| v1.1.2  | Yes | ✅ Correct |

## The Bug

### Location
`definitions["oscal-profile-oscal-profile:merge"].anyOf[*].properties.combine`

### What is broken

In v1.2.0, NIST restructured the `merge` assembly definition from a flat `properties` object to an `anyOf` constraint (to enforce mutual exclusivity between the three merge strategies: `flat`, `as-is`, and `custom`). During that restructuring, the `method` property was dropped from the `combine` object in all three `anyOf` options.

As a result, in v1.2.x the `combine` object is defined as:

```json
{
  "title": "Combination Rule",
  "type": "object",
  "additionalProperties": false
}
```

With `additionalProperties: false` and no `properties` defined, this makes `combine` an object that must be completely empty — rejecting the valid JSON `{"method": "keep"}`.

### What it should be (per v1.1.3 and the OSCAL metaschema)

```json
{
  "title": "Combination Rule",
  "type": "object",
  "properties": {
    "method": {
      "title": "Combination Method",
      "description": "Declare how clashing controls should be handled.",
      "allOf": [
        { "$ref": "#/definitions/StringDatatype" },
        { "enum": ["use-first", "merge", "keep"] }
      ]
    }
  },
  "additionalProperties": false
}
```

### Impact

Any OSCAL profile document containing `<combine method="..."/>` (valid per the XML schema and the OSCAL metaschema in all versions) will fail JSON schema validation for v1.2.0 through v1.2.2. This causes the `oscal-class` library to mark such profiles as schema-invalid, which blocks import resolution and all dict-based operations.

## Verification via Metaschema Index

The processed metaschema index stored in the support database (`complete/processed` asset) correctly reflects the OSCAL specification. The node at `/profile/merge/combine/@method` is present in all checked v1.2.x indexes:

```json
{
  "path": "/profile/merge/combine/@method",
  "use-name": "method",
  "structure-type": "flag",
  "datatype": "string",
  "min-occurs": "0",
  "max-occurs": "1",
  "formal-name": "Combination Method"
}
```

This confirms the bug is in the generated JSON schema files, not in the OSCAL specification itself.

## Recommended Fix

Patch the stored `json-schema` assets for v1.2.0, v1.2.1, and v1.2.2 in the support database: add `method` back to `combine.properties` in all three `anyOf` options of `oscal-profile-oscal-profile:merge`. This can be done as a one-time repair applied during support database initialization, using the v1.1.3 definition as the reference.

This bug should also be reported to the NIST OSCAL project.
