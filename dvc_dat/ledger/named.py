"""``ledgers`` and ``L``: the project's ledgers by name, and the active one (SVP 239).

    from dvc_dat import L, ledgers
    ledgers.record.at()          # the entry `record` of .datconfig.yaml's `ledgers:` section
    ledgers["exp-jb-26"]         # a hyphenated name takes the item form
    L.at()                       # the active ledger: DAT_LEDGER, else `ledgers: {default: ...}`

Both resolve from the working directory at each use, never at import, so a
checkout without a default imports fine and refuses only when ``L`` is used. A
handle is opened once per ledger and kept for the process.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from .errors import LedgerError
from .ledger import CONFIG, Ledger, _find, _section, _target, _values, _walk_up

_handles: Dict[str, Ledger] = {}
_asserted: Set[Tuple[str, str]] = set()


def _handle(target: Any, given: Any, base: Path, cfg: Optional[Path]) -> Ledger:
    """One handle per ledger, shared by ``L`` and ``ledgers``; opened as the active ledger, it asserts the
    config's ``mounts:`` once, as ``Ledger()`` does."""
    key = str(target)
    led = _handles.get(key)
    if led is None:
        led = _handles[key] = Ledger._opened(target, given, base, None)
    if cfg is not None and (key, str(cfg)) not in _asserted:
        led._assert_mounts(cfg)
        _asserted.add((key, str(cfg)))
    return led


class Ledgers:
    """The ``ledgers:`` section of the nearest ``.datconfig.yaml`` (the override file's entries merged in):
    ``ledgers.<name>`` or ``ledgers["<name>"]`` is that ledger's ``Ledger``. A name with a hyphen has no
    attribute form; ``ledgers.exp_jb_26`` is ``AttributeError`` naming ``ledgers['exp-jb-26']``."""

    def _section(self) -> Tuple[Path, Dict[str, str]]:
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
        hyphen = name.replace("_", "-")
        if hyphen != name and hyphen in entries:
            raise AttributeError(f"ledgers.{name}: no such ledger; a hyphenated name takes the item form, "
                                 f"ledgers['{hyphen}']")
        raise AttributeError(f"ledgers.{name}: no such ledger in {cfg} ledgers: ({', '.join(entries) or 'none'})")

    def __iter__(self) -> Iterator[str]:
        return iter(list(self._section()[1]))

    def __contains__(self, name: object) -> bool:
        return name in self._section()[1]

    def __len__(self) -> int:
        return len(self._section()[1])

    def __dir__(self) -> List[str]:
        try:
            return [n for n in self._section()[1] if n.isidentifier()]
        except LedgerError:
            return []

    def __repr__(self) -> str:
        try:
            cfg, entries = self._section()
        except LedgerError as e:
            return f"ledgers (none: {e})"
        return f"ledgers({cfg}: {', '.join(entries)})"


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
