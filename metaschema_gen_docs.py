import asyncio
import sys
import json
# import glob
from html import escape
import html
from loguru import logger
from time import sleep
from oscal_support import *
from common import *

""" OSCAL Metaschema Documentation Generator
This script generates HTML documentation for OSCAL metaschemas.
It processes JSON files containing the metaschema definitions and generates a collapsible HTML tree view for each schema.
It supports multiple formats (XML, JSON, YAML) and can handle various OSCAL versions.
"""

DATA_LOCATION = "./"

# TODO:
# - Handle group-as on output
# - Handle choicie on output
# - Handle unwrapped on output


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
async def generate_documentation(support=None, oscal_version=None) -> int:
    """
    Generate documentation from processed OSCAL metaschema.
    """

    status = False
    ret_value = 1

    # If support object is not provided, we have to instantiate it.
    if support is None:
        base_url = "./support/support.oscal"
        support = await setup_support(base_url)

    if support.ready:
        logger.debug("Support file is ready.")
        status = True
    else:
        logger.error("Support object is not ready.")

    # If the support object is ready, we can proceed.
    if status:
        logger.info("Generating documentation from OSCAL metaschema.")

        if oscal_version is None: # If no version is specified, process all supported versions.
            logger.info("Processing all supported OSCAL versions.")
            for version in support.versions.keys():
                logger.info(f"Version: {version}")
                status = await parse_metaschema_specific(support, version)
                if not status:
                    logger.error(f"Failed to parse metaschema for version {version}.")
                    break

        elif oscal_version in support.versions: # If a valid version is specified, process only that version.
            logger.info(f"Processing OSCAL version: {oscal_version}")
            status = await parse_metaschema_specific(support, oscal_version)

        else: # If an invalid version is specified, log an error and exit.
            logger.error(f"Specified version {oscal_version} is not supported. Available versions: {', '.join(support.versions.keys())}")
            status = False






    if status:
        ret_value = 0
    else:
        logger.error("Failed to generate documentation. Exiting with error code 1.")
        ret_value = 1

    return ret_value

# -------------------------------------------------------------------------



# -------------------------------------------------------------------------
def generate_tree_view(metaschema_model_tree, oscal_version, format):
    """Generate HTML with collapsible tree from OSCAL JSON data."""
    
    style = """
        .tree-view {
            font-family: Arial, sans-serif;
            margin: 20px;
        }
        .tree-item {
            margin-left: 20px;
        }
        .collapsible {
            cursor: pointer;
            user-select: none;
            padding: 5px;
            margin: 2px 0;
            background-color: #f1f1f1;
            border-radius: 4px;
            display: block; /* Changed from inline-block to block */
            width: calc(100% - 10px); /* Account for padding */
        }
        .collapsible:hover {
            background-color: #ddd;
        }
        .content {
            display: none;
            margin-left: 20px;
        }
        .element-name {
            font-weight: bold;
            color: #2c5282;
            text-decoration: none;
        }
        .element-name:hover {
            text-decoration: underline;
        }
        .element-details {
            color: #4a5568;
            font-size: 0.9em;
        }
        .active {
            display: block;
        }
        .type-assembly { color: #3182ce; }
        .type-field { color: #805ad5; }
        .type-flag { color: #dd6b20; }
        .expander {
            display: inline-block;
            width: 15px;
            text-align: center;
            font-weight: bold;
            cursor: pointer;
        }
        .spacer {
            display: inline-block;
            width: 15px;
        }
"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{oscal_version} {metaschema_model_tree.get("schema_name", "[EMPTY]")} ({format.upper()})</title>
    <style>
{style}
    </style>
</head>
<body>
    <h1>{metaschema_model_tree.get("schema_name", "EMPTY")} {format.upper()}</h1>
    <h3>OSCAL Version: {oscal_version}</h3>
    
    <div class="tree-view">
"""
    
    # Process the root element
    if "nodes" in metaschema_model_tree:
        match format:
            case "xml":
                logger.info("Processing XML format")
                html += process_xml_element(metaschema_model_tree["nodes"], level=0)
            case "json" | "yaml":
                pass
                # html += process_json_element(metaschema_tree["nodes"], format, level=0)
    else:
        html += "<p>Model is empty.</p>"
        logger.error("No 'nodes' found in the metaschema model tree.")

    html += """
    </div>
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            var expanders = document.getElementsByClassName("expander");
            for (var i = 0; i < expanders.length; i++) {
                expanders[i].addEventListener("click", function(e) {
                    e.stopPropagation(); // Prevent event bubbling
                    var content = this.parentElement.nextElementSibling;
                    
                    if (content.style.display === "block") {
                        // Collapsing
                        content.style.display = "none";
                        this.textContent = "+";
                    } else {
                        // Expanding
                        content.style.display = "block";
                        this.textContent = "-";
                    }
                });
            }
            
            // Stop propagation for element name clicks
            var elementNames = document.getElementsByClassName("element-name");
            for (var i = 0; i < elementNames.length; i++) {
                elementNames[i].addEventListener("click", function(e) {
                    e.stopPropagation();
                    // You can add your click handler for the path here
                    console.log("Clicked on path:", this.getAttribute("data-path"));
                });
            }
            
            // Add click handler for the collapsible divs (optional)
            var collapsibles = document.getElementsByClassName("collapsible");
            for (var i = 0; i < collapsibles.length; i++) {
                collapsibles[i].addEventListener("click", function(e) {
                    if (e.target.classList.contains('element-name')) return;
                    
                    // Find the expander in this collapsible and trigger its click
                    var expander = this.querySelector('.expander');
                    if (expander) {
                        expander.click();
                    }
                });
            }
        });
    </script>
</body>
</html>
"""
    return html

# -------------------------------------------------------------------------
def process_json_element(element, format, level=0):
    """Process a single element in the OSCAL schema."""
    if not isinstance(element, dict):
        return ""
    
    html = ""
    
    # Get element properties
    use_name = element.get('use-name', element.get('name', 'unknown'))
    structure_type = element.get('structure-type', 'unknown')
    datatype = element.get('datatype', '')
    min_occurs = element.get('min-occurs', '')
    max_occurs = element.get('max-occurs', '')
    path = element.get('path', '')
    
    # Format occurrence information
    occurrence = ""
    if min_occurs == "0" and (max_occurs == "1" or max_occurs == "unbounded"):
        occurrence = "[0 or 1]" if max_occurs == "1" else "[0 or more]"
    elif min_occurs == "1" and max_occurs == "1":
        occurrence = "[exactly 1]"
    elif min_occurs == "1" and max_occurs == "unbounded":
        occurrence = "[1 or more]"
    else:
        occurrence = f"[{min_occurs}..{max_occurs}]"
    
    # Check if element has children or flags to determine if we need expansion control
    has_expandable = (element.get('flags', []) or element.get('children', []))
    
    # Create the element header with details
    html += '<div class="collapsible">'
    if has_expandable:
        # Set the initial expander symbol based on level
        expander_symbol = "-" if level == 0 else "+"
        html += f'<span class="expander">{expander_symbol}</span> '
    else:
        html += '<span class="spacer">&nbsp;</span> '
    html += f'<a href="#" class="element-name" data-path="{escape(path)}">{escape(use_name)}</a> '
    html += f'<span class="element-details type-{structure_type}">({structure_type})</span> '
    html += f'<span class="element-details">{escape(str(datatype))} {occurrence}</span>'
    html += '</div>'
    
    # Create content div for children and flags together
    if has_expandable:
        # Set initial display style based on level
        display_style = "block" if level == 0 else "none"
        html += f'<div class="content tree-item" style="display: {display_style};">'
        
        # Process flags (attributes)
        flags = element.get('flags', [])
        for flag in flags:
            html += process_json_element(flag, format, level + 1)
        
        # Process children
        children = element.get('children', [])
        for child in children:
            html += process_json_element(child, format, level + 1)
        
        html += '</div>'
    
    return html

# -------------------------------------------------------------------------
def process_xml_element(element, level=0):
    """Process a single element in the OSCAL schema."""
    if not isinstance(element, dict):
        return ""
    
    html = ""
    
    # Get element properties
    use_name = element.get('use-name', element.get('name', 'unknown'))
    structure_type = element.get('structure-type', 'unknown')
    datatype = element.get('datatype', '')
    min_occurs = element.get('min-occurs', '')
    max_occurs = element.get('max-occurs', '')
    path = element.get('path', '')
    logger.info(f"Processing element: {path}")
    
    # Format occurrence information
    occurrence = ""
    if min_occurs == "0" and (max_occurs == "1" or max_occurs == "unbounded"):
        occurrence = "[0 or 1]" if max_occurs == "1" else "[0 or more]"
    elif min_occurs == "1" and max_occurs == "1":
        occurrence = "[exactly 1]"
    elif min_occurs == "1" and max_occurs == "unbounded":
        occurrence = "[1 or more]"
    else:
        occurrence = f"[{min_occurs}..{max_occurs}]"
    
    # Check if element has children or flags to determine if we need expansion control
    has_expandable = (element.get('flags', []) or element.get('children', []))
    
    # Create the element header with details
    html += '<div class="collapsible">'
    if has_expandable:
        # Set the initial expander symbol based on level
        expander_symbol = "-" if level == 0 else "+"
        html += f'<span class="expander">{expander_symbol}</span> '
    else:
        html += '<span class="spacer">&nbsp;</span> '
    html += f'<a href="#" class="element-name" data-path="{escape(path)}">{escape(use_name)}</a> '
    html += f'<span class="element-details type-{structure_type}">({structure_type})</span> '
    html += f'<span class="element-details">{escape(str(datatype))} {occurrence}</span>'
    html += '</div>'
    
    # Create content div for children and flags together
    if has_expandable:
        # Set initial display style based on level
        display_style = "block" if level == 0 else "none"
        html += f'<div class="content tree-item" style="display: {display_style};">'
        
        # Process flags (attributes)
        flags = element.get('flags', [])
        for flag in flags:
            html += process_xml_element(flag, level + 1)
        
        # Process children
        children = element.get('children', [])
        for child in children:
            html += process_xml_element(child, level + 1)
        
        html += '</div>'
    
    return html

# -------------------------------------------------------------------------

async def generate_documentation(oscal_version=None, support=None) -> int:
    ret_value = False

    status = False
    ret_value = 1

    # If support object is not provided, we have to instantiate it.
    if support is None:
        base_url = "./support/support.oscal"
        support = await setup_support(base_url)

    if support.ready:
        logger.debug("Support file is ready.")
        status = True
    else:
        logger.error("Support object is not ready.")

    # If the support object is ready, we can proceed.
    if status:
        if oscal_version is None: # If no version is specified, process all supported versions.
            logger.info("Processing all supported OSCAL versions.")
            for version in support.versions.keys():
                logger.info(f"Version: {version}")
                # status = await parse_metaschema_specific(support, version)
                metaschema_tree = json.loads(await support.asset(version, "complete", "processed"))
                
                for format in ["xml"]: # , "json", "yaml"]:
                    for model in metaschema_tree["oscal_models"]:
                        prefix = f"OSCAL_{metaschema_tree['oscal_version']}_{model}_{format}"
                        html_output = generate_tree_view(metaschema_tree["oscal_models"][model], metaschema_tree["oscal_version"], format=format)
                        output_file = f"{DATA_LOCATION}/{prefix}_outline_{format}.html"
                        with open(output_file, 'w', encoding='utf-8') as f:
                            f.write(html_output)



                if not status:
                    logger.error(f"Failed to parse metaschema for version {version}.")
                    break

        elif oscal_version in support.versions: # If a valid version is specified, process only that version.
            logger.info(f"Processing OSCAL version: {oscal_version}")
            # status = await parse_metaschema_specific(support, oscal_version)
            metaschema_tree = json.loads(await support.asset(oscal_version, "complete", "processed"))
            for format in ["xml"]: # , "json", "yaml"]:
                for model in metaschema_tree["oscal_models"]:
                    prefix = f"OSCAL_{metaschema_tree['oscal_version']}_{model}_{format}"
                    html_output = generate_tree_view(metaschema_tree["oscal_models"][model], metaschema_tree["oscal_version"], format=format)
                    output_file = f"{DATA_LOCATION}/{prefix}_outline_{format}.html"
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(html_output)


        else: # If an invalid version is specified, log an error and exit.
            logger.error(f"Specified version {oscal_version} is not supported. Available versions: {', '.join(support.versions.keys())}")
            status = False

    return ret_value

if __name__ == "__main__":
    logger.remove()
    logger.add(
        sys.stderr,
        level="INFO",
        colorize=True
    )

    logger.add(
        "output.log",
        level="DEBUG",  # Log everything to file
        colorize=False,
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=True
    )

    try:
        exit_code = asyncio.run(generate_documentation(oscal_version="v1.1.3"))
        if exit_code == 0:
            logger.info("Application exited successfully.")
        elif exit_code == 1:
            logger.warning("Application exited with warnings.")
        else:
            logger.error(f"Unexpected exit value of type {str(type(exit_code))}")
        sys.exit(exit_code)
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)
