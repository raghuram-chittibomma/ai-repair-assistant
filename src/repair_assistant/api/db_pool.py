"""Small psycopg connection pool for the HTTP API (Phase 10)."""

from __future__ import annotations

import queue
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from repair_assistant.ingest.store import Database

DEFAULT_POOL_SIZE = 4
DEFAULT_POOL_TIMEOUT_SECONDS = 30.0


class PoolTimeoutError(RuntimeError):
    """Raised when no pool connection becomes available within the wait budget."""


class DatabasePool:
    """Bounded pool of ``Database`` wrappers (one psycopg connection each)."""

    def __init__(
        self,
        url: str,
        *,
        size: int = DEFAULT_POOL_SIZE,
        timeout_seconds: float = DEFAULT_POOL_TIMEOUT_SECONDS,
    ) -> None:
        self._url = url
        self._size = max(1, int(size))
        self._timeout = float(timeout_seconds)
        if self._timeout <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._available: queue.Queue[Database] = queue.Queue()
        self._created = 0
        self._lock = threading.Lock()
        self._closed = False

    def _create(self) -> Database:
        return Database(self._url)

    def _acquire(self) -> Database:
        if self._closed:
            raise RuntimeError("database pool is closed")
        try:
            return self._available.get_nowait()
        except queue.Empty:
            with self._lock:
                if self._created < self._size:
                    self._created += 1
                    return self._create()
            try:
                return self._available.get(timeout=self._timeout)
            except queue.Empty as exc:
                raise PoolTimeoutError(
                    f"database pool exhausted (waited {self._timeout:g}s); "
                    "try again shortly"
                ) from exc

    def _release(self, db: Database) -> None:
        if self._closed:
            db.close()
            return
        try:
            db.commit()
        except Exception:
            try:
                db.close()
            except Exception:
                pass
            with self._lock:
                self._created = max(0, self._created - 1)
            return
        self._available.put(db)

    @contextmanager
    def connection(self) -> Iterator[Database]:
        db = self._acquire()
        try:
            yield db
        except Exception:
            try:
                db.close()
            except Exception:
                pass
            with self._lock:
                self._created = max(0, self._created - 1)
            raise
        else:
            self._release(db)

    def close(self) -> None:
        self._closed = True
        while True:
            try:
                db = self._available.get_nowait()
            except queue.Empty:
                break
            db.close()
