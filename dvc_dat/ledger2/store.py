"""The SQLite backend: one quad table, and an art store of bytes by hash beside it.

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
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, List, Optional, Sequence, Tuple

from .codec import sha256
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
        hexd = h.split(":", 1)[1]
        return self.root / "sha256" / hexd[:2] / hexd

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


class Store:
    """One SQLite file. Reads on a per-thread connection; each write on a connection of its own."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.art = ArtStore(self.path.with_suffix(".art"))
        self._local = threading.local()
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

    def _reader(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._local.conn = self._connect(30.0)
        return conn

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

    @contextmanager
    def writer(self, timeout: float, *, locked: bool) -> Iterator["Writer"]:
        """A write transaction holding SQLite's write lock; commits on a clean exit, rolls back otherwise.

        ``locked``: the caller asked for ``lock=``, so failing to take the lock within ``timeout``
        is ``LockTimeout``; otherwise it is ``LedgerError``.
        """
        conn = self._connect(timeout)
        try:
            try:
                conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as e:
                if locked:
                    raise LockTimeout(f"ledger {self.path}: write lock not had within {timeout}s ({e})") from e
                raise LedgerError(f"ledger {self.path}: write lock not had ({e})") from e
            w = Writer(conn)
            try:
                yield w
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()


class Writer:
    """The open write transaction: read the top, append rows under the next revision."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def next_rev(self) -> int:
        return int(self.conn.execute("SELECT COALESCE(MAX(rev), 0) + 1 FROM quads").fetchone()[0])

    def rows(self, subject: str) -> List[Row]:
        cur = self.conn.execute(
            "SELECT rev, ord, subject, predicate, object, added FROM quads WHERE subject = ? ORDER BY rev, ord",
            (subject,))
        return [(int(r[0]), int(r[1]), r[2], r[3], r[4], bool(r[5])) for r in cur.fetchall()]

    def insert(self, rev: int, rows: Sequence[Tuple[str, str, str, bool]]) -> None:
        self.conn.executemany(
            "INSERT INTO quads (rev, ord, subject, predicate, object, added) VALUES (?, ?, ?, ?, ?, ?)",
            [(rev, i, s, p, o, int(a)) for i, (s, p, o, a) in enumerate(rows)])
