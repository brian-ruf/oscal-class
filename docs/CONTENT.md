# OSCAL Class

A class for creation, management, validation and format convertion of OSCAL content.
All published OSCAL versions, formats and models can be validated and converted.
Creation and management is OSCAL 1.2.1 compliant.

OSCAL XML, JSON and YAML formats are supported.
This class ingests, validates and manages OSCAL content in its native format.

Conversion between XML and JSON in either direction uses NIST-published OSCAL support files to ensure accuracy.

## Model-Aware Content Acquisition

When you do not know the OSCAL model in advance, use the general `OSCAL` class to load/acquire the content first.
The model is determined during parsing and exposed via `.model`.

From there, you can return the appropriate model-specific class for typed workflows.

```python
from oscal import (
  OSCAL,
  Catalog,
  Profile,
  Mapping,
  ComponentDefinition,
  SSP,
  AssessmentPlan,
  AssessmentResults,
  POAM,
)

MODEL_CLASS_MAP = {
  "catalog": Catalog,
  "profile": Profile,
  "mapping-collection": Mapping,
  "component-definition": ComponentDefinition,
  "ssp": SSP,
  "assessment-plan": AssessmentPlan,
  "assessment-results": AssessmentResults,
  "poam": POAM,
}


def load_typed_oscal(path: str):
  """Return a model-specific OSCAL object when possible."""
  generic_obj = OSCAL.load(path)
  model_cls = MODEL_CLASS_MAP.get(generic_obj.model)

  if model_cls is None:
    return generic_obj

  return model_cls.load(path)


obj = load_typed_oscal("./example/catalog.xml")
print(type(obj).__name__)  # Catalog
print(obj.model)           # catalog
```


## OSCAL Class States

There are three state types within the OSCAL Class:
- **Content State**: The sate of the OSCAL content itself, which references validity.
- **Origin**: The origin of the OSCAL content, including characteristics related to local caching.
- **Synced**: The state of synchronization between OSCAL formats (XML/tree and JSON/YAML/dict)

### Content State (.content_state)

The content itself can have the following states in progression. Later items on the list cannot be satisfied if lower items on the list are not satisfied. 

- **Acquired** (or failed to acquire) (`.is_acquired`): The content was acquired successfully.
- **Well Formed** (or not well-formed) (`.is_well_formed`): The content is well-formed for its format (XML, JSON, or YAML).
- **schema Valid** (or not schema valid) (`.is_valid`): The content is valid to the appropriate OSCAL version and schema. _This is the minumum state for viewing and editing._
- **Imports Resolved** (or resolution errors) (`.imports_resolved`): All imports of other OSCAL content occurred successfully.
- **Core Metaschema Valid** (or not core metaschema valid) [FUTURE]: All constraints are satisfied in the core OSCAL metaschema.
- **Additional Metaschema Valid** (or not additional metaschema valid) [FUTURE]: All constraints are satisfied in any provided third-party metaschema.

These are defined in `oscal_content.py` as follows:

```python

class ContentState(IntEnum):
    NONE             = -1  # No content / uninitialized
    NOT_AVAILABLE    = 0  # Unable to acquire content
    ACQUIRED         = 1  # Content was acquired (non-empty string)
    WELL_FORMED      = 2  # Content is well-formed XML, JSON, or YAML
    VALID            = 3  # Content passes OSCAL schema validation (minimum for viewing/editing)
    IMPORTS_RESOLVED = 4  # All imported OSCAL documents resolved successfully
    # FUTURE: CORE_METASCHEMA_VALID = 5, ADDITIONAL_METASCHEMA_VALID = 6

```

#### Example Usage

```python

        obj = OSCAL.open(test_file)
        if obj:
            logger.info(f"Successfully loaded {test_file}")
        else:
            logger.error(f"Failed to load {test_file}")

        print("" + "=" * 25 + " LOAD RESULT " + "=" * 25)
        print(obj)
        if obj.is_valid:
            if obj.imports_resolved:
                print(obj.import_list)
                print(obj.import_tree)
            else:
                print("Imports not resolved.")
        elif obj.is_acquired and not obj.is_valid:
            print("Content was acquired, but is not valid.") # not well formed, or not schema valid
        elif obj.is_acquired:
            print("Content was not successfully loaded.")
```

### Origin State (`.`)

The following are states relative to the content's origin  
- **Local** (or remote) (`.is_local`): The OSCAL content was acquired either locally (relative to the executing code) or remotely. 
- **Cached** (or not) (`.is_cached`): Is the remote content cached locally or not?
  - This is only relevant for remote content. Ignored for local content.
- **Fresh** (or stale) The cached content is either within its time to live (TTL) or has exceeded it's TTL. 
  - As determined by adding:
    - `.loaded` (date/time of last acquisition) to
    - `.ttl` (time to live in seconds) and comparing to
    - _now_. 

### Additional States (`.`)

The following state is relative to format conversion and native mutations:
- **Read Only** (or read-write ) (`.is_read_only`): The OSCAL content may be altered, or must not be altered.
  - Remote content is always read-only.
  - Local content may be either read-write or read-only.
- **Synced** (or not): `.tree` and `.dict` are synchronized. (`.is_synced`)
- **Saved** (or not): The content has been mutated, but not saved. (`.is_saved`)

NOTE: local caching of remote content is not yet implemented.

## The Import List 

**THIS WILL BE IMPLEMENTEED IN V2.1.X**

Each OSCAL object maints a `dict` of its imported files in the `.import_list` attribute. This `dict` uses the following structure:

```python
self.import_list = [
    {
        "type": "import", # The statement type that generated the import (`import`, `source`, `target`, `control-implementation`)
        "href_original": "https://example.com/profile.xml", # href specifd in the content
        "href_valid"   : "https://example.com/root.xml",    # valid href (may be same as original or may be different if original could not be loaded)
        "href_local"   : "file://example.com/root.xml",     # local copy (cached copy if remote) 
        "valid": True,                                    # whether the content was successfully loaded and validated
        "remote": True,                                    # whether the source is remote (http/https) or local file
        "cached": True,                                    # whether a remote source has a local cache copy
        "writable": False,                                  # whether the local source is writable (vs read-only)
        "expires": "2024-01-01T00:00:00Z",                        # expiration timestamp for cached content (if applicable)
        "model" : "", # "catalog", "profile", "ssp", etc.
        "status": ImportStatus.FAILED,
        "error" : "",                               # why it failed (empty if loaded)
        "object": OSCAL object if loaded, else None
    } 
] 
```
For ease of processing any variation of syntax with `import` is assigned an `import` type. This includes:
- `import` in profiles;
- `import-component-definition` in cDefs;
- `import-profile` in SSPs;
- `import-ssp` in APs and POA&Ms; and
- `import-assessment-plan` in ARs. 

`source` and `target` are specific to the mapping model, and must be differentiated from each other. `control-implementation` is specific to the component definition model and must be differentiated from `import-component-definition`. 

=== 
Model office
- 800-53 r5 catalog
- Tailored NIST Moderate Moderate Profile
- Requirements for PostgreSQL CIS
- Ubuntu: DISA and CIS
