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
# from typing import Optional
from saxonche import PySaxonProcessor
import markdown
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from markdown.treeprocessors import Treeprocessor
from xml.etree import ElementTree as etree

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

# -------------------------------------------------------------------------
class ParameterInsertionProcessor(InlineProcessor):
    """
    Handles OSCAL parameter insertion syntax: {{ insert: param, pm-9_prm_1 }}
    Converts to: <insert type="param" id-ref="pm-9_prm_1"/>
    """

    def handleMatch(self, m, data):
        # Extract the type and id-ref from the matched pattern
        content = m.group(1).strip()
        parts = [p.strip() for p in content.split(',')]

        if len(parts) != 2:
            # Invalid syntax, return as-is
            return None, None, None

        insert_type = parts[0]
        id_ref = parts[1]

        # Create the insert element
        el = etree.Element('insert')
        el.set('type', insert_type)
        el.set('id-ref', id_ref)

        return el, m.start(0), m.end(0)

# -------------------------------------------------------------------------
class SubscriptProcessor(InlineProcessor):
    """
    Handles OSCAL subscript syntax: ~text~
    Converts to: <sub>text</sub>
    """

    def handleMatch(self, m, data):
        el = etree.Element('sub')
        el.text = m.group(1)
        return el, m.start(0), m.end(0)

# -------------------------------------------------------------------------
class SuperscriptProcessor(InlineProcessor):
    """
    Handles OSCAL superscript syntax: ^text^
    Converts to: <sup>text</sup>
    """

    def handleMatch(self, m, data):
        el = etree.Element('sup')
        el.text = m.group(1)
        return el, m.start(0), m.end(0)

# -------------------------------------------------------------------------
class OscalTableTreeprocessor(Treeprocessor):
    """
    Post-processes tables to remove non-OSCAL compliant HTML elements like <thead> and <tbody>.

    OSCAL only allows: <table>, <tr>, <th>, <td>
    OSCAL does NOT allow: <thead>, <tbody>, <tfoot>, <col>, <colgroup>, <caption>
    """

    def run(self, root):
        # Find all tables and restructure them
        for table in root.iter('table'):
            self._restructure_table(table)

    def _restructure_table(self, table):
        """Restructure table to be OSCAL compliant by removing thead/tbody wrappers."""
        new_rows = []

        # Collect all rows from thead and tbody elements
        for child in list(table):
            if child.tag == 'thead':
                # Move rows from thead to main table
                for tr in child:
                    new_rows.append(tr)
                table.remove(child)
            elif child.tag == 'tbody':
                # Move rows from tbody to main table
                for tr in child:
                    new_rows.append(tr)
                table.remove(child)
            elif child.tag == 'tr':
                # Keep direct tr children
                new_rows.append(child)
            elif child.tag in ['tfoot', 'col', 'colgroup', 'caption']:
                # Remove unsupported elements
                table.remove(child)

        # Clear the table and add restructured rows
        table.clear()
        for row in new_rows:
            table.append(row)

# -------------------------------------------------------------------------
class OscalParameterExtension(Extension):
    """
    Markdown extension to handle OSCAL parameter insertion syntax and ensure OSCAL-compliant HTML.
    """

    def extendMarkdown(self, md):
        # Pattern to match {{ insert: type, id }}
        # Priority 175 puts it before most other inline patterns
        PARAM_PATTERN = r'\{\{\s*insert:\s*([^}]+)\}\}'
        md.inlinePatterns.register(
            ParameterInsertionProcessor(PARAM_PATTERN, md),
            'oscal_param_insert',
            175
        )

        # Pattern to match ~text~ for subscript
        SUBSCRIPT_PATTERN = r'~([^~]+)~'
        md.inlinePatterns.register(
            SubscriptProcessor(SUBSCRIPT_PATTERN, md),
            'oscal_subscript',
            174
        )

        # Pattern to match ^text^ for superscript
        SUPERSCRIPT_PATTERN = r'\^([^^]+)\^'
        md.inlinePatterns.register(
            SuperscriptProcessor(SUPERSCRIPT_PATTERN, md),
            'oscal_superscript',
            173
        )

        # Add table post-processor to ensure OSCAL compliance
        md.treeprocessors.register(
            OscalTableTreeprocessor(md),
            'oscal_table_compliance',
            0  # Run after all other processing
        )

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Markup conversion functions
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
def oscal_html_to_markdown(html_text: str, multiline: bool = True) -> str:
    """
    Converts HTML to OSCAL markup-line or markup-multiline formatted markdown.

    This function handles the reverse conversion from HTML to the specific markdown subset
    defined in the NIST Metaschema specification for OSCAL markup-line and markup-multiline data types.

    Args:
        html_text (str): The HTML text to convert
        multiline (bool): If True, generates markup-multiline (supports block elements).
                         If False, generates markup-line (inline elements only).

    Returns:
        str: Markdown representation of the HTML text

    References:
        https://pages.nist.gov/metaschema/specification/datatypes/#markup-multiline
        https://pages.nist.gov/metaschema/specification/datatypes/#markup-line
    """
    import re

    if not html_text:
        return ""

    markdown = html_text.strip()

    # Handle OSCAL parameter insertion tags with flexible formatting:
    # - attribute order can vary
    # - single or double quoted attributes are accepted
    # - supports both self-closing and empty paired forms
    #   <insert ... /> and <insert ...></insert>
    def replace_insert_tag(match):
        attrs = match.group(1) or ""
        type_match = re.search(r'\btype\s*=\s*(["\'])(.*?)\1', attrs, flags=re.IGNORECASE)
        id_ref_match = re.search(r'\bid-ref\s*=\s*(["\'])(.*?)\1', attrs, flags=re.IGNORECASE)

        if not type_match or not id_ref_match:
            return match.group(0)

        insert_type = type_match.group(2).strip()
        id_ref = id_ref_match.group(2).strip()
        return f'{{{{ insert: {insert_type}, {id_ref} }}}}'

    markdown = re.sub(
        r'<insert\b([^>]*)\s*(?:/\s*>|>\s*</insert\s*>)',
        replace_insert_tag,
        markdown,
        flags=re.IGNORECASE,
    )

    if multiline:
        # Handle block-level elements first (only for markup-multiline)

        # Headers: <h1>text</h1> -> # text
        for level in range(1, 7):
            markdown = re.sub(f'<h{level}>([^<]+)</h{level}>',
                             f'{"#" * level} \\1\n\n', markdown)

        # Code blocks: <pre>code</pre> -> ```code```
        def fix_code_block(match):
            content = match.group(1)
            return f'\n\n```\n{content}\n```\n\n'
        markdown = re.sub(r'<pre>([^<]*)</pre>', fix_code_block, markdown, flags=re.DOTALL)

        # Tables: Convert HTML table back to markdown table
        def convert_html_table(match):
            table_html = match.group(0)

            # Extract header row
            header_match = re.search(r'<tr>((?:<th[^>]*>[^<]*</th>)+)</tr>', table_html)
            if not header_match:
                return table_html  # Not a valid table structure

            header_cells = re.findall(r'<th[^>]*>([^<]*)</th>', header_match.group(1))

            # Extract alignment information
            alignments = []
            for th_match in re.finditer(r'<th[^>]*align="([^"]*)"[^>]*>', header_match.group(1)):
                alignments.append(th_match.group(1))

            # Extract data rows
            data_rows = []
            for row_match in re.finditer(r'<tr>((?:<td[^>]*>.*?</td>)+)</tr>', table_html, flags=re.DOTALL):
                cells = re.findall(r'<td[^>]*>(.*?)</td>', row_match.group(1), flags=re.DOTALL)
                data_rows.append(cells)

            if not header_cells or not data_rows:
                return table_html

            # Build markdown table
            table_lines = []

            # Header row
            table_lines.append('| ' + ' | '.join(header_cells) + ' |')

            # Separator row with alignment
            separators = []
            for i, header in enumerate(header_cells):
                align = alignments[i] if i < len(alignments) else 'left'
                if align == 'center':
                    separators.append(':---:')
                elif align == 'right':
                    separators.append('---:')
                else:
                    separators.append('---')
            table_lines.append('| ' + ' | '.join(separators) + ' |')

            # Data rows
            for row in data_rows:
                # Pad row to match header length
                while len(row) < len(header_cells):
                    row.append('')
                table_lines.append('| ' + ' | '.join(row[:len(header_cells)]) + ' |')

            return '\n\n' + '\n'.join(table_lines) + '\n\n'

        # Match HTML tables
        markdown = re.sub(r'<table>.*?</table>', convert_html_table, markdown, flags=re.DOTALL)

        # Blockquotes: <blockquote>text</blockquote> -> > text
        markdown = re.sub(r'<blockquote>([^<]+)</blockquote>', r'\n\n> \1\n\n', markdown)

        # Lists - unordered: <ul><li>text</li></ul> -> - text
        markdown = re.sub(r'<ul><li>([^<]+)</li></ul>', r'\n\n- \1\n', markdown)

        # Lists - ordered: <ol><li>text</li></ol> -> 1. text
        markdown = re.sub(r'<ol><li>([^<]+)</li></ol>', r'\n\n1. \1\n', markdown)

        # Paragraphs: <p>text</p> -> text (with newlines)
        markdown = re.sub(r'<p>([^<]+)</p>', r'\1\n\n', markdown)

    # Handle inline formatting (for both markup types)

    # Images: <img alt="alt" src="src" title="title"/> -> ![alt](src "title")
    markdown = re.sub(r'<img\s+alt="([^"]*)"\s+src="([^"]+)"\s+title="([^"]*)"\s*/>',
                      r'![\1](\2 "\3")', markdown)
    markdown = re.sub(r'<img\s+alt="([^"]*)"\s+src="([^"]+)"\s*/>',
                      r'![\1](\2)', markdown)

    # Links: <a href="url" title="title">text</a> -> [text](url "title")
    markdown = re.sub(r'<a\s+href="([^"]+)"\s+title="([^"]*)">([^<]+)</a>',
                      r'[\3](\1 "\2")', markdown)
    markdown = re.sub(r'<a\s+href="([^"]+)">([^<]+)</a>',
                      r'[\2](\1)', markdown)

    # Strong emphasis: <strong>text</strong> -> **text**
    markdown = re.sub(r'<strong>([^<]+)</strong>', r'**\1**', markdown)

    # Emphasis: <em>text</em> -> *text*
    markdown = re.sub(r'<em>([^<]+)</em>', r'*\1*', markdown)

    # Inline code: <code>text</code> -> `text`
    markdown = re.sub(r'<code>([^<]+)</code>', r'`\1`', markdown)

    # Superscript: <sup>text</sup> -> ^text^
    markdown = re.sub(r'<sup>([^<]+)</sup>', r'^\1^', markdown)

    # Subscript: <sub>text</sub> -> ~text~
    markdown = re.sub(r'<sub>([^<]+)</sub>', r'~\1~', markdown)

    # Clean up any remaining HTML tags or artifacts
    markdown = re.sub(r'<[^>]+>', '', markdown)

    if multiline:
        # For multiline, preserve line structure but clean up excess whitespace
        lines = markdown.split('\n')
        cleaned_lines = []
        for line in lines:
            line = line.strip()
            if line:
                cleaned_lines.append(line)
            elif cleaned_lines and cleaned_lines[-1]:  # Add empty lines only between content
                cleaned_lines.append('')

        # Join lines and clean up multiple consecutive empty lines
        markdown = '\n'.join(cleaned_lines)
        markdown = re.sub(r'\n\n\n+', '\n\n', markdown)
    else:
        # For inline only, collapse whitespace
        markdown = re.sub(r'\s+', ' ', markdown)

    markdown = markdown.strip()
    return markdown

# -------------------------------------------------------------------------
def oscal_markdown_to_html(markdown_text, multiline=False):
    """
    Convert OSCAL markdown to HTML.

    Args:
        markdown_text (str): The markdown text to convert
        is_multiline (bool): If True, treats as markup-multiline (supports blocks).
                           If False, treats as markup-line (inline only).

    Returns:
        str: The converted HTML

    Examples:
        >>> convert_oscal_markdown_to_html("This is **bold** text")
        '<p>This is <strong>bold</strong> text</p>'

        >>> convert_oscal_markdown_to_html("Value: {{ insert: param, ac-1_prm_1 }}")
        '<p>Value: <insert id-ref="ac-1_prm_1" type="param" /></p>'

        >>> convert_oscal_markdown_to_html("# Title\\n\\nParagraph", is_multiline=True)
        '<h1>Title</h1>\\n<p>Paragraph</p>'
    """
    import re as _re

    # Configure extensions based on whether this is multiline or not
    extensions = [
        'extra',           # Tables, fenced code blocks, etc.
        'sane_lists',      # Better list handling
        OscalParameterExtension(),  # Custom OSCAL parameter insertion
    ]

    extension_configs = {
        'extra': {
            'markdown.extensions.fenced_code': {},
            'markdown.extensions.tables': {},
        }
    }

    # OSCAL markdown does not allow raw HTML.  Escape any angle bracket that
    # looks like the start of an HTML/XML tag (letter, /, or ! after <) so
    # the markdown library treats it as literal text rather than inline HTML.
    # This preserves the original case (e.g. <BREAK> stays <BREAK>, not <break>)
    # and ensures known HTML element names written literally (e.g. <em>text</em>)
    # are not mistaken for markup.  The OscalParameterExtension generates
    # <insert .../> in its *output*, not from the source, so it is unaffected.
    markdown_text = _re.sub(r'<(?=[a-zA-Z/!])', r'&lt;', markdown_text)

    # Create the markdown processor
    md = markdown.Markdown(
        extensions=extensions,
        extension_configs=extension_configs
    )

    # Convert to HTML
    html = md.convert(markdown_text)

    # Handle paragraph wrapping based on multiline setting
    if not multiline:
        # For markup-line (inline only), strip wrapping <p> tag if present
        # and convert any newlines to spaces for inline content
        if html.startswith('<p>') and html.endswith('</p>'):
            html = html[3:-4]  # Remove <p> and </p>
        # Replace any remaining newlines with spaces for true inline behavior
        html = html.replace('\n', ' ').strip()
    else:
        # For markup-multiline, ensure single lines get wrapped in <p> tags
        # Check if we have content that doesn't already have block tags
        has_block_tags = (
            html.startswith(('<p>', '<h1>', '<h2>', '<h3>', '<h4>', '<h5>', '<h6>',
                           '<ul>', '<ol>', '<li>', '<blockquote>', '<pre>', '<div>',
                           '<table>', '<tr>', '<td>', '<th>')) or
            html.endswith(('</p>', '</h1>', '</h2>', '</h3>', '</h4>', '</h5>', '</h6>',
                         '</ul>', '</ol>', '</li>', '</blockquote>', '</pre>', '</div>',
                         '</table>', '</tr>', '</td>', '</th>')) or
            '<p>' in html or '<h1>' in html or '<h2>' in html or '<h3>' in html or
            '<h4>' in html or '<h5>' in html or '<h6>' in html or '<ul>' in html or
            '<ol>' in html or '<blockquote>' in html or '<table>' in html
        )

        # If no block tags present and we have content, wrap in paragraph
        if not has_block_tags and html.strip():
            html = f'<p>{html}</p>'

    return html

# -------------------------------------------------------------------------
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
