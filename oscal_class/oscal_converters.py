"""
OSCAL Format Converter using saxonche and NIST XSLT transformations.

This module provides in-memory functions to convert between OSCAL XML and JSON 
formats using the official NIST OSCAL XSLT 3.0 converters with the saxonche library.

All operations work with string content in memory - no file I/O required.

Requirements:
    - saxonche: pip install saxonche
    - NIST OSCAL XSLT converter content (as strings)

OSCAL Converters Download:
    The XSLT converters can be obtained from NIST OSCAL releases:
    https://github.com/usnistgov/OSCAL/releases
    
    Look for converter files named:
    - oscal_{model}_xml-to-json-converter.xsl
    - oscal_{model}_json-to-xml-converter.xsl
    
    Where {model} is one of: catalog, profile, ssp, component-definition,
    assessment-plan, assessment-results, poam

Author: Generated for OSCAL processing
License: Public Domain (NIST work product)
"""

import json
# from typing import Optional
from saxonche import PySaxonProcessor


class OSCALConverterError(Exception):
    """Exception raised for OSCAL conversion errors."""
    pass


def oscal_xml_to_json(
    xml_content: str,
    xsl_converter: str,
    json_indent: bool = True
) -> str:
    """
    Convert OSCAL XML to JSON using NIST XSLT 3.0 converter.
    
    All inputs and outputs are strings in memory - no file I/O.

    Args:
        xml_content: OSCAL XML content as a string
        xsl_converter: NIST XML-to-JSON XSLT converter content as a string
        json_indent: If True, output indented/pretty JSON (default: True)

    Returns:
        str: Converted JSON content

    Raises:
        OSCALConverterError: If conversion fails

    Example:
        >>> xml_str = '''<?xml version="1.0"?>
        ... <catalog xmlns="http://csrc.nist.gov/ns/oscal/1.0">
        ...     <metadata>...</metadata>
        ... </catalog>'''
        >>> 
        >>> xslt_str = open('oscal_catalog_xml-to-json-converter.xsl').read()
        >>> 
        >>> json_result = oscal_xml_to_json(xml_str, xslt_str)
    """
    if not xml_content or not isinstance(xml_content, str):
        raise OSCALConverterError("xml_content must be a non-empty string")
    
    if not xsl_converter or not isinstance(xsl_converter, str):
        raise OSCALConverterError("xsl_converter must be a non-empty string")

    try:
        # Initialize Saxon processor
        with PySaxonProcessor(license=False) as proc:
            # Create XSLT 3.0 processor
            xslt_proc = proc.new_xslt30_processor()

            # Parse the XML source document from string
            document = proc.parse_xml(xml_text=xml_content)

            # Compile the XSLT stylesheet from string
            executable = xslt_proc.compile_stylesheet(stylesheet_text=xsl_converter)

            # Set the json-indent parameter if requested
            if json_indent:
                # Create XDM atomic value for the parameter
                indent_value = proc.make_string_value("yes")
                executable.set_parameter("json-indent", indent_value)

            # Transform to string (JSON output)
            result = executable.transform_to_string(xdm_node=document)

            return result

    except Exception as e:
        raise OSCALConverterError(
            f"Failed to convert XML to JSON: {str(e)}"
        ) from e


def oscal_json_to_xml(
    json_content: str,
    xsl_converter: str,
    validate_json: bool = True
) -> str:
    """
    Convert OSCAL JSON to XML using NIST XSLT 3.0 converter.
    
    All inputs and outputs are strings in memory - no file I/O.

    The NIST JSON-to-XML converters use XSLT 3.0's json-to-xml() function
    to parse JSON directly from a string parameter.

    Args:
        json_content: OSCAL JSON content as a string
        xsl_converter: NIST JSON-to-XML XSLT converter content as a string
        validate_json: If True, validate JSON can be parsed (default: True)

    Returns:
        str: Converted XML content

    Raises:
        OSCALConverterError: If conversion fails
        json.JSONDecodeError: If JSON is invalid and validate_json=True

    Example:
        >>> json_str = '''{
        ...   "catalog": {
        ...     "uuid": "...",
        ...     "metadata": {...}
        ...   }
        ... }'''
        >>> 
        >>> xslt_str = open('oscal_catalog_json-to-xml-converter.xsl').read()
        >>> 
        >>> xml_result = oscal_json_to_xml(json_str, xslt_str)
    """
    if not json_content or not isinstance(json_content, str):
        raise OSCALConverterError("json_content must be a non-empty string")
    
    if not xsl_converter or not isinstance(xsl_converter, str):
        raise OSCALConverterError("xsl_converter must be a non-empty string")

    # Optionally validate JSON
    if validate_json:
        try:
            json.loads(json_content)
        except json.JSONDecodeError as e:
            raise OSCALConverterError(
                f"Invalid JSON content: {str(e)}"
            ) from e

    try:
        # Initialize Saxon processor
        with PySaxonProcessor(license=False) as proc:
            # Create XSLT 3.0 processor
            xslt_proc = proc.new_xslt30_processor()

            # Compile the XSLT stylesheet from string
            executable = xslt_proc.compile_stylesheet(stylesheet_text=xsl_converter)

            # Set the 'json' parameter with the JSON content string
            # The NIST converters expect this parameter to contain the JSON
            json_param = proc.make_string_value(json_content)
            executable.set_parameter("json", json_param)

            # Call the named template 'from-json'
            # This is the entry point for NIST JSON-to-XML converters
            result = executable.call_template_returning_string(template_name="from-json")

            return result

    except Exception as e:
        raise OSCALConverterError(
            f"Failed to convert JSON to XML: {str(e)}"
        ) from e


# Example usage demonstrating in-memory operation
if __name__ == "__main__":
    # import sys
    
    print("OSCAL In-Memory Format Converter")
    print("=" * 60)
    print("\nAll operations work with strings in memory.\n")
    
    print("Example 1: XML to JSON conversion")
    print("-" * 60)
    print("""
    # Load converter XSLT as string
    with open('oscal_catalog_xml-to-json-converter.xsl', 'r') as f:
        xslt_converter = f.read()
    
    # Load OSCAL XML as string
    with open('catalog.xml', 'r') as f:
        xml_content = f.read()
    
    # Convert in memory
    json_result = oscal_xml_to_json(
        xml_content=xml_content,
        xsl_converter=xslt_converter,
        json_indent=True
    )
    
    # json_result is a string containing JSON
    print(json_result)
    """)
    
    print("\nExample 2: JSON to XML conversion")
    print("-" * 60)
    print("""
    # Load converter XSLT as string
    with open('oscal_profile_json-to-xml-converter.xsl', 'r') as f:
        xslt_converter = f.read()
    
    # Load OSCAL JSON as string
    with open('profile.json', 'r') as f:
        json_content = f.read()
    
    # Convert in memory
    xml_result = oscal_json_to_xml(
        json_content=json_content,
        xsl_converter=xslt_converter,
        validate_json=True
    )
    
    # xml_result is a string containing XML
    print(xml_result)
    """)
    
    print("\nExample 3: Processing from variables")
    print("-" * 60)
    print("""
    # Example with literal string content
    xml_data = '''<?xml version="1.0"?>
    <catalog xmlns="http://csrc.nist.gov/ns/oscal/1.0">
        <metadata>
            <title>My Catalog</title>
        </metadata>
    </catalog>'''
    
    # Converter loaded from file or database or API
    converter_xslt = load_converter_from_database('catalog', 'xml-to-json')
    
    # Convert
    json_output = oscal_xml_to_json(xml_data, converter_xslt)
    
    # Use the result immediately
    send_to_api(json_output)
    store_in_database(json_output)
    """)
    
    print("\n" + "=" * 60)
    print("NOTE: Download OSCAL XSLT converters from:")
    print("https://github.com/usnistgov/OSCAL/releases")
    print("=" * 60)
