# OSCAL Class Concept of Operations (ConOps)

The core modules are:
- `oscal_content_class.py`: A class to contain and manage an OSCAL artifact. One instance per artifact.
- `oscal_support_class.py`: A class to manage tanages the NIST-published OSCAL support files. One instance per application. 

## `oscal_content_class` ConOps

This module includes the `OSCAL` class as well as several stand-alone functions that support processing of OSCAL content. The `OSCAL` class is designed to exist as one class instance per OSCAL document.

### Class Initiation:

1. Acquire Content
1. Validate Content

#### Acquire content

Content is acquired by the instance in one of two ways:
1. **Passed Directly**: When valid OSCAL XML, JSON or YAML content is passed directly via the `content` attribute.
1. **Loaded from File**: When valid OSCAL XML, JSON, or YAML content is present in an accessible file specified via the `filename` attribute.




#### Validate Content

Once acquired, content is interogated as follows:
1. Is the content a recognized OSCAL format?
1. Is the content well formed in its native format?
1. Does the content have a single `/*/metadata/oscal-version` field?
1. Is the value in the `oscal-version`field a supported* OSCAL version?
1. Is the root element a recognized OSCAL model-name for the specified `oscal-version`?
1. Based on the OSCAL format, version and model, is the content OSCAL schema-valid**?

NOTES:
- The OSCAL Class has an OSCAL support module that contains the NIST-published OSCAL validation and conversion support files for each OSCAL version. The support module can "learn" newer versions of OSCAL as they are published.  
- The appropriate XML schema is used for XML content. The appropriate JSON schema is used for JSON and YAML content.


## `oscal_support_class` ConOps

This module includes the `OSCAL_support` class and one stand-alone function. This class manages the NIST-published OSCAL support files (metaschema, schema, and converters) for supported OSCAL versions. 

It is designed to exist as one class instance per for the entire application and to shared by each `oscal_content_class` instance; however, there should not be issues if this class is instantiated more than once.

# JSON Native (Effective April 2026)

The OSCAL class uses JSON for processing of OSCAL Content internally.

## Acquisition

Upon acquisition, OSCAL JSON and YAML are immediately converted to a Python dict. 
`JSON or YAML -> dict -> validation`

Upon acquisition, OSCAL XML is initially converted to an ElementTree object, validated, then converted to OSCAL JSON and then to a Python dict. 
`XML -> ET -> validation -> converter -> JSON -> dict`

## Exportation

When exporting to OSCAL JSON or YAML, the Python dict is serialized directly to JSON or YAML. 
`dict -> JSON or YAML`

When exporting to OSCAL XML, the Python dict is serialized to JSON and converted to XML. 
`dict -> JSON -> converter -> XML`

## Metaschema Validation (Future)

When using metaschema to validate OSCAL content, the dict is serialized to JSON, converted to XML, converted to an ElemenetTree and processed using metaschema xPath.  
`dict -> JSON -> converter -> XML -> ET`

