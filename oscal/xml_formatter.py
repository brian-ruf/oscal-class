"""
XML Formatter Script

This script opens an XML file, formats it with proper indentation and line wrapping,
and saves it back to the same location without changing any meaningful content.
"""

import xml.etree.ElementTree as ET
import xml.dom.minidom
import argparse
import sys
# import re
# import os
from pathlib import Path

# Global configuration
LINE_WRAP_COLUMN = 80


def format_xml_file(file_path):
    """
    Format an XML file with proper indentation and line wrapping.

    Args:
        file_path (str): Path to the XML file to format

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Read the original XML content
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()

        # Validate XML structure with ElementTree
        ET.parse(file_path)

        # Use minidom to format while preserving original structure
        dom = xml.dom.minidom.parseString(content)

        # Format with pretty printing
        pretty_xml = dom.toprettyxml(indent="  ", encoding=None)

        # Clean up the output
        lines = pretty_xml.split('\n')

        # Remove empty lines and clean up
        cleaned_lines = []
        for line in lines:
            stripped = line.rstrip()
            if stripped:  # Only keep non-empty lines
                cleaned_lines.append(stripped)

        # Apply line wrapping for long lines
        wrapped_lines = []
        for line in cleaned_lines:
            if len(line) <= LINE_WRAP_COLUMN:
                wrapped_lines.append(line)
            else:
                # For very long lines, try to wrap at attribute boundaries
                if '=' in line and '<' in line and not line.strip().startswith('<!--'):
                    # This is likely an element with attributes
                    wrapped = wrap_xml_element(line)
                    wrapped_lines.extend(wrapped)
                else:
                    # For other long lines, just add them as-is to preserve content
                    wrapped_lines.append(line)

        # Join lines and ensure proper line endings
        formatted_xml = '\n'.join(wrapped_lines)

        # Ensure file ends with newline
        if not formatted_xml.endswith('\n'):
            formatted_xml += '\n'

        # Write the formatted XML back to the same file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(formatted_xml)

        print(f"Successfully formatted XML file: {file_path}")
        return True

    except ET.ParseError as e:
        print(f"Error parsing XML file {file_path}: {e}")
        return False
    except Exception as e:
        print(f"Error processing file {file_path}: {e}")
        return False


def format_element(element, indent_level):
    """
    Recursively format an XML element with proper indentation.

    Args:
        element: The XML element to format
        indent_level: Current indentation level

    Returns:
        str: Formatted XML string for this element
    """
    indent = '  ' * indent_level
    lines = []

    # Build the opening tag
    tag_parts = [element.tag]

    # Add attributes
    if element.attrib:
        for key, value in element.attrib.items():
            tag_parts.append(f'{key}="{value}"')

    # Create the opening tag line
    if len(tag_parts) == 1:
        opening_tag = f'<{tag_parts[0]}>'
    else:
        # Check if we need to wrap attributes
        full_tag = '<' + ' '.join(tag_parts) + '>'
        if len(indent + full_tag) <= LINE_WRAP_COLUMN:
            opening_tag = full_tag
        else:
            # Wrap attributes
            opening_tag = f'<{tag_parts[0]}'
            for attr in tag_parts[1:]:
                if len(indent + opening_tag + ' ' + attr + '>') <= LINE_WRAP_COLUMN:
                    opening_tag += ' ' + attr
                else:
                    lines.append(indent + opening_tag)
                    opening_tag = indent + '    ' + attr
            opening_tag += '>'

    # Handle element content
    has_children = len(element) > 0
    has_text = element.text and element.text.strip()

    if not has_children and not has_text:
        # Self-closing or empty element
        if opening_tag.endswith('>'):
            opening_tag = opening_tag[:-1] + '/>'
        lines.append(indent + opening_tag)
    elif not has_children and has_text:
        # Element with only text content
        text_content = element.text.strip()
        full_line = indent + opening_tag + text_content + f'</{element.tag}>'
        if len(full_line) <= LINE_WRAP_COLUMN:
            lines.append(full_line)
        else:
            # Split across multiple lines
            lines.append(indent + opening_tag)
            lines.append(indent + '  ' + text_content)
            lines.append(indent + f'</{element.tag}>')
    else:
        # Element with children
        lines.append(indent + opening_tag)

        # Add text content if present
        if has_text:
            lines.append(indent + '  ' + element.text.strip())

        # Add children
        for child in element:
            child_lines = format_element(child, indent_level + 1)
            lines.append(child_lines)

            # Add tail text if present
            if child.tail and child.tail.strip():
                lines.append(indent + '  ' + child.tail.strip())

        # Add closing tag
        lines.append(indent + f'</{element.tag}>')

    return '\n'.join(lines)


def wrap_xml_element(line):
    """
    Wrap a long XML element line at attribute boundaries.

    Args:
        line (str): The XML line to wrap

    Returns:
        list: List of wrapped lines
    """
    # Find the opening tag
    tag_start = line.find('<')
    tag_end = line.find('>')

    if tag_start == -1 or tag_end == -1:
        return [line]

    # Extract indentation
    indent = line[:tag_start]

    # Extract tag name
    tag_content = line[tag_start:tag_end + 1]
    remaining = line[tag_end + 1:]

    # If the tag itself is not too long, don't wrap
    if len(indent + tag_content) <= LINE_WRAP_COLUMN:
        return [line]

    # Try to wrap at attribute boundaries
    if ' ' not in tag_content:
        return [line]  # No attributes to wrap

    # Split tag content into parts
    parts = tag_content.split(' ')
    if len(parts) < 2:
        return [line]

    wrapped_lines = []
    current_line = indent + parts[0]  # Start with opening tag

    for part in parts[1:]:
        # Check if adding this part would exceed the line limit
        if len(current_line + ' ' + part) > LINE_WRAP_COLUMN:
            # Add current line and start a new one
            wrapped_lines.append(current_line)
            current_line = indent + '    ' + part  # Extra indentation for attributes
        else:
            current_line += ' ' + part

    # Add the final line with any remaining content
    wrapped_lines.append(current_line + remaining)

    return wrapped_lines


def find_xml_files(directory_path, recursive=False):
    """
    Find all XML files in a directory.

    Args:
        directory_path (str): Path to the directory to search
        recursive (bool): Whether to search recursively in subdirectories

    Returns:
        list: List of XML file paths
    """
    xml_files = []
    directory = Path(directory_path)

    if recursive:
        # Use glob to find all XML files recursively
        xml_files = list(directory.rglob('*.xml'))
    else:
        # Find XML files only in the current directory
        xml_files = list(directory.glob('*.xml'))

    return [str(xml_file) for xml_file in xml_files]


def main():
    """Main function to handle command line arguments and process the XML file(s)."""
    global LINE_WRAP_COLUMN

    parser = argparse.ArgumentParser(
        description='Format XML files with proper indentation and line wrapping'
    )
    parser.add_argument(
        'xml_path',
        help='Path to the XML file or directory containing XML files to format'
    )
    parser.add_argument(
        '--line-wrap',
        type=int,
        default=LINE_WRAP_COLUMN,
        help=f'Column width for line wrapping (default: {LINE_WRAP_COLUMN})'
    )
    parser.add_argument(
        '-r', '--recurse',
        action='store_true',
        help='Recursively format XML files in subdirectories (only applies when path is a directory)'
    )

    args = parser.parse_args()

    # Update global line wrap setting if provided
    LINE_WRAP_COLUMN = args.line_wrap

    # Check if path exists
    xml_path = Path(args.xml_path)
    if not xml_path.exists():
        print(f"Error: Path '{args.xml_path}' does not exist.")
        sys.exit(1)

    xml_files_to_process = []

    if xml_path.is_file():
        # Single file processing
        if not xml_path.suffix.lower() == '.xml':
            print(f"Error: '{args.xml_path}' is not an XML file.")
            sys.exit(1)
        xml_files_to_process = [str(xml_path)]
    elif xml_path.is_dir():
        # Directory processing
        xml_files_to_process = find_xml_files(args.xml_path, args.recurse)
        if not xml_files_to_process:
            print(f"No XML files found in directory '{args.xml_path}'")
            if not args.recurse:
                print("Use -r/--recurse to search subdirectories")
            sys.exit(0)

        print(f"Found {len(xml_files_to_process)} XML file(s) to format")
        if args.recurse:
            print("Searching recursively in subdirectories")
    else:
        print(f"Error: '{args.xml_path}' is neither a file nor a directory.")
        sys.exit(1)

    # Process all XML files
    success_count = 0
    total_count = len(xml_files_to_process)

    for xml_file in xml_files_to_process:
        success = format_xml_file(xml_file)
        if success:
            success_count += 1

    # Print summary
    if total_count > 1:
        print(f"\nSummary: Successfully formatted {success_count} out of {total_count} XML files")
        if success_count < total_count:
            print(f"Failed to format {total_count - success_count} files")

    if success_count < total_count:
        sys.exit(1)


if __name__ == '__main__':
    main()
