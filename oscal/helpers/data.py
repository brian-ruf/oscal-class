"""
Functions for managing and manipulating XML, JSON and YAML content.
"""
from __future__ import annotations

import logging
import elementpath
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import tostring

from typing import Any, cast

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------------
def detect_data_format(content: str) -> str:
    """Detect whether the content is XML, JSON, or YAML based on its starting characters."""
    content = content.lstrip()  # Remove leading whitespace

    if content.startswith('<?xml') or content.startswith('<'):
        return 'xml'
    elif content.startswith('{') or content.startswith('['):
        return 'json'
    else:
        # Simple heuristic for YAML: presence of ':' and no XML/JSON indicators
        if ':' in content:
            return 'yaml'
    
    return 'unknown'

# -------------------------------------------------------------------------
# -------------------------------------------------------------------------
def safe_load(content: str, data_format: str = "") -> object | None:
    """Check if the provided content string is well-formed based on its format."""
    data_object = None
    if data_format == "":
        data_format = detect_data_format(content)

    if data_format == "xml":
        data_object = safe_load_xml(content)
    elif data_format == "json":
        data_object = safe_load_json(content)
    elif data_format == "yaml":
        data_object = safe_load_yaml(content)
    else:
        logger.error(f"Unknown data format for well-formed check: {data_format}")
        data_object = None

    return data_object
# -------------------------------------------------------------------------
def safe_load_xml(content: str) -> ET.Element | None:
    """
    Returns an XML tree if the provided XML string is well-formed.
    If not well-formed, returns None.
    """
    tree = None

    from xml.etree import ElementTree
    try:
        tree = ElementTree.fromstring(content.encode('utf_8'))  # noqa: F841
        logger.debug("CONTENT APPEARS TO BE WELL FORMED XML")
    except ElementTree.ParseError as e:
        logger.debug("CONTENT DOES NOT APPEAR TO BE VALID XML")
        logger.error(f"XML Parse Error: {e}")
        tree = None

    return tree



# -------------------------------------------------------------------------
def safe_load_json(content: str) -> dict | None:
    """
    Returns a dict if the provided JSON string is well-formed.
    If not well-formed, returns None.
    """
    data_object = None
    import json
    try:
        data_object = json.loads(content)  # noqa: F841
        logger.debug("CONTENT APPEARS TO BE WELL FORMED JSON")
    except json.JSONDecodeError as e:
        logger.debug("CONTENT DOES NOT APPEAR TO BE VALID JSON")
        logger.error(f"JSON Decode Error: {e}")
        data_object = None

    return data_object

# -------------------------------------------------------------------------
def safe_load_yaml(content: str) -> dict | None:
    """
    Returns a dict if the provided YAML string is well-formed.
    If not well-formed, returns None.
    """
    data_object = None
    import yaml
    try:    
        data_object = yaml.safe_load(content)  # noqa: F841
        logger.debug("CONTENT APPEARS TO BE WELL FORMED YAML")
    except yaml.YAMLError as e:
        logger.debug("CONTENT DOES NOT APPEAR TO BE VALID YAML")
        logger.error(f"YAML Error: {e}")
        data_object = None

    return data_object

# -------------------------------------------------------------------------
def xpath(tree: Any, nsmap: dict, xExpr: str, context: ET.Element | None = None) -> object | None:
    """
    Performs an xpath query either on the entire XML document 
    or on a context within the document.

    Parameters:
    - xExpr (str): An xpath expression
    - context (obj)[optional]: Context object.
    If the context object is present, the xpath expression is run against
    that context. If absent, the xpath expression is run against the 
    entire document.

    Returns: 
    - None if there is an error or if nothing is found.
    - A single element if exactly one is found
    - A list of elements if multiple are found
    """
    result = None
    try:
        if context is None:
            logger.debug(f"XPath: {xExpr}")            
            result = elementpath.select(tree, xExpr, namespaces=nsmap)
        else:
            logger.debug(f"XPath (Context: { context.tag }): {xExpr}")            
            result = elementpath.select(context, xExpr, namespaces=nsmap)
        
        # Return None for empty results
        if not result:
            return None
        
        # Return the single element if there's only one result
        if len(result) == 1:
            result= result[0]
        
    except SyntaxError as e:
        logger.error(f"XPath syntax error: {e} in {xExpr}")
    except IndexError as e:
        logger.debug(f"XPath result not found error: {e} for: {xExpr}")
    except Exception as e:
        logger.error(f"XPath error: {e}")
    
    return result
# -------------------------------------------------------------------------
def xpath_atomic(tree: Any, nsmap: dict, xExpr: str, context: ET.Element | None = None) -> str:
    """
    Performs an xpath query either on the entire XML document
    or on a context within the document.
    Parameters:
    - tree (ElementTree): The XML tree to process.
    - xExpr (str): An xpath expression
    - context (obj)[optional]: Context object.
    If the context object is present, the xpath expression is run against
    that context. If absent, the xpath expression is run against the
    entire document.
    Returns:
    - an empty string if there is an error or if nothing is found.
    - The first result of the xpath expression as a string.
    """
    ret_value = ""

    try:
        if context is None:
            logger.debug(f"XPath Atomic: {xExpr}")
            results = elementpath.select(tree, xExpr, namespaces=nsmap)
        else:
            logger.debug(f"XPath Atomic (Context: { context.tag }): {xExpr}")
            results = elementpath.select(context, xExpr, namespaces=nsmap)

        # Check if results exist before accessing
        if results:
            ret_value = results[0]
        else:
            logger.debug(f"XPath result not found: {xExpr}")

    except SyntaxError as e:
        logger.error(f"XPath syntax error: {e} in {xExpr}")
    except Exception as e:
        logger.error(f"Other XPath error: {e}")

    return str(ret_value)

# -------------------------------------------------------------------------
def remove_namespace(element: ET.Element) -> None:
    """Remove namespace from an element and all its children"""
    # Remove namespace from this element
    if '}' in element.tag:
        element.tag = element.tag.split('}', 1)[1]
    
    # Process attributes
    for attr_name in list(element.attrib.keys()):
        if '}' in attr_name:
            new_name = attr_name.split('}', 1)[1]
            element.attrib[new_name] = element.attrib.pop(attr_name)
    
    # Process children
    for child in element:
        remove_namespace(child)


# -------------------------------------------------------------------------
def get_markup_content(tree: Any, nsmap: dict, xExpr: str, context: ET.Element | None = None) -> str:
    """
    Get the content of a specific XML element using XPath, preserving HTML formatting.
    
    Args:
        tree: The XML tree to process
        nsmap: Namespace mapping
        xExpr: The XPath expression to locate the element
        context: The context in which to search for the element
        
    Returns:
        The content of the element as a string with HTML preserved, or empty string if not found
    """
    ret_value = ""
    element = None
    
    try:
        # First, try to get the entire element (not just its children)
        # Modify the XPath to get the element itself if it ends with /node() or /text()
        element_xpath = xExpr
        if xExpr.endswith('/node()'):
            element_xpath = xExpr[:-7]  # Remove '/node()'
        elif xExpr.endswith('/text()'):
            element_xpath = xExpr[:-6]  # Remove '/text()'
            
        # Get the element itself
        element = xpath(tree, nsmap, element_xpath, context)
        
        if element is not None:
            # If we got a list with one element, extract it
            if isinstance(element, list) and len(element) == 1:
                element = element[0]
            elif isinstance(element, list) and len(element) > 1:
                # Multiple elements found - concatenate their content
                content_parts = []
                for elem in element:
                    if hasattr(elem, 'tag'):
                        content_parts.append(extract_element_content(elem))
                    else:
                        content_parts.append(str(elem))
                return ''.join(content_parts)
            
            # Now we have the element, let's extract its complete content
            if hasattr(element, 'tag'):
                # This is an Element object
                ret_value = extract_element_content(cast(ET.Element, element))
            else:
                # This might be a text node or something else
                ret_value = str(element)
                
    except Exception as e:
        logger.error(f"Error getting markup content: {e} {xExpr}")
    
    return ret_value

# -------------------------------------------------------------------------
def xml_to_string(element: Any) -> str:
    """Convert an XML element or list of elements to a string."""
    import copy
    element_str = ""
    
    try:
        # Handle case where element is a list (common with xpath results)
        if isinstance(element, list):
            if len(element) > 0:
                # Take the first element if it's a list
                clean_assembly = copy.deepcopy(element[0])
                remove_namespace(clean_assembly)
                element_str = tostring(clean_assembly, encoding='unicode')
            else:
                # Return empty string for empty list
                return ""
        else:
            # Handle single element case
            clean_assembly = copy.deepcopy(element)
            remove_namespace(clean_assembly)
            element_str = tostring(clean_assembly, encoding='unicode')
    except Exception as e:
        logger.error(f"Error converting XML to string: {e}")

    return element_str


# -------------------------------------------------------------------------
def extract_element_content(element: ET.Element | None) -> str:
    """
    Extract the complete inner content of an XML element, preserving all HTML formatting
    but removing namespaces. Handles both simple text content and complex mixed content.
    
    This function properly handles elements that may contain:
    - Just text (e.g., <description>Simple text with &amp; entities</description>)
    - Mixed content with HTML (e.g., <remarks><p>Text</p><ol><li>Item</li></ol></remarks>)
    - Or a combination of both
    
    Args:
        element: An XML Element object
        
    Returns:
        String containing the complete inner content of the element without namespaces
    """
    if element is None:
        return ""
    
    # Make a deep copy to avoid modifying the original
    import copy
    clean_element = copy.deepcopy(element)
    
    # Remove namespaces from the copy
    remove_namespace(clean_element)
    
    # Check if this element has any child elements
    has_children = len(clean_element) > 0
    
    if not has_children and clean_element.text:
        # Simple case: element only contains text (no child elements)
        # This handles cases like <description>Text with &amp; entities</description>
        return clean_element.text.strip()
    
    # Complex case: element contains child elements and/or mixed content
    # This handles cases like <remarks><p>Para 1</p><ol><li>Item</li></ol></remarks>
    content_parts = []
    
    # Add the element's text if it has any (text before first child)
    if clean_element.text:
        content_parts.append(clean_element.text)
    
    # Process ALL child elements
    for child in clean_element:
        # Convert the entire child element to string including its tag
        child_str = tostring(child, encoding='unicode', method='html')
        content_parts.append(child_str)
        
        # Add any tail text after the child element (text between elements)
        if child.tail:
            content_parts.append(child.tail)
    
    # Join all parts and clean up extra whitespace
    result = ''.join(content_parts)
    
    # Clean up excessive newlines and spaces while preserving structure
    result = result.strip()
    
    return result


# -------------------------------------------------------------------------
def remove_namespace_from_html(html_str: str) -> str:
    """
    Remove XML namespace declarations from HTML string.
    
    Args:
        html_str: HTML string that may contain namespace declarations
        
    Returns:
        Clean HTML string without namespace declarations
    """
    # Remove xmlns attributes using regex
    # This pattern matches xmlns="..." or xmlns:prefix="..."
    import re
    
    # Remove xmlns attributes
    html_str = re.sub(r'\s*xmlns(?::\w+)?="[^"]*"', '', html_str)
    
    # Also remove any namespace prefixes from tags if present
    # This handles cases like <ns:p> -> <p>
    html_str = re.sub(r'<(/?)[\w]+:(\w+)', r'<\1\2', html_str)
    
    return html_str

# -------------------------------------------------------------------------
def deserialize_xml(xml_string: str, nsmap: str) -> ET.Element | None:
    """Deserialize an XML string into a Python dictionary."""
    ret_value = None
    try:
        # When creating the ElementTree parser
        ET.register_namespace("", nsmap)        
        # Parse the XML string
        root = ET.fromstring(xml_string)
        
        ret_value = root
    except ET.ParseError as e:
        logger.error(f"Error parsing XML: {e}")

    return ret_value

# -------------------------------------------------------------------------
def get_attribute_value(element: ET.Element, attribute_name: str, default: str = "") -> str:
    """
    Get the value of a specific attribute from an XML element.
    
    Args:
        element: The XML element to check
        attribute_name: The name of the attribute to look for
        default: The value to return if the attribute doesn't exist (default: empty string)
        
    Returns:
        The attribute value or the default value if the attribute doesn't exist
    """
    # Handle namespace prefixes if needed
    if '}' in attribute_name:
        clean_name = attribute_name.split('}', 1)[1]
    else:
        clean_name = attribute_name

    # Get the value with a default of empty string
    return element.get(clean_name, default)
# -------------------------------------------------------------------------

# =============================================================================
#  --- MAIN: Only runs if the module is executed stand-alone. ---
# =============================================================================
if __name__ == '__main__':
    print("Not intended to be run as a stand-alone file.")


