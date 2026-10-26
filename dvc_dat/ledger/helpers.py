"""``bump``: raise a clock subject's version inside a transaction (Q33); ``bump_source``: raise a module's
``__version__`` in its source (DAT 1043). (``attr`` lives in ``txn``.)"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .codec import show
from .txn import Transaction

_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def bump(t: Transaction, subject: str, part: str = "patch", *,
         confirm: Optional[Callable[[str, str], bool]] = None) -> str:
    """Read ``version`` through ``t.previous_rev`` (``0.0.0`` when absent), add the next by ``part``, return it.

    A read-then-write, so ``t`` must be opened with ``lock=``: unlocked, ``t.previous_rev`` raises
    ``Unlocked`` and nothing is written.

    For clocks only: a subject holding a ``db/alias`` row raises ``TypeError`` naming the alias (a
    value's version is a pred; a new version is a new seal and a re-point), and so does a ``db/repo/``
    subject: a code version lives in its source (``bump_source``), and the first clean run after it moves
    the ``db/repo/<repo>/<package>`` clock, which the ledger alone writes (DAT 1043, 1044). ``minor`` and ``major`` need ``confirm(old, new)`` to answer
    ``True``; without ``confirm`` they are refused (A38). Nothing is written on any refusal.
    """
    if subject.startswith("db/repo/"):
        raise TypeError(f"{subject}: a code version lives in its source; just bump <module> [part] edits "
                        "__version__ there, and the next clean run records it in db/repo/<repo>/<package> "
                        "(the commit in db/repo/<repo>)")
    prev = t.previous_rev                   # Unlocked without lock=
    held = prev._held(subject, "db/alias")
    if held:
        raise TypeError(f"{subject} is an alias; seal a new value and re-point (a value's version is a pred; "
                        f"{subject} names #{show(held[0].obj)[:8]})")
    old = prev.get(subject, "version", default="0.0.0")
    new = _next(subject, old, part, confirm)
    t.add(subject, "version", new)
    return new


def _next(what: str, old: object, part: str, confirm: Optional[Callable[[str, str], bool]]) -> str:
    """The version after ``old`` by ``part``; ``minor`` and ``major`` need ``confirm(old, new) is True``."""
    if part not in ("patch", "minor", "major"):
        raise ValueError(f"part is 'patch', 'minor' or 'major', not {part!r}")
    m = _VERSION.match(old) if isinstance(old, str) else None
    if m is None:
        raise ValueError(f"{what!r} version {old!r} is not MAJOR.MINOR.PATCH")
    a, b, c = (int(x) for x in m.groups())
    new = {"patch": f"{a}.{b}.{c + 1}", "minor": f"{a}.{b + 1}.0", "major": f"{a + 1}.0.0"}[part]
    if part != "patch":
        if confirm is None:
            raise ValueError(f"bump {part} of {what!r} ({old} -> {new}) needs confirm=")
        if confirm(old, new) is not True:
            raise ValueError(f"bump {part} of {what!r} ({old} -> {new}) refused by confirm")
    return new


#: One ``__version__ = "X.Y.Z"`` assignment line, single or double quotes.
_ASSIGN = re.compile(r"""^(__version__\s*=\s*)(['"])([^'"]*)\2(.*)$""", re.M)


@dataclass(frozen=True)
class SourceBump:
    """What ``bump_source`` did: ``module``'s version went ``old -> new`` in the file at ``path``, in checkout
    ``repo``; ``package`` is the dotted root whose ``__version__`` that file declares, the ``<package>`` of
    the ``db/repo/<repo>/<package>`` clock the next clean run moves."""

    module: str
    old: str
    new: str
    path: Path
    repo: Optional[str]
    package: str


def bump_source(module: str, part: str = "patch", *,
                confirm: Optional[Callable[[str, str], bool]] = None) -> SourceBump:
    """Raise ``module``'s ``__version__`` by ``part`` in its source: one line rewritten, nothing else.

    ``module`` is a dotted name importable in this process. The version is the innermost one on its
    dotted path: the module's own file, then each enclosing package's ``__init__.py`` up to the
    top-level package, the first holding one line ``__version__ = "X.Y.Z"`` (so ``demo_game.etl``, a
    mount's root declaring its own, finds ``demo_game/etl/__init__.py``; ``mymodule.mult`` finds
    ``mymodule/__init__.py``). ``minor`` and ``major`` need ``confirm(old, new)`` to answer ``True``, as
    ``bump``. Never commits and never touches a ledger: the first clean run after the commit moves the
    ``db/repo/<repo>/<package>`` clock (DAT 1043, 1044). ``repo`` is the checkout's name by discovery, ``None`` outside one.
    Refusals, nothing written: ``ModuleNotFoundError`` for a module that does not resolve, ``ValueError``
    for no ``__version__`` line (naming the top-level package's file) or one that is not
    ``MAJOR.MINOR.PATCH``."""
    from .env import _git, repo_name

    if not isinstance(module, str) or not module:
        raise TypeError(f"a module is a dotted str, not {module!r}")
    parts = module.split(".")
    found = None
    path = None
    for i in range(len(parts), 0, -1):
        name = ".".join(parts[:i])
        try:
            spec = importlib.util.find_spec(name)
        except ModuleNotFoundError as e:
            raise ModuleNotFoundError(f"no module named {e.name or name!r}", name=e.name or name) from None
        if spec is None:
            raise ModuleNotFoundError(f"no module named {name!r}", name=name)
        if not spec.origin or not Path(spec.origin).is_file():
            continue                        # a namespace package: no file to hold a version
        path = Path(spec.origin)
        text = path.read_text()
        found = _ASSIGN.search(text)
        if found is not None:
            break
    if path is None:
        raise ModuleNotFoundError(f"{module!r} has no source file to bump", name=module)
    m = found
    if m is None:
        raise ValueError(f'{path}: no __version__ = "X.Y.Z" line to bump; add one')
    old = m[3]
    new = _next(module, old, part, confirm)
    path.write_text(text[:m.start(3)] + new + text[m.end(3):])
    top_dir = _git(str(path.parent), "rev-parse", "--show-toplevel")
    return SourceBump(module, old, new, path, repo_name(Path(top_dir)) if top_dir else None, name)
