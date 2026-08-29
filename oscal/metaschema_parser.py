"""
metaschema_parser — parse NIST resolved-metaschema XML into a structural index.

Parses OSCAL resolved-metaschema XML files into a dictionary representation of the
metaschema structure (assemblies, fields, flags, attributes, child elements, and
allowed-value constraints). The resulting index drives XML↔JSON conversion and
validation elsewhere in the library.

While there is some defensive coding, this module assumes metaschema files are
valid; it does not validate metaschema structure or content. It ignores unexpected
structures and logs a WARNING when it encounters expected but unhandled structures.

Module constants:
    SUPPRESS_XPATH_NOT_FOUND_WARNINGS (bool): Suppress warnings when an XPath yields
        no match.
    RUNAWAY_LIMIT (int): Maximum recursion/iteration count before aborting as a
        runaway.
    DEBUG_OBJECT (str): Name of a definition to trace for debugging ("" disables).
    PRUNE_JSON (bool): Remove None values and empty arrays from the resolved JSON output.
    OSCAL_DEFAULT_NAMESPACE (str): The NIST OSCAL namespace URI.
    METASCHEMA_DEFAULT_NAMESPACE (str): The NIST Metaschema namespace URI.
    METASCHEMA_TOP_IGNNORE (list): Top-level metaschema elements to ignore.
    METASCHEMA_TOP_KEEP (list): Top-level metaschema elements to process.
    METASCHEMA_PROPS_HANDLED (list): Metaschema ``prop`` names handled on definitions.
    METASCHEMA_RULE_PROPS_HANDLED (list): Metaschema ``prop`` names handled on rules.
    METASCHEMA_INDEX_PROPS_HANDLED (list): Metaschema ``prop`` names handled on indexes.
    METASCHEMA_ROP_NAMESPACE (list): Recognized metaschema property namespace URIs.
    METASCHEMA_ROOT_ELEMENT (str): Root element name of a metaschema document
        ("METASCHEMA").
    CONSTRAINT_ROOT_ELEMENT (str): Root element name of a meta-constraints document.
    CONSTRAINT_TOP_IGNORE (list): Top-level constraint elements to ignore.
    CONSTRAINT_TOP_KEEP (list): Top-level constraint elements to process.
    GREEN, BLUE, YELLOW, RED, ORANGE, MAGENTA, CYAN, PURPLE, BOLD, RESET (str):
        ANSI terminal escape codes used for colorized diagnostic output.
"""
from __future__ import annotations

import sys
import re
import json
import uuid
from datetime import datetime, timezone
# from html import escape
# import html
# from urllib.parse import urljoin
from typing import cast
import logging
from .oscal_support import get_support, METASCHEMA_INDEX_VERSION
from xml.etree import ElementTree as ET
from ruf_common.helper import iif, compare_semver
from ruf_common.data import deserialize_xml, xpath, xpath_atomic, get_markup_content

logger = logging.getLogger(__name__)

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# TODO:
# - Add support for metaschema constraints
# TODO: Fix the recursion detection, such as for task/task or part/part.
# TODO: Fix handling of Group-as elements (May be fixed. Need to verify.)
# -------------------------------------------------------------------------

global_counter = 0
global_unhandled_report = []
global_stop_here = False

"""Metaschema Parser for OSCAL
This module provides functionality to parse and process OSCAL metaschema XML files.

While there is some defensive coding, this module assumes metaschema files are valid.

It is not intended to validate metaschema structure or content.
It will ignore unexpected structures.
It will issue a WARNING message if it encounteres expected, but unhandled structures. 

"""
SUPPRESS_XPATH_NOT_FOUND_WARNINGS = True
RUNAWAY_LIMIT = 8000
DEBUG_OBJECT = ""

PRUNE_JSON = True  # If true, will remove None values and emnpty arrays from the Resolved JSON Metaschema output
OSCAL_DEFAULT_NAMESPACE = "http://csrc.nist.gov/ns/oscal"
METASCHEMA_DEFAULT_NAMESPACE = "http://csrc.nist.gov/ns/oscal/metaschema/1.0"
METASCHEMA_TOP_IGNNORE = ["schema-name", "schema-version", "short-name", "namespace", "json-base-uri", "remarks", "import"]
METASCHEMA_TOP_KEEP = ["define-assembly", "define-field", "define-flag", "constraint"]
METASCHEMA_PROPS_HANDLED = ["identifier-persistence", "identifier-scope", "identifier-type", "identifier-uniqueness", "value-type"]
METASCHEMA_RULE_PROPS_HANDLED = []
METASCHEMA_INDEX_PROPS_HANDLED = []
METASCHEMA_ROP_NAMESPACE = ["http://csrc.nist.gov/ns/oscal/metaschema/1.0", "http://csrc.nist.gov/ns/metaschema/1.0"]
METASCHEMA_ROOT_ELEMENT = "METASCHEMA"
CONSTRAINT_ROOT_ELEMENT = "metaschema-meta-constraints"
CONSTRAINT_TOP_IGNORE = []
CONSTRAINT_TOP_KEEP = ["context"]

GREEN   = "\033[32m"
BLUE    = "\033[34m"
YELLOW  = "\033[33m"
RED     = "\033[31m"
ORANGE  = "\033[38;5;208m"
MAGENTA = "\033[35m"
CYAN    = "\033[36m"
PURPLE  = "\033[38;5;129m"
BOLD    = "\033[1m"
RESET   = "\033[0m"

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
def parse_metaschema(support=None, oscal_version=None, save_to_fs=False) -> int:
    """
    Parse and store the OSCAL metaschema index for one or all supported versions.

    Args:
        support (OSCALSupport, optional): The OSCAL support object. Currently the
            shared instance is fetched internally via ``get_support()`` regardless
            of this argument. Defaults to None.
        oscal_version (str, optional): The OSCAL version to parse. When None, all
            supported versions are processed. Defaults to None.
        save_to_fs (bool, optional): When True, also write each model index (and the
            parse report) to the local file system. Defaults to False (database only).

    Returns:
        int: 0 on success, 1 on error (process-style exit code).
    """

    status = False
    ret_value = 1

    # If support object is not provided, we have to instantiate it.
    support = get_support()


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
                status = parse_metaschema_specific(support, version, save_to_fs=save_to_fs)
                if not status:
                    logger.error(f"Failed to parse metaschema for version {version}.")
                    break

        elif oscal_version in support.versions: # If a valid version is specified, process only that version.
            logger.info(f"Processing OSCAL version: {oscal_version}")
            status = parse_metaschema_specific(support, oscal_version, save_to_fs=save_to_fs)

        else: # If an invalid version is specified, log an error and exit.
            logger.error(f"Specified version {oscal_version} is not supported. Available versions: {', '.join(support.versions.keys())}")
            status = False
    if status:
        ret_value = 0
    else:
        logger.error("Failed to parse metaschema. Exiting with error code 1.")
        ret_value = 1

    return ret_value

# --------------------------------------------------------------------------
def parse_metaschema_specific(support, oscal_version, save_to_fs=False):
    """
    Parse and store every model index for a specific OSCAL version.

    Each model index is stored in the support database as
    ``(version, model, "processed")``. When ``save_to_fs`` is True it is also written
    to ``support/<version>/<model>.json`` alongside the support database.

    Args:
        support (OSCALSupport, required): The OSCAL support object providing
            metaschema assets and asset storage.
        oscal_version (str, required): The OSCAL version to parse.
        save_to_fs (bool, optional): When True, also write each model index (and the
            parse report) to the local file system. Defaults to False (database only).

    Returns:
        bool: True if all models parsed and stored successfully, False otherwise.
    """
    import os
    global global_counter, global_stop_here
    logger.info(f"{CYAN}Parsing OSCAL {oscal_version} metaschema.{RESET}")
    all_ok = True

    # Output directory (only created/used when writing to the file system): same
    # folder as the support database, under a sub-folder named after the version.
    db_conn = getattr(support, "db_conn", None)
    if db_conn:
        support_dir = os.path.join(os.path.dirname(os.path.abspath(db_conn)), oscal_version)
    else:
        support_dir = os.path.join("support", oscal_version)
    if save_to_fs:
        os.makedirs(support_dir, exist_ok=True)

    models = support.enumerate_models(oscal_version)

    models_processed: list = []
    unresolved_by_model: dict = {}

    # Registry of parsed imports, shared across every model of this version so a
    # metaschema imported by more than one model is parsed once. Cleared at the end.
    import_registry: dict = {}

    for model in models:
        if model == "complete":
            continue
        global_counter = 0
        global_stop_here = False
        logger.info(f"Parsing {model} metaschema.")
        model_metaschema = support.asset(oscal_version, model, "metaschema")
        if not model_metaschema:
            logger.error(f"Failed to fetch {model} metaschema content.")
            all_ok = False
            continue

        parser = MetaschemaParser.create(model_metaschema, support, oscal_version=oscal_version,
                                         import_registry=import_registry)
        if not parser.top_pass():
            logger.error(f"Failed to set up {model} metaschema XML.")
            all_ok = False
            continue

        model_index = parser.build_metaschema_tree()
        if not model_index:
            logger.error(f"Failed to parse {oscal_version} {model} metaschema. No data returned.")
            all_ok = False
            continue

        logger.debug(f"Successfully parsed {model} metaschema.")
        models_processed.append(model)

        nodes = model_index.get("nodes")
        if nodes:
            unresolved = _collect_unresolved_targets(nodes)
            if unresolved:
                unresolved_by_model[model] = unresolved
                logger.info(f"  {model}: {len(unresolved)} unresolved constraint target(s) remaining.")

        model_index = {
            "generated": datetime.now(timezone.utc).isoformat(),
            **model_index,
        }

        stored = support.add_asset(
            oscal_version, model, "processed",
            json.dumps(model_index, indent=2),
            filename=f"{model}.json",
        )
        if not stored:
            logger.error(f"Failed to store {oscal_version}/{model} processed index in support database.")
            all_ok = False

        if save_to_fs:
            output_file = os.path.join(support_dir, f"{model}.json")
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(model_index, f, indent=2)
            logger.debug(f"Wrote {output_file}")

    # Version complete — release the shared import registry.
    import_registry.clear()

    if save_to_fs:
        _write_metaschema_report(models_processed, unresolved_by_model, oscal_version, support_dir)

    if all_ok:
        # Record the index-schema version these processed indexes were built with, so the
        # database and any consuming library can detect index-schema mismatches.
        support.set_version_index_version(oscal_version, METASCHEMA_INDEX_VERSION)
        logger.info(f"{GREEN}Successfully parsed and stored all {oscal_version} metaschema models.{RESET}")
    else:
        logger.error(f"{RED}One or more {oscal_version} metaschema models failed to parse or store.{RESET}")

    return all_ok
# --------------------------------------------------------------------------
def _rebuild_model_index(support, oscal_version: str, model: str) -> dict | None:
    """Parse and store the metaschema index for a single model/version pair.

    Lighter-weight alternative to ``parse_metaschema_specific`` when only one
    model's index needs to be refreshed (e.g. lazy migration on first access).

    Returns the freshly-built model_index dict on success, or ``None`` on failure.
    """
    global global_counter, global_stop_here
    logger.info(f"Rebuilding metaschema index for {oscal_version}/{model}.")

    model_metaschema = support.asset(oscal_version, model, "metaschema")
    if not model_metaschema:
        logger.error(f"_rebuild_model_index: no raw metaschema for {oscal_version}/{model}.")
        return None

    global_counter = 0
    global_stop_here = False

    parser = MetaschemaParser.create(model_metaschema, support, oscal_version=oscal_version)
    if not parser.top_pass():
        logger.error(f"_rebuild_model_index: top_pass failed for {oscal_version}/{model}.")
        return None

    model_index = parser.build_metaschema_tree()
    if not model_index:
        logger.error(f"_rebuild_model_index: build_metaschema_tree returned nothing for {oscal_version}/{model}.")
        return None

    model_index = {
        "generated": datetime.now(timezone.utc).isoformat(),
        **model_index,
    }

    stored = support.add_asset(
        oscal_version, model, "processed",
        json.dumps(model_index, indent=2),
        filename=f"{model}.json",
    )
    if not stored:
        logger.warning(f"_rebuild_model_index: failed to store rebuilt index for {oscal_version}/{model}.")

    logger.info(f"Rebuilt metaschema index for {oscal_version}/{model}.")
    return model_index


# --------------------------------------------------------------------------
def clean_none_values_recursive(dictionary):
    """
    Recursively drop None values and empty containers from a dict.

    Removes key/value pairs whose value is None, and prunes empty nested dicts and
    lists (including dicts nested inside lists), returning a new cleaned dict.

    Args:
        dictionary (dict, required): The dictionary to clean.

    Returns:
        dict: A new dictionary with None values and empty containers removed.
    """
    result = {}
    for k, v in dictionary.items():
        if v is None:
            continue
        elif isinstance(v, dict):
            cleaned = clean_none_values_recursive(v)
            if cleaned:  # Only add non-empty dictionaries
                result[k] = cleaned
        elif isinstance(v, list):
            cleaned_list = []
            for item in v:
                if isinstance(item, dict):
                    cleaned_item = clean_none_values_recursive(item)
                    if cleaned_item:  # Only add non-empty dictionaries
                        cleaned_list.append(cleaned_item)
                elif item is not None:
                    cleaned_list.append(item)
            if cleaned_list:  # Only add non-empty lists
                result[k] = cleaned_list
        else:
            result[k] = v
    return result

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class MetaschemaParser:
    """Parses a single OSCAL resolved-metaschema XML document into a structural index.

    Holds the parsed metaschema tree and namespace/model context, resolves imported
    metaschemas, and walks assemblies, fields, and flags to build the nested index
    (nodes, attributes, allowed-value constraints) consumed by the converter and
    validator. Prefer the :meth:`create` classmethod to construct instances.
    """
    def __init__(self, metaschema, support, oscal_version="", import_registry=None):
        """Initialize a parser for one metaschema document.

        Args:
            metaschema (str, required): The resolved-metaschema XML content to parse.
            support (OSCALSupport, required): The OSCAL support object used to fetch
                imported metaschemas and store results.
            oscal_version (str, optional): The OSCAL version this metaschema belongs
                to. Defaults to "".
            import_registry (dict, optional): Shared registry of already-parsed imports
                (``href -> MetaschemaParser``), so a metaschema imported by more than one
                model is parsed once and reused. Endures across all models of one OSCAL
                version and is cleared when that version finishes. Defaults to ``None``
                (a fresh, isolated registry) — never a mutable default.
        """
        logger.debug("Initializing MetaschemaParser")
        self.content = metaschema
        self.valid_xml = False
        self.top_level = False
        self.xml_namespace = ""
        self.oscal_version = oscal_version
        self.oscal_model = ""
        self.schema_name = ""
        self.oscal_namespace = ""
        self.json_base_uri = ""
        self.tree = None
        self.nsmap = {"": METASCHEMA_DEFAULT_NAMESPACE}
        self.support = support
        self.imports = {} # list of imports {"metaschema_file_name.xml": MetaschemaParser_Object, ...}
        # This parser's node in the import-relationship tree: {"name", "children"}.
        # The name is filled in when known (the import href, or the model name for a root).
        self.import_inventory = {"name": "", "children": []}
        # Shared per-version registry so duplicate imports reuse one parsed object.
        self.import_registry = import_registry if import_registry is not None else {}

    # -------------------------------------------------------------------------
    @classmethod
    def create(cls, metaschema, support, oscal_version="", import_registry=None):
        """Construct a ``MetaschemaParser`` (preferred factory over direct instantiation).

        Args:
            metaschema (str, required): The resolved-metaschema XML content to parse.
            support (OSCALSupport, required): The OSCAL support object.
            oscal_version (str, optional): The OSCAL version. Defaults to "".
            import_registry (dict, optional): Shared per-version import registry (see
                :meth:`__init__`). Defaults to ``None`` — a fresh registry per top-level
                parse. Recursive import parsing threads the parent's registry down.

        Returns:
            MetaschemaParser: A new parser instance.
        """
        logger.debug("Creating MetaschemaParser")
        return cls(metaschema, support, oscal_version, import_registry)

    # -------------------------------------------------------------------------
    def __str__(self):
        """String representation of the MetaschemaParser."""
        ret_value = ""
        ret_value += f"Schema: {self.schema_name}\n"
        ret_value += f"Model: {self.oscal_model}\n"
        ret_value += f"Version: {self.oscal_version}\n"
        ret_value += f"XML Namespace: {self.nsmap}\n"
        ret_value += f"Valid XML: {iif(self.valid_xml, 'Yes', 'No')}\n"
        return ret_value
    
    # -------------------------------------------------------------------------
    def str_node(self, node):
        """Build a human-readable summary of a parsed metaschema index node.

        Args:
            node (dict, required): An index node produced by the parser, carrying
                keys such as ``formal-name``, ``use-name``, ``min-occurs``,
                ``max-occurs``, ``datatype``, ``children``, and ``constraints``.

        Returns:
            str: A multi-line, human-readable description of the node.
        """
        ret_value = ""
        ret_value += f"{node['formal-name']}: {node['use-name']}"
        if node["name"] != node["use-name"]:
            ret_value += f" ({node['name']})"
        if node["deprecated"] is True:
            ret_value += " ** Deprecated**"
        if node["sunsetting"] is not None:
            ret_value += f" Sunsetting: {node['sunsetting']}"
        ret_value += "\n"

        if node["min-occurs"] == "0":
            if node["max-occurs"] == "1":
                ret_value += "[0 or 1]"
            elif node["max-occurs"] == "unbounded":
                ret_value += "[0 or more]"
            elif node["max-occurs"] is not None:
                ret_value += f"[0 to {node['max-occurs']}]"
        elif node["min-occurs"] == "1":
            if node["max-occurs"] == "1":
                ret_value += "[exactly 1]"
            elif node["max-occurs"] == "unbounded":
                ret_value += "[1 or more]"
            elif node["max-occurs"] is not None:
                ret_value += f"[{node['min-occurs']} to {node['max-occurs']}]"
        else:
            if node["min-occurs"] is not None and node["max-occurs"] is not None:
                ret_value += f"[{node['min-occurs']} to {node['max-occurs']}]"
            else:
                ret_value += "[Cardinality not specified]"
        ret_value += f" {node['structure-type']} "
        ret_value += f" [{node['datatype']}]"
        ret_value += f"Path: {node['path']}\n"

        if node["default"] is not None:
            ret_value += f"Default: {node['default']}\n"
        if node["description"] is not None:
            ret_value += f"Description: {node['description']}\n"
        if node["remarks"] is not None:
            ret_value += f"Remarks: {node['remarks']}\n"
        if node["example"] is not None:
            ret_value += f"Example: {node['example']}\n"
        flag_count = sum(1 for c in node.get("children", []) if c.get("structure-type") == "flag")
        if flag_count:
            ret_value += f"Flags: {flag_count}\n"
        if node["source"] is not None:
            ret_value += f"Source: {', '.join(node['source'])}\n"
        if node["children"] is not None:
            ret_value += f"Children: {len(node['children'])}\n"
        if node["props"] is not None:
            ret_value += f"Props: {', '.join(node['props'])}\n"

        if node["group-as"] is not None:
            ret_value += "Group As: "
            if node["group-as-in-json"] is not None:
                ret_value += f" JSON: {node['group-as-in-json']}"
            if node["group-as-in-xml"] is not None:
                ret_value += f" XML: {node['group-as-in-xml']}"
            ret_value += "\n"

        # if node["json-array-name"]:
        #     ret_value += f"JSON Array Name: {node["json-array-name"]} "
        # if node["json-value-key"]:
        #     ret_value += f" JSON Value Key: {node["json-value-key"]}"
        # if node["json-value-key-flag"]:
        #     ret_value += f" JSON Value Key Flag: {node["json-value-key-flag"]}"
        # ret_value += "\n"

        if node["wrapped-in-xml"] is not None:
            if node["wrapped-in-xml"]:
                ret_value += "In XML: WRAPPED\n"
            else:
                ret_value += "In XML: UNWRAPPED\n"
            ret_value += "\n"
        if node.get("constraints"):
            ret_value += f"Constraints: {len(node['constraints'])}\n"
        return ret_value

    # -------------------------------------------------------------------------
    def top_pass(self):
        """Perform the first parsing pass: deserialize XML and read top-level metadata.

        Parses the metaschema content, then extracts the model name, schema name,
        OSCAL version, namespace, and JSON base URI, and sets up imports.

        Returns:
            bool: True if the XML was well-formed and parsed, False otherwise.
        """
        logger.debug("Performing top pass")

        try:
            self.tree = deserialize_xml(self.content, METASCHEMA_DEFAULT_NAMESPACE)
            self.valid_xml = True
            logger.debug(f"XML Valid! Content length: {len(self.content)}")
        except ET.ParseError as e:
            logger.error(f"XML parsing error: {e}")
            self.valid_xml = False

        if self.valid_xml:
            self.oscal_model = self.xpath_atomic("/METASCHEMA/define-assembly/root-name/text()")
            if self.oscal_model:
                self.top_level = True
            else:
                self.oscal_model = self.xpath_atomic("/METASCHEMA/short-name/text()")
                if not self.oscal_model:
                    self.oscal_model = "unnamed-imported-metaschema"
            self.schema_name = self.xpath_atomic("/METASCHEMA/schema-name/text()")
            if self.oscal_version == "":
                self.oscal_version = f"v{self.xpath_atomic('/METASCHEMA/schema-version/text()')}"
                logger.info(f"DEBUG: Setting version to {self.oscal_version} for {self.oscal_model}")

            self.oscal_namespace = self.xpath_atomic("/METASCHEMA/namespace/text()")
            self.json_base_uri = self.xpath_atomic("/METASCHEMA/json-base/text()")

            self.setup_imports()
            # self.handle_imports()
        else:        
            logger.error("Invalid XML content.")

        return self.valid_xml

    # -------------------------------------------------------------------------
    def setup_imports(self):
        """Identify ``import`` elements and load each as a nested ``MetaschemaParser``.

        Imported metaschemas are fetched from the support database and stored in
        ``self.imports`` keyed by model name for later cross-metaschema lookups. Each
        import is also recorded as a child of this parser's ``import_inventory`` tree
        node, so the full import-relationship graph is captured.

        Duplicate imports (the same metaschema reached from more than one model, or via
        more than one path) are parsed only once: an :attr:`import_registry`, shared for
        the whole OSCAL version, is consulted first and its parsed object reused.

        Returns:
            None
        """
        logger.debug(f"Setting up imports for {self.oscal_model}")
        import_directives = xpath(self.tree, self.nsmap, '/./METASCHEMA/import/@href')

        if import_directives is None:
            return
        if not isinstance(import_directives, list):
            import_directives = [import_directives]

        for imp_file in import_directives:
            if not imp_file:
                continue
            key = str(imp_file)

            # Reuse an already-parsed import (this version) instead of re-parsing it.
            import_obj = self.import_registry.get(key)
            if import_obj is not None:
                logger.debug(f"Reusing already-parsed import '{key}'.")
            else:
                model_name = key
                if model_name.startswith("oscal_"):
                    model_name = model_name[len("oscal_"):]
                if model_name.endswith("_metaschema_RESOLVED.xml"):
                    model_name = model_name[:-len("_metaschema_RESOLVED.xml")]

                import_content = self.support.asset(self.oscal_version, model_name, "metaschema")
                if not import_content:
                    logger.error(f"Could not fetch import content for '{key}' (model '{model_name}').")
                    continue

                import_obj = MetaschemaParser.create(
                    import_content, self.support, self.oscal_version,
                    import_registry=self.import_registry)
                import_obj.import_inventory["name"] = key
                # Register before recursing so cyclic/diamond imports reuse this object.
                self.import_registry[key] = import_obj
                if not import_obj.top_pass():
                    logger.error(f"Invalid import file: {key}")
                    self.import_registry.pop(key, None)
                    continue

            # Model name → parser, for cross-metaschema definition lookups.
            model_name = import_obj.oscal_model or key
            self.imports[model_name] = import_obj
            # Record the relationship in this parser's import-inventory tree.
            self.import_inventory["children"].append(import_obj.import_inventory)

    # -------------------------------------------------------------------------
    def xpath_atomic(self, xExpr, context=None):
        """
        Run an XPath query and return the first result as a string.

        Args:
            xExpr (str, required): An XPath expression.
            context (Element, optional): Node to evaluate the expression against.
                When None, the expression runs against the whole document.
                Defaults to None.

        Returns:
            str: The first matching result as a string, or "" on error / no match.
        """

        return xpath_atomic(self.tree, self.nsmap, xExpr, context)

    # -------------------------------------------------------------------------
    def xpath(self, xExpr, context=None) -> ET.Element | list[ET.Element] | None:
        """
        Run an XPath query and return the matching element(s).

        Args:
            xExpr (str, required): An XPath expression.
            context (Element, optional): Node to evaluate the expression against.
                When None, the expression runs against the whole document.
                Defaults to None.

        Returns:
            ET.Element | list[ET.Element] | None: A single element, a list of
                elements, or None on error / no match.
        """


        return cast("ET.Element | list[ET.Element] | None", xpath(self.tree, self.nsmap, xExpr, context))

    # -------------------------------------------------------------------------
    def get_markup_content(self, xExpr, context=None):
        """
        Run an XPath query and return its markup content as a string.

        Handles results that are either plain strings or nodes containing HTML
        (markup) formatting, returning a string in either case.

        Args:
            xExpr (str, required): An XPath expression.
            context (Element, optional): Node to evaluate the expression against.
                Defaults to None (whole document).

        Returns:
            str: The matched content as a string (markup preserved as HTML).
        """
        return get_markup_content(self.tree, self.nsmap, xExpr, context)

    # -------------------------------------------------------------------------
    def build_metaschema_tree(self):
        """
        Build the full structural index for this metaschema's model.

        Recursively walks the root assembly to produce the node tree, applies
        constraints against a synthesized XML skeleton, prunes empty values, and
        annotates namespace conditions and JSON paths.

        Returns:
            dict: The metaschema index — model metadata plus a ``nodes`` tree — or an
                empty dict on error or when the root assembly cannot be found.
        """
        logger.debug(f"Resolving the metaschema tree for {self.oscal_model}")
        metaschema_tree = {}

        try:
            context = self.xpath("/METASCHEMA")
            metaschema_tree = {}
            metaschema_tree["oscal_model"] = self.oscal_model
            metaschema_tree["oscal_version"] = self.oscal_version
            metaschema_tree["index_version"] = METASCHEMA_INDEX_VERSION
            metaschema_tree["schema_name"] = self.schema_name
            metaschema_tree["oscal_namespace"] = self.oscal_namespace
            metaschema_tree["json_base_uri"] = self.json_base_uri
            # Name the root of the import-relationship tree after the model itself
            # (imports are named by their href in setup_imports).
            if not self.import_inventory.get("name"):
                self.import_inventory["name"] = self.oscal_model
            metaschema_tree["import_inventory"] = self.import_inventory

            metaschema_tree["nodes"] = self.recurse_metaschema(self.oscal_model, "define-assembly", context=context)

            # Second pass: process all constraints now that the full tree exists.
            # Build a mock XML skeleton first so that elementpath can evaluate
            # constraint target XPath expressions with structural context.
            # _apply_constraints pops the temporary _constraint_xml key from every
            # node, so no XML references leak into the serialised output.
            if metaschema_tree.get("nodes"):
                self._build_skeleton(metaschema_tree["nodes"])
                self._apply_constraints(metaschema_tree["nodes"])

        except Exception as e:
            metaschema_tree = {}
            logger.error(f"Error building metaschema tree: {e}")

        try:
            nodes = metaschema_tree.get("nodes")
            if metaschema_tree and nodes:
                if PRUNE_JSON:
                    metaschema_tree["nodes"] = clean_none_values_recursive(nodes)
                _annotate_ns_conditions(metaschema_tree["nodes"])
                _compute_json_paths(metaschema_tree["nodes"], "")
            elif metaschema_tree and nodes is None:
                logger.error(f"Metaschema tree for {self.oscal_model} has no root node; root assembly may not have been found.")
                metaschema_tree = {}
        except Exception as e:
            logger.error(f"Error saving metaschema tree: {e}")
            metaschema_tree = {}
        node_count = len(metaschema_tree["nodes"]) if metaschema_tree.get("nodes") else 0
        logger.debug(f"Metaschema tree built for {self.oscal_model} with {node_count} nodes.")

        return metaschema_tree

    # -------------------------------------------------------------------------
    def initialize_metaschema_node(self):
        """
        Create a new, fully-keyed metaschema index node with default (empty) values.

        Called as each node is created, including the top-level node, to guarantee a
        consistent key set (path, name, datatype, cardinality, children, constraints,
        handled props, etc.).

        Returns:
            dict: A new node dict with all expected keys initialized.
        """

        # Reset the metaschema tree
        metaschema_node = {}
        metaschema_node["path"] = None
        metaschema_node["json-path"] = None
        metaschema_node["use-name"] = None
        metaschema_node["name"] = None
        metaschema_node["structure-type"] = None
        metaschema_node["datatype"] = None
        metaschema_node["min-occurs"] = None
        metaschema_node["max-occurs"] = None
        metaschema_node["default"] = None
        metaschema_node["pattern"] = None
        metaschema_node["formal-name"] = None
        metaschema_node["wrapped-in-xml"] = None
        metaschema_node["group-as"] = None
        metaschema_node["group-as-in-json"] = None
        metaschema_node["group-as-in-xml"] = None
        metaschema_node["json-key"] = None
        metaschema_node["json-array-name"] = None
        metaschema_node["json-value-key"] = None
        metaschema_node["json-value-key-flag"] = None
        metaschema_node["json-collapsible"] = None
        metaschema_node["deprecated"] = None
        metaschema_node["sunsetting"] = None
        metaschema_node["sequence"] = 0
        metaschema_node["source"] = []
        for prop_name in METASCHEMA_PROPS_HANDLED:
            metaschema_node[prop_name] = None
        metaschema_node["props"] = []
        metaschema_node["description"] = []
        metaschema_node["remarks"] = []
        metaschema_node["example"] = []
        metaschema_node["children"] = []
        metaschema_node["constraints"] = []

        return metaschema_node

    # -------------------------------------------------------------------------
    def initialize_metaschema_rule(self):
        """
        Create a new, fully-keyed metaschema rule with default (empty) values.

        Called before each rule (e.g. an allowed-values constraint) is populated, to
        guarantee a consistent key set (id, level, datatype, allowed-values,
        allow-other, test, message, cardinality, etc.).

        Returns:
            dict: A new rule dict with all expected keys initialized.
        """

        # Reset the metaschema tree
        metaschema_rule = {}
        metaschema_rule["id"] = None
        metaschema_rule["level"] = None
        metaschema_rule["name"] = None
        metaschema_rule["formal-name"] = None
        metaschema_rule["rule-type"] = None
        metaschema_rule["datatype"] = None
        metaschema_rule["default"] = None
        metaschema_rule["pattern"] = None
        metaschema_rule["allowed-values"] = {}
        metaschema_rule["allow-other"] = None
        metaschema_rule["extensible"] = None
        metaschema_rule["test"] = None
        metaschema_rule["message"] = None
        metaschema_rule["help-url"] = None

        metaschema_rule["min-occurs"] = None
        metaschema_rule["max-occurs"] = None

        metaschema_rule["deprecated"] = None
        metaschema_rule["sunsetting"] = None
        metaschema_rule["sequence"] = 0
        metaschema_rule["source"] = []
        for prop_name in METASCHEMA_RULE_PROPS_HANDLED:
            metaschema_rule[prop_name] = None
        metaschema_rule["props"] = []
        metaschema_rule["description"] = []
        metaschema_rule["remarks"] = []

        metaschema_rule["example"] = []

        return metaschema_rule

    # -------------------------------------------------------------------------
    def initialize_metaschema_index(self):
        """
        Create a new, fully-keyed metaschema index-constraint dict with default values.

        Called before each index constraint is populated, to guarantee a consistent
        key set (id, level, name, target, handled props, etc.).

        Returns:
            dict: A new index dict with all expected keys initialized.
        """

        # Reset the metaschema tree
        metaschema_index = {}
        metaschema_index["id"] = None
        metaschema_index["level"] = None
        metaschema_index["name"] = None
        metaschema_index["target"] = None
        metaschema_index["formal-name"] = None
        metaschema_index["sequence"] = 0
        metaschema_index["source"] = []
        for prop_name in METASCHEMA_INDEX_PROPS_HANDLED:
            metaschema_index[prop_name] = None
        metaschema_index["props"] = []
        metaschema_index["pattern"] = None
        metaschema_index["description"] = []
        metaschema_index["remarks"] = []
        return metaschema_index

    # -------------------------------------------------------------------------
    def recurse_metaschema(self, name, structure_type="define-assembly", parent="", ignore_local=False, already_searched=None, context=None, skip_children=False, use_name=None):
        """
        Recursively build a metaschema index node and its descendants.

        Processes the XML definition for ``name`` and extracts a node dict describing
        its attributes, flags, and child elements, recursing into referenced
        definitions.

        Args:
            name (str, required): The definition/element name to process (e.g. a model
                or field name).
            structure_type (str, optional): The kind of definition — "define-assembly",
                "define-field", "define-flag", or an inline assembly/field/flag.
                Defaults to "define-assembly".
            parent (str, optional): Name of the parent definition, for logging/paths.
                Defaults to "".
            ignore_local (bool, optional): When True, ignore local (non-exported)
                definitions; set True when recursing into an imported metaschema so its
                private locals are not exposed. Defaults to False.
            already_searched (list | None, optional): Definition names already visited,
                to prevent infinite recursion. Defaults to None.
            context (Element, optional): XML context node to search within.
                Defaults to None.
            skip_children (bool, optional): When True, do not recurse into child
                elements. Defaults to False.
            use_name (str | None, optional): Override for the node's effective
                (use-)name. Defaults to None.

        Returns:
            dict: The metaschema index node for ``name`` (with nested children).
        """
        if already_searched is None:
            already_searched = []
        global global_counter, global_unhandled_report, global_stop_here
        global_counter += 1
        logger.debug(f"{GREEN}[{global_counter}] Working in {self.oscal_model} on {structure_type}:{name} at [{parent}]{RESET}")

        # Create the metaschema tree (etablishes consistent sequence for keys that should always be present)
        metaschema_node = self.initialize_metaschema_node()
        metaschema_node["sequence"] = global_counter

        # ===== REASONS TO STOP PROCESSING BEFORE COMPLETION ==========================
        if global_counter > RUNAWAY_LIMIT:
            logger.error("Recursion limit reached. Exiting.")
            global_stop_here = True
            return metaschema_node

        if global_stop_here:
            logger.info("DEBUG: Stopping Early.")
            return None

        # .............................................................................
        # If this metaschema file was already searched, don't check it again
        if self.oscal_model in already_searched:
            logger.debug(f"Already searched {self.oscal_model}. Search List: {already_searched}. For {structure_type} {name}")
            return None
        else:
            already_searched.append(self.oscal_model)

        if DEBUG_OBJECT == name:
            logger.info(f"DEBUG: Working on {structure_type}: {name} in {self.oscal_model} under {parent}")
        if structure_type in ["field", "flag", "assembly"]:
            logger.debug(f"Looking for the {structure_type} definition for {name}")
            metaschema_node = self.recurse_metaschema(name, f"define-{structure_type}", parent=parent, already_searched=[], context=None)
            if not metaschema_node:
                logger.warning(f"Could not resolve definition for {structure_type} '{name}' in {self.oscal_model}; skipping.")
                return None

        # .............................................................................
        # Setup xpath query
        # xpath_query = f"{iif(context, ".", "/METASCHEMA")}/{structure_type}"
        xpath_query = f"./{structure_type}"
        no_local = iif(ignore_local, " and not(@scope='local')", "")
        xpath_query += f"[@{iif(structure_type in ['field', 'flag', 'assembly'], 'ref', 'name')}='{name}'{no_local}]"
        if use_name is not None:
            xpath_query += f"[./use-name='{use_name}']"
        if DEBUG_OBJECT == name:
            logger.info(f"DEBUG: Looking for {structure_type}: {name} in {self.oscal_model} with xpath: {xpath_query}")

        result = self.xpath(xpath_query, context)
    
        if result is None:
            if structure_type in ["define-assembly", "define-field", "define-flag"]:
                if context is not None:
                    metaschema_node = self.recurse_metaschema(name, structure_type, parent=parent, ignore_local=False, already_searched=[], context=None)
                else:
                    # If nothing was found, look in the imported files
                    logger.debug(f"Did not find <{structure_type}: '{name}' ... > in {self.oscal_model}")
                    metaschema_node = self.look_in_imports(name, structure_type, parent=parent, ignore_local=ignore_local, already_searched=already_searched)
            else:
                # assembly, field, and flag should always be found in the passed context.
                pass
        else:
            # .............................................................................
            if isinstance(result, list):
                # Duplicate definitions are not allowed in metaschema, so this would only happen if the metaschema was invliad.
                logger.warning(f"Found multiple {structure_type} objects named '{name}'. Using the first one found. [{xpath_query} ({context})]")
                definition_obj = result[0]
            else:
                # A single element was found as expected
                definition_obj = result
            logger.debug(f"Found: <{structure_type} name='{name}' ... >")

            metaschema_node["name"]                = name # should always be present
            metaschema_node["structure-type"]      = structure_type.replace("define-", "")
            metaschema_node["use-name"]            = self.graceful_override(metaschema_node["use-name"], "./use-name/text()", definition_obj)
            if metaschema_node["use-name"] is None or metaschema_node["use-name"] == "":
                metaschema_node["use-name"] = metaschema_node["name"]
            if metaschema_node["path"] is None or metaschema_node["path"] == "":
                if structure_type in ["define-assembly", "assembly", "define-field", "field"]:
                   metaschema_node["path"] = f"{parent}/{metaschema_node['use-name']}"
                elif structure_type in ["define-flag", "flag"]:
                    metaschema_node["path"] = f"{parent}/@{metaschema_node['use-name']}"

            metaschema_node["formal-name"]         = self.graceful_override(metaschema_node["formal-name"],         "./formal-name/text()", definition_obj)
            metaschema_node["json-key"]            = self.graceful_override(metaschema_node["json-key"],            "./json-key/@flag-ref", definition_obj)
            metaschema_node["json-value-key"]      = self.graceful_override(metaschema_node["json-value-key"],      "./json-value-key/text()", definition_obj)
            metaschema_node["json-value-key-flag"] = self.graceful_override(metaschema_node["json-value-key-flag"], "./json-value-key-flag/text()", definition_obj)

            metaschema_node["description"] = self.graceful_accumulate(metaschema_node["description"], "./description", definition_obj)
            metaschema_node["remarks"]     = self.graceful_accumulate(metaschema_node["remarks"]    , "./remarks", definition_obj)
            metaschema_node["example"]     = self.graceful_accumulate(metaschema_node["example"]    , "./example", definition_obj)


            # Handle metaschmea attributes, such as @datatype, @min-occurs, @max-occurs
            metaschema_node = self.handle_attributes(metaschema_node, definition_obj, structure_type, name, parent)
            if metaschema_node is None or metaschema_node == {}:
                logger.error(f"Lost data handling attributes for {structure_type} / {name}.")
                return {} 
            
            # Set default values where appropriate
            metaschema_node = self.set_default_values(metaschema_node, definition_obj, structure_type, name, parent)
            if metaschema_node is None or metaschema_node == {}:
                logger.error(f"Lost data setting defaults for {structure_type} / {name}.")
                return {} 
            
            # Handle group-as element, which is used to indicate how fields or assemblies should be grouped
            metaschema_node = self.handle_group_as(metaschema_node, definition_obj, structure_type, name, parent)
            if metaschema_node is None or metaschema_node == {}:
                logger.error(f"Lost data handling group-as for {structure_type} / {name}.")
                return {}

            # Handle props 
            metaschema_node = self.handle_props(metaschema_node, definition_obj, structure_type, name, parent)
            if metaschema_node is None or metaschema_node == {}:
                logger.error(f"Lost data handling props for {structure_type} / {name}.")
                return {} 

            # Identify which metaschema file this object is from
            if "source" in metaschema_node:
                metaschema_node["source"].append(self.oscal_model)
            else:
                metaschema_node["source"] = [self.oscal_model]  

            # Cycle guard: stop if this assembly's use-name already appears at
            # least twice as a non-terminal segment in the current path.  Allowing
            # one occurrence (i.e. stopping on the second) means each recursive
            # element (part/part, group/group, task/task, …) gets one additional
            # level of concrete children before hitting the recursive stub, which
            # is enough for constraint routing to reach flags on the first nested
            # instance (e.g. part/part/@name).
            _is_cycle = metaschema_node["path"].count(f"/{metaschema_node['use-name']}/") >= 2
            if not _is_cycle:
                flag_nodes = self.handle_flags(metaschema_node, definition_obj, structure_type, name, parent)
                logger.debug(f"Back from handle flags in {self.oscal_model} for {structure_type} / {name} in {parent}")
                child_nodes = self.handle_children(name, structure_type, metaschema_node, definition_obj)
                logger.debug("Back from handle model")
                metaschema_node["children"] = flag_nodes + child_nodes
                # Defer constraint processing.  Constraints live on the <define-*>
                # element, NOT on <assembly ref>, <field ref>, or <flag ref> elements.
                # When structure_type is a reference, the inner define-* recursion
                # (above) already stored the correct _constraint_xml; don't overwrite it.
                if structure_type.startswith("define-"):
                    metaschema_node["_constraint_xml"] = (definition_obj, structure_type, name, parent)
            else:
                # Circular reference: this assembly already appears as an ancestor.
                # It is identical to its definition and may contain unlimited descendants.
                logger.debug(f"Circular Reference protection: {name} is already an ancestor at {metaschema_node['path']}")
                metaschema_node["structure-type"] = "recursive"
                metaschema_node["max-occurs"] = "unbounded"
                metaschema_node["children"] = []

        # .............................................................................

        if metaschema_node is None or metaschema_node == {}:
            logger.debug(f"Did not find {structure_type} / {name} in {self.oscal_model} or any imports.")
        else:
            if DEBUG_OBJECT == name:
                logger.info(f"****: Found {structure_type} / {name} in {self.oscal_model} with path: {metaschema_node['path']}")
                logger.info(f"****: metaschema_node: {self.str_node(metaschema_node)}")

        return metaschema_node

    # -------------------------------------------------------------------------
    def handle_group_as(self, metaschema_node, definition_obj: ET.Element, structure_type, name, parent):
        """
        Apply a definition's ``group-as`` element to a metaschema node.

        Reads the ``group-as`` name and its ``in-xml``/``in-json`` grouping
        attributes and records them (and XML wrapping) on the node.

        Args:
            metaschema_node (dict, required): The node being built; updated in place.
            definition_obj (ET.Element, required): The XML definition element.
            structure_type (str, required): The definition's structure type.
            name (str, required): The definition name (for logging).
            parent (str, required): The parent path (used to build wrapped paths).

        Returns:
            dict: The updated ``metaschema_node``.
        """
        logger.debug(f"Handling group-as for {structure_type} {name}")

        temp_group_as = self.xpath("./group-as", definition_obj)
        if temp_group_as is not None:
            if structure_type in ["define-assembly", "assembly", "define-field", "field"]:
                logger.debug(f"Found group-as for {structure_type} {name}")
                assert isinstance(temp_group_as, ET.Element)
                if temp_group_as.attrib:
                    logger.debug("Has attributes.")
                    metaschema_node["group-as"] = temp_group_as.attrib.get("name", "")
                    if "in-xml" in temp_group_as.attrib:
                        logger.debug(f"Found in-xml attribute: {temp_group_as.attrib.get('in-xml')}")
                        if temp_group_as.attrib.get("in-xml") in ["GROUPED"]:
                            metaschema_node["wrapped-in-xml"] = True
                            metaschema_node["path"] = f"{parent}/{temp_group_as.attrib.get('name', '')}/{metaschema_node['use-name']}"
                        elif temp_group_as.attrib.get("in-xml") in ["UNGROUPED"]:
                            pass
                        else:
                            logger.warning(f"Unexpected in-xml value: {temp_group_as.attrib.get('in-xml')}")
                        metaschema_node["group-as-in-xml"] = temp_group_as.attrib.get("in-xml")
                    if "in-json" in temp_group_as.attrib:
                        logger.debug(f"Found in-json attribute: {temp_group_as.attrib.get('in-json')}")
                        metaschema_node["group-as-in-json"] = temp_group_as.attrib.get("in-json")
            else:
                logger.warning(f"Group-as found where it is not expected: {structure_type} {name}")

        return metaschema_node

    # -------------------------------------------------------------------------
    def graceful_accumulate(self, current_value, xExpr, context=None):
        """
        Prepend a resolved markup value onto an accumulating list of values.

        Used where a field/assembly reference's values must be added to (rather than
        replace) any values already defined on the referenced define-field/assembly.

        Args:
            current_value (list, required): The existing accumulated values; wrapped in
                a list if not already one.
            xExpr (str, required): XPath expression yielding the markup value to add.
            context (Element, optional): Node to evaluate against. Defaults to None.

        Returns:
            list: ``current_value`` with the resolved value inserted at the front (when
                non-empty).
        """
        logger.debug(f"Handling graceful accumulation for {xExpr}")

        temp_value = self.get_markup_content(xExpr, context)
        if temp_value is not None and temp_value != "":
            if not isinstance(current_value, list):
                current_value = []
            current_value.insert(0, temp_value)

        return current_value

    # -------------------------------------------------------------------------
    def graceful_override(self, current_value, xExpr, context=None):
        """
        Return an overriding value when present, otherwise keep the current value.

        Used where a field/assembly reference's value must replace any value already
        defined on the referenced define-field/assembly.

        Args:
            current_value (Any, required): The existing value to keep if no override
                is found.
            xExpr (str, required): XPath expression yielding the overriding value.
            context (Element, optional): Node to evaluate against. Defaults to None.

        Returns:
            Any: The resolved override value if non-empty, otherwise ``current_value``.
        """
        ret_value = None
        logger.debug("Handling graceful overrides")
        temp_value = self.xpath_atomic(xExpr, context)
        if temp_value != "":
            ret_value = temp_value
        else:
            ret_value = current_value

        return ret_value

    # -------------------------------------------------------------------------
    def set_default_values(self, metaschema_node, definition_obj, structure_type, name, parent):
        """
        Fill in default node values required by the metaschema specification.

        Applies spec defaults for any unset attributes — datatype ("string"),
        cardinality (0..1, or 1..1 for the root), ``json-collapsible``,
        ``deprecated``, ``default``, and XML wrapping for fields/assemblies.

        Args:
            metaschema_node (dict, required): The node being built; updated in place.
            definition_obj (ET.Element, required): The XML definition element.
            structure_type (str, required): The definition's structure type.
            name (str, required): The definition name.
            parent (str, required): The parent path; an empty value marks the root node.

        Returns:
            dict: The updated ``metaschema_node``.
        """
        logger.debug("Setting default values")
        # Set default values for metaschema tree
        if metaschema_node is not None:

            # If any of these have not been defined by this point, set them to default 
            # values per the metaschema specification.
            metaschema_node.setdefault("datatype", "string")
            if metaschema_node.get("datatype") is None:
                metaschema_node["datatype"] = "string"
            if metaschema_node.get("min-occurs") is None:
                metaschema_node["min-occurs"] = "0"
            if metaschema_node.get("max-occurs") is None:
                metaschema_node["max-occurs"] = "1"
            if parent == "": # special case for the root element, which is identified because it has no parent.
                metaschema_node["min-occurs"] = "1"
                metaschema_node["max-occurs"] = "1"

            if metaschema_node.get("json-collapsible") is None:
                metaschema_node["json-collapsible"] = False
            if metaschema_node.get("deprecated") is None:
                metaschema_node["deprecated"] = False
            if metaschema_node.get("default") is None:
                metaschema_node["default"] = None # Explicitly makes present and sets to None

            if structure_type in ["define-field", "field", "define-assembly", "assembly"]:
                if metaschema_node.get("wrapped-in-xml") is None:
                    metaschema_node["wrapped-in-xml"] = True

        return metaschema_node

    # -------------------------------------------------------------------------
    def look_in_imports(self, name, structure_type, parent="", ignore_local=False, already_searched=None):
        """
        Search imported metaschemas for a definition by name and structure type.

        Args:
            name (str, required): The definition name to find.
            structure_type (str, required): The structure type to match
                (e.g. "define-assembly", "define-field", "define-flag").
            parent (str, optional): Parent path for the resolved node. Defaults to "".
            ignore_local (bool, optional): Passed through to recursion; ignore local
                definitions in the imported metaschema. Defaults to False.
            already_searched (list | None, optional): Definition names already visited,
                to prevent cycles. Defaults to None.

        Returns:
            dict | None: The resolved node from the imported metaschema, or None if not
                found.
        """
        if already_searched is None:
            already_searched = []
        logger.debug(f"Looking for {structure_type} {name} in imports")
        metaschema_node = None
        import_file = None

        # Cycle through each of the imported metaschema files
        for item in self.imports:
            import_file = item
            parser_object = self.imports[import_file]
            metaschema_node = parser_object.recurse_metaschema(name, structure_type, parent=parent, ignore_local=True, already_searched=already_searched, context=None)
            if metaschema_node is not None and metaschema_node != {}:
                break

        # Check if we got a meaningful result, not just an empty dict or None
        if metaschema_node is not None and metaschema_node.get("structure-type")!= "":
            logger.debug(f"FOUND in {import_file}: {structure_type}: {name}")
            if name == DEBUG_OBJECT:
                logger.info(f"DEBUG: FOUND in {import_file}: {structure_type}: {name}")
        # else:
        #     # Reset metaschema_node to None so we continue searching
        #     metaschema_node = None

        if metaschema_node is None and not ignore_local: # ignore_local is only false at the top level
            logger.debug(f"Did not find {structure_type}: {name} in {self.oscal_model} nor any imports. Parent: {parent}")

        return metaschema_node

    # -------------------------------------------------------------------------
    def handle_flags(self, metaschema_node, definition_obj, structure_type, name, parent):
        """Resolve the flags defined or referenced by a field or assembly.

        Finds each ``define-flag``/``flag`` child, recurses to build its node, and
        collects the results.

        Args:
            metaschema_node (dict, required): The parent node being built (used for
                path context).
            definition_obj (ET.Element, required): The field/assembly XML definition.
            structure_type (str, required): The parent's structure type.
            name (str, required): The parent definition name.
            parent (str, required): The parent path.

        Returns:
            list: The resolved flag node dicts (empty when none are present).
        """
        logger.debug(f"Handling flags for {structure_type} {name}")
        
        hold_flags = []

        temp_flags = self.xpath("./(define-flag | flag)", definition_obj)
        if temp_flags is not None:
            logger.debug(f"Found {len(temp_flags)} flags in {structure_type} {name}")
            if structure_type not in ["define-assembly", "assembly", "define-field", "field"]:
                logger.warning(f"Flags are only allowed in define-assembly, assembly, define-field, field. Not in {structure_type} {name}")

            if not isinstance(temp_flags, list): # more than one
                temp_flags = [temp_flags]

            for flag in temp_flags:
                flag_structure_type = flag.tag.split('}')[-1]  # Remove namespace
                flag_name = ""
                if "ref" in flag.attrib:
                    flag_name = flag.attrib['ref']
                elif "name" in flag.attrib: 
                    flag_name = flag.attrib['name']
                else:
                    logger.error (f"Flag: {flag_structure_type} contains neither @name nor @ref")

                if flag_name:
                    # print(f"\rBuilding: {metaschema_node["path"]}/@{flag_name}", end="", flush=True)
                    meta_object = self.recurse_metaschema(flag_name, flag_structure_type, parent=metaschema_node["path"], already_searched=[], context=definition_obj)
                    if meta_object is not None and meta_object != {}:
                        hold_flags.append(meta_object)
        else:
            logger.debug(f"No flags found within {structure_type} {name}")
        
        return hold_flags

    # -------------------------------------------------------------------------
    def handle_attributes(self, metaschema_node, definition_obj: ET.Element, structure_type, name, parent):
        """
        Map an XML definition's attributes onto a metaschema node.

        Translates attributes such as ``as-type`` (datatype), ``required``,
        ``min-occurs``/``max-occurs`` (cardinality), ``collapsible``, ``deprecated``,
        ``default``, and ``in-xml`` (XML wrapping) into node fields. Unhandled
        attributes are logged as warnings.

        Args:
            metaschema_node (dict, required): The node being built; updated in place.
            definition_obj (ET.Element, required): The XML definition element.
            structure_type (str, required): The definition's structure type.
            name (str, required): The definition name.
            parent (str, required): The parent path.

        Returns:
            dict: The updated ``metaschema_node``.
        """
        logger.debug("Handling attributes")

        if definition_obj.attrib:
            for attr_name, attr_value in definition_obj.attrib.items():
                logger.debug(f"{structure_type} ({name}) Attribute: {attr_name} = {attr_value}")
                if attr_name in ("name", "ref", "scope"):
                    pass  # Already captured: name, ref. Ignoring: scope
                elif attr_name == "as-type":  # for fields and flags
                    metaschema_node["datatype"] = attr_value or metaschema_node["datatype"]
                elif attr_name == "required":  # For flags
                    if attr_value == "yes":
                        metaschema_node["min-occurs"] = "1"
                        metaschema_node["max-occurs"] = "1"
                    elif attr_value == "no":
                        metaschema_node["min-occurs"] = "0"
                        metaschema_node["max-occurs"] = "1"
                elif attr_name == "min-occurs":  # For fields and assemblies
                    metaschema_node["min-occurs"] = attr_value or metaschema_node["min-occurs"]
                elif attr_name == "max-occurs":  # For fields and assemblies
                    metaschema_node["max-occurs"] = attr_value or metaschema_node["max-occurs"]
                elif attr_name == "collapsible":  # For fields
                    if attr_value == "yes":
                        metaschema_node["json-collapsible"] = True
                    elif attr_value == "no":  # default is "no"
                        metaschema_node["json-collapsible"] = False
                    logger.debug(f"Collapsible: {metaschema_node['json-collapsible']}")
                    unhandled = {"path": metaschema_node["path"], "structure": metaschema_node["structure-type"], attr_name: attr_value}
                    global_unhandled_report.append(unhandled)
                elif attr_name == "deprecated":
                    if compare_semver(attr_value, self.oscal_version) <= 0:
                        metaschema_node["deprecated"] = True
                    else:
                        metaschema_node["sunsetting"] = attr_value
                elif attr_name == "default":
                    if structure_type in ["define-field", "define-flag"]:
                        metaschema_node["default"] = attr_value
                    else:
                        logger.warning(f"Unexpected attribute: <define-{structure_type} name='{name}' {attr_name}='{attr_value}'")
                elif attr_name == "in-xml":
                    if structure_type in ["define-field", "field", "define-assembly", "assembly"]:
                        if attr_value in ["WRAPPED", "WITH_WRAPPER"]:
                            metaschema_node["wrapped-in-xml"] = True
                        else:
                            metaschema_node["wrapped-in-xml"] = False
                    else:
                        logger.warning(f"Unexpected attribute: <define-{structure_type} name='{name}' {attr_name}='{attr_value}'")
                else:
                    logger.warning(f"Unexpected attribute: <{structure_type} ({name}) {attr_name}='{attr_value}'")

        return metaschema_node

    # -------------------------------------------------------------------------
    def handle_props(self, metaschema_node, definition_obj, structure_type, name, parent):
        """
        Map a definition's ``prop`` elements onto a metaschema node.

        Recognized props (``METASCHEMA_PROPS_HANDLED`` in the OSCAL namespace) are
        promoted to dedicated node keys; any other prop is appended to the node's
        ``props`` list as ``{"name", "value", "namespace"}``.

        Args:
            metaschema_node (dict, required): The node being built; updated in place.
            definition_obj (ET.Element, required): The XML definition element.
            structure_type (str, required): The definition's structure type.
            name (str, required): The definition name.
            parent (str, required): The parent path.

        Returns:
            dict: The updated ``metaschema_node``.
        """
        logger.debug("Handling metaschema props")
        hold_props = metaschema_node.get("props", [])

        props = self.xpath('./prop', definition_obj)

        if props is not None:
            if not isinstance(props, list):
                props = [props]
            for prop in props:
                prop_name = prop.attrib.get("name", "")
                prop_value = prop.attrib.get("value", "")
                prop_namespace = prop.attrib.get("namespace", "")

                if prop_name in METASCHEMA_PROPS_HANDLED and prop_namespace == "": # TODO handle default namespace
                    metaschema_node[prop_name] = prop_value
                else:
                    prop_obj = {
                        "name": prop_name,
                        "value": prop_value,
                        "namespace": prop_namespace}
                    hold_props.append(prop_obj)

        else:
            logger.debug(f"No props found in {structure_type} {name}")

        metaschema_node["props"] = hold_props
        return metaschema_node
    
    # -------------------------------------------------------------------------
    def handle_children(self, name, structure_type, metaschema_node, context, handle_choice=0):
        """Resolve the child model of an assembly (fields, assemblies, choices, any).

        Walks the assembly's ``model`` (or a specific ``choice`` group), recursing to
        build each child node and constructing synthetic nodes for ``choice``/``any``.

        Args:
            name (str, required): The definition name being processed.
            structure_type (str, required): "define-assembly" or "choice".
            metaschema_node (dict, required): The parent node (provides path/source).
            context (Element, required): The XML context to search within.
            handle_choice (int, optional): 1-based index of the choice group to process
                when ``structure_type`` is "choice". Defaults to 0.

        Returns:
            list: The resolved child node dicts.
        """
        global global_unhandled_report, global_counter
        hold_children = metaschema_node.get("children", [])
        choice_count = 0
        child_use_name = None
        child_name = None

        if structure_type == "define-assembly":
            xExpr = "./model"
        elif structure_type == "choice":
            logger.debug(f"Handling choice {handle_choice} for {metaschema_node['path']}")
            xExpr = f"(./model/choice)[{handle_choice}]"
            # logger.debug(f"{xExpr} for {structure_type} {name} in {metaschema_node["path"]}")
        else:
            xExpr = ""

        if xExpr != "":
            children = self.xpath(xExpr, context)
            if children is not None:
                for child in children:
                    child_use_name = None  # Reset per-child; only ref elements supply a use-name override
                    child_structure_type = child.tag.split('}')[-1]  # Remove namespace
                    if child_structure_type in ["field", "assembly", "define-field", "define-assembly", "choice", "any"]:
                        if child_structure_type in ["define-field", "define-assembly"]:
                            child_name = child.attrib.get("name", "")
                        elif child_structure_type in ["field", "assembly"]:
                            child_name = child.attrib.get("ref", "")
                            child_use_name = self.graceful_override(child_use_name, "./use-name/text()", child)
                        elif child_structure_type in ["choice", "any"]:
                            logger.debug(f"FOUND {child_structure_type} in {metaschema_node['path']}")
                            child_name = f"{child_structure_type.upper()}"

                        # print(f"\r[{global_counter}] {ORANGE}Building: {metaschema_node["path"]}/{child_name} [{child.attrib}]", end="", flush=True)
                        # print(f"{ORANGE}[{global_counter}] Building: {metaschema_node['path']}/{child_name} ")  # , end="", flush=True)

                        if child_structure_type in ["define-field", "define-assembly", "field", "assembly"]:

                            meta_object = self.recurse_metaschema(child_name, child_structure_type, parent=metaschema_node["path"], ignore_local=False, context=children, already_searched=[], use_name=child_use_name)
                            if meta_object is not None and meta_object != {}:
                                hold_children.append(meta_object)
                            else:
                                logger.warning(f"Unexpected empty return at {metaschema_node['path']} for child: {child_structure_type} {child_name}")


                        elif child_structure_type == "choice":
                            choice_count += 1
                            logger.debug(f"Handling choice {choice_count} for {metaschema_node['path']}")
                            temp_object = {}
                            temp_object["name"] = "CHOICE"
                            temp_object["structure-type"] = "choice"
                            temp_object["path"] = metaschema_node["path"] 
                            temp_object["source"] = metaschema_node["source"]
                            temp_object["children"] = self.handle_children(child_name, child_structure_type, temp_object, context=context, handle_choice=choice_count)

                            hold_children.append(temp_object)

                        elif child_structure_type == "any":
                            temp_object = {}
                            temp_object["name"] = "ANY"
                            temp_object["structure-type"] = "any"
                            temp_object["path"] = metaschema_node["path"] + "/*"
                            temp_object["source"] = metaschema_node["source"]
                            hold_children.append(temp_object)

                    else:
                        logger.error(f"Unexpected child structure type: {child_structure_type} in model for {structure_type} {name}")
            else:
                logger.debug(f"No children found in model for {structure_type} {name}")
        return hold_children

    # -------------------------------------------------------------------------
    def _apply_constraints(self, node: dict, _seen: set | None = None) -> None:
        """Second pass: walk the complete tree and process all deferred constraints.

        Every non-recursive node in the tree has a ``_constraint_xml`` key set by
        ``recurse_metaschema`` during the first (structural) pass.  This method
        pops that key and calls ``handle_constraints`` now that the full tree is
        in place, so all potential target nodes already exist regardless of the
        order they were built.
        """
        if _seen is None:
            _seen = set()
        node_id = id(node)
        if node_id in _seen:
            return
        _seen.add(node_id)

        pending = node.pop("_constraint_xml", None)
        if pending is not None:
            definition_obj, structure_type, name, parent = pending
            self.handle_constraints(node, definition_obj, structure_type, name, parent)

        for child in node.get("children", []):
            self._apply_constraints(child, _seen)

    # -------------------------------------------------------------------------
    def _build_skeleton(self, root_node: dict) -> None:
        """Build a mock XML element tree from the index for XPath constraint resolution.

        Two look-up tables are populated after this call:
          _skel_elem_map  – id(element) → index_node  (assembly / field nodes)
          _skel_path_map  – node_path   → element     (context look-up by path)

        Flag nodes are represented as attributes on their parent element; the
        attribute value is always empty because the skeleton encodes structure only.
        """
        self._skel_elem_map: dict = {}
        self._skel_path_map: dict = {}
        self._skel_root = self._build_skeleton_node(root_node, None)

    def _build_skeleton_node(self, index_node: dict, parent_elem: "ET.Element | None") -> "ET.Element | None":
        """Recursive helper for _build_skeleton."""
        stype = index_node.get("structure-type", "")
        name  = (index_node.get("use-name") or index_node.get("name") or "").strip()
        path  = index_node.get("path") or ""

        if not name:
            return None

        if stype == "flag":
            if parent_elem is not None:
                parent_elem.set(name, "")
            return None

        # "choice" nodes are transparent in XML: their children appear directly
        # under the parent element with no intervening wrapper.  Fold them in place.
        if stype == "choice":
            for child in index_node.get("children", []):
                self._build_skeleton_node(child, parent_elem)
            return None

        try:
            elem = ET.Element(name)
        except Exception:
            return None

        self._skel_elem_map[id(elem)] = index_node
        # Only register the first element to claim a path.  CHOICE nodes carry
        # their parent's path and must not overwrite the parent's entry.
        if path and path not in self._skel_path_map:
            self._skel_path_map[path] = elem

        if parent_elem is not None:
            parent_elem.append(elem)

        for child in index_node.get("children", []):
            self._build_skeleton_node(child, elem)

        return elem

    # -------------------------------------------------------------------------
    def handle_constraints(self, metaschema_node, definition_obj, structure_type, name, parent):
        """Process ``<constraint><allowed-values>`` elements from a definition object.

        Targets are handled as follows: ``.`` or absent applies to the current node;
        ``@flag-name`` applies to the named flag child; complex Metapath targets are
        resolved against the XML skeleton (or stored with the unresolved target
        preserved). Multiple allowed-values sets for the same target are cumulative;
        ``allow-other`` conflicts resolve with 'yes' winning and emit a warning.

        Args:
            metaschema_node (dict, required): The node being built; updated in place.
            definition_obj (ET.Element, required): The XML definition element.
            structure_type (str, required): The definition's structure type.
            name (str, required): The definition name.
            parent (str, required): The parent path.

        Returns:
            dict: The updated ``metaschema_node``.
        """
        logger.debug(f"Handling constraints for {structure_type} {name}")

        constraint_elements = self.xpath("./constraint", definition_obj)
        if constraint_elements is None:
            return metaschema_node

        if not isinstance(constraint_elements, list):
            constraint_elements = [constraint_elements]

        # Collect allowed-values grouped by target string
        target_map = {}
        for constraint_elem in constraint_elements:
            av_elements = self.xpath("./allowed-values", constraint_elem)
            if av_elements is None:
                continue
            if not isinstance(av_elements, list):
                av_elements = [av_elements]
            for av_elem in av_elements:
                parsed = self._parse_allowed_values_elem(av_elem)
                if parsed is None:
                    continue
                target = parsed["target"]
                if target not in target_map:
                    target_map[target] = []
                target_map[target].append(parsed)

        for target, av_list in target_map.items():
            merged = self._merge_allowed_values(av_list, context=f"{structure_type}/{name}")

            # Extract has-oscal-namespace() condition and simplify the target before routing.
            # e.g. ".[has-oscal-namespace('...')]/@name" → cleaned="./@name", condition={...}
            # e.g. "prop[has-oscal-namespace(...) and @name='type']/@value" → "prop[@name='type']/@value"
            cleaned_target, ns_condition = _extract_oscal_namespace_condition(target)

            # Route via elementpath against the skeleton.  Alternation groups
            # (A|B|C)/rest are expanded so each branch can be reported independently.
            routing_target = cleaned_target.strip()
            expanded_rts = _expand_top_level_alternation(routing_target)

            for rt in expanded_rts:
                resolved, pred_conds, ep_error = self._resolve_via_elementpath(metaschema_node, rt)
                all_conditions = ([ns_condition] if ns_condition else []) + pred_conds

                if resolved:
                    c = dict(merged)
                    if all_conditions:
                        c["conditions"] = all_conditions
                    for target_node in resolved:
                        self._add_constraint_to_node(target_node, c)
                else:
                    reason = "pattern-unsupported" if ep_error else "navigation-failed"
                    logger.debug(
                        f"Constraint target '{target}' (branch '{rt}') in "
                        f"{structure_type}/{name}: unresolved ({reason})"
                    )
                    merged_with_target = dict(merged)
                    merged_with_target["unresolved-target"] = rt
                    merged_with_target["unresolved-reason"] = reason
                    self._add_constraint_to_node(metaschema_node, merged_with_target)

        return metaschema_node

    # -------------------------------------------------------------------------
    def _parse_allowed_values_elem(self, av_elem):
        """Parse a single <allowed-values> XML element into a constraint dict."""
        av_id    = av_elem.attrib.get("id", "")
        allow_others_str = av_elem.attrib.get("allow-other", "no")
        target   = av_elem.attrib.get("target", ".").strip() or "."

        enums = []
        enum_elems = self.xpath("./enum", av_elem)
        if enum_elems is not None:
            if not isinstance(enum_elems, list):
                enum_elems = [enum_elems]
            for enum_elem in enum_elems:
                enum_value = enum_elem.attrib.get("value", "")
                if not enum_value:
                    continue
                deprecated_at = enum_elem.attrib.get("deprecated", None)
                enum_desc = self.get_markup_content(".", enum_elem) or ""
                entry = {"value": enum_value, "description": enum_desc}
                if deprecated_at is not None:
                    entry["deprecated"] = deprecated_at
                enums.append(entry)

        return {
            "type": "allowed-values",
            "id": av_id,
            "target": target,
            "allow-other": allow_others_str == "yes",
            "values": enums,
        }

    # -------------------------------------------------------------------------
    def _merge_allowed_values(self, av_list, context=""):
        """Merge a list of allowed-values dicts for the same target.

        Values are cumulative (additive, deduped by value key).
        allow-other: 'yes' wins; warns when contradictory inputs disagree.
        """
        if len(av_list) == 1:
            return av_list[0]

        merged_values = []
        seen_values = set()
        allow_others_seen = set()
        first_id = av_list[0].get("id", "")
        first_target = av_list[0].get("target", ".")

        for av in av_list:
            allow_others_seen.add(av.get("allow-other", False))
            for v in av.get("values", []):
                key = v.get("value", "")
                if key and key not in seen_values:
                    merged_values.append(v)
                    seen_values.add(key)

        if True in allow_others_seen and False in allow_others_seen:
            logger.warning(f"Contradictory allow-other values for allowed-values in {context}: treating as allow-other=yes")

        result = {
            "type": "allowed-values",
            "id": first_id,
            "target": first_target,
            "allow-other": True in allow_others_seen,
            "values": merged_values,
        }
        conditions = next((av["conditions"] for av in av_list if "conditions" in av), None)
        if conditions is not None:
            result["conditions"] = conditions
        return result

    # -------------------------------------------------------------------------
    @staticmethod
    def _constraint_merge_key(constraint):
        """Return a hashable key that identifies which allowed-values constraints
        can be merged.  Two constraints merge only when both their unresolved-target
        AND their conditions match — constraints scoped to different namespaces (or
        with different flag-equals guards) must stay separate so validation can
        evaluate each one independently.
        """
        unresolved = constraint.get("unresolved-target")
        conds = constraint.get("conditions") or []
        # Produce a stable, order-independent fingerprint of the conditions list.
        parts = []
        for c in sorted(conds, key=lambda x: (x.get("type", ""), x.get("flag", ""))):
            parts.append(
                f"{c.get('type','')}:{c.get('flag','')}:{c.get('value','')}"
                f":{','.join(sorted(str(v) for v in c.get('values', [])))}"
            )
        return (unresolved, "|".join(parts))

    def _add_constraint_to_node(self, node, constraint):
        """Add a constraint to a node's constraints list.

        Allowed-values constraints are cumulative: if an existing constraint on
        the same node has the same unresolved-target AND the same conditions, their
        value lists are merged rather than duplicated.  Constraints with different
        conditions (e.g. one scoped to the OSCAL namespace, another to a vendor
        namespace) are kept as separate entries so validation can evaluate each one
        independently.
        """
        if "constraints" not in node:
            node["constraints"] = []

        incoming_key = self._constraint_merge_key(constraint)
        for i, existing in enumerate(node["constraints"]):
            if (existing.get("type") == "allowed-values"
                    and self._constraint_merge_key(existing) == incoming_key):
                node["constraints"][i] = self._merge_allowed_values(
                    [existing, constraint],
                    context=node.get("path", "")
                )
                return

        node["constraints"].append(constraint)

    # -------------------------------------------------------------------------
    def _resolve_via_elementpath(self, context_node: dict, routing_target: str) -> tuple:
        """Resolve a Metapath routing target against the skeleton using elementpath.

        Returns (resolved_nodes, conditions, is_error).
          resolved_nodes – list of index nodes the XPath reaches, or None if nothing found
          conditions     – flag-equals / flag-in dicts extracted from value predicates
          is_error       – True when elementpath raises (malformed / unsupported XPath)
        """
        import elementpath

        context_stype = context_node.get("structure-type", "")

        # Flag nodes have no element representation in the skeleton.
        # The only sensible target from a flag is "." (self).
        if context_stype == "flag":
            clean_rt, pred_conds = _make_skeleton_xpath(routing_target)
            stripped = clean_rt.strip().lstrip("./")
            if not stripped:
                return [context_node], pred_conds, False
            return None, pred_conds, False

        if not hasattr(self, "_skel_path_map"):
            return None, [], False

        path = context_node.get("path") or ""
        context_elem = self._skel_path_map.get(path)
        if context_elem is None:
            return None, [], False

        # Strip @attr=value predicates — skeleton elements have no real values so
        # predicate filters would never match; convert them to conditions instead.
        skeleton_xpath, pred_conds = _make_skeleton_xpath(routing_target)

        # Split off a trailing /@attr_name so flags are looked up via the index
        # rather than relying on elementpath attribute-node return types.
        attr_name: str | None = None
        nav_expr = skeleton_xpath.strip()

        segs = _split_path_segments(nav_expr)
        if segs and segs[-1].startswith("@"):
            attr_name = segs[-1][1:]
            nav_expr = "/".join(segs[:-1]).strip() if len(segs) > 1 else "."
        elif nav_expr.startswith("@") and "/" not in nav_expr:
            attr_name = nav_expr[1:]
            nav_expr = "."

        try:
            elem_results = elementpath.select(context_elem, nav_expr)
        except Exception as exc:
            logger.debug(
                f"elementpath error evaluating '{nav_expr}' "
                f"(from '{routing_target}'): {exc}"
            )
            return None, pred_conds, True

        index_nodes: list = []
        for r in elem_results:
            if not isinstance(r, ET.Element):
                continue
            idx_node = self._skel_elem_map.get(id(r))
            if idx_node is None:
                continue
            if attr_name:
                flag_node = next(
                    (c for c in idx_node.get("children", [])
                     if c.get("structure-type") == "flag"
                     and (c.get("use-name") == attr_name or c.get("name") == attr_name)),
                    None,
                )
                if flag_node is not None:
                    index_nodes.append(flag_node)
            else:
                index_nodes.append(idx_node)

        return (index_nodes or None), pred_conds, False

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Module-level helpers kept outside MetaschemaParser so oscal_support can
# import them for lazy annotation of indexes loaded from the DB without
# triggering a circular import.

# Matches @flag='value' predicates inside [...] brackets.
_ATTR_PRED_RE = re.compile(r"@([\w][\w-]*)='([^']*)'")
# Matches @flag=('v1','v2',...) multi-value sequence predicates (spaces around commas allowed).
_ATTR_PRED_MULTI_RE = re.compile(r"@([\w][\w-]*)=\(('(?:[^']*)'(?:\s*,\s*'[^']*')*)\)")


def _expand_top_level_alternation(target: str) -> list:
    """Expand a leading (A|B|C)/rest alternation into [A/rest, B/rest, C/rest].

    Only expands when the very first character is '(' — this is the Metapath
    pattern for a union of paths, e.g.
        (.|statement|.//by-component)/prop/@name
        (component|inventory-item)/prop/@value

    The '|' split is done at depth 0 only so nested predicates like
    ``@name=('v1','v2')`` are not split.  Returns ``[target]`` unchanged when no
    top-level alternation is present or when the parens are unbalanced.
    """
    if not target.startswith("("):
        return [target]

    # Locate the closing ')' at depth 0.
    depth = 0
    close = -1
    for i, ch in enumerate(target):
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
            if depth == 0:
                close = i
                break

    if close < 0:
        return [target]  # unbalanced

    inner = target[1:close]
    rest  = target[close + 1:]  # e.g. "/prop/@name"

    # Split inner on '|' at depth 0 (guard nested brackets/parens).
    alternatives: list = []
    current: list = []
    depth = 0
    for ch in inner:
        if ch in "([":
            depth += 1
            current.append(ch)
        elif ch in ")]":
            depth -= 1
            current.append(ch)
        elif ch == "|" and depth == 0:
            alt = "".join(current).strip()
            if alt:
                alternatives.append(alt)
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail:
        alternatives.append(tail)

    if len(alternatives) <= 1:
        return [target]  # no real alternation

    return [f"{alt}{rest}" for alt in alternatives]


def _split_path_segments(path: str) -> list:
    """Split a Metapath-style path on '/' without splitting inside [...] brackets.

    Naive str.split('/') breaks targets like
    ``responsible-party[role-id=(/catalog/metadata/role/@id)]/@party-uuid``
    because the inner path also contains slashes.  This function only splits at
    top-level slashes (depth == 0).
    """
    segments: list = []
    current: list = []
    depth = 0
    for ch in path:
        if ch == "[":
            depth += 1
            current.append(ch)
        elif ch == "]":
            depth = max(depth - 1, 0)
            current.append(ch)
        elif ch == "/" and depth == 0:
            segments.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        segments.append("".join(current))
    return segments or [path]


def _parse_child_predicates(child_ref: str) -> tuple:
    """Parse a child reference that may include bracket predicates.

    Returns ``(plain_name, [condition, ...])`` where each condition is one of:
    - ``{"type": "flag-equals", "flag": ..., "value": ...}`` for ``@f='v'``
    - ``{"type": "flag-in", "flag": ..., "values": [...]}`` for ``@f=('v1','v2',...)``

    The plain_name may be ``"."`` or ``"(."`` to indicate the current node
    (self-reference); callers should check for this and skip navigation.

    Returns ``(None, [])`` when the predicate contains expressions that cannot
    be reduced to the above forms (e.g. positional or function predicates).
    The caller should fall through to unresolved in that case.
    """
    if "[" not in child_ref:
        return child_ref, []

    bracket_start = child_ref.index("[")
    plain_name = child_ref[:bracket_start]
    inner = child_ref[bracket_start + 1 : child_ref.rindex("]")]

    pred_conditions = []

    for m in _ATTR_PRED_MULTI_RE.finditer(inner):
        values = [v.strip().strip("'") for v in m.group(2).split(",")]
        pred_conditions.append({"type": "flag-in", "flag": m.group(1), "values": values})

    for m in _ATTR_PRED_RE.finditer(inner):
        pred_conditions.append({"type": "flag-equals", "flag": m.group(1), "value": m.group(2)})

    # Verify the predicate contained only recognised terms joined by 'and'/'or'
    remaining = _ATTR_PRED_MULTI_RE.sub("", inner)
    remaining = _ATTR_PRED_RE.sub("", remaining)
    remaining = re.sub(r"\s*(and|or)\s*", "", remaining).strip()
    if remaining:
        return None, []

    return plain_name, pred_conditions


def _make_skeleton_xpath(target: str) -> tuple:
    """Strip @attr=value predicates from an XPath expression.

    Returns (stripped_xpath, conditions) where conditions is a list of
    flag-equals / flag-in dicts.  Empty brackets left by removal are deleted.
    Non-attribute predicate content (functions, positional tests) is preserved
    verbatim so that elementpath can evaluate it (or raise, signalling an
    unsupported pattern).
    """
    conditions: list = []
    result: list = []
    i = 0
    n = len(target)
    while i < n:
        if target[i] == "[":
            depth = 1
            j = i + 1
            while j < n and depth > 0:
                if target[j] == "[":
                    depth += 1
                elif target[j] == "]":
                    depth -= 1
                j += 1
            inner = target[i + 1 : j - 1]

            local_conds: list = []
            for m in _ATTR_PRED_MULTI_RE.finditer(inner):
                values = [v.strip().strip("'") for v in m.group(2).split(",")]
                local_conds.append({"type": "flag-in", "flag": m.group(1), "values": values})
            for m in _ATTR_PRED_RE.finditer(inner):
                local_conds.append({"type": "flag-equals", "flag": m.group(1), "value": m.group(2)})

            remaining = _ATTR_PRED_MULTI_RE.sub("", inner)
            remaining = _ATTR_PRED_RE.sub("", remaining)
            remaining = re.sub(r"\s*(and|or)\s*", " ", remaining).strip()

            conditions.extend(local_conds)
            if remaining:
                result.append(f"[{remaining}]")
            i = j
        else:
            result.append(target[i])
            i += 1

    return "".join(result), conditions


# Matches has-oscal-namespace('ns') or has-oscal-namespace(('ns1','ns2',...))
_HAS_NS_RE = re.compile(
    r"has-oscal-namespace\("
    r"("
    r"'[^']*'"           # single-quoted string
    r"|"
    r"\([^)]*\)"         # tuple in parens (NS URIs contain no parens)
    r")"
    r"\)"
)


def _parse_ns_arg(arg: str) -> list:
    """Extract namespace URI strings from a has-oscal-namespace() argument."""
    return re.findall(r"'([^']*)'", arg)


def _extract_oscal_namespace_condition(target: str) -> tuple:
    """Detect has-oscal-namespace() in a Metapath target.

    Returns (cleaned_target, condition) where condition is a dict or None.

    condition format:
        {"type": "namespace", "values": [...], "allow-absent": bool}

    allow-absent is True when OSCAL_DEFAULT_NAMESPACE is among the values,
    meaning a prop/part with no ns field satisfies the condition (the default
    namespace applies).  For any other namespace the ns field must be present
    and equal one of the listed values (case-sensitive).
    """
    if "has-oscal-namespace" not in target:
        return target, None

    collected_ns: list = []

    def _remove_call(m: re.Match) -> str:
        collected_ns.extend(_parse_ns_arg(m.group(1)))
        return ""

    cleaned = _HAS_NS_RE.sub(_remove_call, target)
    cleaned = re.sub(r"\[\s*and\s+", "[", cleaned)
    cleaned = re.sub(r"\s+and\s*\]", "]", cleaned)
    cleaned = re.sub(r"\[\s*\]", "", cleaned)

    if not collected_ns:
        return target, None

    unique_values = list(dict.fromkeys(collected_ns))
    allow_absent = OSCAL_DEFAULT_NAMESPACE in unique_values
    if allow_absent and "" not in unique_values:
        # "" represents the absent/default ns field (treated as NIST namespace)
        unique_values.append("")
    condition = {
        "type": "namespace",
        "values": unique_values,
        "allow-absent": allow_absent,
    }
    return cleaned, condition


def _migrate_flags_to_children(node: dict, _seen: set | None = None) -> None:
    """Migrate legacy nodes that store flags separately into children.

    Older cached indexes have a top-level ``flags`` key alongside ``children``.
    This function merges those flags into the beginning of ``children`` and
    removes the stale key so the rest of the code only needs to look in one place.
    Safe to call on already-migrated data (no-op when ``flags`` key is absent).
    """
    if _seen is None:
        _seen = set()
    node_id = id(node)
    if node_id in _seen:
        return
    _seen.add(node_id)

    if "flags" in node:
        old_flags = node.pop("flags") or []
        if old_flags:
            node["children"] = old_flags + node.get("children", [])

    for constraint in node.get("constraints", []):
        if "condition" in constraint and "conditions" not in constraint:
            constraint["conditions"] = [constraint.pop("condition")]

    for child in node.get("children", []):
        _migrate_flags_to_children(child, _seen)


def _reroute_unresolved_constraints(node: dict, _seen: set | None = None) -> None:
    """Re-route unresolved constraints in old cached indexes to their correct nodes.

    Cached indexes built before the current routing improvements store constraints
    like ``./child/@flag``, ``child/@flag``, and ``@flag`` as unresolved on the
    parent node.  This function walks the tree and moves those constraints to the
    correct flag node, extracting conditions along the way — matching the logic
    now used by ``handle_constraints`` at parse time.
    """
    if _seen is None:
        _seen = set()
    node_id = id(node)
    if node_id in _seen:
        return
    _seen.add(node_id)

    remaining = []
    for constraint in node.get("constraints", []):
        if "unresolved-target" not in constraint:
            remaining.append(constraint)
            continue

        target = constraint["unresolved-target"]
        cleaned, ns_cond = _extract_oscal_namespace_condition(target)
        rt = cleaned.strip()
        if rt.startswith("./"):
            rt = rt[2:].strip()

        routed = False

        if rt.startswith("@") and "/" not in rt:
            # @flag-name → route to named flag child of current node
            flag_name = rt[1:]
            for c in node.get("children", []):
                if c.get("structure-type") == "flag" and (
                    c.get("use-name") == flag_name or c.get("name") == flag_name
                ):
                    re_routed = {k: v for k, v in constraint.items()
                                 if k not in ("unresolved-target", "conditions")}
                    if ns_cond:
                        re_routed["conditions"] = [ns_cond]
                    c.setdefault("constraints", []).append(re_routed)
                    routed = True
                    break

        elif "/" in rt and _split_path_segments(rt)[-1].startswith("@"):
            # N-level descent: seg1/.../segN/@flag (same logic as handle_constraints)
            *path_segs, flag_ref = _split_path_segments(rt)
            flag_name = flag_ref[1:]

            current = node
            all_conds = [ns_cond] if ns_cond else []
            nav_ok = True
            for seg in path_segs:
                plain, pred_conds = _parse_child_predicates(seg)
                if plain is None:
                    nav_ok = False
                    break
                all_conds.extend(pred_conds)
                if plain in (".", "(.)", "(.)"):
                    continue  # self-reference: stay at current node
                nxt = next(
                    (c for c in current.get("children", [])
                     if c.get("structure-type") != "flag"
                     and (c.get("use-name") == plain or c.get("name") == plain)),
                    None,
                )
                if nxt is None:
                    nav_ok = False
                    break
                current = nxt

            if nav_ok:
                flag_node = next(
                    (c for c in current.get("children", [])
                     if c.get("structure-type") == "flag"
                     and (c.get("use-name") == flag_name or c.get("name") == flag_name)),
                    None,
                )
                if flag_node is not None:
                    re_routed = {k: v for k, v in constraint.items()
                                 if k not in ("unresolved-target", "conditions")}
                    if all_conds:
                        re_routed["conditions"] = all_conds
                    flag_node.setdefault("constraints", []).append(re_routed)
                    routed = True

        if not routed:
            remaining.append(constraint)

    node["constraints"] = remaining

    for child in node.get("children", []):
        _reroute_unresolved_constraints(child, _seen)


def _annotate_ns_conditions(node: dict, _seen: set | None = None) -> None:
    """Recursively stamp a condition key onto every unresolved-target constraint
    that uses has-oscal-namespace()."""
    if _seen is None:
        _seen = set()
    node_id = id(node)
    if node_id in _seen:
        logger.warning(f"Cycle detected in index tree during ns-condition annotation at {node.get('path', '?')}")
        return
    _seen.add(node_id)

    for constraint in node.get("constraints", []):
        if "unresolved-target" in constraint and "conditions" not in constraint:
            _, condition = _extract_oscal_namespace_condition(
                constraint["unresolved-target"]
            )
            if condition is not None:
                constraint["conditions"] = [condition]
    for child in node.get("children", []):
        _annotate_ns_conditions(child, _seen)


def _compute_json_paths(node: dict, parent_json: str, _seen: set | None = None) -> None:
    """Recursively set json-path on every node in the index tree.

    json-path is the JSON-equivalent of path:
    - Flags lose the @ prefix  (XML @name → JSON name)
    - Assemblies/fields with group-as use the group-as key (XML prop → JSON props)
    - In-xml GROUPED wrappers collapse: the group-as key IS the JSON path segment,
      not group-as + use-name (XML revisions/revision → JSON revisions)
    - Everything else keeps its use-name unchanged
    """
    if _seen is None:
        _seen = set()
    node_id = id(node)
    if node_id in _seen:
        logger.warning(f"Cycle detected in index tree during json-path computation at {node.get('path', '?')}")
        return
    _seen.add(node_id)

    use_name = node.get("use-name") or node.get("name", "")
    structure_type = node.get("structure-type", "")
    group_as = node.get("group-as")

    if structure_type == "flag":
        json_path = f"{parent_json}/{use_name}"
    elif group_as:
        json_path = f"{parent_json}/{group_as}"
    else:
        json_path = f"{parent_json}/{use_name}"

    node["json-path"] = json_path

    for child in node.get("children", []):
        _compute_json_paths(child, json_path, _seen)


# Stable namespace for deterministic metaschema node reference UUIDs (RFC-4122 URL namespace).
_NODE_REF_NAMESPACE = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


def _assign_node_refs(node: dict, base_seed: str, parent_ref: str | None = None,
                      _seen: set | None = None) -> None:
    """Assign a stable reference id (``ref``) and ``parent-ref`` to every node.

    Each node receives a deterministic UUID (uuid5 over its positional path within the
    index), so the same node always resolves to the same reference across index
    rebuilds and process restarts. This gives the documentation views an unambiguous
    handle for linking every element in an outline to its detail, and for walking from
    a node to its immediate parent and children. ``parent-ref`` is None for the root.

    Args:
        node (dict, required): The current node (the model root on the first call).
        base_seed (str, required): Seed uniquely identifying this index, e.g.
            ``"v1.1.3/profile"``; each node extends it with its positional path.
        parent_ref (str, optional): The parent node's ``ref``; None for the root.
        _seen (set, optional): Cycle-guard accumulator.
    """
    if not isinstance(node, dict):
        return
    if _seen is None:
        _seen = set()
    node_id = id(node)
    if node_id in _seen:
        return
    _seen.add(node_id)

    node["ref"] = str(uuid.uuid5(_NODE_REF_NAMESPACE, base_seed))
    node["parent-ref"] = parent_ref

    for i, child in enumerate(node.get("children", []) or []):
        if isinstance(child, dict):
            _assign_node_refs(child, f"{base_seed}.{i}", node["ref"], _seen)

def _index_uses_stale_allow_other_key(node: dict, _seen: set | None = None) -> bool:
    """Return True if any constraint in the subtree uses the deprecated 'allow-others' key.

    Indexes built by older parser versions stored the allow-other flag under the
    plural key 'allow-others'.  The current parser and validator both use the
    singular 'allow-other'.  When the old key is present the stored value may also
    be incorrect, so the whole index must be rebuilt rather than simply renamed.
    """
    if _seen is None:
        _seen = set()
    node_id = id(node)
    if node_id in _seen:
        return False
    _seen.add(node_id)

    for c in node.get("constraints", []):
        if "allow-others" in c:
            return True
    for child in node.get("children", []):
        if isinstance(child, dict) and _index_uses_stale_allow_other_key(child, _seen):
            return True
    return False


def _collect_unresolved_targets(node: dict, results: list | None = None, _seen: set | None = None) -> list:
    """Walk the index tree and return all constraints that still have unresolved-target.

    Each entry is a dict with keys:
      path    – node path where the constraint was stored
      target  – the unresolved target expression
      values  – allowed values list (list of value strings)
      id      – constraint XML id attribute (may be empty)
      source  – list of metaschema model names the node was sourced from
      reason  – "pattern-unsupported" | "navigation-failed" | "unknown"
    """
    if results is None:
        results = []
    if _seen is None:
        _seen = set()
    node_id = id(node)
    if node_id in _seen:
        return results
    _seen.add(node_id)

    node_path = node.get("path", "")
    node_source = node.get("source", [])
    for constraint in node.get("constraints", []):
        if "unresolved-target" in constraint:
            results.append({
                "path":   node_path,
                "target": constraint["unresolved-target"],
                "values": [v.get("value", "") for v in constraint.get("values", [])],
                "id":     constraint.get("id", ""),
                "source": list(node_source),
                "reason": constraint.get("unresolved-reason", "unknown"),
            })

    for child in node.get("children", []):
        _collect_unresolved_targets(child, results, _seen)

    return results


def _write_metaschema_report(
    models_processed: list,
    unresolved_by_model: dict,
    oscal_version: str,
    support_dir: str,
) -> str:
    """Write a markdown summary report for an OSCAL version's metaschema parse run.

    The report lists every model processed and, for each model with remaining
    unresolved constraint targets, a two-section breakdown:

    * **Unhandled patterns** – the target expression uses a Metapath construct
      (deep-descent ``//``, bare field names, etc.) that the parser does not yet
      support.  These require a parser enhancement to resolve.

    * **Navigation failures** – the target pattern is understood but the named
      child or flag was not found in the index tree.  These may indicate a
      metaschema element that was skipped, or a bug in the index build.
    """
    import os

    lines = [
        f"# OSCAL Metaschema Index — {oscal_version}",
        "",
        "## Models Processed",
        "",
    ]
    for model in models_processed:
        status = " ⚠" if model in unresolved_by_model else " ✓"
        lines.append(f"- {model}{status}")
    lines.append("")

    lines.append("## Unresolved Allowed-Values Constraints")
    lines.append("")

    total = sum(len(v) for v in unresolved_by_model.values())
    if total == 0:
        lines.append("_None — all constraint targets were fully resolved._")
        lines.append("")
    else:
        for model in models_processed:
            items = unresolved_by_model.get(model)
            if not items:
                continue

            unsupported = [i for i in items if i.get("reason") == "pattern-unsupported"]
            nav_failed  = [i for i in items if i.get("reason") == "navigation-failed"]
            other       = [i for i in items if i.get("reason") not in ("pattern-unsupported", "navigation-failed")]

            lines.append(f"### {model}  ({len(items)} unresolved)")
            lines.append("")

            def _table(section_items: list, heading: str) -> None:
                if not section_items:
                    return
                lines.append(f"#### {heading}")
                lines.append("")
                lines.append("| Path | Target | Values | Source |")
                lines.append("|------|--------|--------|--------|")
                for item in section_items:
                    def _esc(s: str) -> str:
                        return s.replace("|", "\\|")
                    path   = _esc(item.get("path", ""))
                    tgt    = _esc(item.get("target", ""))
                    vals   = _esc(", ".join(item.get("values", [])) or "—")
                    source = _esc(", ".join(item.get("source", [])) or "—")
                    lines.append(f"| `{path}` | `{tgt}` | {vals} | {source} |")
                lines.append("")

            _table(unsupported, "Unhandled Patterns")
            _table(nav_failed,  "Navigation Failures")
            _table(other,       "Other")

    report_path = os.path.join(support_dir, "metaschema_report.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    logger.info(f"Metaschema report written to {report_path}")
    return report_path


# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s - %(message)s",
    )

    try:
        exit_code = parse_metaschema(oscal_version="v1.2.2")
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
