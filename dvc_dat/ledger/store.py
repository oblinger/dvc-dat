"""The store interface, the SQLite backend behind it, and the art store of bytes by hash.

``Store`` names what the ledger reads and writes: ``top``, ``rows``,
``subjects``, ``has_predicate``, ``writer`` (the write lock and one open
transaction), ``reading_through`` (reads routed through that transaction) and
``index_names``; ``Writer`` is the open transaction (``next_rev``, ``insert``,
``create_index`` for ``db/index``). The art store stays a folder whatever the
backend. ``SqliteStore`` is below; ``PostgresStore`` is in ``pgstore``.

A SQLite ledger is a folder: ``ledger.db`` and ``art/`` (bytes by hash,
and ``art/dats/`` where a ``Dat`` is materialised) inside it (A54).

``quads(rev, ord, subject, predicate, object, added)``: ``rev`` the revision,
``ord`` the row's place within its transaction, ``object`` the tagged string
(``codec``), ``added`` 0 for a ``remove`` row. Nothing is ever updated or
deleted. Two SQL indexes, ``(subject, predicate, rev)`` and
``(predicate, object, rev)``, are the index table a where clause reads.
Revisions come from ``MAX(rev) + 1`` under SQLite's write lock.
"""

from __future__ import annotations

import sqlite3
import threading
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ContextManager, Iterator, List, Optional, Sequence, Tuple

from .codec import hash_text, sha256
from .errors import LedgerError, LockTimeout

#: ``(rev, ord, subject, predicate, object, added)``
Row = Tuple[int, int, str, str, str, bool]

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS quads (rev INTEGER NOT NULL, ord INTEGER NOT NULL, subject TEXT NOT NULL,"
    " predicate TEXT NOT NULL, object TEXT NOT NULL, added INTEGER NOT NULL, PRIMARY KEY (rev, ord))",
    "CREATE INDEX IF NOT EXISTS quads_sp ON quads (subject, predicate, rev)",
    "CREATE INDEX IF NOT EXISTS quads_po ON quads (predicate, object, rev)",
)


class ArtStore:
    """Bytes by ``sha256:<hex>``, write-once, in a folder."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path(self, h: str) -> Path:
        return self.root / "sha256" / h[:2] / h

    def put(self, data: bytes) -> str:
        h = sha256(data)
        p = self.path(h)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp-" + str(threading.get_ident()))
            tmp.write_bytes(data)
            tmp.replace(p)
        return h

    def get(self, h: str) -> bytes:
        p = self.path(h)
        if not p.exists():
            raise FileNotFoundError(f"art store {self.root}: no bytes for {h}")
        return p.read_bytes()


def index_name(pred: str) -> str:
    """The ``db/index`` partial index's name (hashed over the quote-doubled predicate, as since 5.0)."""
    return f"pred_{hash_text(pred.replace(chr(39), chr(39) * 2), 16)}"


class Writer(ABC):
    """The open write transaction, holding the write lock: read the top, append rows under the next revision."""

    @abstractmethod
    def next_rev(self) -> int:
        """``MAX(rev) + 1``, read under the lock."""

    @abstractmethod
    def insert(self, rev: int, rows: Sequence[Tuple[str, str, str, bool]]) -> None:
        """Append ``(subject, predicate, object, added)`` rows as ``rev``, ``ord`` their place."""

    @abstractmethod
    def create_index(self, pred: str) -> None:
        """``db/index``: a partial index on ``(object, subject, rev)`` where ``predicate = pred``."""


class Store(ABC):
    """What the ledger reads and writes; ``art`` is the art store (a folder, whatever the backend)."""

    art: ArtStore

    @abstractmethod
    def top(self) -> int:
        """The highest revision, 0 for an empty ledger."""

    @abstractmethod
    def rows(self, upto: int, *, subject: Optional[str] = None, predicate: Optional[str] = None,
             obj: Optional[str] = None, prefix: Optional[str] = None, after: int = 0) -> List[Row]:
        """Every row with ``after < rev <= upto`` matching the columns given, in (rev, ord) order."""

    @abstractmethod
    def subjects(self, upto: int, *, predicate: Optional[str] = None, obj: Optional[str] = None,
                 prefix: Optional[str] = None, subject: Optional[str] = None, after: int = 0) -> List[str]:
        """The distinct subjects with an add row matching the columns given, in ``after < rev <= upto``,
        ordered by their first such row."""

    @abstractmethod
    def has_predicate(self, predicate: str, upto: int) -> bool:
        """Any row with this predicate at or below ``upto``."""

    @abstractmethod
    def writer(self, timeout: float, *, locked: bool) -> ContextManager[Writer]:
        """A write transaction holding the write lock; commits on a clean exit, rolls back otherwise.

        ``locked``: the caller asked for ``lock=``, so failing to take the lock within ``timeout``
        is ``LockTimeout``; otherwise it is ``LedgerError``.
        """

    @abstractmethod
    def reading_through(self, w: Writer) -> ContextManager[None]:
        """Reads in this thread go through ``w`` (the open write transaction) for the block."""

    @abstractmethod
    def index_names(self) -> List[str]:
        """The names of the indexes on the quad table."""

    @abstractmethod
    def close(self) -> None:
        """Close every reader connection this store opened, in every thread; a later read reopens one."""


class SqliteStore(Store):
    """One SQLite file. Reads on a per-thread connection; each write on a connection of its own."""

    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self.path = self.folder / "ledger.db"
        self.art = ArtStore(self.folder / "art")
        self._local = threading.local()
        self._readers: List[sqlite3.Connection] = []
        self._readers_lock = threading.Lock()
        self._gen = 0
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = self._connect(30.0)
            conn.execute("PRAGMA journal_mode=WAL")
            for stmt in SCHEMA:
                conn.execute(stmt)
            conn.close()
        except sqlite3.Error as e:
            raise LedgerError(f"sqlite ledger {self.path}: cannot open ({e})") from e

    def _connect(self, timeout: float) -> sqlite3.Connection:
        return sqlite3.connect(str(self.path), isolation_level=None, timeout=timeout, check_same_thread=False)

    @contextmanager
    def reading_through(self, w: Writer) -> Iterator[None]:
        """Reads in this thread go through ``w`` (an open write transaction) for the block."""
        assert isinstance(w, SqliteWriter)
        old = getattr(self._local, "override", None)
        self._local.override = w.conn
        try:
            yield
        finally:
            self._local.override = old

    def _reader(self) -> sqlite3.Connection:
        over = getattr(self._local, "override", None)
        if over is not None:
            return over
        conn = getattr(self._local, "conn", None)
        if conn is None or getattr(self._local, "gen", None) != self._gen:
            conn = self._local.conn = self._connect(30.0)
            with self._readers_lock:
                self._local.gen = self._gen
                self._readers.append(conn)
        return conn

    def close(self) -> None:
        with self._readers_lock:
            conns, self._readers = self._readers, []
            self._gen += 1
        for conn in conns:
            conn.close()

    def read(self, sql: str, params: Sequence[Any] = ()) -> List[Tuple[Any, ...]]:
        try:
            return list(self._reader().execute(sql, tuple(params)).fetchall())
        except sqlite3.Error as e:
            raise LedgerError(f"sqlite ledger {self.path} refused a read: {e}") from e

    def top(self) -> int:
        return int(self.read("SELECT COALESCE(MAX(rev), 0) FROM quads")[0][0])

    def rows(self, upto: int, *, subject: Optional[str] = None, predicate: Optional[str] = None,
             obj: Optional[str] = None, prefix: Optional[str] = None, after: int = 0) -> List[Row]:
        """Every row with ``after < rev <= upto`` matching the columns given, in (rev, ord) order."""
        sql = "SELECT rev, ord, subject, predicate, object, added FROM quads WHERE rev <= ? AND rev > ?"
        params: List[Any] = [upto, after]
        for col, val in (("subject", subject), ("predicate", predicate), ("object", obj)):
            if val is not None:
                sql += f" AND {col} = ?"
                params.append(val)
        if prefix is not None:
            sql += " AND subject >= ? AND subject < ?"
            params.extend([prefix, prefix + "\U0010ffff"])
        sql += " ORDER BY rev, ord"
        return [(int(r[0]), int(r[1]), r[2], r[3], r[4], bool(r[5])) for r in self.read(sql, params)]

    def subjects(self, upto: int, *, predicate: Optional[str] = None, obj: Optional[str] = None,
                 prefix: Optional[str] = None, subject: Optional[str] = None, after: int = 0) -> List[str]:
        """The distinct subjects with an add row matching the columns given, in ``after < rev <= upto``."""
        sql = "SELECT subject, MIN(rev * 1000000 + ord) FROM quads WHERE rev <= ? AND rev > ? AND added = 1"
        params: List[Any] = [upto, after]
        for col, val in (("predicate", predicate), ("object", obj), ("subject", subject)):
            if val is not None:
                sql += f" AND {col} = ?"
                params.append(val)
        if prefix is not None:
            sql += " AND subject >= ? AND subject < ?"
            params.extend([prefix, prefix + "\U0010ffff"])
        sql += " GROUP BY subject ORDER BY 2"
        return [r[0] for r in self.read(sql, params)]

    def has_predicate(self, predicate: str, upto: int) -> bool:
        return bool(self.read("SELECT 1 FROM quads WHERE predicate = ? AND rev <= ? LIMIT 1", (predicate, upto)))

    def index_names(self) -> List[str]:
        return [r[0] for r in self.read("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'quads'")]

    @contextmanager
    def writer(self, timeout: float, *, locked: bool) -> Iterator["SqliteWriter"]:
        """A write transaction holding SQLite's write lock (``BEGIN IMMEDIATE``)."""
        conn = self._connect(timeout)
        try:
            try:
                conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as e:
                if locked:
                    raise LockTimeout(f"ledger {self.path}: write lock not had within {timeout}s ({e})") from e
                raise LedgerError(f"ledger {self.path}: write lock not had ({e})") from e
            w = SqliteWriter(conn)
            try:
                yield w
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()


class SqliteWriter(Writer):
    """The open SQLite write transaction."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def next_rev(self) -> int:
        return int(self.conn.execute("SELECT COALESCE(MAX(rev), 0) + 1 FROM quads").fetchone()[0])

    def insert(self, rev: int, rows: Sequence[Tuple[str, str, str, bool]]) -> None:
        self.conn.executemany(
            "INSERT INTO quads (rev, ord, subject, predicate, object, added) VALUES (?, ?, ?, ?, ?, ?)",
            [(rev, i, s, p, o, int(a)) for i, (s, p, o, a) in enumerate(rows)])

    def create_index(self, pred: str) -> None:
        lit = pred.replace("'", "''")
        self.conn.execute(f'CREATE INDEX IF NOT EXISTS "{index_name(pred)}" ON quads '
                          f"(object, subject, rev) WHERE predicate = '{lit}'")
