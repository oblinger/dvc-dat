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

The platform record (SVP 1474) is what a memo entry stores of the machine its function ran on:
``platform`` (today's short tag, ``<os>-<machine>-py<X.Y>``), ``os``, ``machine``, ``python``
(``X.Y.Z``), ``cpu`` (the CPU model), and ``card``, ``driver``, ``cuda``, ``torch``, each ``None``
when absent (no NVIDIA card, no torch). It is probed once per process; ``Env.record`` carries it,
and the ledger's memo policy (``policy``) judges it at lookup.
"""

from __future__ import annotations

import functools
import json
import os
import platform as _platform
import re
import subprocess
import sys
import sysconfig
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

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
    """What a provider reports: ``code`` (repo -> ``Checkout``), the platform's short tag, and its full
    ``record`` (the fields of ``platform_record``; ``None``: only the tag is known)."""

    code: Dict[str, Checkout]
    platform: str
    mounts: Optional[str] = field(default=None)
    record: Optional[Mapping[str, Optional[str]]] = field(default=None)

    def platform_record(self) -> Dict[str, Optional[str]]:
        """The platform record, its ``platform`` field this environment's tag."""
        out = dict(self.record or {})
        out["platform"] = self.platform
        return out


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


#: The dependency item holding the full platform record, beside the short ``platform`` item.
RECORD_ITEM = "platform/record"


def platform_items(env: Env) -> Dict[str, str]:
    """A run's platform items: ``platform`` (the short tag, as before 1474) and ``platform/record`` (the
    full record as canonical JSON), both of the environment the function ran in."""
    from .codec import canonical

    return {"platform": env.platform, RECORD_ITEM: canonical(env.platform_record())}


def stored_record(trace: Mapping[str, str]) -> Optional[Dict[str, Any]]:
    """The platform record a trace holds: its ``platform/record`` item; an entry written before it
    (the short item alone) is ``{"platform": <tag>}``; ``None`` when it holds neither, or the record
    no longer parses."""
    text = trace.get(RECORD_ITEM)
    if text is None:
        return {"platform": trace["platform"]} if "platform" in trace else None
    try:
        rec = json.loads(text)
    except ValueError:
        return None
    if not isinstance(rec, dict):
        return None
    if "platform" in trace:
        rec["platform"] = trace["platform"]
    return rec


def _run(*cmd: str) -> Optional[str]:
    try:
        out = subprocess.run(list(cmd), capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def cpu_model() -> Optional[str]:
    """The CPU's model name: ``sysctl`` on macOS, ``/proc/cpuinfo`` on Linux, else ``platform.processor()``."""
    if sys.platform == "darwin":
        text = _run("sysctl", "-n", "machdep.cpu.brand_string")
        if text and text.strip():
            return text.strip()
    if sys.platform.startswith("linux"):
        try:
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                key, _, value = line.partition(":")
                if key.strip() in ("model name", "Model") and value.strip():
                    return value.strip()
        except OSError:
            pass
    return _platform.processor() or None


def parse_smi(text: str, visible: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """``(card, driver)`` from ``nvidia-smi --query-gpu=index,name,driver_version --format=csv,noheader``:
    the distinct names of the GPUs the process sees (``visible``, ``CUDA_VISIBLE_DEVICES``, when it is a
    list of indexes), sorted and joined by `` + ``; ``(None, None)`` for none."""
    rows = [[c.strip() for c in line.split(",")] for line in text.splitlines() if line.strip()]
    rows = [r for r in rows if len(r) >= 3]
    if visible is not None and all(v.strip().isdigit() for v in visible.split(",") if v.strip()):
        keep = {v.strip() for v in visible.split(",") if v.strip()}
        rows = [r for r in rows if r[0] in keep]
    if not rows:
        return None, None
    return " + ".join(sorted({r[1] for r in rows})), rows[0][2]


def gpu_fields() -> Dict[str, Optional[str]]:
    """``card`` and ``driver`` (``nvidia-smi``), ``torch`` (its installed distribution's version) and
    ``cuda`` (the CUDA torch was built against, read off ``torch/version.py``); torch is never imported."""
    import shutil
    from importlib import metadata

    card = driver = cuda = torch = None
    if shutil.which("nvidia-smi"):
        text = _run("nvidia-smi", "--query-gpu=index,name,driver_version", "--format=csv,noheader")
        if text:
            card, driver = parse_smi(text, os.environ.get("CUDA_VISIBLE_DEVICES"))
    try:
        dist = metadata.distribution("torch")
        torch = dist.version
        mod = sys.modules.get("torch")
        if mod is not None and getattr(getattr(mod, "version", None), "cuda", None):
            cuda = str(mod.version.cuda)
        else:
            m = re.search(r"^cuda\s*(?::[^=]*)?=\s*['\"]([^'\"]+)['\"]",
                          Path(str(dist.locate_file("torch/version.py"))).read_text(), re.M)
            cuda = m.group(1) if m else None
    except (metadata.PackageNotFoundError, OSError):
        pass
    return {"card": card, "driver": driver, "cuda": cuda, "torch": torch}


@functools.lru_cache(maxsize=1)
def _probed() -> Tuple[Tuple[str, Optional[str]], ...]:
    rec: Dict[str, Optional[str]] = {"platform": platform_tag(), "os": sys.platform,
                                     "machine": _platform.machine(), "python": _platform.python_version(),
                                     "cpu": cpu_model()}
    rec.update(gpu_fields())
    return tuple(rec.items())


def platform_record() -> Dict[str, Optional[str]]:
    """This process's platform record (module doc), probed once per process."""
    return dict(_probed())


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
    """The default provider: git over the folders of the modules this process imported.

    A folder that no longer exists is skipped (DAT 1023): a deleted checkout's modules stay in
    ``sys.modules`` and its toplevel in the ``_toplevel`` cache, so without the check a re-run's previous,
    deleted scratch checkout was reported. Of two existing checkouts sharing a name, the one the most
    recently imported module was loaded from wins (``sys.modules`` is in import order), not the one whose
    path sorts last."""
    skip = _skip_roots()
    folders: Dict[str, int] = {}                # folder -> order of the latest module imported from it
    for i, m in enumerate(list(sys.modules.values())):
        f = getattr(m, "__file__", None)
        if not f:
            continue
        d = os.path.dirname(os.path.realpath(f))
        if any(d == r or d.startswith(r + os.sep) for r in skip):
            continue
        folders[d] = i
    tops: Dict[str, int] = {}                   # checkout -> order of the latest module imported from it
    for d, i in folders.items():
        t = _toplevel(d) if os.path.isdir(d) else None
        if t and os.path.isdir(t):
            tops[t] = max(i, tops.get(t, -1))
    chosen: Dict[str, str] = {}
    for top in sorted(tops, key=lambda t: (tops[t], t)):
        name = repo_name(Path(top))
        if name != SELF:                        # dvc-dat itself, its demos included (A56)
            chosen[name] = top                  # a later import overrides an earlier same-named checkout
    return Env({name: code_at(top) for name, top in sorted(chosen.items())}, platform_tag(),
               record=platform_record())


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
