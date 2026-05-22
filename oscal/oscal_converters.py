"""
OSCAL Format Convertion

Includes markup conversion functions for OSCAL-compliant markdown to HTML and vice
    versa. Also includes functions to convert between OSCAL XML and JSON formats 
    using the official NIST-published artifacts.
     
      
This module provides in-memory functions to convert OSCAL XML and JSON
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
import re
import xml.etree.ElementTree as ET
from xml.etree.ElementTree import Element

# from typing import Optional
import markdown
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from markdown.treeprocessors import Treeprocessor
from saxonche import PySaxonProcessor

# ---------------------------------------------------------------------------
# OSCAL markdown ↔ HTML conversion
# ---------------------------------------------------------------------------

class _ParameterInsertionProcessor(InlineProcessor):
    """Handles OSCAL ``{{ insert: param, id }}`` syntax → ``<insert>`` element."""

    def handleMatch(self, m, data):
        parts = [p.strip() for p in m.group(1).strip().split(",")]
        if len(parts) != 2:
            return None, None, None
        el = Element("insert")
        el.set("type", parts[0])
        el.set("id-ref", parts[1])
        return el, m.start(0), m.end(0)


class _SubscriptProcessor(InlineProcessor):
    """Handles ``~text~`` → ``<sub>text</sub>``."""

    def handleMatch(self, m, data):
        el = Element("sub")
        el.text = m.group(1)
        return el, m.start(0), m.end(0)


class _SuperscriptProcessor(InlineProcessor):
    """Handles ``^text^`` → ``<sup>text</sup>``."""

    def handleMatch(self, m, data):
        el = Element("sup")
        el.text = m.group(1)
        return el, m.start(0), m.end(0)


class _OscalTableTreeprocessor(Treeprocessor):
    """
    Removes non-OSCAL table wrapper elements (thead, tbody, tfoot, etc.)
    so the table only contains ``<tr>`` children directly.
    """

    def run(self, root):
        for table in root.iter("table"):
            self._flatten(table)

    def _flatten(self, table):
        rows = []
        for child in list(table):
            if child.tag in ("thead", "tbody"):
                rows.extend(child)
                table.remove(child)
            elif child.tag == "tr":
                rows.append(child)
            elif child.tag in ("tfoot", "col", "colgroup", "caption"):
                table.remove(child)
        table.clear()
        for row in rows:
            table.append(row)


class _OscalParameterExtension(Extension):
    """Markdown extension wiring up all OSCAL inline/tree processors."""

    def extendMarkdown(self, md):
        md.inlinePatterns.register(
            _ParameterInsertionProcessor(r"\{\{\s*insert:\s*([^}]+)\}\}", md),
            "oscal_param_insert", 175,
        )
        md.inlinePatterns.register(
            _SubscriptProcessor(r"~([^~]+)~", md),
            "oscal_subscript", 174,
        )
        md.inlinePatterns.register(
            _SuperscriptProcessor(r"\^([^^]+)\^", md),
            "oscal_superscript", 173,
        )
        md.treeprocessors.register(
            _OscalTableTreeprocessor(md), "oscal_table_compliance", 0
        )


def oscal_markdown_to_html(markdown_text: str, multiline: bool = False) -> str:
    """
    Convert OSCAL CommonMark to an HTML fragment.

    ``multiline=True``  → markup-multiline: block elements preserved, ``<p>`` wrap applied.
    ``multiline=False`` → markup-line: inline only, outer ``<p>`` stripped.
    """
    if not markdown_text:
        return ""

    # OSCAL markdown does not allow raw HTML.  Escape any angle bracket that
    # looks like the start of an HTML/XML tag so the markdown library treats it
    # as literal text rather than inline HTML.  This preserves original case
    # (e.g. <BREAK> → &lt;BREAK&gt;) and ensures known element names written
    # literally are not mis-parsed.  The OscalParameterExtension generates
    # <insert .../> in its *output*, not in the source, so it is unaffected.
    markdown_text = re.sub(r"<(?=[a-zA-Z/!])", r"&lt;", markdown_text)

    md = markdown.Markdown(
        extensions=["extra", "sane_lists", _OscalParameterExtension()],
        extension_configs={
            "extra": {
                "markdown.extensions.fenced_code": {},
                "markdown.extensions.tables": {},
            }
        },
    )
    html = md.convert(markdown_text)

    if not multiline:
        if html.startswith("<p>") and html.endswith("</p>"):
            html = html[3:-4]
        html = html.replace("\n", " ").strip()
    else:
        has_block = any(
            tag in html
            for tag in ("<p>", "<h1>", "<h2>", "<h3>", "<h4>", "<h5>", "<h6>",
                        "<ul>", "<ol>", "<blockquote>", "<table>")
        )
        if not has_block and html.strip():
            html = f"<p>{html}</p>"

    return html


def oscal_html_to_markdown(html_text: str, multiline: bool = True) -> str:
    """
    Convert an HTML fragment to OSCAL CommonMark.

    ``multiline=True``  → markup-multiline (block elements converted).
    ``multiline=False`` → markup-line (inline elements only).
    """
    if not html_text:
        return ""

    md = html_text.strip()

    # OSCAL insert tags → {{ insert: type, id-ref }}
    def _replace_insert(match):
        attrs = match.group(1) or ""
        type_m = re.search(r'\btype\s*=\s*(["\'])(.*?)\1', attrs, flags=re.IGNORECASE)
        id_m   = re.search(r'\bid-ref\s*=\s*(["\'])(.*?)\1', attrs, flags=re.IGNORECASE)
        if not type_m or not id_m:
            return match.group(0)
        return f"{{{{ insert: {type_m.group(2).strip()}, {id_m.group(2).strip()} }}}}"

    md = re.sub(
        r"<insert\b([^>]*)\s*(?:/\s*>|>\s*</insert\s*>)",
        _replace_insert, md, flags=re.IGNORECASE,
    )

    if multiline:
        for level in range(1, 7):
            md = re.sub(f"<h{level}>([^<]+)</h{level}>", f'{"#" * level} \\1\n\n', md)

        def _code_block(m):
            return f"\n\n```\n{m.group(1)}\n```\n\n"
        md = re.sub(r"<pre>([^<]*)</pre>", _code_block, md, flags=re.DOTALL)

        def _table(m):
            t = m.group(0)
            hdr = re.search(r"<tr>((?:<th[^>]*>[^<]*</th>)+)</tr>", t)
            if not hdr:
                return t
            cols = re.findall(r"<th[^>]*>([^<]*)</th>", hdr.group(1))
            aligns = [a for a in re.findall(r'<th[^>]*align="([^"]*)"', hdr.group(1))]
            rows = []
            for rm in re.finditer(r"<tr>((?:<td[^>]*>.*?</td>)+)</tr>", t, flags=re.DOTALL):
                rows.append(re.findall(r"<td[^>]*>(.*?)</td>", rm.group(1), flags=re.DOTALL))
            if not cols or not rows:
                return t
            lines = ["| " + " | ".join(cols) + " |"]
            seps = []
            for i in range(len(cols)):
                a = aligns[i] if i < len(aligns) else "left"
                seps.append(":---:" if a == "center" else "---:" if a == "right" else "---")
            lines.append("| " + " | ".join(seps) + " |")
            for row in rows:
                row = (row + [""] * len(cols))[: len(cols)]
                lines.append("| " + " | ".join(row) + " |")
            return "\n\n" + "\n".join(lines) + "\n\n"

        md = re.sub(r"<table>.*?</table>", _table, md, flags=re.DOTALL)
        md = re.sub(r"<blockquote>([^<]+)</blockquote>", r"\n\n> \1\n\n", md)
        md = re.sub(r"<ul><li>([^<]+)</li></ul>", r"\n\n- \1\n", md)
        md = re.sub(r"<ol><li>([^<]+)</li></ol>", r"\n\n1. \1\n", md)
        md = re.sub(r"<p>([^<]+)</p>", r"\1\n\n", md)

    # Inline formatting
    md = re.sub(r'<img\s+alt="([^"]*)"\s+src="([^"]+)"\s+title="([^"]*)"\s*/>', r'![\1](\2 "\3")', md)
    md = re.sub(r'<img\s+alt="([^"]*)"\s+src="([^"]+)"\s*/>', r"![\1](\2)", md)
    md = re.sub(r'<a\s+href="([^"]+)"\s+title="([^"]*)">([^<]+)</a>', r'[\3](\1 "\2")', md)
    md = re.sub(r'<a\s+href="([^"]+)">([^<]+)</a>', r"[\2](\1)", md)
    md = re.sub(r"<strong>([^<]+)</strong>", r"**\1**", md)
    md = re.sub(r"<em>([^<]+)</em>", r"*\1*", md)
    md = re.sub(r"<code>([^<]+)</code>", r"`\1`", md)
    md = re.sub(r"<sup>([^<]+)</sup>", r"^\1^", md)
    md = re.sub(r"<sub>([^<]+)</sub>", r"~\1~", md)
    md = re.sub(r"<[^>]+>", "", md)

    if multiline:
        lines = [l.strip() for l in md.split("\n")]
        cleaned: list[str] = []
        for line in lines:
            if line:
                cleaned.append(line)
            elif cleaned and cleaned[-1]:
                cleaned.append("")
        md = re.sub(r"\n\n\n+", "\n\n", "\n".join(cleaned))
    else:
        md = re.sub(r"\s+", " ", md)

    return md.strip()


# -------------------------------------------------------------------------
class OSCALConverterError(Exception):
    """Exception raised for OSCAL conversion errors."""
    pass

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# XML/JSON conversion functions/classes
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
def oscal_xml_to_json(
    xml_content: str,
    xsl_converter: str,
    json_indent: bool = False
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

# -------------------------------------------------------------------------
def oscal_json_to_xml(
    json_content: str,
    xsl_converter: str,
    validate_json: bool = False
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

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Markup conversion wrappers (implementations live in oscal_converter)
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
def convert_markup_line(markdown_text):
    """
    Convert OSCAL markup-line markdown to HTML.

    This is for inline text only (no block elements like paragraphs, headers, lists).

    Args:
        markdown_text (str): The markup-line markdown text

    Returns:
        str: The converted HTML (without wrapping paragraph tags)

    Example:
        >>> convert_markup_line("This implements {{ insert: param, pm-9_prm_1 }} as required.")
        'This implements <insert id-ref="pm-9_prm_1" type="param" /> as required.'
    """
    return oscal_markdown_to_html(markdown_text, multiline=False)

# -------------------------------------------------------------------------
def convert_markup_multiline(markdown_text):
    """
    Convert OSCAL markup-multiline markdown to HTML.

    This supports full block-level elements (paragraphs, headers, lists, tables, etc.).

    Args:
        markdown_text (str): The markup-multiline markdown text

    Returns:
        str: The converted HTML

    Example:
        >>> text = '''# Overview
        ...
        ... This system implements {{ insert: param, ac-1_prm_1 }}.
        ...
        ... ## Requirements
        ...
        ... - First requirement
        ... - Second requirement'''
        >>> convert_markup_multiline(text)
        # Returns HTML with proper structure
    """
    return oscal_markdown_to_html(markdown_text, multiline=True)

# -------------------------------------------------------------------------
def escape_for_json(text):
    """
    Helper function to properly escape text for JSON/YAML representation.

    Handles the special characters that need escaping in OSCAL markdown
    when used in JSON/YAML contexts.

    Args:
        text (str): The text to escape

    Returns:
        str: The escaped text
    """
    # Escape backslashes first
    text = text.replace('\\', '\\\\')
    # Escape special markdown characters
    text = text.replace('*', '\\*')
    text = text.replace('`', '\\`')
    text = text.replace('~', '\\~')
    text = text.replace('^', '\\^')
    # Escape quotes for JSON
    text = text.replace('"', '\\"')

    return text

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
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


    print("\n=== Testing markup-line ===")
    line_text = "This implements {{ insert: param, pm-9_prm_1 }} as **required** to address *organizational* changes."
    print("Input:", line_text)
    print("Output:", convert_markup_line(line_text))
    print()

    # Test markup-multiline
    print("=== Testing markup-multiline ===")
    multiline_text = """# Security Control Implementation

This control requires {{ insert: param, ac-1_prm_1 }} and must be reviewed.

## Implementation Details

The system implements the following:

- Access control policies
- Procedures for `authentication`
- Monitoring of **critical** systems

| Control | Status |
|---------|--------|
| AC-1    | Implemented |
| AC-2    | In Progress |

> **Note**: This is a draft implementation.
"""
    print("Input:", multiline_text)
    print("\nOutput:", convert_markup_multiline(multiline_text))
    print()

    # Test with subscript and superscript
    print("=== Testing subscript/superscript ===")
    special_text = "The formula is H~2~O and E=mc^2^"
    print("Input:", special_text)
    print("Output:", convert_markup_line(special_text))
