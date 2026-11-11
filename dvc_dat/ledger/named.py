"""``ledgers`` and ``L``: the project's ledgers by name, and the active one (SVP 239).

    from dvc_dat import L, dat, ledgers
    ledgers.games.at()           # a ledger registered on root, by name
    ledgers.root                 # the root ledger itself: root: in .datconfig.yaml
    del ledgers["prod_kit"]      # this process no longer reaches it by name
    ledgers["tmp"] = Ledger(p)   # a ledger by hand, for this process
    L.at()                       # the active ledger: DAT_LEDGER, else the config's default:
    dat.at("do26@512")           # a revision on any registered ledger
    dat.load("do26@512:run/G1")  # a value by the global reference <ledger>@<rev>:<name-or-sha> (SVP 248)

**Root, the one list.** ``.datconfig.yaml`` names one ledger, ``root:`` (a folder relative to the file, or a DSN);
without it the root is a SQLite folder under the first dat folder, made on first use, so a project that never asks a
name never meets a ledger. Root's *registry* names every other ledger: a subject ``ledger/<name>`` holding
``ledger/location`` (a DSN, or a folder relative to the config), and ``ledger/dropped`` once it is gone, whose name
then resolves no more. ``ledgers`` is filled from it lazily, at the first name asked that this process has not
set, one read of root per project and process; nothing reads root before that.

``ledgers`` is a mutable mapping over that view. ``ledgers[name]`` and ``ledgers.<name>`` are the ledger's handle,
opened on first use and kept for the process; a name the registry does not hold is ``KeyError`` (``AttributeError``
as an attribute) naming the root. ``del ledgers[name]`` drops a name from this process, so nothing here reaches it
by name (a handle already in hand keeps working: a weak permission, not a guard); ``ledgers[name] = Ledger(...)``
puts one in by hand, for this process. Setting ``ledgers["root"]`` before the first read replaces the root itself,
which is how a test runs on a temp root. Iteration is ``root`` and the registry's names in revision order; ``len``
counts them.

``L`` is the active ledger as one object (``from dvc_dat import L``): a ``Ledger`` (``isinstance`` holds, so
``v.seal(L)`` and ``seal=L`` take it) whose every attribute is the ledger ``Ledger()`` would open: ``DAT_LEDGER``,
else the config's ``default:``, each a name resolved through ``ledgers`` or a location, at each use and never at
import. A checkout with neither imports it fine and raises the one-line ``LedgerError`` at the first use. ``L.at()``
is the ``Head`` of the real handle, the same handle ``ledgers.<name>`` gives for that ledger; ``repr(L)`` names it, or
says why it is unresolved. See [Many ledgers][many-ledgers].

In a sandbox worker (SVP 1521 Q3 (A)) ``ledgers`` is the caller's view, shipped on the request
(``shipped_section``, ``adopt_section``): its names as the caller has them, or, when the caller never read root, the
root's location, read there on the first name asked. Every handle it gives is read-only; a body's
``ledgers.<name>``, ``dat.at`` and ``dat.load`` all come through it.

**The read guard** (SVP 1596): ``register_read_guard(guard)`` makes ``guard(name)`` run before ``ledgers[name]``,
``ledgers.<name>``, ``dat.at("<name>@<rev>")`` and ``dat.load("<name>@<rev>:…")`` open the ledger ``name``; it refuses
by raising, and its exception is the caller's. One guard per process (registering again replaces it; ``None``
removes it). It crosses to a sandbox worker by its import path (``module:qualname``) and is imported there at the
body's first named open, so it is a module-level function. ``L``, a ``Ledger(location)`` and a ``Ref`` key's ledger
are not opened by name and are not guarded.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple

from .errors import LedgerError
from .ledger import CONFIG, ENV, ROOT, Ledger, Target, _find, _is_name, _target, _values, _walk_up, opened, \
    root_target
from .pgstore import is_dsn

#: The registry's subject prefix and predicates on root (SVP 1516): ``ledger/<name> ledger/location <where>``.
REGISTRY = "ledger/"
LOCATION = "ledger/location"
DROPPED = "ledger/dropped"

_handles: Dict[str, Ledger] = {}
_asserted: Set[Tuple[str, str]] = set()
#: The view a request ships to a sandbox worker: ``{"cfg", "root", "entries", "filled", "removed"}``; ``None``: the
#: caller has no config.
Section = Optional[Dict[str, Any]]
#: In a sandbox worker: the view adopted, and how a location is opened there.
_worker: Optional[Tuple[Section, Any]] = None


#: The read guard (SVP 1596): called with a ledger's name before a named open; ``None``, none. In a sandbox worker it is
#: imported from ``_guard_ref`` at the first named open.
_guard: Optional[Callable[[str], Any]] = None
#: The guard's import path, ``module:qualname``: what crosses to a sandbox worker.
_guard_ref: Optional[str] = None


def _resolve_guard(ref: str) -> Callable[[str], Any]:
    module, _, qualname = ref.partition(":")
    obj: Any = importlib.import_module(module)
    for part in qualname.split("."):
        obj = getattr(obj, part)
    return obj


def register_read_guard(guard: Optional[Callable[[str], Any]]) -> None:
    """Make ``guard`` the read guard: ``guard(name)`` runs before ``ledgers[name]``, ``ledgers.<name>``, ``dat.at`` and
    ``dat.load`` open the ledger ``name``, in this process and in a sandbox worker, and refuses the open by raising.
    Registering again replaces it; ``None`` removes it.

    The guard crosses to a sandbox worker by its import path, so it is a module-level function its module's import
    finds; anything else is ``TypeError``.
    """
    global _guard, _guard_ref
    if guard is None:
        _guard = _guard_ref = None
        return
    if not callable(guard):
        raise TypeError(f"a read guard is a function of a ledger's name, not {guard!r}")
    ref = f"{getattr(guard, '__module__', None)}:{getattr(guard, '__qualname__', None)}"
    try:
        found = None if ref.startswith("__main__:") else _resolve_guard(ref)
    except (ImportError, AttributeError):
        found = None
    if found is not guard:
        raise TypeError(f"a read guard crosses to a sandbox worker by its import path, and {guard!r} is not found "
                        f"at {ref!r}: register a module-level function of an importable module")
    _guard, _guard_ref = guard, ref


def check_read(name: str) -> None:
    """The read guard on ``name`` (nothing when none is registered): before a named open."""
    global _guard
    if _guard is None and _guard_ref is not None:   # a sandbox worker: the caller's guard, at its first use
        from .sandbox import unguarded

        with unguarded():
            _guard = _resolve_guard(_guard_ref)
    if _guard is not None:
        from .sandbox import unguarded

        with unguarded():                           # the caller's policy, not the body: its reads are not the body's
            _guard(name)


def shipped_read_guard() -> Optional[str]:
    """The read guard's import path, as a request ships it to a sandbox worker."""
    return _guard_ref


def adopt_read_guard(ref: Optional[str]) -> None:
    """In a sandbox worker: the caller's read guard, by its import path, imported at the first named open."""
    global _guard, _guard_ref
    _guard, _guard_ref = None, ref


def _handle(target: Any, given: Any, base: Path, cfg: Optional[Path]) -> Ledger:
    """One handle per ledger, shared by ``L`` and ``ledgers``; opened as the active ledger, it asserts the
    config's ``mounts:`` once, as ``Ledger()`` does."""
    key = str(target)
    led = _handles.get(key)
    if led is None:
        led = _handles[key] = Ledger._opened(target, given, base, None) if _worker is None \
            else _worker[1](target, given, base)
    if cfg is not None and (key, str(cfg)) not in _asserted:
        led._assert_mounts(cfg)
        _asserted.add((key, str(cfg)))
    return led


class _View:
    """One project's names in this process: what was set by hand, what was dropped, and what root's registry said
    (read once, at the first name asked that is neither)."""

    def __init__(self, cfg: Path, root: Target, made: bool) -> None:
        self.cfg, self.root, self.made = cfg, root, made
        self.entries: Dict[str, Any] = {}       # name -> a Target, or a Ledger set by hand
        self.removed: Set[str] = set()
        self.filled = False

    def location(self, value: Any) -> str:
        return str(value.path) if isinstance(value, Ledger) else str(value)

    def _root(self) -> Ledger:
        held = self.entries.get(ROOT)
        if isinstance(held, Ledger):
            return held
        target = held if held is not None else self.root
        if _worker is None and self.made and isinstance(target, Path) and not (target / "ledger.db").is_file():
            _handles[str(target)] = Ledger(target, create=True)     # the default SQLite root, on first use
        return _handle(target, f"root ({self.cfg})", self.cfg.parent, None)

    def fill(self) -> None:
        if self.filled:
            return
        top = self._root().at()
        dropped = {s for s, _o in top.all(REGISTRY + "*", DROPPED)}
        found: Dict[str, Any] = {ROOT: self.root}
        for s, loc in top.all(REGISTRY + "*", LOCATION):
            if s not in dropped and isinstance(loc, str) and loc.strip():
                found[s[len(REGISTRY):]] = _target(self.cfg, loc)
        merged = {n: self.entries.get(n, v) for n, v in found.items() if n not in self.removed}
        for name, value in self.entries.items():           # set by hand, not registered: after the registry's
            merged.setdefault(name, value)
        self.entries, self.filled = merged, True

    def names(self) -> List[str]:
        self.fill()
        return [n for n in self.entries if n not in self.removed]

    def get(self, name: str) -> Any:
        if name in self.removed:
            raise KeyError(f"{name!r}: dropped from this process's ledgers (del ledgers[{name!r}])")
        if name not in self.entries:
            self.fill()
        if name not in self.entries:
            raise KeyError(f"{name!r}: no such ledger on the root ledger's registry ({self.location(self.root)}, "
                           f"{REGISTRY}<name> {LOCATION}) or set in this process: "
                           f"{', '.join(self.names()) or 'none'}")
        return self.entries[name]

    def ship(self) -> Dict[str, Any]:
        live = {n: self.location(v) for n, v in self.entries.items() if n not in self.removed}
        root = live.get(ROOT, self.location(self.root))
        return {"cfg": str(self.cfg), "root": root, "entries": live, "filled": self.filled,
                "removed": sorted(self.removed), "made": self.made}


_views: Dict[Tuple[str, str], _View] = {}


def _view() -> _View:
    """This project's view: the worker's adopted one in a sandbox, else the nearest config's."""
    if _worker is not None:
        section = _worker[0]
        if section is None:
            raise LedgerError(f"no ledgers: the caller of this sandboxed function has no {CONFIG}")
        key = (section["cfg"], section["root"])
        view = _views.get(key)
        if view is None:
            cfg = Path(section["cfg"])
            view = _views[key] = _View(cfg, _target(cfg, section["root"]), False)
            view.entries = {n: _target(cfg, loc) for n, loc in section["entries"].items()}
            view.removed, view.filled = set(section["removed"]), section["filled"]
        return view
    cfg, searched = _walk_up(Path.cwd().resolve())
    if cfg is None:
        raise LedgerError(f"no ledgers: no {CONFIG} in " + ", ".join(str(s) for s in searched))
    return view_of(cfg)


def view_of(cfg: Path) -> _View:
    root, made = root_target(cfg, _values(cfg))
    key = (str(cfg), str(root))
    view = _views.get(key)
    if view is None:
        view = _views[key] = _View(cfg, root, made)
    return view


def target_of(cfg: Path, name: str, why: str) -> Target:
    """Where the ledger ``name`` is, through the project's view (``ledgers``); ``LedgerError`` saying ``why`` the name
    was asked when the view does not hold it."""
    try:
        value = view_of(cfg).get(name)
    except KeyError as e:
        raise LedgerError(f"{why}: {e.args[0]}") from None
    return value.path if isinstance(value, Ledger) else value


def _open(view: _View, name: str) -> Ledger:
    value = view.get(name)
    if isinstance(value, Ledger):
        return value
    if name == ROOT:
        return view._root()
    return _handle(value, f"{name} ({view.cfg})", view.cfg.parent, None)


class Ledgers(MutableMapping):
    """The project's ledgers by name: ``root`` and every ledger root's registry names, filled lazily (the module
    docstring). ``ledgers.<name>`` or ``ledgers["<name>"]`` is that ledger's handle, opened on first use and kept for
    the process; an unknown name is ``KeyError`` (``AttributeError`` as an attribute) naming the root.

    ``del ledgers[name]`` and ``ledgers[name] = Ledger(...)`` change this process's view only, never the registry
    (``just create ledger`` writes that). A named handle asserts no ``mounts:``; only the active ledger does. In a
    sandboxed body it is the caller's view, and every handle is read-only (DAT Ledger § Another ledger from a
    sandboxed body, SVP 1521).
    """

    def __getitem__(self, name: str) -> Ledger:
        check_read(name)
        return _open(_view(), name)

    def __setitem__(self, name: str, ledger: Ledger) -> None:
        if not _is_name(name):
            raise ValueError(f"ledgers[{name!r}]: a ledger name is a Python identifier (lowercase letters, digits "
                             "and underscores, a letter first, not a keyword)")
        if not isinstance(ledger, Ledger):
            raise TypeError(f"ledgers[{name!r}] = ...: a Ledger (Ledger(location)), got {type(ledger).__name__}")
        view = _view()
        view.entries[name] = ledger
        view.removed.discard(name)

    def __delitem__(self, name: str) -> None:
        view = _view()
        view.get(name)                              # KeyError when there is nothing to drop
        view.removed.add(name)

    def __getattr__(self, name: str) -> Ledger:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self[name]
        except KeyError as e:
            raise AttributeError(f"ledgers.{name}: {e.args[0]}") from None

    def __iter__(self) -> Iterator[str]:
        return iter(_view().names())

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        try:
            _view().get(name)
        except KeyError:
            return False
        return True

    def __len__(self) -> int:
        return len(_view().names())

    def __dir__(self) -> List[str]:
        try:
            return _view().names()
        except LedgerError:
            return []

    def __repr__(self) -> str:
        try:
            view = _view()
            names = view.names()
        except LedgerError as e:
            return f"ledgers (none: {e})"
        return f"ledgers({view.cfg}: {', '.join(names)})"


def shipped_section() -> Section:
    """The view a sandboxed run sees: the caller's (``_View.ship``), in a worker the one it was given; ``None`` with no
    config. Root is not read for it: a caller that never asked a name ships root's location, read in the worker on
    the body's first name."""
    if _worker is not None:
        return _view().ship() if _worker[0] is not None else None
    cfg, _ = _walk_up(Path.cwd().resolve())
    return None if cfg is None else view_of(cfg).ship()


def adopt_section(section: Section, read_only: Any) -> None:
    """In a sandbox worker: ``ledgers`` is ``section``, its handles opened by ``read_only(target, given, base)``."""
    global _worker
    _worker = (section, read_only)


def handle_at(location: str) -> Ledger:
    """In a sandbox worker: the handle on a ledger named by location, for a ``Ref`` key on it."""
    return _handle(location if is_dsn(location) else Path(location), location, Path.cwd(), None)


def ledger_named(name: str) -> Ledger:
    """The ledger a ``<ledger>@<rev>`` names: one open in this process under that name, else ``ledgers[name]``;
    ``KeyError`` or ``LedgerError`` when neither knows it. The read guard first."""
    check_read(name)
    led = opened(name)
    return led if led is not None else _open(_view(), name)


def rev_named(text: str, near: Optional[Ledger] = None) -> Any:
    """The plain ``Rev`` ``<ledger>@<rev>`` names; ``near``, a ledger already in hand, answers first when the name
    is its."""
    name, _, rev = text.rpartition("@")
    if not name or not rev.isdigit():
        raise ValueError(f"{text!r}: a revision is named <ledger>@<rev>")
    led = near if near is not None and near._store.name == name else ledger_named(name)
    return led.at(int(rev))


#: A global reference's sha: ``sha256:<64 hex>``, the hash of a value's bytes.
SHA_PREFIX = "sha256:"


def _hash_subject(rev: Any, h: str) -> Optional[str]:
    """The subject of the latest value at ``rev`` whose bytes hash to ``h``, else None: the ``db/value`` rows, read
    in full (one ledger, one predicate; a value sealed twice has two subjects and one hash)."""
    from .codec import parse_ref

    plain = rev._plain()
    found = [s for s, _p, held in plain._held_rows(predicate="db/value") if parse_ref(held.obj)[1] == h]
    return found[-1] if found else None


def _value_at(rev: Any, name: str) -> Any:
    """What ``name`` names at ``rev``: a ``sha256:`` by its hash, anything else as ``rev.load`` takes it."""
    if not name.startswith(SHA_PREFIX):
        return rev.load(name)
    subject = _hash_subject(rev, name[len(SHA_PREFIX):])
    if subject is None:
        raise KeyError(f"{name!r} has no value at {rev.ledger._store.name}@{rev.id}")
    return rev.load(subject)


def _ledger_of(default: Any) -> Ledger:
    """``default`` as a ledger: a ``Ledger``, a registered name, or None for the active one."""
    if default is None:
        return L
    return ledger_named(default) if isinstance(default, str) else default


def at(ref: Any, default: Any = None) -> Any:
    """The plain ``Rev`` ``ref`` names: ``<ledger>@<rev>`` on any registered ledger; a bare revision on ``default``
    (a ``Ledger`` or a name; None: the active ledger). SVP 248: ``ledger.at(rev)`` works on that ledger alone."""
    text = str(ref)
    if "@" in text:
        return rev_named(text)
    if not text.isdigit():
        raise ValueError(f"{text!r}: a revision is <ledger>@<rev>, or a bare revision number")
    return _ledger_of(default).at(int(text))


def load(ref: str, default: Any = None) -> Any:
    """The value the global reference ``<ledger>@<rev>:<name-or-sha>`` names (``do26@512:run/G1``,
    ``do26@512:sha256:<hex>``); a bare ``<name-or-sha>`` reads ``default`` (a ``Ledger`` or a name; None: the active
    ledger) at its head. With no default, in a project with no ledger, it is ``Dat.manager.load(ref)``."""
    head, sep, rest = ref.partition(":")
    if sep and "@" in head:
        return _value_at(rev_named(head), rest)
    if default is None and _no_ledger():
        from . import hooks

        return hooks.manager().load(ref)
    return _value_at(_ledger_of(default).at(), ref)


def _no_ledger() -> bool:
    """Does this project name no active ledger (no ``DAT_LEDGER``, no ``default:`` in its ``.datconfig.yaml``)?"""
    if os.environ.get(ENV):
        return False
    cfg, _ = _walk_up(Path.cwd().resolve())
    return cfg is None or _values(cfg).get("default") is None


def _active() -> Ledger:
    """The active ledger, resolved now (``ledger._find``), its handle kept per location."""
    return _handle(*_find(False))


_OWN = frozenset({"__class__", "__dict__"})


class _Active(Ledger):
    """``L``: a ``Ledger`` that is whichever ledger is active at each use (``DAT_LEDGER``, else the config's
    ``default:``); every attribute is the active ledger's."""

    def __init__(self) -> None:                     # opens nothing: resolved at use
        pass

    def __getattribute__(self, name: str) -> Any:
        if name in _OWN:
            return object.__getattribute__(self, name)
        return getattr(_active(), name)

    def __repr__(self) -> str:
        try:
            return f"L = {_active()!r}"
        except LedgerError as e:
            return f"L (unresolved: {e})"

    def __enter__(self) -> Ledger:
        return _active().__enter__()

    def __exit__(self, *exc: Any) -> None:
        _active().__exit__(*exc)


ledgers = Ledgers()
L: Ledger = _Active()

__all__ = ["ledgers", "L", "Ledgers", "register_read_guard"]
