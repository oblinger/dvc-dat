"""The store interface, the SQLite backend behind it, and the art store of bytes by hash.

``Store`` names what the ledger reads and writes: ``top``, ``rows``,
``subjects``, ``has_predicate``, ``writer`` (the write lock and one open
transaction), ``reading_through`` (reads routed through that transaction) and
``index_names``; ``Writer`` is the open transaction (``next_rev``, ``insert``,
``create_index`` for ``db/index``). The art store stays a folder whatever the
backend. ``SqliteStore`` is below; ``PostgresStore`` is in ``pgstore``.

A SQLite ledger is a folder: ``ledger.db`` and ``art/`` (bytes by hash,
and ``art/dats/`` where a ``Dat`` is materialised) inside it. A large
value's parts enter the art store by ``put_path`` (a copy-on-write clone where
the filesystem can, else a streamed copy; never a hardlink) and leave by
``get_to``; no part's bytes are ever held in memory whole.

``quads(rev, ord, subject, predicate, object, added)``: ``rev`` the revision,
``ord`` the row's place within its transaction, ``object`` the tagged string
(``codec``), ``added`` 0 for a ``remove`` row. Nothing is ever updated or
deleted. Two SQL indexes, ``(subject, predicate, rev)`` and
``(predicate, object, rev)``, are the index table a where clause reads; a
``(db/pred/<p>, db/index, true)`` row adds a partial index on ``<p>``.
Revisions come from ``MAX(rev) + 1`` under SQLite's write lock.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import threading
import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any, Callable, ContextManager, Dict, Iterator, List, Optional, Sequence, Tuple, Union

from .codec import HashSink, hash_text

try:
    import fcntl
except ImportError:             # not a POSIX platform: fsync alone
    fcntl = None  # type: ignore[assignment]
from .errors import LedgerError, LockTimeout

#: ``(rev, ord, subject, predicate, object, added)``
Row = Tuple[int, int, str, str, str, bool]

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS quads (rev INTEGER NOT NULL, ord INTEGER NOT NULL, subject TEXT NOT NULL,"
    " predicate TEXT NOT NULL, object TEXT NOT NULL, added INTEGER NOT NULL, PRIMARY KEY (rev, ord))",
    "CREATE INDEX IF NOT EXISTS quads_sp ON quads (subject, predicate, rev)",
    "CREATE INDEX IF NOT EXISTS quads_po ON quads (predicate, object, rev)",
)


#: Where a part's bytes come from: a file, or a zero-arg opener returning a binary stream.
Source = Union[Path, Callable[[], IO[bytes]]]
#: A value's further bytes: ``(sha256 hex, source)``.
Part = Tuple[str, Source]

#: The block a part is hashed and copied in.
BLOCK = 1 << 20


def file_sha(path: Path) -> str:
    """The hex sha256 of a file, read in 1 MiB blocks."""
    d = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(BLOCK), b""):
            d.update(block)
    return d.hexdigest()


def flush(fd: int) -> None:
    """Make the bytes behind ``fd`` durable: ``F_FULLFSYNC`` on macOS, where ``fsync`` leaves them in the
    drive's cache (a removable drive pulled after an ``fsync`` can lose them), else ``fsync``. A filesystem
    that refuses ``F_FULLFSYNC`` (``ENOTSUP``, some network mounts) gets the ``fsync`` it does support."""
    full = getattr(fcntl, "F_FULLFSYNC", None) if fcntl is not None else None
    if full is not None:
        try:
            fcntl.fcntl(fd, full)
            return
        except OSError:
            pass
    os.fsync(fd)


def flush_path(path: Path) -> None:
    """:func:`flush` a file or a folder by path; a folder's flush makes a rename inside it durable."""
    fd = os.open(path, os.O_RDONLY)
    try:
        flush(fd)
    finally:
        os.close(fd)


class Changed(ValueError):
    """Bytes placed under the name ``h`` hash to ``got``: the source changed since it was hashed."""

    def __init__(self, h: str, got: str) -> None:
        super().__init__(f"a part named {h[:12]}… hashes to {got[:12]}…: its source changed since it was hashed")
        self.h, self.got = h, got


def _copy(src: IO[bytes], dest: Path, h: str) -> None:
    """Stream ``src`` into ``dest`` block by block; ``Changed`` when the bytes do not hash to ``h``."""
    d = hashlib.sha256()
    with open(dest, "wb") as out:
        for block in iter(lambda: src.read(BLOCK), b""):
            d.update(block)
            out.write(block)
    if d.hexdigest() != h:
        dest.unlink(missing_ok=True)
        raise Changed(h, d.hexdigest())


def clone(src: Any, dest: Path) -> bool:
    """Make ``dest`` a copy-on-write clone of the file ``src`` (macOS APFS ``clonefile``, Linux ``FICLONE``
    reflink); ``True`` when cloned, ``False`` when the filesystem or platform cannot (nothing written).

    A clone shares the source's blocks until either is written, so it costs no disk, and an in-place
    write to the source never reaches it -- unlike a hardlink."""
    import sys

    if sys.platform == "darwin":
        import ctypes

        try:
            libc = ctypes.CDLL("/usr/lib/libSystem.dylib", use_errno=True)
            fn = libc.clonefile
        except (OSError, AttributeError):
            return False
        fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        fn.restype = ctypes.c_int
        return fn(os.fsencode(os.fspath(src)), os.fsencode(os.fspath(dest)), 0) == 0
    if sys.platform.startswith("linux"):
        import fcntl

        FICLONE = 0x40049409
        try:
            with open(src, "rb") as s, open(dest, "xb") as d:
                try:
                    fcntl.ioctl(d.fileno(), FICLONE, s.fileno())
                    return True
                except OSError:
                    pass
        except OSError:
            return False
        Path(dest).unlink(missing_ok=True)
    return False


#: How many parts ``place`` cloned in this process (the tests read it).
CLONES = [0]


def place(source: Source, dest: Path, h: str, *, durable: bool = False, checked: bool = False) -> bool:
    """Put the bytes of ``source`` (sha256 ``h``) at ``dest``, write-once; ``True`` when written here.

    A ``Path`` is cloned copy-on-write where the filesystem can (``clone``: no disk), else copied in
    blocks; an opener is always copied; either way the bytes are checked against ``h``. Never a hardlink:
    the placed file and its source are two inodes, so an in-place write to either (a rolling
    ``_result_.yaml``, an editor saving a page) cannot reach the other, and a blob keeps its name.
    A ``Path``'s mode and mtime are carried over, as stat'ed before its bytes are read: a write landing after
    the check leaves the source newer than the placed file, never the reverse. The bytes land at a temp name
    and are renamed into place, so a reader never sees a partial file. With ``durable`` the temp file is
    flushed (:func:`flush`) before the rename and the folder after it. ``Changed`` when the bytes do not hash
    to ``h``. ``checked``: the source's bytes were hashed to ``h`` a moment ago by the caller, so a clone is not
    hashed again (a copy is hashed as it is written, at no extra read).
    """
    if dest.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f"{dest.name}.tmp-{uuid.uuid4().hex[:8]}")
    try:
        if isinstance(source, (str, os.PathLike)):
            st = os.stat(source)
            if clone(source, tmp):
                CLONES[0] += 1
                got = h if checked else file_sha(tmp)
                if got != h:
                    tmp.unlink(missing_ok=True)
                    raise Changed(h, got)
            else:
                with open(source, "rb") as f:
                    _copy(f, tmp, h)
            os.chmod(tmp, stat.S_IMODE(st.st_mode))
            os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))
        else:
            with source() as f:
                _copy(f, tmp, h)
        if durable:
            flush_path(tmp)
        os.replace(tmp, dest)
        if durable:
            flush_path(dest.parent)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return True


class FileSink(HashSink):
    """A sink backed by a temp file in ``folder``: the bytes stream to disk as they are hashed,
    never held whole. At close, with ``dest`` (hash -> path), the file is renamed to ``dest(hash)``, write-once
    (``created`` says whether it landed here; with ``expect``, a hash other than ``expect`` lands nowhere);
    without ``dest`` it stays at ``path``, staged, until the owner places or ``discard``s it. Used as a
    context manager, an exception in the block discards the file. With ``durable`` the file is flushed
    (:func:`flush`) before it is closed, and its folder after the rename."""

    def __init__(self, folder: Path, dest: Optional[Callable[[str], Path]] = None, *,
                 expect: Optional[str] = None, durable: bool = False) -> None:
        super().__init__()
        folder.mkdir(parents=True, exist_ok=True)
        self.path: Optional[Path] = folder / f".sink-{uuid.uuid4().hex}"
        self._f: Optional[IO[bytes]] = open(self.path, "wb")
        self._dest = dest
        self._expect = expect
        self._durable = durable
        self.created = False

    def _out(self, view: memoryview) -> None:
        assert self._f is not None
        self._f.write(view)

    def close(self) -> None:
        if self.closed:
            return
        f, self._f = self._f, None
        try:
            if f is not None:
                if self._durable:
                    f.flush()
                    flush(f.fileno())
                f.close()
        finally:
            super().close()
        if self._dest is None or self.path is None:
            return
        tmp, self.path = self.path, None
        dest = self._dest(self.hash)
        if (self._expect is not None and self.hash != self._expect) or dest.exists():
            tmp.unlink(missing_ok=True)
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, dest)
        if self._durable:
            flush_path(dest.parent)
        self.path, self.created = dest, True

    def discard(self) -> None:
        """Close and drop a staged (or unfinished) file; a placed one is not touched."""
        if not self.closed:
            self._dest = None
            self.close()
        if self.path is not None and not self.created:
            self.path.unlink(missing_ok=True)
            self.path = None

    def __exit__(self, et: Any, ev: Any, tb: Any) -> None:
        if et is not None:
            self.discard()
        else:
            self.close()


class ArtStore:
    """Bytes by ``sha256:<hex>``, write-once, in a folder; on a miss inside ``fetching``, fetched into it."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._scope = threading.local()
        self._fresh: set = set()        # blobs put_path just placed and hashed; the next get_to of each skips a re-hash

    @contextmanager
    def fetching(self, fetch: Optional[Callable[[str, Path], None]]) -> Iterator[None]:
        """For the block, in this thread, a miss in ``open``/``get_to`` calls ``fetch(h, path)`` first, which puts
        the bytes of ``h`` at ``path`` (the ledger's values URI); ``None`` fetches nothing."""
        old = getattr(self._scope, "fetch", None)
        self._scope.fetch = fetch
        try:
            yield
        finally:
            self._scope.fetch = old

    def _have(self, h: str) -> Path:
        p = self.path(h)
        if not p.exists():
            fetch = getattr(self._scope, "fetch", None)
            if fetch is not None:
                fetch(h, p)
            if not p.exists():
                raise FileNotFoundError(f"art store {self.root}: no bytes for {h}")
        return p

    def path(self, h: str) -> Path:
        return self.root / "sha256" / h[:2] / h

    @property
    def dats(self) -> Path:
        """The data folder, where a ``Dat``'s folder is rebuilt."""
        return self.root / "dats"

    def exists(self, h: str) -> bool:
        return self.path(h).exists()

    def sink(self, *, staged: bool = False) -> FileSink:
        """A write stream for one encoding: hashed as written, renamed at close to its place by hash,
        write-once (``created``), so a reader never sees a partial file. ``staged``: left at a temp name in
        the store's folder (``path``) for the owner to place with ``put_path`` or ``discard``."""
        return FileSink(self.root / "tmp", None if staged else self.path)

    def put_path(self, source: Source, h: str) -> bool:
        """Store a part by its hash ``h`` without reading it into memory (:func:`place`: a clone where the
        filesystem can, else a streamed copy, never a link); ``True`` when written here. A blob placed here was
        hashed as placed, so the next ``get_to`` of it (a seal's view, in the same call) does not hash it again."""
        placed = place(source, self.path(h), h)
        if placed:
            self._fresh.add(h)
        return placed

    def open(self, h: str) -> IO[bytes]:
        """The bytes of ``h`` as a read stream (a real, seekable file); inside ``fetching`` a miss fetches first."""
        return open(self._have(h), "rb")

    def put_staged(self, path: Path, h: str) -> bool:
        """Move a temp file this store wrote itself (``sink(staged=True)``, hashed as written to ``h``) into place
        by rename: no copy, and no other name is left on it. ``True`` when moved; ``False`` when ``h`` is held
        already, the temp file left for its owner to discard."""
        dest = self.path(h)
        if dest.exists():
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(path, dest)
        return True

    def get_to(self, h: str, dest: Path) -> None:
        """Put the bytes of ``h`` at ``dest`` (a clone or a copy, never a link: :func:`place`); ``ValueError`` naming
        the blob when its bytes no longer hash to ``h``."""
        checked = h in self._fresh and self.path(h).exists()    # a blob dropped since, then fetched, is hashed
        self._fresh.discard(h)
        blob = self._have(h)
        try:
            place(blob, Path(dest), h, checked=checked)
        except Changed as e:
            raise ValueError(f"art store {self.root}: the blob {blob} is corrupt: its bytes hash to {e.got}, not to "
                             "its name") from None

    def _scanned(self) -> List[Path]:
        """The folders whose ``sha256/`` blobs :meth:`mismatched` reads."""
        return [self.root]

    def _writable(self) -> List[Path]:
        """The folders whose ``sha256/`` blobs :meth:`detach` may replace."""
        return [self.root]

    @staticmethod
    def _blobs(roots: List[Path]) -> List[Path]:
        """Every blob file under each root's ``sha256/`` (temp files left out), in name order."""
        return sorted(p for r in roots for p in (r / "sha256").glob("*/*") if p.is_file() and len(p.name) == 64)

    def mismatched(self) -> List[Tuple[str, str]]:
        """``(name, sha256 of its bytes)`` for every blob under ``sha256/`` whose bytes no longer hash to its name,
        in name order; reads every blob, writes nothing. Covers this art store (a read-only handle's
        overlay too), not ``Kept``'s ``blobs/`` nor a dat manager's ``art/``."""
        out = []
        for p in self._blobs(self._scanned()):
            got = file_sha(p)
            if got != p.name:
                out.append((p.name, got))
        return out

    def detach(self, *, dry_run: bool = False) -> int:
        """Give every blob that shares its inode with another file (``st_nlink > 1``: a hardlink placed by a release up
        to 3.2.0) an inode of its own, so an in-place write to the other name can no longer reach it; the count of such
        blobs. Each is replaced by a clone or copy of itself (mode and mtime kept, checked against the bytes it had,
        renamed over it), so its bytes never change, a corrupt one included; the other names keep the old inode.
        ``dry_run``: only count. A read-only handle detaches its overlay's blobs only."""
        n = 0
        for p in self._blobs(self._writable()):
            if p.stat().st_nlink <= 1:
                continue
            n += 1
            if dry_run:
                continue
            tmp = p.with_name(f".detach-{uuid.uuid4().hex[:8]}")
            try:
                if not place(p, tmp, file_sha(p)):
                    raise FileExistsError(tmp)
                os.replace(tmp, p)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
        return n

    def _stamp_path(self, dest: Path) -> Path:
        return self.dats.parent / "stamps" / f"{hashlib.sha256(os.fsencode(os.path.abspath(dest))).hexdigest()[:32]}.json"

    def stamp(self, dest: Path, files: Dict[str, str]) -> None:
        """Record, for the folder ``dest`` holding ``files`` (``{relpath: sha256}``), each file's (inode, size, mtime,
        ctime) beside the store (``stamps/``, outside every folder and hash), for :meth:`stamped`."""
        rows = {}
        for rel, h in sorted(files.items()):
            st = os.stat(Path(dest) / rel)
            rows[rel] = [h, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]
        out = self._stamp_path(dest)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f"{out.name}.tmp-{uuid.uuid4().hex[:8]}")
        tmp.write_text(json.dumps({"path": os.path.abspath(dest), "files": rows}, sort_keys=True))
        os.replace(tmp, out)

    def stamps(self, dest: Path) -> Dict[str, List[Any]]:
        """The rows :meth:`stamp` last recorded for ``dest``, ``{relpath: [sha256, inode, size, mtime, ctime]}``;
        ``{}`` with no stamp."""
        try:
            files = json.loads(self._stamp_path(dest).read_text())["files"]
        except (OSError, ValueError, KeyError, TypeError):
            return {}
        return files if isinstance(files, dict) else {}


def stamp_holds(row: Any, path: Path, h: str) -> bool:
    """Does the file ``path`` stand as its :meth:`ArtStore.stamp` row recorded it holding ``h``: the same inode, size,
    mtime and ctime? A ctime cannot be set back from userspace, so a write or a replacement since, its mtime restored
    or not, reads ``False``; so does a missing row."""
    if not isinstance(row, list) or len(row) != 5 or row[0] != h:
        return False
    try:
        st = os.stat(path)
    except OSError:
        return False
    return row[1:] == [st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns]


class ReadOnlyArt(ArtStore):
    """A ledger's art store as a read-only handle sees it: bytes come from ``root``; what a read
    has to place (a ``Dat``'s folder, bytes fetched from the value's store) lands in ``overlay``, the reader's own,
    so that nothing lands on the ledger."""

    def __init__(self, root: Path, overlay: Path) -> None:
        super().__init__(root)
        self.overlay = Path(overlay)

    def path(self, h: str) -> Path:
        p = super().path(h)
        return p if p.exists() else self.overlay / "sha256" / h[:2] / h

    @property
    def dats(self) -> Path:
        return self.overlay / "dats"

    def _scanned(self) -> List[Path]:
        return [self.root, self.overlay]

    def _writable(self) -> List[Path]:
        return [self.overlay]


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
    """What the ledger reads and writes; ``art`` is the art store (a folder, whatever the backend: the cache of the
    ledger's bytes on this machine); ``name`` the ledger's name: a SQLite ledger's folder name, a Postgres ledger's
    database."""

    art: ArtStore
    name: str
    read_only: bool = False

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
    """One SQLite file. Reads on a per-thread connection; each write on a connection of its own. Given ``overlay``,
    read-only: every connection ``mode=ro``, nothing made or changed on open, the art a ``ReadOnlyArt``."""

    def __init__(self, folder: Path, overlay: Optional[Path] = None) -> None:
        self.folder = Path(folder)
        self.path = self.folder / "ledger.db"
        self.name = self.folder.name
        self.read_only = overlay is not None
        self.art = ReadOnlyArt(self.folder / "art", overlay) if overlay is not None else ArtStore(self.folder / "art")
        self._local = threading.local()
        self._readers: List[sqlite3.Connection] = []
        self._readers_lock = threading.Lock()
        self._gen = 0
        if self.read_only:
            return
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
        if self.read_only:
            return sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True, isolation_level=None, timeout=timeout,
                                   check_same_thread=False)
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
        sql = "SELECT subject, MIN(rev * 4294967296 + ord) FROM quads WHERE rev <= ? AND rev > ? AND added = 1"
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
