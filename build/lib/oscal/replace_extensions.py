"""
Simple script to replace file extension references within a file.
Given a file with extension .xml, .json, or .yaml, this script will
find references to the other two extensions and replace them with
the current file's extension.
"""

import sys
import os


def replace_extensions(filename):
    """
    Replace extension references in a file with the file's own extension.
    
    Args:
        filename: Path to the file to process
    """
    # Check if file exists
    if not os.path.exists(filename):
        print(f"Error: File '{filename}' not found")
        sys.exit(1)
    
    # Get the file extension
    _, ext = os.path.splitext(filename)
    ext = ext.lower()
    
    # Validate extension
    valid_extensions = ['.xml', '.json', '.yaml']
    if ext not in valid_extensions:
        print(f"Error: File must have extension .xml, .json, or .yaml (got '{ext}')")
        sys.exit(1)
    
    # Determine which extensions to replace
    extensions_to_replace = [e for e in valid_extensions if e != ext]
    
    # Map extensions to media types
    media_type_map = {
        '.xml': 'application/xml',
        '.json': 'application/json',
        '.yaml': 'application/yaml'
    }
    
    # Read the file content
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading file: {e}")
        sys.exit(1)
    
    # Replace the other extensions and media types with the current one
    original_content = content
    current_media_type = media_type_map[ext]
    
    for old_ext in extensions_to_replace:
        # Replace file extensions
        content = content.replace(old_ext, ext)
        # Replace media types
        old_media_type = media_type_map[old_ext]
        content = content.replace(old_media_type, current_media_type)
    
    # Check if any changes were made
    if content == original_content:
        print(f"No changes needed - no {' or '.join(extensions_to_replace)} references found")
        return
    
    # Write the modified content back to the file
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Successfully replaced extension and media-type references in '{filename}'")
        print(f"Extensions: {', '.join(extensions_to_replace)} → {ext}")
        print(f"Media types: {', '.join([media_type_map[e] for e in extensions_to_replace])} → {current_media_type}")
    except Exception as e:
        print(f"Error writing file: {e}")
        sys.exit(1)


def main():
    """Main entry point."""
    if len(sys.argv) != 2:
        print("Usage: python replace_extensions.py <filename>")
        print("Example: python replace_extensions.py data/file.xml")
        sys.exit(1)
    
    filename = sys.argv[1]
    replace_extensions(filename)


if __name__ == "__main__":
    main()
