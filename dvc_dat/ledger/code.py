"""``Code``: the code a function is loaded from, at a version, as a ``Value`` (DAT 1037).

One object whether the function is installed in the ledger's own Python environment or mounted from a
checkout (``code.sandboxed``). Its content is the manifest: ``modules`` (the relpaths the loader walked),
``mounts`` (``prefix -> {repo, root}``; empty for installed code), ``commit`` (the checkout's at load),
``lock`` (the blob id of that checkout's ``uv.lock``), ``sandboxed`` and ``version``. Its name is
``<unit>@<version>``: the unit is the mount prefix for mounted code (``plane``, ``algs.ocr``) and the
function's top-level package for installed code (``geometry``). Immutable: accessors only.

The version is read as a module attribute after import, never parsed from source. Mounted: the root
package's ``__version__``; else the last commit that touched the loaded files (8 hex, ``+dirty`` when one
differs from HEAD); else ``#`` + 8 hex of ``fn.sha``. Installed: ``__version__`` on the top-level package;
else the version of the distribution providing it; else the short commit of the checkout holding it
(``+dirty``); else ``#`` + 8 hex of ``fn.sha``. A ``Code`` is computed at ``load_fn`` and attached to
the ``Fn``; it is not written to the ledger.
"""

from __future__ import annotations

import functools
import importlib
import importlib.metadata as md
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence

from .codec import canonical
from .env import Env, _git
from .value import Value

if TYPE_CHECKING:
    from .store import ArtStore

#: Every short hash in a version: 8 hex.
SHORT = 8


class Code(Value):
    """The code a function is loaded from, at a version: ``<Code plane@2.7.1>``."""

    def __init__(self, manifest: Mapping[str, Any], *, unit: str) -> None:
        self.__dict__["_manifest"] = {
            "modules": list(manifest["modules"]), "mounts": {k: dict(v) for k, v in manifest["mounts"].items()},
            "commit": manifest["commit"], "lock": manifest["lock"], "sandboxed": bool(manifest["sandboxed"]),
            "version": str(manifest["version"])}
        self.__dict__["_unit"] = unit

    @property
    def name(self) -> Optional[str]:  # type: ignore[override]
        """``<unit>@<version>``: ``plane@2.7.1``, ``geometry@5.3.9``."""
        return f"{self._unit}@{self.version}"

    @property
    def modules(self) -> List[str]:
        """The relpaths of every module the loader walked (under the repo root, mounted; under the top-level
        package's parent, installed)."""
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

    def encode(self) -> bytes:
        return canonical(self._manifest).encode()

    @classmethod
    def decode(cls, data: bytes, store: "ArtStore", name: Optional[str] = None) -> "Code":
        manifest = json.loads(data)
        unit = name.rpartition("@")[0] if name else "?"
        return cls(manifest, unit=unit)

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


def mounted_version(attr: Any, checkout: Path, files: Sequence[str], sha: str) -> str:
    """The mounted ladder: the root's ``__version__``; else the last commit touching ``files``
    (``+dirty``); else ``#`` + 8 hex of ``sha``."""
    if attr is not None:
        return str(attr)
    last = _git(str(checkout), "log", "-1", "--format=%h", f"--abbrev={SHORT}", "--", *files)
    if last:
        dirty = _git(str(checkout), "status", "--porcelain", "--", *files)
        return last[:SHORT] + ("+dirty" if dirty else "")
    return "#" + sha[:SHORT]


@functools.lru_cache(maxsize=1)
def _top_dists() -> Mapping[str, List[str]]:
    return md.packages_distributions()


def installed_version(top: str, env: Env, repo: Optional[str], sha: str) -> str:
    """The installed ladder: ``__version__`` on the top-level package; else its distribution's version;
    else the short commit of the checkout holding it (``+dirty``); else ``#`` + 8 hex of ``sha``."""
    mod = sys.modules.get(top) or importlib.import_module(top)
    attr = getattr(mod, "__version__", None)
    if attr is not None:
        return str(attr)
    for dist in _top_dists().get(top, []):
        try:
            return md.version(dist)
        except md.PackageNotFoundError:
            continue
    co = env.code.get(repo) if repo else None
    if co is not None and co.commit:
        return co.commit[:SHORT] + ("+dirty" if co.dirty else "")
    return "#" + sha[:SHORT]
