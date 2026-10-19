"""The environment a function runs in, found by discovery; ``set_env_provider`` is the test seam (A51).

Discovery: git over the folder of each module the process imported, skipping
the standard library, ``site-packages`` and dvc-dat itself (the ledger's own
library is infrastructure, like ``site-packages``). A checkout is a repo; its
name is ``[project].name`` of the ``pyproject.toml`` at its root, normalised
(``dvc_dat`` -> ``dvc-dat``), else the checkout folder's name. ``Code`` holds
the commit at HEAD, whether tracked files are modified (``dirty``), and the
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

from .codec import sha256

try:
    import tomllib
except ImportError:  # pragma: no cover - 3.10
    tomllib = None  # type: ignore


@dataclass(frozen=True)
class Code:
    """One repo's code as the environment has it."""

    version: Optional[str]
    commit: Optional[str]
    dirty: bool = False
    path: Optional[Path] = None


@dataclass(frozen=True)
class Env:
    """What a provider reports: ``code`` (repo -> ``Code``), the ``uv.lock`` hash, the platform."""

    code: Dict[str, Code]
    lock: str
    platform: str
    mounts: Optional[str] = field(default=None)


Provider = Callable[[], Env]
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


def lock_hash() -> str:
    """sha256 of the ``uv.lock`` of the project whose venv runs this process; ``<none>`` without one."""
    for folder in (Path(sys.prefix).parent, Path.cwd()):
        lock = folder / "uv.lock"
        if lock.is_file():
            return "sha256:" + sha256(lock.read_bytes())
    return "<none>"


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


def code_at(top: str) -> Code:
    commit = _git(top, "rev-parse", "HEAD")
    dirty = bool(_git(top, "status", "--porcelain", "--untracked-files=no"))
    return Code(None, commit, dirty, Path(top))


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
    code: Dict[str, Code] = {}
    for top in sorted({t for t in (_toplevel(d) for d in folders) if t}):
        code[repo_name(Path(top))] = code_at(top)
    return Env(code, lock_hash(), platform_tag())


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
