# OSCAL Format Converter

Converts between OSCAL XML and JSON formats in either direction. 

**Current state**: Conversion uses the NIST-published XSLT 3.x format conversion files, processed using the `saxonche` library.

**Target state**: Conversion uses pure Python code and the NIST-published OSCAL metaschema files.

See [usage notes](#usage) below for more information.

## Overview

This module provides Python functions to perform bidirectional conversion between OSCAL XML and JSON formats using:
- **saxonche**: Open-source Python bindings for Saxon XSLT 3.0 processor
- **NIST OSCAL XSLT Converters**: Official format converters from NIST

All conversion functions work entirely in memory with string inputs and outputs, making them perfect for web APIs, microservices, database operations, and stream processing.

## Features

- ✅ **In-Memory Operation**: All conversions use string inputs/outputs (no file I/O)
- ✅ **Full XSLT 3.0 Support**: Uses saxonche for complete XSLT 3.0/XPath 3.1 compliance
- ✅ **Bidirectional Conversion**: XML ↔ JSON for all OSCAL models
- ✅ **All OSCAL Models Supported**:
  - Catalog
  - Profile
  - System Security Plan (SSP)
  - Component Definition
  - Assessment Plan (SAP)
  - Assessment Results (SAR)
  - Plan of Action and Milestones (POA&M)
- ✅ **Error Handling**: Comprehensive exception handling and validation
- ✅ **Type Hints**: Full type annotations for better IDE support
- ✅ **API-Ready**: Perfect for web services, databases, and streaming applications

## Usage

When using the OSCAL content classes, there is no setup to use the converters. The OSCAL support module maintains the NIST OSCAL XSLT converters in its support database. The OSCAL class and support module work together and use the converters as needed. 

**The information below is only necessary for using the `oscal_converters.py` module separate from the the rest of the OSCAL library.**

### Requirements

- Python 3.9+
- saxonche library
- NIST OSCAL XSLT converters

### Setup

Place `oscal_converter.py` in your project directory or Python path.

Install SaxonC-HE

```bash

pip install saxonche

```

### Download OSCAL XSLT Converters

Download the official NIST OSCAL XSLT converters from the OSCAL releases.

There is a separate XSLT conversion file for each OSCAL model. These are updated with each published version of OSCAL. 

While you can likely just use the latest OSCAL 1.x.x files for all prior 1.x.x versions of OSCAL, it is best to use the converter for the OSCAL syntax version declared in the OSCAL content you are converting. 

```bash
# Download the latest OSCAL release
wget https://github.com/usnistgov/OSCAL/releases/download/{version}/oscal-{version}.zip

# Extract converters
unzip oscal-{version}.zip "xml/convert/*"
```

Replace `{version}` with the desired OSCAL version, expressed as `v1.#.#`, such as `v1.2.1`.

The converters are XSLT files named:
- `oscal_{model}_xml-to-json-converter.xsl`
- `oscal_{model}_json-to-xml-converter.xsl`



### Basic XML to JSON Conversion

```python
from oscal_converter import oscal_xml_to_json

# Load the XSLT converter as a string (from file, database, API, etc.)
with open('oscal_catalog_xml-to-json-converter.xsl', 'r') as f:
    xslt_converter = f.read()

# Your OSCAL XML content as a string (from any source)
xml_content = '''<?xml version="1.0"?>
<catalog xmlns="http://csrc.nist.gov/ns/oscal/1.0">
    <metadata>
        <title>My Catalog</title>
    </metadata>
</catalog>'''

# Convert in memory - returns JSON string
json_result = oscal_xml_to_json(
    xml_content=xml_content,
    xsl_converter=xslt_converter,
    json_indent=True
)

# Use the result (send to API, store in DB, etc.)
print(json_result)
```

### Basic JSON to XML Conversion

```python
from oscal_converter import oscal_json_to_xml

# Load the XSLT converter as a string
with open('oscal_profile_json-to-xml-converter.xsl', 'r') as f:
    xslt_converter = f.read()

# Your OSCAL JSON content as a string
json_content = '''{
  "profile": {
    "uuid": "...",
    "metadata": {...}
  }
}'''

# Convert in memory - returns XML string
xml_result = oscal_json_to_xml(
    json_content=json_content,
    xsl_converter=xslt_converter,
    validate_json=True
)

# Use the result
print(xml_result)
```


## References

- **OSCAL Project**: https://pages.nist.gov/OSCAL/
- **OSCAL GitHub**: https://github.com/usnistgov/OSCAL
- **Saxon Documentation**: https://www.saxonica.com/documentation/
- **saxonche PyPI**: https://pypi.org/project/saxonche/

## License

This code is provided under the MIT License and carries no warranty.

NIST OSCAL work products are in the public domain.

The saxonche library is licensed under the Mozilla Public License 2.0 (MPL-2.0).

## Support

For OSCAL-specific questions:
- OSCAL Gitter: https://gitter.im/usnistgov-OSCAL/Lobby
- OSCAL Issues: https://github.com/usnistgov/OSCAL/issues

For saxonche issues:
- Saxon Support: https://saxonica.plan.io
- Stack Overflow: Use tag `saxon`
