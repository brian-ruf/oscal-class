"""
Script to fix import statement references in OSCAL files.
Ensures referenced files match the current file's format (XML, JSON, or YAML).
Handles both direct href links and resource fragment references.
"""

import json
import yaml
import xml.etree.ElementTree as ET
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# OSCAL namespace
OSCAL_NS = "http://csrc.nist.gov/ns/oscal/1.0"

# OSCAL model types (document root elements)
OSCAL_MODELS = [
    'assessment-plan',
    'assessment-results',
    'system-security-plan',
    'component-definition',
    'profile',
    'catalog',
    'plan-of-action-and-milestones'
]

# Media type mappings
MEDIA_TYPES = {
    'xml': 'application/xml',
    'json': 'application/json',
    'yaml': 'application/yaml'
}

# File extension mappings
EXTENSIONS = {
    'xml': '.xml',
    'json': '.json',
    'yaml': '.yaml'
}

def detect_file_format(file_path: Path) -> str:
    """Detect the format of an OSCAL file based on its extension."""
    suffix = file_path.suffix.lower()
    if suffix == '.xml':
        return 'xml'
    elif suffix == '.json':
        return 'json'
    elif suffix in ['.yaml', '.yml']:
        return 'yaml'
    else:
        raise ValueError(f"Unsupported file format: {suffix}")

def get_import_statements_xml(root: ET.Element) -> List[ET.Element]:
    """Find all import statements in XML OSCAL document."""
    import_elements = []

    # Find all import statement types (XML uses singular form)
    import_types = ['import-profile', 'import-ssp', 'import-ap', 'import-component-definition']
    for import_type in import_types:
        elements = root.findall(f".//{{{OSCAL_NS}}}{import_type}")
        import_elements.extend(elements)

    return import_elements

def get_import_statements_json_yaml(data: Dict) -> List[Dict]:
    """Find all import statements in JSON/YAML OSCAL document."""
    import_statements = []

    # Determine the document type and get the appropriate root element
    doc_root = None
    for model in OSCAL_MODELS:
        if model in data:
            doc_root = data[model]
            break

    if doc_root is None:
        # Fallback to root level
        doc_root = data

    # Check for import statements (JSON/YAML uses plural for component-definitions)
    import_types = ['import-profile', 'import-ssp', 'import-ap', 'import-component-definitions']
    for import_type in import_types:
        if import_type in doc_root:
            # Handle both single import and array of imports
            import_data = doc_root[import_type]
            if isinstance(import_data, list):
                # Multiple imports (like import-component-definitions)
                for item in import_data:
                    import_statements.append({
                        'type': import_type,
                        'data': item
                    })
            else:
                # Single import
                import_statements.append({
                    'type': import_type,
                    'data': import_data
                })

    return import_statements

def find_resource_by_uuid(back_matter: Dict, uuid: str) -> Optional[Dict]:
    """Find a resource in back-matter by UUID."""
    if not back_matter or 'resources' not in back_matter:
        return None

    for resource in back_matter['resources']:
        if resource.get('uuid') == uuid:
            return resource

    return None

def find_resource_by_uuid_xml(root: ET.Element, uuid: str) -> Optional[ET.Element]:
    """Find a resource in XML back-matter by UUID."""
    resources = root.findall(f".//{{{OSCAL_NS}}}back-matter/{{{OSCAL_NS}}}resource[@uuid='{uuid}']")
    return resources[0] if resources else None

def update_file_extension(href: str, target_format: str) -> str:
    """Update file extension to match target format."""
    # Handle relative paths
    path_parts = href.split('/')
    filename = path_parts[-1]

    # Remove existing extension and add new one
    name_without_ext = os.path.splitext(filename)[0]
    new_filename = name_without_ext + EXTENSIONS[target_format]

    # Reconstruct path
    path_parts[-1] = new_filename
    return '/'.join(path_parts)

def clean_rlinks(resource: Dict, target_format: str) -> bool:
    """Clean rlinks in a resource, keeping only target format and non-OSCAL formats."""
    if 'rlinks' not in resource:
        return False

    modified = False
    target_media_type = MEDIA_TYPES[target_format]
    rlinks_to_keep = []
    oscal_rlink_found = False

    for rlink in resource['rlinks']:
        media_type = rlink.get('media-type', '')
        href = rlink.get('href', '')

        # If it's an OSCAL format (xml, json, yaml)
        if media_type in MEDIA_TYPES.values():
            # Only keep the first OSCAL rlink and update it to target format
            if not oscal_rlink_found:
                oscal_rlink_found = True

                # Update media-type if needed
                if media_type != target_media_type:
                    rlink['media-type'] = target_media_type
                    modified = True

                # Update href file extension if needed
                if href:
                    new_href = update_file_extension(href, target_format)
                    if new_href != href:
                        rlink['href'] = new_href
                        modified = True

                rlinks_to_keep.append(rlink)
            else:
                # Remove additional OSCAL format rlinks
                modified = True
        # Keep all non-OSCAL formats (PDFs, web pages, etc.)
        else:
            rlinks_to_keep.append(rlink)

    if modified:
        resource['rlinks'] = rlinks_to_keep

    return modified

def clean_rlinks_xml(resource_elem: ET.Element, target_format: str) -> bool:
    """Clean rlinks in XML resource, keeping only target format and non-OSCAL formats."""
    rlinks = resource_elem.findall(f"{{{OSCAL_NS}}}rlink")
    if not rlinks:
        return False

    modified = False
    target_media_type = MEDIA_TYPES[target_format]
    oscal_rlink_found = False
    rlinks_to_remove = []

    for rlink in rlinks:
        media_type = rlink.get('media-type', '')
        href = rlink.get('href', '')

        # If it's an OSCAL format (xml, json, yaml)
        if media_type in MEDIA_TYPES.values():
            # Only keep the first OSCAL rlink and update it to target format
            if not oscal_rlink_found:
                oscal_rlink_found = True

                # Update media-type if needed
                if media_type != target_media_type:
                    rlink.set('media-type', target_media_type)
                    modified = True

                # Update href file extension if needed
                if href:
                    new_href = update_file_extension(href, target_format)
                    if new_href != href:
                        rlink.set('href', new_href)
                        modified = True
            else:
                # Mark additional OSCAL format rlinks for removal
                rlinks_to_remove.append(rlink)
                modified = True
        # Keep all non-OSCAL formats (PDFs, web pages, etc.)

    # Remove marked rlinks
    for rlink in rlinks_to_remove:
        resource_elem.remove(rlink)

    return modified

def fix_xml_references(file_path: Path) -> bool:
    """Fix references in XML OSCAL files."""
    try:
        # Parse XML
        tree = ET.parse(file_path)
        root = tree.getroot()

        # Register namespace
        ET.register_namespace('', OSCAL_NS)

        modified = False
        target_format = detect_file_format(file_path)

        # Find all import statements
        import_elements = get_import_statements_xml(root)

        for import_elem in import_elements:
            href = import_elem.get('href')
            if not href:
                continue

            # Handle resource fragment references (starting with #)
            if href.startswith('#'):
                uuid = href[1:]  # Remove the #
                resource_elem = find_resource_by_uuid_xml(root, uuid)

                if resource_elem is not None:
                    # Clean rlinks in the referenced resource
                    if clean_rlinks_xml(resource_elem, target_format):
                        modified = True

            # Handle direct file references
            else:
                # Update file extension to match current format
                new_href = update_file_extension(href, target_format)
                if new_href != href:
                    import_elem.set('href', new_href)
                    modified = True

        # Find all link elements with URI fragment references
        link_elements = root.findall(f".//{{{OSCAL_NS}}}link")
        for link_elem in link_elements:
            href = link_elem.get('href')
            if href and href.startswith('#'):
                uuid = href[1:]  # Remove the #
                resource_elem = find_resource_by_uuid_xml(root, uuid)

                if resource_elem is not None:
                    # Clean rlinks in the referenced resource
                    if clean_rlinks_xml(resource_elem, target_format):
                        modified = True

        # Save if modified
        if modified:
            tree.write(file_path, encoding='utf-8', xml_declaration=True)
            print(f"Fixed references in: {file_path}")
            return True

    except Exception as e:
        print(f"Error processing XML file {file_path}: {e}")
        return False

    return False

def fix_json_yaml_references(file_path: Path, is_yaml: bool = False) -> bool:
    """Fix references in JSON/YAML OSCAL files."""
    try:
        # Load data
        with open(file_path, 'r', encoding='utf-8') as f:
            if is_yaml:
                data = yaml.safe_load(f)
            else:
                data = json.load(f)

        modified = False
        target_format = detect_file_format(file_path)

        # Determine the document type and get the appropriate root element
        doc_root = None
        for model in OSCAL_MODELS:
            if model in data:
                doc_root = data[model]
                break

        if doc_root is None:
            # Fallback to root level
            doc_root = data

        # Find all import statements
        import_statements = get_import_statements_json_yaml(data)

        for import_stmt in import_statements:
            import_data = import_stmt['data']
            href = import_data.get('href')

            if not href:
                continue

            # Handle resource fragment references (starting with #)
            if href.startswith('#'):
                uuid = href[1:]  # Remove the #
                back_matter = doc_root.get('back-matter', {})
                resource = find_resource_by_uuid(back_matter, uuid)

                if resource is not None:
                    # Clean rlinks in the referenced resource
                    if clean_rlinks(resource, target_format):
                        modified = True

            # Handle direct file references
            else:
                # Update file extension to match current format
                new_href = update_file_extension(href, target_format)
                if new_href != href:
                    import_data['href'] = new_href
                    modified = True

        # Save if modified
        if modified:
            with open(file_path, 'w', encoding='utf-8') as f:
                if is_yaml:
                    yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
                else:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"Fixed references in: {file_path}")
            return True

    except Exception as e:
        print(f"Error processing {'YAML' if is_yaml else 'JSON'} file {file_path}: {e}")
        return False

    return False

def process_file(file_path: Path) -> bool:
    """Process a single OSCAL file."""
    try:
        file_format = detect_file_format(file_path)

        if file_format == 'xml':
            return fix_xml_references(file_path)
        elif file_format == 'json':
            return fix_json_yaml_references(file_path, is_yaml=False)
        elif file_format == 'yaml':
            return fix_json_yaml_references(file_path, is_yaml=True)
        else:
            print(f"Unsupported file format: {file_path}")
            return False

    except Exception as e:
        print(f"Error processing file {file_path}: {e}")
        return False

def process_directory(directory: Path) -> Tuple[int, int]:
    """Process all OSCAL files in directory and subdirectories."""
    if not directory.exists():
        print(f"Directory does not exist: {directory}")
        return 0, 0

    files_processed = 0
    files_modified = 0

    # Find all OSCAL files
    for pattern in ['*.xml', '*.json', '*.yaml', '*.yml']:
        for file_path in directory.rglob(pattern):
            files_processed += 1
            if process_file(file_path):
                files_modified += 1

    return files_processed, files_modified

def main():
    """Main function."""
    if len(sys.argv) < 2:
        print("Usage: python fix_references.py <file_or_directory> [file_or_directory...]")
        print("Examples:")
        print("  python fix_references.py data/")
        print("  python fix_references.py file1.xml file2.json")
        print("  python fix_references.py data/xml/ data/json/ data/yaml/")
        sys.exit(1)

    print("Fixing OSCAL import statement references...")
    print("=" * 60)

    total_processed = 0
    total_modified = 0

    for arg in sys.argv[1:]:
        path = Path(arg)

        if not path.exists():
            print(f"Error: Path '{path}' does not exist")
            continue

        if path.is_file():
            # Process single file
            print(f"Processing file: {path}")
            total_processed += 1
            if process_file(path):
                total_modified += 1

        elif path.is_dir():
            # Process directory
            print(f"Processing directory: {path}")
            processed, modified = process_directory(path)
            total_processed += processed
            total_modified += modified
            print(f"  Processed {processed} files, modified {modified}")

        else:
            print(f"Error: '{path}' is neither a file nor directory")

    print("=" * 60)
    print(f"Summary: Processed {total_processed} files, modified {total_modified}")

    if total_modified > 0:
        print("✅ Reference fixing completed successfully!")
    else:
        print("ℹ️  No files needed modification")

if __name__ == "__main__":
    main()
