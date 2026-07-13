"""
oscal_registry — process-shared identity map for loaded OSCAL objects.

Ensures a given OSCAL document is held in memory once and reused across branches
of an import tree (and across separate resolves in the same process), so two
references to the same file share a single object instead of loading it twice.

Objects are keyed by a composite **content identity** — ``(root-uuid,
last-modified, published)`` — which treats the same content as identical
regardless of format or location, with a **canonicalized href** as a pre-fetch
fast path. Values are held via weak references (``WeakValueDictionary``), so an
object stays registered only while some importer still holds it and is dropped
automatically once no longer referenced.

The default registry is a process-global singleton (``get_registry()``). The
``ObjectRegistry`` class is injectable so a future Workspace/session can own an
isolated instance.

Module constants:
    (none exported)
"""
import contextvars
import threading
import weakref
from contextlib import contextmanager
from typing import Any, Optional


class ObjectRegistry:
    """An identity map of loaded OSCAL objects, keyed by content identity and href.

    Lookups check the canonical href first (cheap, pre-fetch), then the composite
    content-identity key. Stale entries — objects whose own TTL has expired
    (``is_cache_expired``) — are treated as misses and dropped so the caller
    reloads. Thread-safe via an internal lock.
    """

    def __init__(self) -> None:
        """Initialize an empty registry (weak identity/href maps and a resolution stack)."""
        self._by_key: "weakref.WeakValueDictionary[tuple, Any]" = weakref.WeakValueDictionary()
        self._by_href: "weakref.WeakValueDictionary[str, Any]" = weakref.WeakValueDictionary()
        self._resolving: set = set()   # canonical hrefs currently on the resolution stack
        self._lock = threading.RLock()

    # -- resolution stack (cycle detection) -----------------------------------
    def enter_resolving(self, href: str) -> None:
        """Mark a canonical href as currently being resolved (push onto the DFS stack)."""
        if href:
            with self._lock:
                self._resolving.add(href)

    def exit_resolving(self, href: str) -> None:
        """Unmark a canonical href once its resolution completes (pop from the stack)."""
        if href:
            with self._lock:
                self._resolving.discard(href)

    def is_resolving(self, href: str) -> bool:
        """Return True when ``href`` is an ancestor currently being resolved (a cycle)."""
        if not href:
            return False
        with self._lock:
            return href in self._resolving

    # -- lookup ---------------------------------------------------------------
    def get(self, *, key: Optional[tuple] = None, href: str = "") -> Optional[Any]:
        """Return a live, fresh object matching ``href`` (checked first) or ``key``.

        Args:
            key (tuple | None, optional): Composite content-identity key.
            href (str, optional): Canonicalized href.

        Returns:
            Any | None: The registered object, or None on miss or when the match is
                stale (its ``is_cache_expired`` is True), in which case it is dropped.
        """
        with self._lock:
            obj = None
            if href:
                obj = self._by_href.get(href)
            if obj is None and key is not None:
                obj = self._by_key.get(key)
            if obj is not None and getattr(obj, "is_cache_expired", False):
                self._forget(obj)
                return None
            return obj

    # -- registration ---------------------------------------------------------
    def register(self, obj: Any, *, key: Optional[tuple] = None, href: str = "") -> Any:
        """Register ``obj`` under its content-identity key and/or canonical href.

        Args:
            obj (Any, required): The object to register.
            key (tuple | None, optional): Composite content-identity key.
            href (str, optional): Canonicalized href.

        Returns:
            Any: The registered object (``obj``).
        """
        with self._lock:
            if key is not None:
                self._by_key[key] = obj
            if href:
                self._by_href[href] = obj
            return obj

    def alias_href(self, href: str, obj: Any) -> None:
        """Point an additional canonical href at an already-registered object.

        Args:
            href (str, required): The canonical href to alias.
            obj (Any, required): The object the href should resolve to.
        """
        with self._lock:
            if href:
                self._by_href[href] = obj

    # -- maintenance ----------------------------------------------------------
    def _forget(self, obj: Any) -> None:
        """Remove every reference to ``obj`` from both maps."""
        for store in (self._by_href, self._by_key):
            for k, v in list(store.items()):
                if v is obj:
                    del store[k]

    def clear(self) -> None:
        """Drop all entries (primarily for test isolation)."""
        with self._lock:
            self._by_key.clear()
            self._by_href.clear()
            self._resolving.clear()

    def __len__(self) -> int:
        """Return the number of distinct live objects registered by identity key."""
        with self._lock:
            return len(set(self._by_key.values()))


# Process-global default registry, plus an optional "active" registry (set by a
# Workspace) that overrides it for objects created within its context.
_default_registry = ObjectRegistry()
_active_registry: "contextvars.ContextVar[Optional[ObjectRegistry]]" = contextvars.ContextVar(
    "oscal_active_registry", default=None
)


def get_registry() -> ObjectRegistry:
    """Return the currently active object registry.

    Returns the registry activated by :func:`use_registry` (e.g. a Workspace's own
    registry) when one is in effect on the current context, otherwise the
    process-global default. Because a document load cascades synchronously, every
    object created during the load picks up whichever registry is active.

    Returns:
        ObjectRegistry: The active registry, or the process-global default.
    """
    active = _active_registry.get()
    return active if active is not None else _default_registry


@contextmanager
def use_registry(registry: ObjectRegistry):
    """Activate ``registry`` for the duration of the ``with`` block.

    Objects created while this context is active (including transitively-loaded
    imports) use ``registry`` instead of the process-global default.

    Args:
        registry (ObjectRegistry, required): The registry to activate.

    Yields:
        ObjectRegistry: The activated registry.
    """
    token = _active_registry.set(registry)
    try:
        yield registry
    finally:
        _active_registry.reset(token)
