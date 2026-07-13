"""
oscal_workspace — a Workspace that owns a set of related OSCAL documents.

A ``Workspace`` is the entry point for opening/creating OSCAL content as a project.
It owns an isolated in-memory object registry (so two workspaces are independent
object graphs) and injects that registry into every document it loads — including
transitively-loaded imports — via :func:`oscal.oscal_registry.use_registry`.

Within one workspace, opening the same file twice returns the **same** object
(root documents are shared, keyed by their source path/href), which is the basis
for multi-view editing. The remote-content disk cache remains process-global
(shared across workspaces).

A workspace can be **saved to a single SQLite project file** (content + state,
reusing the shared ``filecache`` schema) and reloaded self-contained, without
refetching. The project file also carries project-level metadata (title, path,
last-modified, remarks, and an extensible attributes bag) and is the intended
substrate for future multi-view / multi-user (locking, sync) support.

Module constants:
    WORKSPACE_META_TABLE (dict): Schema for the ``workspace_meta`` key/value table.
    WORKSPACE_DOCS_TABLE (dict): Schema for the ``workspace_documents`` table.
"""
import json
import os
import time
import uuid as uuid_module
from typing import Any, Optional

import logging
from ruf_common.lfs import chkdir, normalize_content
from ruf_common import database

from .oscal_registry import ObjectRegistry, use_registry
from .oscal_content import OSCAL, ContentState, ImportState, _canonicalize_ref, current_actor, use_actor
from .oscal_datatypes import oscal_date_time_with_timezone

logger = logging.getLogger(__name__)


WORKSPACE_META_TABLE = {
    "table_name": "workspace_meta",
    "table_fields": [
        {"name": "key",   "type": "TEXT", "attributes": "PRIMARY KEY", "description": "Metadata key."},
        {"name": "value", "type": "TEXT", "description": "Metadata value."},
    ],
}

WORKSPACE_DOCS_TABLE = {
    "table_name": "workspace_documents",
    "table_fields": [
        {"name": "doc_id",          "type": "TEXT", "attributes": "PRIMARY KEY", "description": "Per-document persistence id."},
        {"name": "source",          "type": "TEXT",    "description": "Canonical source href/path (root key)."},
        {"name": "is_root",         "type": "NUMERIC", "description": "1 for workspace root documents."},
        {"name": "model",           "type": "TEXT",    "description": "OSCAL model name."},
        {"name": "oscal_version",   "type": "TEXT",    "description": "OSCAL version."},
        {"name": "uuid",            "type": "TEXT",    "description": "Root document UUID."},
        {"name": "original_format", "type": "TEXT",    "description": "Original serialization format."},
        {"name": "content_state",   "type": "NUMERIC", "description": "ContentState value."},
        {"name": "is_canonical",    "type": "NUMERIC", "description": "1 when canonical/read-only."},
        {"name": "is_read_only",    "type": "NUMERIC", "description": "1 when read-only."},
        {"name": "filecache_uuid",  "type": "TEXT",    "description": "filecache uuid of the JSON content."},
        {"name": "imports",         "type": "TEXT",    "description": "JSON import edges (href/status/child doc_id)."},
        {"name": "state",           "type": "TEXT",    "description": "JSON derived state (validation results, indexes, subclass state)."},
    ],
}


class Workspace:
    """A named set of related OSCAL documents with an isolated object registry.

    Documents opened through the workspace share one registry (imports dedup within
    the workspace) and one document identity map (opening the same source twice
    returns the same object). Carries project metadata and can be persisted to a
    single SQLite project file.
    """

    def __init__(self, title: str = "", path: str = "", registry: Optional[ObjectRegistry] = None) -> None:
        """Create a workspace.

        Args:
            title (str, optional): Project title.
            path (str, optional): Default path for the workspace's project file.
            registry (ObjectRegistry | None, optional): Registry to use; a fresh
                isolated one is created when omitted.
        """
        self.title = title
        self.path = path
        self.remarks = ""
        self.last_modified = oscal_date_time_with_timezone()
        self.attributes: dict[str, Any] = {}     # extensible project-specific attributes
        self._registry = registry or ObjectRegistry()
        self._documents: dict[str, OSCAL] = {}    # canonical source (or "new:*") -> root document
        self._locks: dict[int, str] = {}          # id(document) -> actor holding the write lock

    # -------------------------------------------------------------------------
    @property
    def registry(self) -> ObjectRegistry:
        """ObjectRegistry: This workspace's isolated object registry."""
        return self._registry

    @property
    def documents(self) -> list:
        """list: The workspace's open root documents."""
        return list(self._documents.values())

    def _bind(self, doc: OSCAL) -> OSCAL:
        doc._workspace = self
        doc._registry = self._registry
        return doc

    def _source_key(self, source) -> str:
        return _canonicalize_ref(source) if isinstance(source, str) and source else ""

    # -- opening / creating ---------------------------------------------------
    def open(self, source) -> OSCAL:
        """Open a document into the workspace (loading it under the workspace registry).

        Re-opening the same source returns the already-open document (shared root).

        Args:
            source (str, required): A path or URI to load.

        Returns:
            OSCAL: The (possibly already-open) document.
        """
        key = self._source_key(source)
        if key and key in self._documents:
            return self._documents[key]
        with use_registry(self._registry):
            doc = OSCAL.open(source)
        self._bind(doc)
        if key:
            self._documents[key] = doc
        return doc

    def loads(self, content: str, *, href: Optional[str] = None) -> OSCAL:
        """Open in-memory content into the workspace.

        Args:
            content (str, required): Serialized OSCAL content.
            href (str | None, optional): Source URI to key/track the document by.

        Returns:
            OSCAL: The opened document.
        """
        with use_registry(self._registry):
            doc = OSCAL.loads(content, href=href)
        self._bind(doc)
        key = self._source_key(href) if href else f"new:{uuid_module.uuid4()}"
        self._documents[key] = doc
        return doc

    def new(self, model_cls, title: str, **kwargs) -> OSCAL:
        """Create a new document in the workspace.

        Args:
            model_cls (type, required): A model class (e.g. ``Catalog``).
            title (str, required): Document title.
            **kwargs: Passed through to ``model_cls.new``.

        Returns:
            OSCAL: The new document, tracked by the workspace.
        """
        with use_registry(self._registry):
            doc = model_cls.new(title, **kwargs)
        self._bind(doc)
        self._documents[f"new:{uuid_module.uuid4()}"] = doc
        return doc

    def close(self, doc: OSCAL) -> None:
        """Stop tracking a document (releasing the workspace's strong reference and lock)."""
        for key, value in list(self._documents.items()):
            if value is doc:
                del self._documents[key]
        self._locks.pop(id(doc), None)

    def close_all(self) -> None:
        """Release all tracked documents and their locks."""
        self._documents.clear()
        self._locks.clear()

    # -- write locks (in-memory, multi-view within one process) ---------------
    def as_actor(self, actor: str):
        """Context manager that attributes mutations in the block to ``actor``.

        Args:
            actor (str, required): The actor (view/session) id.

        Returns:
            A context manager activating ``actor`` as the current actor.
        """
        return use_actor(actor)

    def lock(self, doc: OSCAL, actor: Optional[str] = None) -> bool:
        """Acquire the write lock on ``doc`` for ``actor`` (exclusive editing).

        While held, the document is read-only to every other actor. Re-locking by
        the same actor succeeds (idempotent).

        Args:
            doc (OSCAL, required): The document to lock.
            actor (str | None, optional): The actor; defaults to the current actor.

        Returns:
            bool: True if the lock is held by ``actor`` afterward, False if another
                actor already holds it.

        Raises:
            ValueError: When no actor is given and none is active.
        """
        actor = actor if actor is not None else current_actor()
        if actor is None:
            raise ValueError("lock() requires an actor (pass actor= or use as_actor()).")
        holder = self._locks.get(id(doc))
        if holder is not None and holder != actor:
            logger.info(f"lock: '{getattr(doc, 'title', '')}' already locked by '{holder}'.")
            return False
        self._locks[id(doc)] = actor
        return True

    def unlock(self, doc: OSCAL, actor: Optional[str] = None) -> bool:
        """Release the write lock on ``doc``.

        Args:
            doc (OSCAL, required): The document to unlock.
            actor (str | None, optional): The actor; defaults to the current actor.
                A caller may only release its own lock (unless ``actor`` is None-held).

        Returns:
            bool: True when the document is unlocked afterward; False when the lock
                is held by a different actor and cannot be released.
        """
        actor = actor if actor is not None else current_actor()
        holder = self._locks.get(id(doc))
        if holder is None:
            return True
        if actor is not None and holder != actor:
            return False
        del self._locks[id(doc)]
        return True

    def lock_holder(self, doc: OSCAL) -> Optional[str]:
        """Return the actor holding the write lock on ``doc``, or None.

        Args:
            doc (OSCAL, required): The document.

        Returns:
            Optional[str]: The lock-holding actor, or None when unlocked.
        """
        return self._locks.get(id(doc))

    def is_locked(self, doc: OSCAL) -> bool:
        """Return True when ``doc`` is write-locked by any actor."""
        return id(doc) in self._locks

    # -- persistence ----------------------------------------------------------
    def _collect_documents(self) -> dict:
        """Return {id(obj): obj} for every document reachable from the roots."""
        seen: dict[int, OSCAL] = {}

        def visit(obj):
            if obj is None or id(obj) in seen:
                return
            seen[id(obj)] = obj
            for entry in getattr(obj, "import_list", []):
                visit(entry.get("object"))

        for root in self._documents.values():
            visit(root)
        return seen

    def _root_source(self, obj: OSCAL) -> str:
        for key, value in self._documents.items():
            if value is obj:
                return key
        return obj.href or obj.href_original or ""

    def save(self, path: str = "") -> bool:
        """Save the workspace (content + state + project metadata) to a SQLite file.

        Every reachable document (roots and their resolved imports) is serialized as
        JSON into the shared ``filecache`` table, with its state and import edges
        recorded in ``workspace_documents``; project metadata goes in
        ``workspace_meta``. Reusing ``filecache`` means no schema change to the
        support database.

        Args:
            path (str, optional): Destination path. Defaults to ``self.path``.

        Returns:
            bool: True on success.
        """
        path = path or self.path
        if not path:
            raise ValueError("Workspace.save requires a path (set 'path' or pass one).")
        self.path = path
        self.last_modified = oscal_date_time_with_timezone()

        directory = os.path.dirname(path)
        if directory:
            chkdir(directory, make_if_not_present=True)

        db = database.Database("sqlite3", path)
        db.check_for_tables({
            "filecache": database.OSCAL_COMMON_TABLES["filecache"],
            "workspace_meta": WORKSPACE_META_TABLE,
            "workspace_documents": WORKSPACE_DOCS_TABLE,
        })
        db.db_execute([
            "DELETE FROM workspace_documents",
            "DELETE FROM workspace_meta",
            "DELETE FROM filecache",
        ])

        docs = self._collect_documents()
        doc_ids = {oid: str(uuid_module.uuid4()) for oid in docs}
        root_ids = {id(d) for d in self._documents.values()}

        for oid, obj in docs.items():
            content = obj.dumps(format="json") if obj._dict is not None else ""
            fc_uuid = str(uuid_module.uuid4())
            db.cache_file(content, fc_uuid, {
                "filename": f"{obj.model or 'document'}.json",
                "file_type": "workspace-document",
                "acquired": time.time(),
            })
            edges = []
            for entry in obj.import_list:
                child = entry.get("object")
                status = entry.get("status")
                edges.append({
                    "href_original": entry.get("href_original", ""),
                    "status": status.value if hasattr(status, "value") else str(status),
                    "child": doc_ids.get(id(child)) if child is not None else None,
                })
            db.insert("workspace_documents", {
                "doc_id":          doc_ids[oid],
                "source":          self._root_source(obj) if oid in root_ids else (obj.href or obj.href_original or ""),
                "is_root":         1 if oid in root_ids else 0,
                "model":           obj.model or "",
                "oscal_version":   obj.oscal_version or "",
                "uuid":            obj.uuid or "",
                "original_format": obj.original_format or "json",
                "content_state":   int(obj.content_state),
                "is_canonical":    1 if obj.is_canonical else 0,
                "is_read_only":    1 if obj.is_read_only else 0,
                "filecache_uuid":  fc_uuid,
                "imports":         json.dumps(edges),
                "state":           json.dumps(obj._export_state()),
            })

        for key, value in {
            "title":         self.title,
            "path":          self.path,
            "last_modified": self.last_modified,
            "remarks":       self.remarks,
            "attributes":    json.dumps(self.attributes),
        }.items():
            db.insert("workspace_meta", {"key": key, "value": value})

        logger.info(f"Workspace saved to '{path}' ({len(docs)} document(s)).")
        return True

    @classmethod
    def load(cls, path: str) -> "Workspace":
        """Load a workspace from its SQLite project file (self-contained; no refetch).

        Args:
            path (str, required): The workspace project file.

        Returns:
            Workspace: The reconstructed workspace, with documents rehydrated and
                their import trees rewired from the persisted content and state.
        """
        ws = cls(path=path)
        db = database.Database("sqlite3", path)

        for row in db.query("SELECT key, value FROM workspace_meta"):
            k, v = row.get("key"), row.get("value")
            if k == "title":
                ws.title = v or ""
            elif k == "last_modified":
                ws.last_modified = v or ws.last_modified
            elif k == "remarks":
                ws.remarks = v or ""
            elif k == "attributes":
                ws.attributes = json.loads(v) if v else {}

        rows = db.query("SELECT * FROM workspace_documents")
        by_id: dict[str, OSCAL] = {}
        for row in rows:
            content = normalize_content(db.retrieve_file(row["filecache_uuid"]))
            by_id[row["doc_id"]] = ws._rehydrate(row, content)

        # Second pass: rewire each document's import_list to the rehydrated children.
        for row in rows:
            obj = by_id[row["doc_id"]]
            obj.import_list = []
            for edge in json.loads(row.get("imports") or "[]"):
                child = by_id.get(edge.get("child")) if edge.get("child") else None
                raw_status = edge.get("status", "")
                status = ImportState(raw_status) if raw_status in ImportState._value2member_map_ else ImportState.NOT_LOADED
                obj.import_list.append({
                    "href_original": edge.get("href_original", ""),
                    "href_valid":    (child.href or child.href_original) if child else "",
                    "href_list":     [{"href": edge.get("href_original", ""), "original": True}],
                    "status":        status,
                    "is_valid":      status == ImportState.READY,
                    "is_local":      None,
                    "is_remote":     None,
                    "is_cached":     False,
                    "object":        child,
                    "failure":       None,
                })
            obj._import_tree = None

        # Register documents and record roots.
        for row in rows:
            obj = by_id[row["doc_id"]]
            if obj._identity is not None:
                ws._registry.register(
                    obj, key=obj._identity,
                    href=_canonicalize_ref(obj.href or obj.href_original),
                )
            if row.get("is_root"):
                ws._documents[row.get("source") or f"new:{uuid_module.uuid4()}"] = obj

        logger.info(f"Workspace loaded from '{path}' ({len(rows)} document(s)).")
        return ws

    def _rehydrate(self, row: dict, content: str) -> OSCAL:
        """Reconstruct one document from persisted content + state (no import resolution)."""
        data = json.loads(content) if isinstance(content, str) else content
        model = row.get("model") or (next(iter(data), "") if isinstance(data, dict) else "")

        obj = OSCAL.__new__(OSCAL)
        obj.__init_common__()
        obj._origin = "workspace"
        obj._dict = data
        obj._registry = self._registry
        obj._workspace = self
        obj.model = model
        obj.oscal_version = row.get("oscal_version") or ""
        obj.uuid = row.get("uuid") or ""
        obj.original_format = row.get("original_format") or "json"
        obj.href_original = row.get("source") or ""
        obj.href = obj.href_original
        try:
            obj.content_state = ContentState(int(row.get("content_state")))
        except (TypeError, ValueError):
            obj.content_state = ContentState.VALID
        obj.is_canonical = bool(row.get("is_canonical"))
        obj._is_read_only = bool(row.get("is_read_only"))

        root = data.get(model, {}) if isinstance(data, dict) else {}
        meta = root.get("metadata", {}) if isinstance(root, dict) else {}
        obj.title = meta.get("title", "")
        obj.version = meta.get("version", "")
        obj.published = meta.get("published", "")
        obj._identity = (obj.uuid, meta.get("last-modified", ""), obj.published) if obj.uuid else None

        # Re-class to the typed model subclass, then restore derived state (validation
        # results, subclass state, indexes) so it need not be re-determined.
        obj._upgrade_to_model_class()
        obj._import_state(json.loads(row.get("state") or "{}"))
        return obj
