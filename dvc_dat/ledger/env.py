"""The environment a function runs in, found by discovery; ``set_env_provider`` is the test seam (A51).

Discovery: git over the folder of each module the process imported, skipping
the standard library, ``site-packages`` and the dvc-dat checkout itself, its
demo folders included (A56: the ledger's own repo is infrastructure, like
``site-packages``; a demo repository is its own nested checkout). A checkout is a repo; its
name is ``[project].name`` of the ``pyproject.toml`` at its root, normalised
(``dvc_dat`` -> ``dvc-dat``), else the checkout folder's name. ``Checkout`` holds
the commit at HEAD, whether tracked files are modified (``dirty``: none whose
path the repo's ``.gitattributes`` marks ``dat-noncode``, as ``core._code_of``), and the
checkout ``path`` a mount's ``db/root`` resolves under. The commit is read on
every call, never cached: a notebook commits mid-session.
"""

from __future__ import annotations

import os
import platform as _platform
import re
import subprocess
import sys
import sysconfig
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional

from ..core import CODE_PATHSPEC

try:
    import tomllib
except ImportError:  # pragma: no cover - 3.10
    tomllib = None  # type: ignore


@dataclass(frozen=True)
class Checkout:
    """One repo's code as the environment has it."""

    version: Optional[str]
    commit: Optional[str]
    dirty: bool = False
    path: Optional[Path] = None


@dataclass(frozen=True)
class Env:
    """What a provider reports: ``code`` (repo -> ``Checkout``) and the platform."""

    code: Dict[str, Checkout]
    platform: str
    mounts: Optional[str] = field(default=None)


Provider = Callable[[], Env]
#: The ledger's own repo: discovery never reports it (A56), whatever folder of it a module sits in.
SELF = "dvc-dat"
_provider: Optional[Provider] = None


def set_env_provider(provider: Optional[Provider]) -> Optional[Provider]:
    """Replace discovery with ``provider() -> Env`` (tests only); ``None`` restores discovery. Returns the old."""
    global _provider
    old, _provider = _provider, provider
    return old


def current_env() -> Env:
    return (_provider or discover)()


def platform_tag() -> str:
    return f"{sys.platform}-{_platform.machine()}-py{sys.version_info[0]}.{sys.version_info[1]}"


def _git(folder: str, *args: str) -> Optional[str]:
    try:
        out = subprocess.run(["git", "-C", folder, *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


_tops: Dict[str, Optional[str]] = {}


def _toplevel(folder: str) -> Optional[str]:
    if folder not in _tops:
        _tops[folder] = _git(folder, "rev-parse", "--show-toplevel")
    return _tops[folder]


def repo_name(top: Path) -> str:
    """A checkout's repo name: its pyproject's ``[project].name``, normalised, else its folder name."""
    pp = top / "pyproject.toml"
    if pp.is_file() and tomllib is not None:
        try:
            name = tomllib.loads(pp.read_text()).get("project", {}).get("name")
        except (ValueError, OSError):
            name = None
        if isinstance(name, str) and name:
            return re.sub(r"[-_.]+", "-", name).lower()
    return top.name


def code_at(top: str) -> Checkout:
    commit = _git(top, "rev-parse", "HEAD")
    dirty = bool(_git(top, "status", "--porcelain", "--untracked-files=no", "--", *CODE_PATHSPEC))
    return Checkout(None, commit, dirty, Path(top))


def _skip_roots() -> list:
    roots = {sys.prefix, sys.base_prefix, sys.exec_prefix}
    for k in ("stdlib", "platstdlib", "purelib", "platlib"):
        p = sysconfig.get_paths().get(k)
        if p:
            roots.add(p)
    roots.add(str(Path(__file__).resolve().parent.parent))      # dvc_dat itself
    return [os.path.realpath(r) for r in roots]


def discover() -> Env:
    """The default provider: git over the folders of the modules this process imported."""
    skip = _skip_roots()
    folders = set()
    for m in list(sys.modules.values()):
        f = getattr(m, "__file__", None)
        if not f:
            continue
        d = os.path.dirname(os.path.realpath(f))
        if any(d == r or d.startswith(r + os.sep) for r in skip):
            continue
        folders.add(d)
    code: Dict[str, Checkout] = {}
    for top in sorted({t for t in (_toplevel(d) for d in folders) if t}):
        name = repo_name(Path(top))
        if name == SELF:
            continue            # dvc-dat itself, its demos included (A56)
        code[name] = code_at(top)
    return Env(code, platform_tag())


def repo_of(env: Env, path: Optional[Path]) -> Optional[str]:
    """The repo whose checkout holds ``path``, the deepest one."""
    if path is None:
        return None
    p = os.path.realpath(path)
    best = None
    for name, c in env.code.items():
        if c.path is None:
            continue
        root = os.path.realpath(c.path)
        if (p == root or p.startswith(root + os.sep)) and (best is None or len(root) > best[1]):
            best = (name, len(root))
    return best[0] if best else None
