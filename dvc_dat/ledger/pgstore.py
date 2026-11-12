"""The Postgres backend: the same quad table behind the same ``Store`` interface.

A Postgres ledger is a URI, ``postgresql://user:pw@host:port/db``: the quads
live in the database (in the first schema of the connection's ``search_path``;
``options=-csearch_path%3D<schema>`` puts one ledger per schema). One backend
serves every host; a cloud's login stays outside (a proxy, a token in the
URI). The bytes are cached in ``<cache root>/<database>/art`` on this machine
(``DAT_CACHE``, else ``cache:`` in ``.datconfig.yaml``) and live at the
ledger's values URI (``backends``, SVP 1599).

Same rows, same order, same fold as ``SqliteStore``. What differs underneath:
the write lock is ``SELECT … FOR UPDATE`` on the one row of ``ledger_lock``
(bounded by ``lock_timeout``); prefix scans compare bytes with the
``text_pattern_ops`` operators ``~>=~`` / ``~<~`` (a ``C``-order range, as
SQLite's), which the ``text_pattern_ops`` indexes serve whatever the
database's collation; ``db/index`` is a partial index as in SQLite. Statements
are never server-prepared, so each is planned with its values (a partial index
or a prefix range is usable only then). Postgres text cannot hold NUL: a row
carrying one is refused (``LedgerError``); a read asking for one finds nothing.

Needs psycopg 3: ``pip install 'dvc_dat[pg]'``.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, List, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from .errors import LedgerError, LockTimeout
from .store import ArtStore, ReadOnlyArt, Row, Store, Writer, index_name

SCHEMES = ("postgresql://", "postgres://")

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS quads (rev BIGINT NOT NULL, ord INTEGER NOT NULL, subject TEXT NOT NULL,"
    " predicate TEXT NOT NULL, object TEXT NOT NULL, added BOOLEAN NOT NULL, PRIMARY KEY (rev, ord))",
    "CREATE INDEX IF NOT EXISTS quads_sp ON quads (subject text_pattern_ops, predicate, rev)",
    "CREATE INDEX IF NOT EXISTS quads_po ON quads (predicate, object text_pattern_ops, rev)",
    "CREATE TABLE IF NOT EXISTS ledger_lock (id INTEGER PRIMARY KEY CHECK (id = 1))",
    "INSERT INTO ledger_lock (id) VALUES (1) ON CONFLICT DO NOTHING",
)

#: ``pg_advisory_xact_lock`` key serialising concurrent ``create=True`` (CREATE … IF NOT EXISTS races).
_CREATE_KEY = 0x6476635F646174


def _psycopg() -> Any:
    try:
        import psycopg
    except ImportError as e:
        raise LedgerError("a Postgres ledger needs psycopg 3: pip install 'dvc_dat[pg]'") from e
    return psycopg


def split_dsn(dsn: str) -> Tuple[str, str]:
    """``(dsn, redacted dsn)``; a ``?art=`` parameter (removed, SVP 1599) is ``LedgerError`` naming what replaces it."""
    parts = urlsplit(dsn)
    netloc = parts.netloc
    if "@" in netloc and ":" in netloc.split("@", 1)[0]:
        user = netloc.split("@", 1)[0].split(":", 1)[0]
        redacted_netloc = f"{user}:***@{netloc.split('@', 1)[1]}"
    else:
        redacted_netloc = netloc
    redacted = urlunsplit((parts.scheme, redacted_netloc, parts.path, parts.query, ""))
    if any(k == "art" for k, _v in parse_qsl(parts.query, keep_blank_values=True)):
        raise LedgerError(f"Postgres ledger {redacted}: '?art=' was removed (SVP 1599). The bytes' cache on this "
                          "machine is <root>/<database>/art, <root> being DAT_CACHE or 'cache:' in .datconfig.yaml; "
                          "where they live beyond it is the ledger's row (db, db/values, <uri>)")
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, "")), redacted


def _has_nul(*vals: Optional[str]) -> bool:
    return any(v is not None and "\x00" in v for v in vals)


class PostgresStore(Store):
    """One Postgres schema. Reads on a per-thread autocommit connection; each write on a connection of its own.
    Given ``overlay``, read-only: every connection's session refuses writes, the art a ``ReadOnlyArt``."""

    def __init__(self, dsn: str, *, create: bool, overlay: Optional[Path] = None) -> None:
        from .backends import cache_folder

        self.dsn, self.redacted = split_dsn(dsn)
        self._conninfo = self.dsn
        self.read_only = overlay is not None
        parts = urlsplit(self.dsn)
        self.name = parts.path.lstrip("/") or (parts.username or "")      # libpq's default database: the user
        art = cache_folder(self.name, self.redacted)
        self.art = ReadOnlyArt(art, overlay) if overlay is not None else ArtStore(art)
        self._pg = _psycopg()
        self._local = threading.local()
        self._readers: List[Any] = []
        self._readers_lock = threading.Lock()
        self._gen = 0
        try:
            conn = self._connect(30.0, autocommit=True)
        except self._pg.Error as e:
            raise LedgerError(f"Postgres ledger {self.redacted}: cannot connect ({e})") from e
        try:
            if conn.execute("SELECT to_regclass('quads') IS NOT NULL AND to_regclass('ledger_lock') IS NOT NULL"
                            ).fetchone()[0]:
                return
            if not create:
                raise LedgerError(f"no ledger at {self.redacted}")
            with conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(%s)", (_CREATE_KEY,))
                for stmt in SCHEMA:
                    conn.execute(stmt)
        except self._pg.Error as e:
            raise LedgerError(f"Postgres ledger {self.redacted}: cannot open ({e})") from e
        finally:
            conn.close()

    def _connect(self, timeout: float, *, autocommit: bool) -> Any:
        conn = self._pg.connect(self._conninfo, autocommit=autocommit, prepare_threshold=None,
                                connect_timeout=max(1, int(timeout)))
        if self.read_only:
            conn.execute("SET default_transaction_read_only = on")
            if not autocommit:
                conn.commit()                       # the setting binds the transactions after this one
        return conn

    @contextmanager
    def reading_through(self, w: Writer) -> Iterator[None]:
        assert isinstance(w, PostgresWriter)
        old = getattr(self._local, "override", None)
        self._local.override = w.conn
        try:
            yield
        finally:
            self._local.override = old

    def _reader(self) -> Any:
        over = getattr(self._local, "override", None)
        if over is not None:
            return over
        conn = getattr(self._local, "conn", None)
        if conn is None or conn.closed or conn.broken or getattr(self._local, "gen", None) != self._gen:
            conn = self._local.conn = self._connect(30.0, autocommit=True)
            with self._readers_lock:
                self._local.gen = self._gen
                self._readers = [c for c in self._readers if not c.closed]
                self._readers.append(conn)
        return conn

    def close(self) -> None:
        with self._readers_lock:
            conns, self._readers = self._readers, []
            self._gen += 1
        for conn in conns:
            conn.close()

    def read(self, sql: str, params: Sequence[Any] = ()) -> List[Tuple[Any, ...]]:
        conn = self._reader()
        try:
            return list(conn.execute(sql, tuple(params)).fetchall())
        except self._pg.Error as e:
            raise LedgerError(f"Postgres ledger {self.redacted} refused a read: {e}") from e
        except BaseException:
            # interrupted mid-statement (a ``lock=`` alarm): the connection still awaits its result
            # and refuses the next one ("another command is already in progress"); drop it, and the
            # next read opens a fresh one. A writer's connection is its transaction's to close.
            if conn is not getattr(self._local, "override", None):
                conn.close()
            raise

    def top(self) -> int:
        return int(self.read("SELECT COALESCE(MAX(rev), 0) FROM quads")[0][0])

    @staticmethod
    def _where(params: List[Any], cols: Sequence[Tuple[str, Optional[str]]], prefix: Optional[str]) -> str:
        sql = ""
        for col, val in cols:
            if val is not None:
                sql += f" AND {col} = %s"
                params.append(val)
        if prefix is not None:
            sql += " AND subject ~>=~ %s AND subject ~<~ %s"
            params.extend([prefix, prefix + "\U0010ffff"])
        return sql

    def rows(self, upto: int, *, subject: Optional[str] = None, predicate: Optional[str] = None,
             obj: Optional[str] = None, prefix: Optional[str] = None, after: int = 0) -> List[Row]:
        if _has_nul(subject, predicate, obj, prefix):
            return []
        params: List[Any] = [upto, after]
        sql = ("SELECT rev, ord, subject, predicate, object, added FROM quads WHERE rev <= %s AND rev > %s"
               + self._where(params, (("subject", subject), ("predicate", predicate), ("object", obj)), prefix)
               + " ORDER BY rev, ord")
        return [(int(r[0]), int(r[1]), r[2], r[3], r[4], bool(r[5])) for r in self.read(sql, params)]

    def subjects(self, upto: int, *, predicate: Optional[str] = None, obj: Optional[str] = None,
                 prefix: Optional[str] = None, subject: Optional[str] = None, after: int = 0) -> List[str]:
        if _has_nul(subject, predicate, obj, prefix):
            return []
        params: List[Any] = [upto, after]
        sql = ("SELECT subject, MIN(rev * 4294967296 + ord) FROM quads WHERE rev <= %s AND rev > %s AND added"
               + self._where(params, (("predicate", predicate), ("object", obj), ("subject", subject)), prefix)
               + " GROUP BY subject ORDER BY 2")
        return [r[0] for r in self.read(sql, params)]

    def has_predicate(self, predicate: str, upto: int) -> bool:
        if _has_nul(predicate):
            return False
        return bool(self.read("SELECT 1 FROM quads WHERE predicate = %s AND rev <= %s LIMIT 1", (predicate, upto)))

    def index_names(self) -> List[str]:
        return [r[0] for r in self.read("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()"
                                        " AND tablename = 'quads'")]

    @contextmanager
    def writer(self, timeout: float, *, locked: bool) -> Iterator["PostgresWriter"]:
        """A transaction holding the ``ledger_lock`` row (``FOR UPDATE``, bounded by ``lock_timeout``).

        READ COMMITTED: each statement sees every commit before it, so ``MAX(rev)`` read after the
        lock is had is the top the previous writer left.
        """
        pg = self._pg
        try:
            conn = self._connect(timeout, autocommit=False)
        except pg.Error as e:
            raise LedgerError(f"Postgres ledger {self.redacted}: cannot connect ({e})") from e
        try:
            try:
                conn.execute("SELECT set_config('lock_timeout', %s, true)", (f"{max(1, int(timeout * 1000))}ms",))
                conn.execute("SELECT id FROM ledger_lock WHERE id = 1 FOR UPDATE")
            except pg.errors.LockNotAvailable as e:
                _rollback(conn)
                if locked:
                    raise LockTimeout(f"ledger {self.redacted}: write lock not had within {timeout}s ({e})") from e
                raise LedgerError(f"ledger {self.redacted}: write lock not had ({e})") from e
            except pg.Error as e:
                _rollback(conn)
                raise LedgerError(f"ledger {self.redacted}: write lock not had ({e})") from e
            conn.execute("SELECT set_config('lock_timeout', '0', true)")
            w = PostgresWriter(conn)
            try:
                yield w
            except BaseException:
                _rollback(conn)
                raise
            try:
                conn.commit()
            except pg.Error as e:
                raise LedgerError(f"ledger {self.redacted}: commit refused ({e})") from e
        finally:
            conn.close()


def _rollback(conn: Any) -> None:
    """Roll back; a connection interrupted mid-statement (a ``lock=`` alarm) cannot, and closing it does."""
    try:
        conn.rollback()
    except Exception:
        conn.close()


class PostgresWriter(Writer):
    """The open Postgres write transaction."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def next_rev(self) -> int:
        return int(self.conn.execute("SELECT COALESCE(MAX(rev), 0) + 1 FROM quads").fetchone()[0])

    def insert(self, rev: int, rows: Sequence[Tuple[str, str, str, bool]]) -> None:
        for s, p, o, _ in rows:
            if _has_nul(s, p, o):
                raise LedgerError(f"Postgres text cannot hold NUL (\\x00): row {s!r} {p!r} {o!r}")
        with self.conn.cursor().copy("COPY quads (rev, ord, subject, predicate, object, added) FROM STDIN") as cp:
            for i, (s, p, o, a) in enumerate(rows):
                cp.write_row((rev, i, s, p, o, bool(a)))

    def create_index(self, pred: str) -> None:
        lit = pred.replace("'", "''")
        self.conn.execute(f'CREATE INDEX IF NOT EXISTS "{index_name(pred)}" ON quads '
                          f"(object text_pattern_ops, subject, rev) WHERE predicate = '{lit}'")
