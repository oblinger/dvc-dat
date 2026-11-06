"""Value stores (SVP 1511): where a ledger's bytes live beyond the machine that wrote them.

A ledger's art store is a folder on the machine that opened it. A **value store** is a remote place
the bytes also go, named by one row, ``(db, db/store, <name>)``: ``local`` (the default, no row) means
whatever store this process resolves ``local`` to; any other name is a store some code in the process
registered. dvc-dat carries no cloud code: a consumer registers each store it can reach,

    from dvc_dat.ledger import register_store
    register_store("gcp", lambda ledger: MyGcsRemote(bucket="gs://data", ledger=ledger))

and the factory is called once per process with a ledger's name, returning a ``Remote``: three
methods by sha256 hex, ``exists(h)``, ``put_path(path, h)`` (upload the file at ``path``, whose bytes
hash to ``h``) and ``get_to(h, dest)`` (download to the new file ``dest``). The conventional layout on
the remote is ``ledgers/<ledger>/sha256/<2>/<hash>`` (``blob_name``); ledger names are never reused,
so the path is unique.

**Writing.** A transaction sealing values on a ledger whose store resolves to a remote uploads every
part and the encoding of each newly sealed value before it takes the write lock (an orphan blob of a
commit that then fails is harmless: write-once, by hash), and writes ``(<value subject>, db/store,
<name>)`` beside the seal, naming where the bytes went. The local folder keeps a copy, as before.

**Reading.** A value's bytes are read from the local folder; on a miss, the value's own ``db/store``
row names the store they are fetched from (into the folder, which is so a cache), checked against the
hash. A value with no row (written before 1511, or to the folder alone) is read from the folder as
before. A process that reads a value stored on a name it never registered fails on the miss with a
``LedgerError`` naming the store.

**``local``** is resolved once per process, first to last: ``DAT_STORE_LOCAL`` (a store name, or
``folder``); else the cloud the machine runs in, by a 0.3 s probe of the instance metadata endpoint
(``gcp`` on Google Compute Engine, ``azure`` on Azure), when this process registered that name; else
``stores: {local: <name>}`` in the nearest ``.datconfig.yaml``; else ``folder``. ``folder`` is the built-in store meaning the ledger's own art folder alone:
nothing uploaded, no per-value row, exactly the behaviour before 1511. With no store registered,
``local`` is ``folder`` and nothing is probed.
"""

from __future__ import annotations

import os
import re
import socket
import threading
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Protocol, Tuple, runtime_checkable

from .errors import LedgerError

#: The row naming a ledger's store, ``(db, db/store, <name>)``, and each stored value's.
PREDICATE = "db/store"
#: The default when a ledger has no row: what this process resolves ``local`` to.
LOCAL = "local"
#: The built-in store: the ledger's own art folder, nothing uploaded.
FOLDER = "folder"
#: The environment variable naming ``local`` for this process.
ENV = "DAT_STORE_LOCAL"

_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


@runtime_checkable
class Remote(Protocol):
    """Bytes by sha256 hex on a remote place, for one ledger.

    Three methods: ``exists(h) -> bool``; ``put_path(path: Path, h)``, upload the file at ``path`` (its bytes hash to
    ``h``), write-once; ``get_to(h, dest: Path)``, download to the new file ``dest``.

    Every method may raise: a failed upload fails the commit (nothing written), a failed download fails the read
    (``LedgerError``).

    The conventional layout is ``<bucket>/ledgers/<ledger>/sha256/<2>/<hash>``
    (``dvc_dat.ledger.remote.blob_name(ledger, h)``). A fetched file is checked against its hash by the ledger, not
    the remote.
    """

    def exists(self, h: str) -> bool:
        """The remote holds the bytes of ``h``."""

    def put_path(self, path: Path, h: str) -> None:
        """Upload the file at ``path`` (its bytes hash to ``h``) as ``h``, write-once."""

    def get_to(self, h: str, dest: Path) -> None:
        """Download the bytes of ``h`` to the new file ``dest``."""


Factory = Callable[[str], Remote]

STORES: Dict[str, Factory] = {}
_REMOTES: Dict[Tuple[str, str], Remote] = {}
_LOCK = threading.Lock()
_PROBED: Dict[str, Optional[str]] = {}


def check_name(name: Any, what: str = "a store name") -> str:
    if not (isinstance(name, str) and _NAME.match(name)):
        raise ValueError(f"{what} is [a-z][a-z0-9_]*, such as 'gcp', not {name!r}")
    return name


def register_store(name: str, factory: Factory) -> None:
    """Make ``factory`` (ledger name -> ``Remote``) the store named ``name`` ([Value stores][value-stores]).

    For a ``(db, db/store, name)`` row or ``local`` to select. ``name`` is ``[a-z][a-z0-9_]*``; ``local`` and
    ``folder`` are refused (built in, ``ValueError``), a non-callable ``factory`` is ``TypeError``; registering a name
    again replaces it.

    Process-local, like ``register_policy``: every process that writes or reads values on the store registers it
    first, else ``LedgerError`` naming the store.

    dvc-dat ships no cloud code; the consumer brings it (sv-pipe registers ``gcp`` and ``azure``).
    """
    check_name(name)
    if name in (LOCAL, FOLDER):
        raise ValueError(f"{name!r} is a built-in store name; register yours under another name")
    if not callable(factory):
        raise TypeError(f"a store is a function from a ledger name to a Remote, not {factory!r}")
    with _LOCK:
        STORES[name] = factory
        for key in [k for k in _REMOTES if k[0] == name]:
            del _REMOTES[key]


def blob_name(ledger: str, h: str) -> str:
    """The conventional path of ``h``'s bytes on a remote: ``ledgers/<ledger>/sha256/<2>/<hash>``."""
    return f"ledgers/{ledger}/sha256/{h[:2]}/{h}"


def remote(name: str, ledger: str) -> Remote:
    """The ``Remote`` of store ``name`` for ``ledger``, made once per process."""
    if not ledger:
        raise LedgerError(f"store {name!r}: the ledger has no name to store its values under")
    with _LOCK:
        r = _REMOTES.get((name, ledger))
        if r is not None:
            return r
        factory = STORES.get(name)
    if factory is None:
        raise LedgerError(f"store {name!r} is named on ledger {ledger!r}, but no code in this process registered "
                          f"it (registered: {', '.join(sorted(STORES)) or 'none'}; register_store)")
    r = factory(ledger)
    with _LOCK:
        return _REMOTES.setdefault((name, ledger), r)


# -- local ----------------------------------------------------------------------------------- #

#: The instance metadata endpoint, link-local on both clouds (an IP, so no DNS lookup can outlast the timeout).
METADATA = "169.254.169.254"
PROBE_TIMEOUT = 0.3


def _get(url: str, headers: Dict[str, str]) -> Optional[Any]:
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as resp:      # noqa: S310 (a fixed http URL)
            return resp
    except Exception:
        return None


def probe() -> Optional[str]:
    """``gcp`` or ``azure`` when this machine is a VM of that cloud, by its metadata endpoint; else ``None``.
    Once per process."""
    if "cloud" in _PROBED:
        return _PROBED["cloud"]
    found: Optional[str] = None
    try:
        with socket.create_connection((METADATA, 80), timeout=PROBE_TIMEOUT):
            reachable = True
    except OSError:
        reachable = False
    if reachable:
        g = _get(f"http://{METADATA}/computeMetadata/v1/", {"Metadata-Flavor": "Google"})
        if g is not None and g.headers.get("Metadata-Flavor") == "Google":
            found = "gcp"
        elif _get(f"http://{METADATA}/metadata/instance?api-version=2021-02-01", {"Metadata": "true"}) is not None:
            found = "azure"
    _PROBED["cloud"] = found
    return found


def _configured() -> Optional[str]:
    """``stores: {local: <name>}`` of the nearest ``.datconfig.yaml``, else ``None``."""
    from .ledger import CONFIG, _values

    for folder in (Path.cwd(), *Path.cwd().parents):
        cfg = folder / CONFIG
        if cfg.is_file():
            stores = _values(cfg).get("stores")
            if stores is None:
                return None
            if not isinstance(stores, dict):
                raise LedgerError(f"{cfg}: 'stores:' is a mapping, such as {{local: gcp}}, got {stores!r}")
            got = stores.get(LOCAL)
            return None if got is None else check_name(got, f"{cfg}: stores: local")
    return None


def _known(name: str, why: str) -> str:
    if name != FOLDER and name not in STORES:
        raise LedgerError(f"{why} names store {name!r}, which no code in this process registered (registered: "
                          f"{', '.join(sorted(STORES)) or 'none'}; register_store, or {FOLDER})")
    return name


def resolve_local() -> str:
    """What ``local`` means in this process: ``DAT_STORE_LOCAL``, the cloud probed (when registered), the config's
    ``stores: {local: ...}``, else ``folder``."""
    env = os.environ.get(ENV)
    if env:
        return _known(check_name(env, ENV), ENV)
    if not STORES:
        return FOLDER
    cloud = probe()
    if cloud is not None and cloud in STORES:
        return cloud
    got = _configured()
    if got is not None:
        return _known(got, "stores: local")
    return FOLDER


def resolve(name: str) -> str:
    """A ledger's store name made concrete: ``local`` resolved, any other name as written."""
    return resolve_local() if name == LOCAL else name


def store_name(rev: Any) -> str:
    """The ledger's store as of ``rev``: its ``(db, db/store)`` row, else ``local``."""
    from .codec import show

    held = rev._held("db", PREDICATE)
    return show(held[0].obj) if held else LOCAL


def fetcher(name: str, ledger: str) -> Callable[[str, Path], None]:
    """A fetch of ``h`` from store ``name`` to ``dest``, checked against the hash; ``LedgerError`` when it fails."""
    from .sandbox import unguarded
    from .store import file_sha

    def fetch(h: str, dest: Path) -> None:
        r = remote(name, ledger)
        tmp = dest.with_name(f"{dest.name}.fetch-{os.getpid()}-{threading.get_ident()}")
        with unguarded():                   # the ledger's own machinery, as a dat's materialisation is
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                try:
                    r.get_to(h, tmp)
                except Exception as e:
                    raise LedgerError(f"store {name!r} (ledger {ledger!r}): cannot fetch {h[:12]}… ({e})") from e
                got = file_sha(tmp)
                if got != h:
                    raise LedgerError(f"store {name!r} (ledger {ledger!r}): {h[:12]}… arrived hashing to "
                                      f"{got[:12]}…")
                os.replace(tmp, dest)
            finally:
                tmp.unlink(missing_ok=True)
    return fetch


__all__ = ["Remote", "register_store", "blob_name", "resolve_local", "PREDICATE", "LOCAL", "FOLDER", "ENV"]
