"""
oscal_cache — on-disk cache of remote OSCAL content.

Provides a persistent, cross-session cache of content fetched from remote URLs so
the same remote document is not downloaded repeatedly. It reuses the shared
``filecache`` file-store schema (the same table the support database uses) in a
separate ``local_cache.db`` located alongside the support database. The database
is created lazily on first use, not at startup.

Cached content is keyed by its (canonicalized) remote URL via the ``filecache``
``original_location`` column, with the fetch time stored in ``acquired``; an entry
is served only while it is within ``LOCAL_CACHE_TTL`` seconds of that time,
otherwise it is refetched and the entry refreshed.

This complements the in-memory object registry (``oscal_registry``): the registry
avoids re-loading/parsing a live object, while this cache avoids the network round
trip across process runs.

Caching is controlled per fetch by a :class:`CacheDirective`. The directive is
applied first, then the fetch is evaluated for local reuse vs. refresh. Because
the directive's TTL is compared against the entry's last-fetch time, changing the
TTL re-evaluates freshness against that time (e.g. an entry fetched 6h ago is
still fresh under a new 12h TTL). ``CACHE_NEVER`` purges any copy and always
fetches remotely; ``CACHE_FOREVER`` reuses a copy of any age; ``refresh`` forces a
refetch now.

Module constants:
    LOCAL_CACHE_TTL (int): Default seconds a cached item stays fresh (86400 = 24h).
    CACHE_FOREVER (int): TTL sentinel — never expires (reuse a copy of any age).
    CACHE_NEVER (int): TTL sentinel — do not cache (purge and always fetch remotely).
    LOCAL_CACHE_FILENAME (str): Filename of the cache database ("local_cache.db").
"""
import os
import time
import uuid as uuid_module
from dataclasses import dataclass
from typing import Optional

import logging
from ruf_common.lfs import chkdir, normalize_content
from ruf_common import database

logger = logging.getLogger(__name__)

LOCAL_CACHE_TTL = 86400            # 24 hours, in seconds
CACHE_FOREVER = -1                 # TTL sentinel: never expires
CACHE_NEVER = -2                   # TTL sentinel: do not cache
LOCAL_CACHE_FILENAME = "local_cache.db"


@dataclass(frozen=True)
class CacheDirective:
    """A per-fetch instruction for how the remote-content cache should behave.

    The directive is applied first, then the fetch is evaluated: the (possibly
    overridden) TTL is compared against the cached entry's last-fetch time to decide
    whether the local copy is reused or the content is refetched.

    Attributes:
        ttl (int): Freshness window in seconds, or a sentinel — ``CACHE_FOREVER``
            (reuse a copy of any age) or ``CACHE_NEVER`` (purge and always fetch).
            Defaults to ``LOCAL_CACHE_TTL`` (24h).
        refresh (bool): When True, force a refetch now regardless of freshness
            (the refreshed content replaces the cached copy). Defaults to False.
    """
    ttl: int = LOCAL_CACHE_TTL
    refresh: bool = False

    @classmethod
    def default(cls) -> "CacheDirective":
        """Default behavior: 24h TTL, no forced refresh.

        Returns:
            CacheDirective: A directive with the default TTL and no refresh.
        """
        return cls()

    @classmethod
    def of(cls, seconds: int) -> "CacheDirective":
        """Cache with a specific TTL.

        Args:
            seconds (int, required): Freshness window in seconds.

        Returns:
            CacheDirective: A directive with ``ttl=seconds``.
        """
        return cls(ttl=seconds)

    @classmethod
    def forever(cls) -> "CacheDirective":
        """Keep the cached copy until manually purged or refreshed.

        Returns:
            CacheDirective: A directive with ``ttl=CACHE_FOREVER``.
        """
        return cls(ttl=CACHE_FOREVER)

    @classmethod
    def never(cls) -> "CacheDirective":
        """Never cache: purge any existing copy and always fetch remotely.

        Returns:
            CacheDirective: A directive with ``ttl=CACHE_NEVER``.
        """
        return cls(ttl=CACHE_NEVER)

    @classmethod
    def refresh_now(cls, ttl: int = LOCAL_CACHE_TTL) -> "CacheDirective":
        """Force a refetch now, then cache the result.

        Args:
            ttl (int, optional): TTL to apply to the refreshed copy. Defaults to
                ``LOCAL_CACHE_TTL`` (24h).

        Returns:
            CacheDirective: A directive with ``refresh=True`` and the given ``ttl``.
        """
        return cls(ttl=ttl, refresh=True)


def _sql_escape(value: str) -> str:
    """Escape single quotes for safe inline use in a SQL string literal."""
    return value.replace("'", "''")


class LocalCache:
    """Persistent cache of remote content, backed by a ``filecache`` table.

    The backing ``local_cache.db`` is opened/created lazily on first access. Entries
    are keyed by remote URL and expire ``LOCAL_CACHE_TTL`` seconds after they were
    fetched.
    """

    def __init__(self, db_path: str = "") -> None:
        """Initialize the cache.

        Args:
            db_path (str, optional): Explicit path to the cache database. When empty,
                the path is resolved lazily to ``local_cache.db`` beside the support
                database.
        """
        self._db_path = db_path
        self._db = None

    # -------------------------------------------------------------------------
    def _resolve_path(self) -> str:
        if self._db_path:
            return self._db_path
        # Place the cache alongside the support database.
        from .oscal_support import get_support
        support = get_support()
        base = os.path.dirname(getattr(support, "db_conn", "") or "") or "."
        return os.path.join(base, LOCAL_CACHE_FILENAME)

    def _ensure_db(self):
        """Open (creating on first use) the cache database and return it."""
        if self._db is None:
            path = self._resolve_path()
            directory = os.path.dirname(path)
            if directory:
                chkdir(directory, make_if_not_present=True)
            self._db = database.Database("sqlite3", path)
            self._db.check_for_tables({"filecache": database.OSCAL_COMMON_TABLES["filecache"]})
            logger.debug(f"local cache ready at '{path}'.")
        return self._db

    def _row_for(self, url: str) -> Optional[dict]:
        db = self._ensure_db()
        rows = db.query(
            f"SELECT uuid, acquired FROM filecache WHERE original_location = '{_sql_escape(url)}'"
        )
        return rows[0] if rows else None

    # -------------------------------------------------------------------------
    def get(self, url: str, directive: Optional[CacheDirective] = None) -> Optional[str]:
        """Apply ``directive``, then return cached content for ``url`` if reusable.

        The directive is applied first: ``CACHE_NEVER`` purges any copy; ``refresh``
        forces a miss. Freshness is then evaluated by comparing the directive's TTL
        against the entry's last-fetch time (``CACHE_FOREVER`` reuses any age).

        Args:
            url (str, required): The (canonicalized) remote URL key.
            directive (CacheDirective | None, optional): Caching directive; defaults
                to :meth:`CacheDirective.default` (24h, no refresh).

        Returns:
            Optional[str]: The cached content to reuse, or None to fetch remotely.
        """
        if not url:
            return None
        directive = directive or CacheDirective()
        try:
            # --- apply the directive first ---
            if directive.ttl == CACHE_NEVER:
                self.purge(url)
                return None
            if directive.refresh:
                return None  # force a refetch; a successful put() will replace the copy

            # --- evaluate the cached entry for reuse ---
            row = self._row_for(url)
            if not row:
                return None
            if directive.ttl != CACHE_FOREVER:
                acquired = float(row.get("acquired") or 0)
                if (time.time() - acquired) >= directive.ttl:
                    logger.debug(f"local cache: '{url}' is stale (ttl={directive.ttl}s).")
                    return None
            content = normalize_content(self._ensure_db().retrieve_file(row["uuid"]))
            if content:
                logger.debug(f"local cache: hit for '{url}'.")
                return content
            return None
        except Exception as error:
            logger.warning(f"local cache get failed for '{url}': {type(error).__name__} - {error}")
            return None

    def put(self, url: str, content, directive: Optional[CacheDirective] = None) -> bool:
        """Store or refresh cached content for ``url``, resetting its last-fetch time.

        A ``CACHE_NEVER`` directive stores nothing (the content is used but not cached).

        Args:
            url (str, required): The (canonicalized) remote URL key.
            content (str | bytes, required): The fetched content to cache.
            directive (CacheDirective | None, optional): Caching directive; defaults
                to :meth:`CacheDirective.default`.

        Returns:
            bool: True when stored, False when skipped or on error.
        """
        if not url or not content:
            return False
        directive = directive or CacheDirective()
        if directive.ttl == CACHE_NEVER:
            return False  # never cache
        try:
            db = self._ensure_db()
            row = self._row_for(url)
            cache_uuid = row["uuid"] if row else str(uuid_module.uuid4())
            attributes = {
                "filename": os.path.basename(url.split("?")[0]) or "remote-content",
                "original_location": url,
                "file_type": "remote-content",
                "acquired": time.time(),
            }
            db.cache_file(content, cache_uuid, attributes)
            logger.debug(f"local cache: stored '{url}'.")
            return True
        except Exception as error:
            logger.warning(f"local cache put failed for '{url}': {type(error).__name__} - {error}")
            return False

    def purge(self, url: str) -> None:
        """Remove the cached entry for a single ``url`` (manual deletion).

        Args:
            url (str, required): The (canonicalized) remote URL key.
        """
        if not url:
            return
        try:
            self._ensure_db().db_execute(
                f"DELETE FROM filecache WHERE original_location = '{_sql_escape(url)}'"
            )
            logger.debug(f"local cache: purged '{url}'.")
        except Exception as error:
            logger.warning(f"local cache purge failed for '{url}': {type(error).__name__} - {error}")

    def clear(self) -> None:
        """Remove all cached entries (primarily for maintenance/tests)."""
        try:
            self._ensure_db().db_execute("DELETE FROM filecache")
        except Exception as error:
            logger.warning(f"local cache clear failed: {type(error).__name__} - {error}")


# Process-global default cache (created lazily).
_default_cache: Optional[LocalCache] = None


def get_local_cache() -> LocalCache:
    """Return the process-global default remote-content cache.

    Returns:
        LocalCache: The shared cache instance (its database is created on first use).
    """
    global _default_cache
    if _default_cache is None:
        _default_cache = LocalCache()
    return _default_cache
