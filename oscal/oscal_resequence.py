#!/usr/bin/env python3
"""
oscal_resequence.py

Resequences keys in OSCAL JSON and YAML files to match the canonical order
defined by the NIST OSCAL metaschema. Data and parent/child relationships are
preserved exactly; only key ordering changes.

Canonical order is derived from the **processed metaschema index** (the same
structural index that drives XML↔JSON conversion), not from hand-maintained key
tables. For each object the order is: flags (in metaschema order), then the
field value key (for a value-bearing field with flags), then child
fields/assemblies in metaschema order (choices flattened, recursive definitions
resolved). Each child's JSON key is its ``group-as`` (for collections) or
``use-name``. This automatically covers every model, version, and nested
structure the metaschema defines.

Because ordering is metaschema-driven, this module depends on the OSCAL support
database (via ``OSCALSupport``). The OSCAL version is taken from the document's
``metadata/oscal-version`` (overridable), falling back to the latest supported
version; versions below the minimum with a published resolved metaschema fall
back to that minimum. When no index is available the document is returned
unchanged (a warning is logged) rather than mis-ordered.

Supports all 8 OSCAL models (catalog, profile, mapping-collection,
component-definition, SSP, SAP, SAR, POA&M).

Usage:
    python -m oscal.oscal_resequence <input_file> [output_file]

    If output_file is omitted, the resequenced content is written back to
    input_file (in-place).

Library use:
    from oscal.oscal_resequence import resequence_oscal, resequence_oscal_file
    resequence_oscal_file("ssp.json")
    resequence_oscal_file("catalog.yaml", "catalog_ordered.yaml")
    ordered = resequence_oscal(doc_dict)              # version from metadata
    ordered = resequence_oscal(doc_dict, version="v1.2.0")
"""

import json
import logging
import sys
from pathlib import Path
from typing import List, Optional, Union

from ruf_common.helper import compare_semver

from .oscal_support import get_support, METASCHEMA_MIN_VERSION

logger = logging.getLogger(__name__)

try:
    import yaml

    class _OscalLoader(yaml.SafeLoader):
        """SafeLoader variant that preserves datetime strings as plain strings.

        PyYAML's default SafeLoader maps ISO 8601 timestamps to Python
        datetime objects, which yaml.dump then serializes in a different
        format (e.g. '2025-02-28 00:00:00+00:00') that is not valid per the
        OSCAL date-time-with-timezone pattern.  Removing the implicit
        resolver for the 'tag:yaml.org,2002:timestamp' tag prevents that
        conversion so the original string is round-tripped unchanged.
        """

    # Remove the timestamp resolver from our custom loader only.
    _OscalLoader.yaml_implicit_resolvers = {
        key: [(tag, regexp) for tag, regexp in resolvers
              if tag != "tag:yaml.org,2002:timestamp"]
        for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    _OscalLoader = None # type: ignore


# ---------------------------------------------------------------------------
# Model / version detection
# ---------------------------------------------------------------------------

_KNOWN_ROOTS = [
    "catalog",
    "profile",
    "mapping",
    "mapping-collection",
    "component-definition",
    "system-security-plan",
    "assessment-plan",
    "assessment-results",
    "plan-of-action-and-milestones",
]


def _detect_model_root_key(data: dict) -> Optional[str]:
    """Identify which OSCAL model root key is present in the document."""
    for root in _KNOWN_ROOTS:
        if root in data:
            return root
    return None


def _normalize_version(version: Optional[str]) -> str:
    """Return a ``v``-prefixed OSCAL version string (or "" when unset)."""
    version = (version or "").strip()
    if not version:
        return ""
    return version if version.startswith("v") else f"v{version}"


def _reorder_dict(d: dict, ordered_keys: List[str]) -> dict:
    """
    Return a new dict with keys from *ordered_keys* first (in that order),
    followed by any remaining keys not in *ordered_keys* (preserving their
    original relative order). Keys in *ordered_keys* not present in *d* are
    skipped; keys in *d* not covered by *ordered_keys* (extensions, ``$schema``,
    ``_unmodeled``, …) are appended last, unchanged.
    """
    result: dict = {}
    for k in ordered_keys:
        if k in d:
            result[k] = d[k]
    for k in d:
        if k not in result:
            result[k] = d[k]
    return result


# ---------------------------------------------------------------------------
# Metaschema-driven ordering engine
# ---------------------------------------------------------------------------

class _MetaschemaOrderer:
    """Reorders an OSCAL JSON object tree to canonical metaschema key order.

    Built from a processed metaschema index (``support.get_metaschema_index``).
    Mirrors the converter's definition-resolution so recursive references
    (e.g. nested ``control`` / ``part``) resolve to their defining node.
    """

    def __init__(self, model_index: dict) -> None:
        self.root_node: dict = model_index.get("nodes") or {}
        self._defs: dict[str, dict] = {}
        self._index_defs(self.root_node)

    @classmethod
    def from_support(cls, model: str, version: str,
                     support=None) -> "Optional[_MetaschemaOrderer]":
        """Build an orderer for *model* at *version* from the support database.

        Falls back to ``METASCHEMA_MIN_VERSION`` for versions older than the
        first NIST resolved metaschema, and to the latest supported version when
        the requested version's index is missing. Returns None when no usable
        index is available.
        """
        if support is None:
            support = get_support()

        latest = _normalize_version(support.get_latest_version())
        index_version = _normalize_version(version) or latest

        if index_version and compare_semver(index_version, METASCHEMA_MIN_VERSION) < 0:
            logger.warning(
                f"No metaschema index for {index_version} (resolved metaschema not "
                f"published before {METASCHEMA_MIN_VERSION}); using {METASCHEMA_MIN_VERSION}."
            )
            index_version = METASCHEMA_MIN_VERSION

        model_index = support.get_metaschema_index(index_version, model)
        if model_index is None and index_version != latest and latest:
            logger.warning(
                f"No metaschema index for {model}/{index_version}; falling back to {latest}."
            )
            model_index = support.get_metaschema_index(latest, model)
        if model_index is None:
            return None
        return cls(model_index)

    # -- definition resolution (recursive stubs) ---------------------------
    def _index_defs(self, node: Optional[dict]) -> None:
        """Record the first occurrence of each named assembly/field/flag def."""
        if not node or node.get("structure-type") == "recursive":
            return
        name = node.get("name", "")
        stype = node.get("structure-type", "")
        if name and stype in ("assembly", "field") and name not in self._defs:
            self._defs[name] = node
        for child in node.get("children") or []:
            if child and child.get("structure-type") == "flag":
                fn = child.get("name", "")
                if fn and fn not in self._defs:
                    self._defs[fn] = child
            else:
                self._index_defs(child)

    def _resolve(self, node: dict) -> dict:
        """Return the full definition node for a recursive stub."""
        if node.get("structure-type") == "recursive":
            return self._defs.get(node.get("name", ""), node)
        return node

    @staticmethod
    def _json_key(child: dict) -> str:
        """The JSON property name for a child node: group-as (collection) or use-name."""
        return child.get("group-as") or child.get("use-name") or ""

    # -- ordering ----------------------------------------------------------
    def _ordered_child_keys(self, node: dict) -> List[str]:
        """Canonical JSON key order for *node*: flags, then field value, then children."""
        node = self._resolve(node)
        children = node.get("children") or []
        keys: List[str] = []

        # 1. Flags, in metaschema order.
        for c in children:
            if c and c.get("structure-type") == "flag":
                un = c.get("use-name", "")
                if un:
                    keys.append(un)

        # 2. Field value key (a value-bearing field that also carries flags).
        if node.get("structure-type") == "field":
            jvk = node.get("json-value-key")
            if jvk:
                keys.append(jvk)

        # 3. Child fields/assemblies, in metaschema order (choices flattened).
        for c in children:
            if not c:
                continue
            stype = c.get("structure-type", "")
            if stype in ("flag", "any"):
                continue
            if stype == "choice":
                for alt in c.get("children") or []:
                    if alt:
                        k = self._json_key(alt)
                        if k:
                            keys.append(k)
            else:
                k = self._json_key(c)
                if k:
                    keys.append(k)
        return keys

    def _child_node_for_key(self, node: dict, key: str) -> Optional[dict]:
        """Return the child index node whose JSON key is *key* (choices flattened).

        Flags and ``any`` wildcards are skipped — their JSON values are scalars
        or opaque and are never recursed into.
        """
        node = self._resolve(node)
        for c in node.get("children") or []:
            if not c:
                continue
            stype = c.get("structure-type", "")
            if stype in ("flag", "any"):
                continue
            if stype == "choice":
                for alt in c.get("children") or []:
                    if alt and self._json_key(alt) == key:
                        return alt
            elif self._json_key(c) == key:
                return c
        return None

    def resequence_object(self, obj: dict, node: dict) -> dict:
        """Return *obj* with its keys reordered to *node*'s canonical order, recursively."""
        node = self._resolve(node)
        ordered = _reorder_dict(obj, self._ordered_child_keys(node))
        out: dict = {}
        for k, v in ordered.items():
            out[k] = self._resequence_child(v, self._child_node_for_key(node, k))
        return out

    def _resequence_child(self, value, child: Optional[dict]):
        """Recurse into a child value using its index node (handling arrays / BY_KEY maps)."""
        if child is None:
            # Unknown key: a flag scalar, extension, $schema, _unmodeled, … — leave as-is.
            return value
        group_in_json = child.get("group-as-in-json")   # read cardinality from the (stub) reference
        if isinstance(value, list):
            return [self._resequence_item(item, child) for item in value]
        if group_in_json == "BY_KEY" and isinstance(value, dict):
            # A JSON object keyed by a flag value: reorder each instance, keep map order.
            return {mk: self._resequence_item(mv, child) for mk, mv in value.items()}
        return self._resequence_item(value, child)

    def _resequence_item(self, value, child: dict):
        if isinstance(value, dict):
            return self.resequence_object(value, child)
        if isinstance(value, list):
            return [self._resequence_item(item, child) for item in value]
        return value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resequence_oscal(data: dict, version: Optional[str] = None) -> dict:
    """
    Resequence all keys in an OSCAL document dict to canonical metaschema order.

    The single model root key is placed first (after a leading ``$schema`` if
    present); its object and the whole subtree are reordered per the metaschema
    index for the document's model and version.

    Args:
        data: Parsed OSCAL document as a Python dict.
        version: OSCAL version to order against (e.g. "v1.2.0" or "1.2.0"). When
            omitted, the document's ``metadata/oscal-version`` is used, falling
            back to the latest supported version.

    Returns:
        A new dict with keys in canonical order (same data, new ordering). The
        input is returned unchanged when the model can't be identified or no
        metaschema index is available.
    """
    model = _detect_model_root_key(data)
    if not model:
        logger.warning("resequence: no OSCAL model root key found; returning data unchanged.")
        return data

    root_obj = data.get(model)

    doc_version = ""
    if isinstance(root_obj, dict):
        metadata = root_obj.get("metadata")
        if isinstance(metadata, dict):
            doc_version = metadata.get("oscal-version", "") or ""

    orderer = _MetaschemaOrderer.from_support(model, version or doc_version)
    if orderer is None:
        logger.warning(
            f"resequence: no metaschema index for model '{model}' "
            f"(version '{version or doc_version or 'latest'}'); returning data unchanged."
        )
        return data

    ordered_root = (
        orderer.resequence_object(root_obj, orderer.root_node)
        if isinstance(root_obj, dict) else root_obj
    )

    # Emit $schema (if any) first, then the model root, then any other extras.
    out: dict = {}
    if "$schema" in data:
        out["$schema"] = data["$schema"]
    out[model] = ordered_root
    for k, v in data.items():
        if k != model and k != "$schema":
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def _detect_format(path: Path) -> str:
    """Return 'json' or 'yaml' based on file extension."""
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    elif suffix in (".yaml", ".yml"):
        return "yaml"
    else:
        # Try sniffing the first non-whitespace character
        try:
            text = path.read_text(encoding="utf-8").lstrip()
            if text.startswith("{") or text.startswith("["):
                return "json"
        except OSError:
            pass
        return "yaml"  # default fallback


def _load_file(path: Path, fmt: str) -> dict:
    text = path.read_text(encoding="utf-8")
    if fmt == "json":
        return json.loads(text)
    else:
        if not YAML_AVAILABLE:
            raise ImportError(
                "PyYAML is not installed. Install it with: pip install pyyaml"
            )
        return yaml.load(text, Loader=_OscalLoader) # type: ignore


def _dump_file(data: dict, path: Path, fmt: str) -> None:
    if fmt == "json":
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    else:
        if not YAML_AVAILABLE:
            raise ImportError(
                "PyYAML is not installed. Install it with: pip install pyyaml"
            )
        text = yaml.dump( # type: ignore
            data,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,    # preserve our metaschema-imposed ordering
            indent=2,
            width=120,
        )
    path.write_text(text, encoding="utf-8")


def resequence_oscal_file(
    input_path: Union[str, Path],
    output_path: Union[str, Path, None] = None,
    version: Optional[str] = None,
) -> Path:
    """
    Load an OSCAL JSON or YAML file, resequence all keys to canonical metaschema
    order, and write the result.

    Args:
        input_path:  Path to the source OSCAL file.
        output_path: Destination path.  If None, the input file is overwritten
                     in-place.
        version:     OSCAL version to order against; defaults to the document's
                     ``metadata/oscal-version`` (then the latest supported).

    Returns:
        The Path object of the written output file.
    """
    input_path = Path(input_path)
    if output_path is None:
        output_path = input_path
    output_path = Path(output_path)

    fmt = _detect_format(input_path)
    data = _load_file(input_path, fmt)
    ordered = resequence_oscal(data, version=version)

    # Use the output file's extension to determine output format (allows
    # implicit JSON→YAML or YAML→JSON conversion if extensions differ).
    out_fmt = _detect_format(output_path)
    _dump_file(ordered, output_path, out_fmt)

    return output_path


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else None

    if not input_path.exists():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    out = resequence_oscal_file(input_path, output_path)
    action = "resequenced in-place" if output_path is None or output_path == input_path else f"written to {out}"
    model = _detect_model_root_key(_load_file(input_path, _detect_format(input_path))) or "unknown model"
    print(f"✓ [{model}] {input_path.name} — {action}")


if __name__ == "__main__":
    main()
