# OSCAL In-Memory Format Converter for Python

Python utilities for converting between OSCAL XML and JSON formats using NIST's official XSLT 3.0 converters and the `saxonche` library.

**All operations work with strings in memory - no file I/O required.**

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

## Requirements

- Python 3.9+
- saxonche library
- NIST OSCAL XSLT converters

## Installation

### 1. Install saxonche

```bash
pip install saxonche
```

### 2. Download OSCAL XSLT Converters

Download the official NIST OSCAL XSLT converters from the OSCAL releases:

**Option A: From GitHub Releases (Recommended)**
```bash
# Download the latest OSCAL release
wget https://github.com/usnistgov/OSCAL/releases/download/v1.1.3/oscal-v1.1.3.zip

# Extract converters
unzip oscal-v1.1.3.zip "xml/convert/*"
```

**Option B: Clone and Build**
```bash
git clone https://github.com/usnistgov/OSCAL.git
cd OSCAL
make converters
# Converters will be in: build/generated/
```

The converters are XSLT files named:
- `oscal_{model}_xml-to-json-converter.xsl`
- `oscal_{model}_json-to-xml-converter.xsl`

### 3. Copy Module Files

Place `oscal_converter.py` in your project directory or Python path.

## Usage

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

### Web API Pattern

```python
from flask import Flask, request
from oscal_converter import oscal_xml_to_json

app = Flask(__name__)

# Load converter once at startup
with open('converters/oscal_catalog_xml-to-json-converter.xsl') as f:
    XSLT_CONVERTER = f.read()

@app.route('/convert', methods=['POST'])
def convert():
    # Get XML from request body
    xml_content = request.data.decode('utf-8')
    
    # Convert in memory
    json_result = oscal_xml_to_json(
        xml_content=xml_content,
        xsl_converter=XSLT_CONVERTER
    )
    
    # Return JSON string
    return json_result, 200, {'Content-Type': 'application/json'}
```

### Database Pattern

```python
from oscal_converter import oscal_xml_to_json
import psycopg2

# Load converter
with open('converter.xsl') as f:
    xslt_converter = f.read()

# Fetch XML from database
conn = psycopg2.connect(database="oscal_db")
cur = conn.cursor()
cur.execute("SELECT xml_content FROM catalogs WHERE id = %s", (catalog_id,))
xml_content = cur.fetchone()[0]

# Convert in memory
json_content = oscal_xml_to_json(
    xml_content=xml_content,
    xsl_converter=xslt_converter
)

# Store JSON back to database
cur.execute(
    "UPDATE catalogs SET json_content = %s WHERE id = %s",
    (json_content, catalog_id)
)
conn.commit()
```

## API Reference

### `oscal_xml_to_json()`

Convert OSCAL XML to JSON format (in-memory operation).

**Parameters:**
- `xml_content` (str): OSCAL XML content as a string
- `xsl_converter` (str): XSLT converter content as a string
- `json_indent` (bool): Output indented JSON (default: True)

**Returns:**
- `str`: Converted JSON content

**Raises:**
- `OSCALConverterError`: If conversion fails

**Example:**
```python
# Load converter
with open('oscal_catalog_xml-to-json-converter.xsl') as f:
    xslt = f.read()

# XML content from any source
xml = get_xml_from_database()  # or API, file, etc.

# Convert
json_output = oscal_xml_to_json(
    xml_content=xml,
    xsl_converter=xslt,
    json_indent=True
)

# Use the result
send_to_api(json_output)
```

### `oscal_json_to_xml()`

Convert OSCAL JSON to XML format (in-memory operation).

**Parameters:**
- `json_content` (str): OSCAL JSON content as a string
- `xsl_converter` (str): XSLT converter content as a string
- `validate_json` (bool): Validate JSON syntax (default: True)

**Returns:**
- `str`: Converted XML content

**Raises:**
- `OSCALConverterError`: If conversion fails
- `json.JSONDecodeError`: If JSON is invalid and validate_json=True

**Example:**
```python
# Load converter
with open('oscal_profile_json-to-xml-converter.xsl') as f:
    xslt = f.read()

# JSON content from any source
json_data = api_response.text

# Convert
xml_output = oscal_json_to_xml(
    json_content=json_data,
    xsl_converter=xslt,
    validate_json=True
)

# Use the result
store_in_database(xml_output)
```

## Technical Details

### In-Memory Operation

All conversion functions work entirely in memory:
- **Input**: XML or JSON content as strings
- **Output**: Converted content returned as strings
- **No file I/O**: Functions never read or write files directly
- **Flexibility**: Load converters and content from any source (files, databases, APIs, streams)

### XSLT Processing

The module uses saxonche, which provides:
- Full XSLT 3.0 compliance
- XPath 3.1 support
- Native JSON handling via `json-to-xml()` and `xml-to-json()`
- Streaming transformations
- Schema-aware processing (with PE/EE editions)

### NIST Converter Behavior

**XML to JSON:**
- Parses XML from string using `parse_xml(xml_text=...)`
- Compiles XSLT from string using `compile_stylesheet(stylesheet_text=...)`
- Sets `json-indent` parameter for pretty printing
- Returns JSON as string

**JSON to XML:**
- Compiles XSLT from string
- Passes JSON content via `json` parameter
- Uses named template `from-json` as entry point
- XSLT internally uses `json-to-xml()` to parse JSON
- Transforms through OSCAL supermodel intermediate format
- Returns XML as string

### Error Handling

The module provides comprehensive error handling:

```python
from oscal_converter import OSCALConverterError
import json

try:
    json_result = oscal_xml_to_json(xml_content, xslt_converter)
except OSCALConverterError as e:
    print(f"Conversion failed: {e}")
except json.JSONDecodeError as e:
    print(f"Invalid JSON: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

## Performance Considerations

- **In-Memory Processing**: Entire documents load into memory during transformation
- **Converter Caching**: Load and store XSLT converter strings once, reuse for multiple conversions
- **Compilation Caching**: For high-volume scenarios, compile XSLT once and reuse (see advanced usage)
- **Validation Overhead**: JSON validation adds minimal overhead
- **No I/O Bottleneck**: Eliminates file system I/O bottlenecks

## Advanced Usage

### Reusing Compiled Stylesheets

For better performance when processing multiple documents:

```python
from saxonche import PySaxonProcessor

# Load converter as string
with open('oscal_catalog_xml-to-json-converter.xsl') as f:
    xslt_content = f.read()

# Process multiple XML documents
xml_documents = get_xml_documents_from_database()

with PySaxonProcessor(license=False) as proc:
    xslt_proc = proc.new_xslt30_processor()
    
    # Compile once
    executable = xslt_proc.compile_stylesheet(stylesheet_text=xslt_content)
    
    # Reuse for multiple documents
    for xml_content in xml_documents:
        document = proc.parse_xml(xml_text=xml_content)
        json_result = executable.transform_to_string(xdm_node=document)
        
        # Process result
        store_in_database(json_result)
```

### Converter Class for Caching

```python
from saxonche import PySaxonProcessor

class OSCALConverterCache:
    """Cache compiled XSLT stylesheets for better performance."""
    
    def __init__(self):
        self.proc = PySaxonProcessor(license=False)
        self.xslt_proc = self.proc.new_xslt30_processor()
        self.compiled_xslts = {}
    
    def load_converter(self, converter_path):
        """Load and compile converter once."""
        if converter_path not in self.compiled_xslts:
            with open(converter_path, 'r') as f:
                xslt_content = f.read()
            
            executable = self.xslt_proc.compile_stylesheet(
                stylesheet_text=xslt_content
            )
            self.compiled_xslts[converter_path] = executable
        
        return self.compiled_xslts[converter_path]
    
    def xml_to_json(self, xml_content, converter_path):
        """Convert XML to JSON using cached converter."""
        executable = self.load_converter(converter_path)
        document = self.proc.parse_xml(xml_text=xml_content)
        return executable.transform_to_string(xdm_node=document)
    
    def __del__(self):
        # Cleanup
        del self.proc

# Usage
converter = OSCALConverterCache()

# Convert multiple documents - converter compiled only once
for xml in xml_documents:
    json_result = converter.xml_to_json(
        xml, 
        'converters/oscal_catalog_xml-to-json-converter.xsl'
    )
```

### Generator Pattern for Large Datasets

```python
def convert_oscal_stream(xml_documents, xslt_converter_content):
    """
    Generator that converts documents one at a time.
    Memory efficient for large datasets.
    """
    from oscal_converter import oscal_xml_to_json
    
    for xml_doc in xml_documents:
        try:
            json_result = oscal_xml_to_json(
                xml_content=xml_doc,
                xsl_converter=xslt_converter_content
            )
            yield json_result
        except Exception as e:
            yield {'error': str(e)}

# Usage
with open('converter.xsl') as f:
    converter = f.read()

# Process one at a time - previous results can be garbage collected
for json_output in convert_oscal_stream(xml_docs_iterator, converter):
    process_and_store(json_output)
```

## Troubleshooting

### "No file found at {file}" Error

**Problem**: JSON-to-XML conversion fails with file not found.

**Solution**: Ensure the JSON file path is accessible. The converter uses the file URI scheme:
```python
# Converter expects absolute path
json_input = Path('catalog.json').resolve()
```

### "Invalid JSON in input file"

**Problem**: JSON syntax error.

**Solution**: Validate your JSON:
```bash
python -m json.tool catalog.json
```

### Converter Not Found

**Problem**: `FileNotFoundError` for XSLT converter.

**Solution**: Verify converter filename matches OSCAL model type:
```python
# For SSP model:
converter = 'oscal_ssp_xml-to-json-converter.xsl'  # Correct
# Not: 'oscal_system-security-plan_xml-to-json-converter.xsl'
```

### Memory Issues with Large Files

**Problem**: Out of memory with very large OSCAL files.

**Solution**: Consider splitting large catalogs or using streaming if supported.

## References

- **OSCAL Project**: https://pages.nist.gov/OSCAL/
- **OSCAL GitHub**: https://github.com/usnistgov/OSCAL
- **Saxon Documentation**: https://www.saxonica.com/documentation/
- **saxonche PyPI**: https://pypi.org/project/saxonche/

## License

This code is provided as a utility for OSCAL processing. NIST OSCAL work products are in the public domain.

The saxonche library is licensed under the Mozilla Public License 2.0 (MPL-2.0).

## Contributing

Contributions welcome! This utility is designed to work with official NIST OSCAL converters. When contributing:

1. Maintain compatibility with saxonche and NIST converters
2. Add comprehensive error handling
3. Include type hints
4. Update documentation

## Support

For OSCAL-specific questions:
- OSCAL Gitter: https://gitter.im/usnistgov-OSCAL/Lobby
- OSCAL Issues: https://github.com/usnistgov/OSCAL/issues

For saxonche issues:
- Saxon Support: https://saxonica.plan.io
- Stack Overflow: Use tag `saxon`
