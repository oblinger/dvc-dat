"""``Code``: the code a function is loaded from, at a version, as a ``Value`` (DAT 1037).

One object whether the function is installed in the ledger's own Python environment or mounted from a
checkout (``code.sandboxed``). Only the snapshot has identity; a function is a name looked up inside it
(``fn.name`` + ``fn.code``). The identity is the bytes: ``encode()`` is the canonical
``{"modules": relpath -> sha256, "mounts": <hash of the db/mount rows, or None>}``, ``hash`` its sha256 and
``subject`` ``db/code/<hash 16>``, the 16 hex the memo key carried as ``db/fn/<name>/<hash 16>`` before.
Beside it, fixed at load and not hashed, the description: ``mounts`` (``prefix -> {repo, root}``; empty for
installed code), ``commit`` (the checkout's at load), ``lock`` (the blob id of that checkout's
``uv.lock``), ``sandboxed``, ``version`` and ``package`` (the dotted root whose declared version it is, or
``None``). The version is a name over the hash, never the identity, and the commit is a result's
``code/<repo>`` dependency item, so neither moves the hash. Its name is
``<unit>@<version>``: the unit is the mount prefix for mounted code (``plane``, ``algs.ocr``) and the
function's top-level package for installed code (``geometry``). Immutable: accessors only.

The version is read as a module attribute after import, never parsed from source, and a declared
version counts only from a clean checkout (DAT 1043): when the checkout holding the code has modified
tracked files, the version is ``<commit 8>+dirty`` whatever ``__version__`` says (mounted: the last
commit that touched the loaded files, else HEAD; installed: the checkout's HEAD). Clean, mounted: the root
package's ``__version__``; else the last commit that touched the loaded files (8 hex, ``+dirty`` when one
differs from HEAD); else ``#`` + 8 hex of the hash. Clean or outside any checkout (a wheel), installed:
``__version__`` on the top-level package; else the version of the distribution providing it; else the
short commit of the checkout holding it; else ``#`` + 8 hex of the hash. A ``Code`` is computed at ``load_fn`` and attached to the
``Fn``; a run's memo entry writes its identity as the ``db/code/<hash 16>`` item (``db/modules``,
``db/mounts``); the description is not written to the ledger yet.
"""

from __future__ import annotations

import functools
import importlib
import importlib.metadata as md
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .codec import canonical, sha256
from .env import Env, _git, code_at
from .value import Value

if TYPE_CHECKING:
    from .store import ArtStore

#: Every short hash in a version: 8 hex.
SHORT = 8


def identity(modules: Mapping[str, str], mounts: Optional[str]) -> str:
    """The canonical identity a ``Code`` hashes: the module checksums and the mounts hash."""
    return canonical({"modules": dict(sorted(modules.items())), "mounts": mounts})


def identity_hash(modules: Mapping[str, str], mounts: Optional[str]) -> str:
    """The hex sha256 of ``identity``: ``Code.hash`` before the ``Code`` exists (for the ``#hash8`` version)."""
    return sha256(identity(modules, mounts).encode())


class Code(Value):
    """The code a function is loaded from, at a version: ``<Code plane@2.7.1>``."""

    def __init__(self, manifest: Mapping[str, Any], *, unit: str) -> None:
        self.__dict__["_manifest"] = {
            "modules": dict(sorted(manifest["modules"].items())), "mounts_hash": manifest["mounts_hash"],
            "mounts": {k: dict(v) for k, v in manifest["mounts"].items()},
            "commit": manifest["commit"], "lock": manifest["lock"], "sandboxed": bool(manifest["sandboxed"]),
            "version": str(manifest["version"]), "package": manifest.get("package")}
        self.__dict__["_unit"] = unit
        self.__dict__["_hash"] = sha256(self.encode())

    @property
    def name(self) -> Optional[str]:  # type: ignore[override]
        """``<unit>@<version>``: ``plane@2.7.1``, ``geometry@5.3.9``."""
        return f"{self._unit}@{self.version}"

    @property  # type: ignore[override]
    def subject(self) -> str:
        """``db/code/<hash 16>``: the item a run's memo entry names in its ``code`` dependency."""
        return "db/code/" + self.hash[:16]

    @property
    def modules(self) -> List[str]:
        """The relpaths of every module the loader walked (under the repo root, mounted; under the top-level
        package's parent, installed), sorted."""
        return list(self._manifest["modules"])

    @property
    def mounts(self) -> Dict[str, Dict[str, str]]:
        """``prefix -> {"repo", "root"}`` at load; empty for installed code."""
        return {k: dict(v) for k, v in self._manifest["mounts"].items()}

    @property
    def commit(self) -> Optional[str]:
        """The checkout's commit at load, or ``None`` outside any checkout."""
        return self._manifest["commit"]

    @property
    def lock(self) -> Optional[str]:
        """The git blob id of ``uv.lock`` at that commit, or ``None``."""
        return self._manifest["lock"]

    @property
    def sandboxed(self) -> bool:
        """True for code mounted from a checkout (boxed); False for code installed in the ledger's env."""
        return bool(self._manifest["sandboxed"])

    @property
    def version(self) -> str:
        """The name after ``@``: ``2.7.1``, ``4be21c7e+dirty``, ``#2db69ce1``."""
        return str(self._manifest["version"])

    @property
    def package(self) -> Optional[str]:
        """The dotted root whose declared version ``version`` is (DAT 1044): the unit (``plane``,
        ``demo_game.etl``, ``geometry``), the ``<package>`` of the ``db/repo/<repo>/<package>`` clock a clean
        run moves; ``None`` when the version came from a commit or the hash (or a dirty checkout)."""
        return self._manifest["package"]

    def encode(self) -> bytes:
        """The identity: ``{"modules": relpath -> sha256, "mounts": <mounts hash or None>}``, canonical."""
        return identity(self._manifest["modules"], self._manifest["mounts_hash"]).encode()

    def _rows(self) -> List[Tuple[str, str]]:
        """The ``db/code/<hash 16>`` item's rows: the identity, so a lookup can re-hash it."""
        return [("db/modules", "json:" + canonical(self._manifest["modules"])),
                ("db/mounts", "str:" + (self._manifest["mounts_hash"] or "none"))]

    def _with_modules(self, more: Mapping[str, str]) -> "Code":
        """The same code with ``more`` modules beside its own: what a run actually loaded."""
        return Code({**self._manifest, "modules": {**self._manifest["modules"], **more}}, unit=self._unit)

    @classmethod
    def decode(cls, data: bytes, store: "ArtStore", name: Optional[str] = None) -> "Code":
        raise NotImplementedError("a Code is not stored as a value yet: its description arrives with the "
                                  "history tier (DAT 1037)")

    def _label(self) -> Optional[str]:
        return self.name

    def __repr__(self) -> str:
        return f"<Code {self.name}>"

    def __str__(self) -> str:
        return str(self.name)


def lock_of(checkout: Optional[Path]) -> Optional[str]:
    """The git blob id of ``uv.lock`` at HEAD in ``checkout``, or ``None``."""
    if checkout is None:
        return None
    return _git(str(checkout), "rev-parse", "HEAD:uv.lock") or None


def mounted_version(attr: Any, checkout: Path, files: Sequence[str], ident: str) -> str:
    """The mounted ladder: a dirty checkout, ``<commit 8>+dirty`` (the last commit touching ``files``,
    else HEAD); else the root's ``__version__``; else the last commit touching ``files`` (``+dirty``);
    else ``#`` + 8 hex of ``ident`` (the code's hash)."""
    last = _git(str(checkout), "log", "-1", "--format=%h", f"--abbrev={SHORT}", "--", *files)
    if attr is not None:
        co = code_at(str(checkout))
        if not co.dirty:
            return str(attr)
        head = last or (co.commit or "")[:SHORT]
        return head[:SHORT] + "+dirty" if head else "#" + ident[:SHORT]
    if last:
        dirty = _git(str(checkout), "status", "--porcelain", "--", *files)
        return last[:SHORT] + ("+dirty" if dirty else "")
    return "#" + ident[:SHORT]


@functools.lru_cache(maxsize=1)
def _top_dists() -> Mapping[str, List[str]]:
    return md.packages_distributions()


def declared_version(top: str) -> Optional[str]:
    """``__version__`` on the top-level package ``top``, else its distribution's version, else ``None``."""
    mod = sys.modules.get(top) or importlib.import_module(top)
    attr = getattr(mod, "__version__", None)
    if attr is not None:
        return str(attr)
    for dist in _top_dists().get(top, []):
        try:
            return md.version(dist)
        except md.PackageNotFoundError:
            continue
    return None


def installed_version(top: str, env: Env, repo: Optional[str], ident: str) -> str:
    """The installed ladder: a dirty checkout, its short commit ``+dirty``; else ``__version__`` on the
    top-level package; else its distribution's version; else the short commit of the checkout holding it;
    else ``#`` + 8 hex of ``ident`` (the code's hash)."""
    co = env.code.get(repo) if repo else None
    if co is not None and co.commit and co.dirty:
        return co.commit[:SHORT] + "+dirty"
    declared = declared_version(top)
    if declared is not None:
        return declared
    if co is not None and co.commit:
        return co.commit[:SHORT]
    return "#" + ident[:SHORT]
