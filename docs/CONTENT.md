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

The OSCAL Class can have the following states. 

- valid or not valid (`.valid`): The OSCAL content is either OSCAL schema valid or it is not.
- local or remote (`.remote`): The OSCAL content was acquired either locally (relative to the executing code) or remotely. 
- read-write or read-only (`.read_only`): The OSCAL content may be altered, or must not be altered.
  - Remote content is always treated as read-only.
  - Local content may be either read-write or read-only.
- cached or not (`.cached`): Is the remote content cached locally or not.
  - This is only relevant to remote content.
  - This is ignored for local content.
- cache is either valid or expired 
  - As determined by comparing `.loaded` (date/time of last acquisition) to `.ttl` (time to live in seconds) and the current date/time. 

- Synced: `.tree` and `.dict` are synchronized. (`.synced`)

NOTE: local caching of remote content is not yet implemented.

## The Import List 

**THIS WILL BE IMPLEMENTEED IN V2.1.X**

Each OSCAL object maints a `dict` of its imported files in the `.import_list` attribute. This `dict` uses the following structure:

```python
self.import_list = [
    {
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

