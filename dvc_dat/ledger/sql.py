"""The SQL backend: a shared base over one table shape, and SQLite on it.

``events(id, ord, subject, predicate, object, added)``: ``id`` is the rev,
``ord`` the event's place within its transaction (so a transaction that
removes and re-adds one triple folds to the re-add), ``object`` the typed
string. Beside it ``whereabouts(hash, region)``, status not history. The
state at a rev is the newest event per ``(subject, predicate, object)`` with
``id <= rev``, kept when ``added``: a window query, never a pull of the log.
Revs come from one counter under one lock: ``MAX(id) + 1`` under SQLite's
write lock. Another database subclasses :class:`SqlLedger`, supplying
``_read``, ``_writing`` and ``_next_rev`` (and, if it must, ``_fold_sql`` and
``_obj_clause``), and is named in a profile by its dotted class name.
"""

from __future__ import annotations

import sqlite3
import threading
from abc import abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple, Type

from .core import Ledger, Op, Row
from .errors import LedgerError
from .ref import Rev
from .shelf import LocalShelf, Shelf

Exec = Callable[[str, Sequence[Any]], List[Tuple[Any, ...]]]

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS events ("
    " id BIGINT NOT NULL, ord INTEGER NOT NULL, subject TEXT NOT NULL, predicate TEXT NOT NULL,"
    " object TEXT NOT NULL, added BOOLEAN NOT NULL, PRIMARY KEY (id, ord))",
    "CREATE TABLE IF NOT EXISTS whereabouts (hash TEXT NOT NULL, region TEXT NOT NULL, PRIMARY KEY (hash, region))",
)


def _where(subject: Optional[str], predicate: Optional[str], obj: Optional[str],
           obj_clause: str = "object = ?") -> Tuple[str, List[Any]]:
    parts: List[str] = []
    params: List[Any] = []
    for clause, value in (("subject = ?", subject), ("predicate = ?", predicate), (obj_clause, obj)):
        if value is not None:
            parts.append(clause)
            params.extend([value] * clause.count("?"))
    return "".join(" AND " + p for p in parts), params


class SqlLedger(Ledger):
    """The shared statements; a dialect supplies the connection, the lock and the rev counter."""

    backend = "sql"

    # -- dialect ----------------------------------------------------------

    @abstractmethod
    def _read(self, sql: str, params: Sequence[Any]) -> List[Tuple[Any, ...]]:
        """Run a read outside any write transaction."""

    @abstractmethod
    @contextmanager
    def _writing(self) -> Iterator[Exec]:
        """One write transaction holding the ledger's lock; commits on a clean exit, rolls back otherwise."""

    @abstractmethod
    def _next_rev(self, ex: Exec) -> Rev:
        """The next rev, inside the write transaction and under the lock."""

    _errors: Tuple[Type[BaseException], ...] = ()

    def _fold_sql(self, where: str) -> str:
        return (
            "SELECT id, subject, predicate, object, added FROM ("
            " SELECT id, ord, subject, predicate, object, added, ROW_NUMBER() OVER ("
            "  PARTITION BY subject, predicate, object ORDER BY id DESC, ord DESC) AS rn"
            f" FROM events WHERE id <= ?{where}) AS f"
            " WHERE rn = 1 AND added ORDER BY id, ord")

    def _obj_clause(self) -> str:
        return "object = ?"

    # -- primitives -------------------------------------------------------

    def _guard(self, what: str, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except self._errors as e:
            raise LedgerError(f"{self.backend} ledger refused {what}: {e}") from e

    def rev(self) -> Rev:
        rows = self._guard("reading the rev", lambda: self._read("SELECT COALESCE(MAX(id), 0) FROM events", ()))
        return int(rows[0][0])

    def _has_rev(self, rev: Rev) -> bool:
        return bool(self._guard(f"reading rev {rev}",
                                lambda: self._read("SELECT 1 FROM events WHERE id = ? LIMIT 1", (rev,))))

    def _events(self, subject: Optional[str], predicate: Optional[str], obj: Optional[str],
                tx: Optional[Rev], upto: Rev) -> List[Row]:
        where, params = _where(subject, predicate, obj, self._obj_clause())
        if tx is not None:
            where += " AND id = ?"
            params.append(tx)
        sql = f"SELECT id, subject, predicate, object, added FROM events WHERE id <= ?{where} ORDER BY id, ord"
        rows = self._guard("reading the log", lambda: self._read(sql, [upto, *params]))
        return [self._row(r) for r in rows]

    def _fold_with(self, ex: Exec, subject: Optional[str], predicate: Optional[str], obj: Optional[str],
                   at: Rev) -> List[Row]:
        where, params = _where(subject, predicate, obj, self._obj_clause())
        return [self._row(r) for r in ex(self._fold_sql(where), [at, *params])]

    def _fold(self, subject: Optional[str], predicate: Optional[str], obj: Optional[str], at: Rev) -> List[Row]:
        return self._guard("reading the state", lambda: self._fold_with(self._read, subject, predicate, obj, at))

    @staticmethod
    def _row(r: Tuple[Any, ...]) -> Row:
        return (int(r[0]), str(r[1]), str(r[2]), str(r[3]), bool(r[4]))

    def _commit(self, ops: Sequence[Op], by: str, blobs: Dict[str, bytes]) -> Rev:
        for data in blobs.values():  # content-addressed and write-once: a rolled-back blob is harmless
            self._shelf.put(data, "json")
        rev: Optional[Rev] = None
        rows: List[Tuple[str, str, str, bool]] = []
        try:
            with self._writing() as ex:
                rev = self._next_rev(ex)
                rows = self._resolve(ex, ops)
                rows.append((f"tx/{rev}", "by", "str:" + by, True))
                rows.append((f"tx/{rev}", "date", "str:" + self._today().isoformat(), True))
                for i, (s, p, o, added) in enumerate(rows):
                    ex("INSERT INTO events (id, ord, subject, predicate, object, added) VALUES (?, ?, ?, ?, ?, ?)",
                       (rev, i, s, p, o, added))
        except self._errors as e:
            first = rows[0][:3] if rows else ("tx/?", "by", by)
            raise LedgerError(f"{self.backend} ledger refused rev {rev} writing {first!r}: {e}") from e
        assert rev is not None
        return rev

    def _resolve(self, ex: Exec, ops: Sequence[Op]) -> List[Tuple[str, str, str, bool]]:
        """The rows ``ops`` land: ``assign`` removes every object held, counting this transaction's earlier ops."""
        held: Dict[Tuple[str, str], List[str]] = {}
        out: List[Tuple[str, str, str, bool]] = []
        for op in ops:
            key = (op.subject, op.predicate)
            if key not in held:
                held[key] = [r[3] for r in self._fold_with(ex, op.subject, op.predicate, None, 2**62)]
            now = held[key]
            if op.kind == "assign":
                out.extend((op.subject, op.predicate, o, False) for o in now)
                out.append((op.subject, op.predicate, op.object, True))
                held[key] = [op.object]
            elif op.kind == "add":
                out.append((op.subject, op.predicate, op.object, True))
                held[key] = [o for o in now if o != op.object] + [op.object]
            else:
                out.append((op.subject, op.predicate, op.object, False))
                held[key] = [o for o in now if o != op.object]
        return out

    def _set_whereabouts(self, hash: str, region: str) -> None:
        def run() -> None:
            with self._writing() as ex:
                ex("INSERT INTO whereabouts (hash, region) VALUES (?, ?) ON CONFLICT DO NOTHING", (hash, region))
        self._guard(f"writing whereabouts ({hash[:19]}, {region})", run)

    def _whereabouts(self, hash: str) -> List[str]:
        rows = self._guard("reading whereabouts", lambda: self._read(
            "SELECT region FROM whereabouts WHERE hash = ? ORDER BY region", (hash,)))
        return [str(r[0]) for r in rows]


class SqliteLedger(SqlLedger):
    """A single SQLite file, its artifacts on a shelf beside it (``ledger.db`` and ``ledger.art/`` in a folder)."""

    backend = "sqlite"
    _errors = (sqlite3.Error,)

    def __init__(self, path: Path, shelf: Optional[Shelf] = None) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._shelf = shelf if shelf is not None else LocalShelf(self.path.with_suffix(".art"))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.path), isolation_level=None, timeout=30,
                                         check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            for stmt in (*SCHEMA,
                         "CREATE INDEX IF NOT EXISTS events_spo ON events (subject, predicate, object, id)",
                         "CREATE INDEX IF NOT EXISTS events_po ON events (predicate, object, id)"):
                self._conn.execute(stmt)
        except sqlite3.Error as e:
            raise LedgerError(f"sqlite ledger {self.path}: cannot open ({e})") from e

    @classmethod
    def from_profile(cls, profile: Dict[str, Any], folder: Path, shelf: Optional[Shelf]) -> "SqliteLedger":
        """Profile keys: ``path`` (the database file, relative to the profile's folder), ``art``, ``region``."""
        if "path" not in profile:
            raise ValueError(f"{folder}: a sqlite ledger profile names its database under 'path'")
        p = Path(str(profile["path"])).expanduser()
        return cls(p if p.is_absolute() else folder / p, shelf=shelf)

    def close(self) -> None:
        self._conn.close()

    def _exec(self, sql: str, params: Sequence[Any]) -> List[Tuple[Any, ...]]:
        return list(self._conn.execute(sql, tuple(params)).fetchall())

    def _read(self, sql: str, params: Sequence[Any]) -> List[Tuple[Any, ...]]:
        with self._lock:
            return self._exec(sql, params)

    @contextmanager
    def _writing(self) -> Iterator[Exec]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._exec
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def _next_rev(self, ex: Exec) -> Rev:
        return int(ex("SELECT COALESCE(MAX(id), 0) + 1 FROM events", ())[0][0])
