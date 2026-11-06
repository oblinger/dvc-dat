"""``ledgers`` and ``L``: the project's ledgers by name, and the active one (SVP 239).

    from dvc_dat import L, dat, ledgers
    ledgers.record.at()          # the entry `record` of .datconfig.yaml's `ledgers:` section
    ledgers.prod_run26           # a name is a Python identifier; ledgers["prod_run26"] is the same handle
    L.at()                       # the active ledger: DAT_LEDGER, else `ledgers: {default: ...}`
    dat.at("do26@512")           # a revision on any registered ledger
    dat.load("do26@512:run/G1")  # a value by the global reference <ledger>@<rev>:<name-or-sha> (SVP 248)

Both resolve from the working directory at each use, never at import, so a
checkout without a default imports fine and refuses only when ``L`` is used. A
handle is opened once per ledger and kept for the process.

In a sandbox worker (SVP 1521 Q3 (A)) ``ledgers`` is the section of the caller's
config, shipped on the request (``shipped_section``, ``adopt_section``), and every
handle it gives is read-only; a body's ``ledgers.<name>``, ``dat.at`` and ``dat.load``
all come through it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from .errors import LedgerError
from .ledger import CONFIG, ENV, Ledger, _find, _section, _target, _values, _walk_up, opened
from .pgstore import is_dsn

_handles: Dict[str, Ledger] = {}
_asserted: Set[Tuple[str, str]] = set()
#: ``(config path, {name: location})`` of the caller's ``ledgers:`` section, as a request ships it; ``None``: it has none.
Section = Optional[Tuple[str, Dict[str, str]]]
#: In a sandbox worker: the section adopted, and how a location is opened there.
_worker: Optional[Tuple[Section, Any]] = None


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


class Ledgers:
    """The ``ledgers:`` section of the nearest ``.datconfig.yaml`` (the override file's entries merged in):
    ``ledgers.<name>`` or ``ledgers["<name>"]`` is that ledger's ``Ledger``; every name is a Python identifier
    (``ledger.NAME``), so every entry has the attribute form."""

    def _section(self) -> Tuple[Path, Dict[str, str]]:
        if _worker is not None:
            if _worker[0] is None:
                raise LedgerError("no ledgers: the caller of this sandboxed function has no 'ledgers:' section in a "
                                  f"{CONFIG}")
            return Path(_worker[0][0]), _worker[0][1]
        cfg, searched = _walk_up(Path.cwd().resolve())
        if cfg is None:
            raise LedgerError(f"no ledgers: no {CONFIG} with a 'ledgers:' section in "
                              + ", ".join(str(s) for s in searched))
        values = _values(cfg)
        if "ledgers" not in values:
            raise LedgerError(f"{cfg}: a one-ledger project ('ledger:', no 'ledgers:' section); its ledger is L")
        return cfg, _section(cfg, values)[0]

    def __getitem__(self, name: str) -> Ledger:
        cfg, entries = self._section()
        if name not in entries:
            raise KeyError(f"{name!r}: no such ledger in {cfg} ledgers: ({', '.join(entries) or 'none'})")
        target = _target(cfg, entries[name])
        return _handle(target, f"{name} ({cfg})", cfg.parent, None)

    def __getattr__(self, name: str) -> Ledger:
        if name.startswith("_"):
            raise AttributeError(name)
        cfg, entries = self._section()
        if name in entries:
            return self[name]
        raise AttributeError(f"ledgers.{name}: no such ledger in {cfg} ledgers: ({', '.join(entries) or 'none'})")

    def __iter__(self) -> Iterator[str]:
        return iter(list(self._section()[1]))

    def __contains__(self, name: object) -> bool:
        return name in self._section()[1]

    def __len__(self) -> int:
        return len(self._section()[1])

    def __dir__(self) -> List[str]:
        try:
            return list(self._section()[1])
        except LedgerError:
            return []

    def __repr__(self) -> str:
        try:
            cfg, entries = self._section()
        except LedgerError as e:
            return f"ledgers (none: {e})"
        return f"ledgers({cfg}: {', '.join(entries)})"


def shipped_section() -> Section:
    """The ``ledgers:`` section a sandboxed run sees: the caller's, by its working directory, in a worker the one it
    was given. A ``Section``, so that it crosses the pipe to the worker."""
    if _worker is not None:
        return _worker[0]
    cfg, _ = _walk_up(Path.cwd().resolve())
    if cfg is None or "ledgers" not in _values(cfg):
        return None
    return str(cfg), _section(cfg, _values(cfg))[0]


def adopt_section(section: Section, read_only: Any) -> None:
    """In a sandbox worker: ``ledgers`` is ``section``, its handles opened by ``read_only(target, given, base)``."""
    global _worker
    _worker = (section, read_only)


def handle_at(location: str) -> Ledger:
    """In a sandbox worker: the handle on a ledger named by location, for a ``Ref`` key on it."""
    return _handle(location if is_dsn(location) else Path(location), location, Path.cwd(), None)


def ledger_named(name: str) -> Ledger:
    """The ledger a ``<ledger>@<rev>`` names: one open in this process under that name, else the entry of
    ``ledgers:``; ``KeyError`` or ``LedgerError`` when neither knows it."""
    led = opened(name)
    return led if led is not None else ledgers[name]


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
        from ..core import Dat

        return Dat.manager.load(ref)
    return _value_at(_ledger_of(default).at(), ref)


def _no_ledger() -> bool:
    """Does this project name no ledger at all (no ``DAT_LEDGER``, no ``.datconfig.yaml`` ``ledger:``/``ledgers:``)?"""
    cfg, _ = _walk_up(Path.cwd().resolve())
    return cfg is None and not os.environ.get(ENV)


def _active() -> Ledger:
    """The active ledger, resolved now (``ledger._find``), its handle kept per location."""
    return _handle(*_find(False))


_OWN = frozenset({"__class__", "__dict__"})


class _Active(Ledger):
    """``L``: a ``Ledger`` that is whichever ledger is active at each use (``DAT_LEDGER``, else the config's
    ``ledgers:`` default or ``ledger:``); every attribute is the active ledger's."""

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

__all__ = ["ledgers", "L", "Ledgers"]
