# OSCAL Class

A class for creation, manipulation, validation and format convertion of OSCAL content.
All published OSCAL versions, formats and models can be validated and converted.
Creation and manipulation is OSCAL 1.2.1 compliant where implemented.

OSCAL XML, JSON and YAML formats are supported.
This class ingests and validates OSCAL content in its native format using the appropriate
NIST-published OSCAL schema.

Conversion between XML and JSON in either direction uses the NIST-published conversion XSLT stylesheets.
Conversion between JSON and YAML in either direction uses internal conversion via Python dictionaries.

In the fFuture this library will perform validation and conversion using the NIST-published
OSCAL metaschema definitions, which include additional rules not handled by the XML and JSON schemas.



## OSCAL Class States

The OSCAL Class can have the following states. 

- valid or not valid (`self.valid`)
- local or remote (`self.remote`)
    - if remote (always read-only):
        - cached locally or not (self.cached)
            - if cached locally:
                - cache is valid or expired
    - if local:
        - read-only or read-write

- synced or not synced (`self.synced`)
    - native XML, JSON or YAML outupt
        - not synced requires syncing first
    - native JSON or YAML, XML output
        - not synced requires syncing first 


## The Import List

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
        "model" : "profile",                                # "profile" or "catalog"
        "status": ImportStatus.FAILED,
        "error" : "",                               # why it failed (empty if loaded)
        "object": OSCAL object if loaded, else None,
        "import_list": [ ... ]
    } 
] # An array of dictionaries representing imported OSCAL content
```
