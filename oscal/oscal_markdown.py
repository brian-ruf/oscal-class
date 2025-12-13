"""
OSCAL Markdown to HTML Converter

Converts OSCAL-compliant markdown (markup-line and markup-multiline) to HTML,
with support for the special parameter insertion syntax using {{ insert: type, id }}.
"""

# import re
import markdown
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from xml.etree import ElementTree as etree


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


class SubscriptProcessor(InlineProcessor):
    """
    Handles OSCAL subscript syntax: ~text~
    Converts to: <sub>text</sub>
    """
    
    def handleMatch(self, m, data):
        el = etree.Element('sub')
        el.text = m.group(1)
        return el, m.start(0), m.end(0)


class SuperscriptProcessor(InlineProcessor):
    """
    Handles OSCAL superscript syntax: ^text^
    Converts to: <sup>text</sup>
    """
    
    def handleMatch(self, m, data):
        el = etree.Element('sup')
        el.text = m.group(1)
        return el, m.start(0), m.end(0)


class OscalParameterExtension(Extension):
    """
    Markdown extension to handle OSCAL parameter insertion syntax.
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


def oscal_markdown_to_html(markdown_text, is_multiline=False):
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
    
    # Create the markdown processor
    md = markdown.Markdown(
        extensions=extensions,
        extension_configs=extension_configs
    )
    
    # Convert to HTML
    html = md.convert(markdown_text)
    
    # For markup-line (inline only), we may want to strip the wrapping <p> tag
    # that markdown automatically adds
    if not is_multiline and html.startswith('<p>') and html.endswith('</p>'):
        html = html[3:-4]  # Remove <p> and </p>
    
    return html


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
    return oscal_markdown_to_html(markdown_text, is_multiline=False)


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
    return oscal_markdown_to_html(markdown_text, is_multiline=True)


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


# Example usage
if __name__ == '__main__':
    # Test markup-line
    print("=== Testing markup-line ===")
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
