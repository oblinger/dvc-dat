"""Backends by URI scheme (SVP 1599): where a ledger's records and its bytes live.

A ledger carries two URIs. **triples** is its location, the records: a folder (the SQLite
ledger there, also written ``sqlite://<folder>``) or ``postgresql://…``. **values** is where its
bytes live beyond the machine that wrote them, one row in the ledger itself, ``(db, db/values,
<uri>)``, set like ``db/timezone``; with no row the bytes live in the cache folder alone.

The URI's scheme picks the backend, from two registries:

    from dvc_dat.ledger import register_values
    register_values("gs", lambda uri: MyBucket(uri))

``register_values(scheme, factory)``: ``factory(uri)`` returns a ``Values``, three methods by
sha256 hex, ``has(hash)``, ``pull(hash, path)`` (the bytes to the new file ``path``) and
``push(path, hash)`` (the file at ``path``, write-once). One per URI per process. Built in:
``file`` (``file:///abs/folder``, the bytes at ``<folder>/sha256/<2>/<hash>``, ``blob_path``).
dvc-dat carries no cloud code; a consumer registers each scheme it can reach.

``register_triples(scheme, factory)``: ``factory(uri, create, overlay)`` returns a ``Store``.
Built in: ``sqlite``, ``postgresql`` and ``postgres`` (one backend whatever the host).

A scheme nothing registered is ``LedgerError`` listing what is. Before that error, the
``backends:`` of the nearest ``.datconfig.yaml`` at or above the working directory (in a sandbox
worker, the caller's) are imported, a list of dotted module names, each registering as it is
imported, once per config per process: so a fresh process has them.

**The cache.** A value's bytes are read from a folder on this machine and, on a miss, pulled into
it from the values URI at the ledger's top, checked against the hash. A SQLite ledger's cache is
``<folder>/art``. Any other ledger's is ``<root>/<ledger name>/art``, ``<root>`` being
``DAT_CACHE``, else ``cache:`` in the nearest ``.datconfig.yaml`` (relative to it).

**Writing.** A transaction sealing values on a ledger with a ``db/values`` row pushes every part
and each encoding before it takes the write lock (an orphan of a commit that then fails is
harmless: write-once, by hash); a failed push fails the commit, nothing written.
"""

from __future__ import annotations

import importlib
import os
import re
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Set, Tuple, runtime_checkable
from urllib.parse import unquote, urlsplit

from .errors import LedgerError

#: The row naming where a ledger's bytes live: ``(db, db/values, <uri>)``.
VALUES = "db/values"
#: The environment variable naming the cache root for ledgers that are not a folder.
CACHE_ENV = "DAT_CACHE"
#: The config key of the same, and the one listing modules to import.
CACHE_KEY = "cache"
BACKENDS_KEY = "backends"

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*$")
_URI = re.compile(r"^([a-z][a-z0-9+.-]*)://")
SQLITE = "sqlite"


@runtime_checkable
class Values(Protocol):
    """A ledger's bytes by sha256 hex at one values URI, behind the cache folder.

    Every method may raise: a failed ``push`` fails the commit (nothing written), a failed ``pull`` fails the read
    (``LedgerError``). A pulled file is checked against its hash by the ledger, not the backend.
    """

    def has(self, hash: str) -> bool:
        """The backend holds the bytes of ``hash``."""

    def pull(self, hash: str, path: Path) -> None:
        """Put the bytes of ``hash`` at the new file ``path``."""

    def push(self, path: Path, hash: str) -> None:
        """Store the file at ``path`` (its bytes hash to ``hash``) as ``hash``, write-once."""


ValuesFactory = Callable[[str], Values]
TriplesFactory = Callable[[str, bool, Optional[Path]], Any]

_VALUES: Dict[str, ValuesFactory] = {}
_TRIPLES: Dict[str, TriplesFactory] = {}
_MADE: Dict[str, Values] = {}
_IMPORTED: Set[str] = set()
_LOCK = threading.Lock()


def scheme_of(uri: Any) -> Optional[str]:
    """The scheme of ``uri`` when it is written ``<scheme>://…``, else ``None`` (a folder)."""
    m = _URI.match(uri) if isinstance(uri, str) else None
    return m.group(1) if m else None


def is_uri(target: Any) -> bool:
    """A string naming a ledger by a URI some triples backend opens: any ``<scheme>://…`` but ``sqlite://``, which
    is a folder."""
    return scheme_of(target) not in (None, SQLITE)


def sqlite_folder(uri: str) -> str:
    """The folder ``sqlite://<folder>`` names."""
    return uri[len(SQLITE) + 3:]


def blob_path(hash: str) -> str:
    """Where the bytes of ``hash`` sit under a values URI, by convention: ``sha256/<2>/<hash>``."""
    return f"sha256/{hash[:2]}/{hash}"


def _check(scheme: Any, factory: Any, what: str) -> None:
    if not (isinstance(scheme, str) and _SCHEME.match(scheme)):
        raise ValueError(f"a URI scheme is [a-z][a-z0-9+.-]*, such as 'gs', not {scheme!r}")
    if not callable(factory):
        raise TypeError(f"a {what} backend is registered as a factory (a callable), not {factory!r}")


def register_values(scheme: str, factory: ValuesFactory) -> None:
    """Make ``factory`` (values URI -> ``Values``) the backend of every ``<scheme>://…`` values URI.

    ``scheme`` is ``[a-z][a-z0-9+.-]*`` (``ValueError``), ``factory`` a callable (``TypeError``); registering a scheme
    again replaces it. Process-local: a module listed under ``backends:`` in ``.datconfig.yaml`` is imported when a
    scheme is asked that nothing registered, so a fresh process has it.
    """
    _check(scheme, factory, "values")
    with _LOCK:
        _VALUES[scheme] = factory
        for uri in [u for u in _MADE if scheme_of(u) == scheme]:
            del _MADE[uri]


def register_triples(scheme: str, factory: TriplesFactory) -> None:
    """Make ``factory`` (``(uri, create, overlay)`` -> ``Store``) the backend of every ledger at ``<scheme>://…``.

    ``create``: make the ledger when absent; ``overlay``: a read-only handle, what its reads place going there.
    Checked and replaced as ``register_values``.
    """
    _check(scheme, factory, "triples")
    with _LOCK:
        _TRIPLES[scheme] = factory


def _config() -> Optional[Path]:
    """The config whose ``backends:`` and ``cache:`` this process reads: in a sandbox worker the caller's, else the
    nearest at or above the working directory."""
    from . import named
    from .ledger import _walk_up

    if named._worker is not None and named._worker[0] is not None:
        return Path(named._worker[0]["cfg"])
    return _walk_up(Path.cwd().resolve())[0]


def _import_configured() -> None:
    """Import the ``backends:`` modules of the config, once per config per process."""
    from .ledger import _values
    from .sandbox import unguarded

    with unguarded():                               # the ledger's own machinery, also inside a sandboxed body
        cfg = _config()
        if cfg is None or str(cfg) in _IMPORTED:
            return
        _IMPORTED.add(str(cfg))
        modules = _values(cfg).get(BACKENDS_KEY) or []
        if not (isinstance(modules, list) and all(isinstance(m, str) and m.strip() for m in modules)):
            raise LedgerError(f"{cfg}: '{BACKENDS_KEY}:' is a list of module names to import, got {modules!r}")
        for module in modules:
            try:
                importlib.import_module(module)
            except Exception as e:
                raise LedgerError(f"{cfg}: {BACKENDS_KEY}: cannot import {module!r} ({type(e).__name__}: {e})") from e


def _factory(kind: str, table: Dict[str, Any], uri: str) -> Any:
    scheme = scheme_of(uri)
    if scheme is None:
        raise LedgerError(f"a {kind} URI is <scheme>://…, not {uri!r}")
    if scheme not in table:
        _import_configured()
    factory = table.get(scheme)
    if factory is None:
        raise LedgerError(f"no {kind} backend for scheme {scheme!r} ({redact(uri)}): registered: "
                          f"{', '.join(sorted(table)) or 'none'}; call register_{kind}({scheme!r}, factory), or "
                          f"list its module under {BACKENDS_KEY}: in .datconfig.yaml")
    return factory


def redact(uri: str) -> str:
    """``uri`` without a password, for messages."""
    return re.sub(r"(://[^:/@?]*):[^@/?]*@", r"\1:***@", uri)


def check_values(uri: Any, what: str = VALUES) -> str:
    """``uri`` as a values URI some backend is registered for; ``ValueError`` when it is not a URI, ``LedgerError``
    naming the registered schemes when nothing serves it."""
    if scheme_of(uri) is None:
        raise ValueError(f"{what}: a values URI is <scheme>://…, such as file:///shared/art, not {uri!r}")
    _factory("values", _VALUES, uri)
    return str(uri)


def values_at(uri: str) -> Values:
    """The ``Values`` at ``uri``, made once per process."""
    with _LOCK:
        made = _MADE.get(uri)
    if made is not None:
        return made
    made = _factory("values", _VALUES, uri)(uri)
    with _LOCK:
        return _MADE.setdefault(uri, made)


def open_triples(uri: str, create: bool, overlay: Optional[Path]) -> Any:
    """The ``Store`` of the ledger at ``uri``, by its scheme's backend."""
    return _factory("triples", _TRIPLES, uri)(uri, create, overlay)


def registered() -> Tuple[List[str], List[str]]:
    """``(triples schemes, values schemes)`` registered in this process."""
    return sorted(_TRIPLES), sorted(_VALUES)


# -- the cache ------------------------------------------------------------------------------- #

def cache_root() -> Optional[Path]:
    """The cache root of this process: ``DAT_CACHE``, else ``cache:`` of the config (relative to it), else ``None``."""
    from .ledger import _values

    env = os.environ.get(CACHE_ENV)
    if env:
        return Path(env).expanduser().resolve()
    cfg = _config()
    got = _values(cfg).get(CACHE_KEY) if cfg is not None else None
    if got is None:
        return None
    if not (isinstance(got, str) and got.strip()):
        raise LedgerError(f"{cfg}: '{CACHE_KEY}:' is a folder, got {got!r}")
    p = Path(got).expanduser()
    assert cfg is not None
    return (p if p.is_absolute() else cfg.parent / p).resolve()


def cache_folder(name: str, shown: str) -> Path:
    """The cache folder of the ledger ``name`` that is not a folder itself: ``<root>/<name>/art``."""
    root = cache_root()
    if root is None:
        raise LedgerError(f"ledger {shown}: no cache folder for its values' bytes; set {CACHE_ENV}=<folder>, or "
                          f"'{CACHE_KEY}: <folder>' in .datconfig.yaml (the ledger's cache is <folder>/{name}/art)")
    if not name:
        raise LedgerError(f"ledger {shown}: it has no name to keep its cache under")
    return root / name / "art"


# -- file ------------------------------------------------------------------------------------ #

class FileValues:
    """The ``file`` backend: ``file:///abs/folder``, the bytes at ``<folder>/sha256/<2>/<hash>``."""

    def __init__(self, uri: str) -> None:
        parts = urlsplit(uri)
        path = unquote(parts.path)
        if parts.netloc not in ("", "localhost") or not path.startswith("/"):
            raise LedgerError(f"{uri}: a file values URI is file:///<absolute folder> (the row is shared, so a "
                              "relative folder names nothing)")
        self.root = Path(path)

    def _path(self, hash: str) -> Path:
        return self.root / blob_path(hash)

    def has(self, hash: str) -> bool:
        return self._path(hash).exists()

    def pull(self, hash: str, path: Path) -> None:
        from .store import place

        place(self._path(hash), Path(path), hash, link=False)

    def push(self, path: Path, hash: str) -> None:
        from .store import place

        place(Path(path), self._path(hash), hash, link=False)


# -- pull, push ------------------------------------------------------------------------------ #

def puller(ledger: Any) -> Callable[[str, Path], None]:
    """A cache miss on ``ledger``: pull ``h`` from the values URI at its top to ``dest``, checked against the hash
    (``LedgerError`` when it fails); nothing with no ``db/values`` row, and the miss stays a miss."""
    from .sandbox import unguarded
    from .store import file_sha

    def pull(h: str, dest: Path) -> None:
        with unguarded():                           # the ledger's own machinery, as a dat's materialisation is
            uri = ledger.values
            if uri is None:
                return
            backend = values_at(uri)
            tmp = dest.with_name(f"{dest.name}.fetch-{os.getpid()}-{threading.get_ident()}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                try:
                    backend.pull(h, tmp)
                except Exception as e:
                    raise LedgerError(f"values {redact(uri)}: cannot pull {h[:12]}… ({e})") from e
                got = file_sha(tmp)
                if got != h:
                    raise LedgerError(f"values {redact(uri)}: {h[:12]}… arrived hashing to {got[:12]}…")
                os.replace(tmp, dest)
            finally:
                tmp.unlink(missing_ok=True)
    return pull


def _sqlite(uri: str, create: bool, overlay: Optional[Path]) -> Any:
    from .store import SqliteStore

    return SqliteStore(Path(sqlite_folder(uri)), overlay)


def _postgres(uri: str, create: bool, overlay: Optional[Path]) -> Any:
    from .pgstore import PostgresStore

    return PostgresStore(uri, create=create, overlay=overlay)


register_triples(SQLITE, _sqlite)
register_triples("postgresql", _postgres)
register_triples("postgres", _postgres)
register_values("file", FileValues)

__all__ = ["Values", "register_values", "register_triples", "blob_path", "VALUES", "CACHE_ENV"]
