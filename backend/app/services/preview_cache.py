import time
import uuid
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class PreviewEntry:
    query_id: str
    query: str
    sql: str
    explanation: str
    involved_tables: list[str]
    involved_columns: list[str]
    safety_status: str  # "safe", "blocked", "pending"
    executable: bool
    error_message: str | None
    created_at: float = field(default_factory=time.time)
    progress_events: list[dict] = field(default_factory=list)


class PreviewCache:
    """In-memory cache for preview results with TTL-based expiration."""

    def __init__(self, ttl_seconds: int = 1800):  # 30 minutes default
        self._cache: dict[str, PreviewEntry] = {}
        self._ttl = ttl_seconds
        self._lock = Lock()

    def put(self, entry: PreviewEntry) -> str:
        """Store a preview entry and return its query_id."""
        with self._lock:
            self._evict_expired()
            self._cache[entry.query_id] = entry
            return entry.query_id

    def get(self, query_id: str) -> PreviewEntry | None:
        """Retrieve a preview entry by query_id. Returns None if missing or expired."""
        with self._lock:
            self._evict_expired()
            entry = self._cache.get(query_id)
            if entry is None:
                return None
            if time.time() - entry.created_at > self._ttl:
                del self._cache[query_id]
                return None
            return entry

    def remove(self, query_id: str) -> None:
        """Remove a preview entry after execution."""
        with self._lock:
            self._cache.pop(query_id, None)

    def _evict_expired(self) -> None:
        """Remove expired entries (caller must hold lock)."""
        now = time.time()
        expired = [
            qid for qid, entry in self._cache.items()
            if now - entry.created_at > self._ttl
        ]
        for qid in expired:
            del self._cache[qid]


# Global instance
preview_cache = PreviewCache()
