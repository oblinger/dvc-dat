"""``Ledger``: the store handle. One constructor (A49), ``at`` for views, ``transaction`` for writes.

A ledger is a folder holding the database and the art store (A54.2), or a
Postgres DSN ``postgresql://…?art=<folder>`` (``pgstore``); its location is
either. ``Ledger(location)`` opens it; ``Ledger()`` opens the project's *active*
ledger (A37, A44): ``DAT_LEDGER`` (a name from the config's ``ledgers:`` section,
or a location), else the nearest ``.datconfig.yaml`` at or above the working
directory with a ``ledgers:`` section (its ``default:``, the override file
``.datconfig.override.yaml`` beside it winning) or a single ``ledger:`` key.
``create=True`` is the one act that makes a ledger (``Ledger(location,
create=True)``), or a project in the working directory (``Ledger(create=True)``:
``.datconfig.yaml`` with ``ledger: .dat/ledger``, or the active entry of its
``ledgers:``). Without it nothing is ever created.

The named handles (``ledgers.record``) and ``L``, the active ledger as one
object, are ``named``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

from .errors import LedgerError
from .rev import Rev
from .pgstore import PostgresStore, is_dsn
from .store import SqliteStore, Store
from .txn import Transaction

ENV = "DAT_LEDGER"
CONFIG = ".datconfig.yaml"
OVERRIDE = ".datconfig.override.yaml"
DEFAULT = ".dat/ledger"
NAME = re.compile(r"^[a-z][a-z0-9-]*$")    # a ledger's name in ``ledgers:``: lowercase, digits, hyphens
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")

Target = Union[str, Path]                  # a DSN, or a folder


def _read_config(cfg: Path) -> Dict[str, Any]:
    data = yaml.safe_load(cfg.read_text()) or {}
    return data if isinstance(data, dict) else {}


def _values(cfg: Path) -> Dict[str, Any]:
    """The config's keys with the override file beside it over them; ``ledgers:`` merges by name."""
    data = _read_config(cfg)
    over = cfg.parent / OVERRIDE
    if not over.is_file():
        return data
    extra = _read_config(over)
    merged = {**data, **extra}
    if isinstance(data.get("ledgers"), dict) and isinstance(extra.get("ledgers"), dict):
        merged["ledgers"] = {**data["ledgers"], **extra["ledgers"]}
    return merged


def _names_ledger(values: Dict[str, Any]) -> bool:
    led = values.get("ledger")
    return (isinstance(led, str) and bool(led)) or "ledgers" in values


def _walk_up(start: Path) -> Tuple[Optional[Path], List[Path]]:
    searched = []
    for folder in (start, *start.parents):
        searched.append(folder)
        cfg = folder / CONFIG
        if cfg.is_file() and _names_ledger(_values(cfg)):
            return cfg, searched
    return None, searched


def _relative(cfg: Path, led: str) -> Path:
    p = Path(led).expanduser()
    return p if p.is_absolute() else (cfg.parent / p)


def _target(cfg: Path, led: str) -> Target:
    return led if is_dsn(led) else _relative(cfg, led)


def _section(cfg: Path, values: Dict[str, Any]) -> Tuple[Dict[str, str], Optional[str]]:
    """The ``ledgers:`` section, checked: ``({name: location}, default name or None)``."""
    if values.get("ledger"):
        raise LedgerError(f"{cfg}: both 'ledger:' and 'ledgers:'; 'ledger: X' is the one-ledger project, "
                          "keep one of the two")
    section = values.get("ledgers")
    if not isinstance(section, dict):
        raise LedgerError(f"{cfg}: 'ledgers:' is a mapping of name to location, got {section!r}")
    entries: Dict[str, str] = {}
    for name, loc in section.items():
        if name == "default":
            continue
        if not (isinstance(name, str) and NAME.match(name)):
            raise LedgerError(f"{cfg}: ledgers: {name!r} is not a ledger name (lowercase letters, digits and "
                              "hyphens, a letter first)")
        if not (isinstance(loc, str) and loc.strip()):
            raise LedgerError(f"{cfg}: ledgers: {name} is a folder or a DSN, got {loc!r}")
        entries[name] = loc
    default = section.get("default")
    if default is not None and not (isinstance(default, str) and default in entries):
        raise LedgerError(f"{cfg}: ledgers: default: {default!r} names no entry of the section "
                          f"({', '.join(entries) or 'none'})")
    return entries, default


def _entries(cfg: Path) -> Dict[str, str]:
    """``{name: location}`` of the config's ``ledgers:`` section, the override file's merged in."""
    return _section(cfg, _values(cfg))[0]


def _resolve(cfg: Optional[Path], values: Dict[str, Any],
             env: Optional[str]) -> Tuple[Target, Any, Path, Optional[Path]]:
    """The active ledger: ``(target, as named in errors, base for a DSN's relative art=, config whose mounts
    to assert or None)``. ``DAT_LEDGER`` first (an entry's name, else a location), then the section's
    ``default:``, then the one-ledger ``ledger:`` key."""
    if env:
        given: Any = env
        if cfg is not None and "ledgers" in values and NAME.match(env):
            entries, _ = _section(cfg, values)
            if env in entries:
                return _target(cfg, entries[env]), f"{env} ({ENV}, {cfg})", cfg.parent, cfg
            given = f"{env} ({ENV}: a location; not a name in {cfg} ledgers: {', '.join(entries) or 'none'})"
        return (env if is_dsn(env) else Path(env).expanduser()), given, Path.cwd(), None
    assert cfg is not None
    if "ledgers" in values:
        entries, default = _section(cfg, values)
        if default is None:
            raise LedgerError(f"no active ledger: {cfg} lists ledgers ({', '.join(entries) or 'none'}) and names "
                              f"no default; set {ENV}=<name>, or 'ledgers: {{default: <name>}}' in "
                              f"{cfg.parent / OVERRIDE}")
        target = _target(cfg, entries[default])
        return target, f"{default} ({cfg})", cfg.parent, cfg
    target = _target(cfg, values["ledger"])
    return target, target, cfg.parent, cfg


def _find(create: bool) -> Tuple[Target, Any, Path, Optional[Path]]:
    """``Ledger(None)``'s resolution, from the working directory (``_resolve``)."""
    env = os.environ.get(ENV)
    if create:
        if env:
            raise ValueError(f"Ledger(create=True) makes a project in the working directory, but {ENV} is "
                             "set: ambiguous; unset it, or pass the location")
        here = Path.cwd() / CONFIG
        if here.is_file() and not isinstance(yaml.safe_load(here.read_text()) or {}, dict):
            raise LedgerError(f"{here}: not a mapping; Ledger(create=True) adds a 'ledger:' key to it")
        values = _values(here) if here.is_file() else {}
        if "ledgers" in values:
            return _resolve(here, values, None)
        led = values.get("ledger")
        if not (isinstance(led, str) and led):
            text = here.read_text() if here.is_file() else ""
            if text and not text.endswith("\n"):
                text += "\n"
            here.write_text(text + f"ledger: {DEFAULT}\n")
            led = DEFAULT
        target = _target(here, led)
        return target, target, here.parent, here
    if env and not NAME.match(env):              # a location: no config read
        return _resolve(None, {}, env)
    cfg, searched = _walk_up(Path.cwd().resolve())
    if cfg is None and not env:
        raise LedgerError(f"no ledger: {ENV} unset and no {CONFIG} with a 'ledger:' key or a 'ledgers:' section "
                          "in " + ", ".join(str(s) for s in searched) + " (Ledger(create=True) makes one)")
    return _resolve(cfg, _values(cfg) if cfg is not None else {}, env)


class Ledger:
    """One logical store of quads ``(rev, subject, predicate, object)``."""

    def __init__(self, location: Union[str, Path, None] = None, *, create: bool = False) -> None:
        """Open the ledger at ``location``: a folder or a DSN (a ``Path``, or a ``str`` that is not a DSN, is a
        folder); ``None`` opens the active ledger (``DAT_LEDGER``, else ``.datconfig.yaml``'s ``ledgers:``
        default or ``ledger:``)."""
        cfg: Optional[Path] = None
        target: Target
        if location is None:
            target, given, base, cfg = _find(create)
        else:
            if isinstance(location, str) and not location.strip():
                raise TypeError("Ledger(location): an empty location; pass a folder or a DSN, or None to find it")
            target = location if is_dsn(location) else Path(location).expanduser()
            given, base = location, Path.cwd()      # where a DSN's relative art= resolves
        self._open(target, given, base, create)
        if cfg is not None and not create:
            self._assert_mounts(cfg)

    @classmethod
    def _opened(cls, target: Target, given: Any, base: Path, cfg: Optional[Path]) -> "Ledger":
        """A handle on a resolved target (``named``, ``do``); ``cfg`` names the config whose mounts to assert."""
        led = cls.__new__(cls)
        led._open(target, given, base, False)
        if cfg is not None:
            led._assert_mounts(cfg)
        return led

    def _open(self, target: Target, given: Any, base: Path, create: bool) -> None:
        self._values: Dict[Any, Any] = {}
        self._store: Store
        if isinstance(target, str):
            store = PostgresStore(target, base=base, create=create)
            self._store = store
            self.path: Union[str, Path] = store.dsn
            self._shown = store.redacted
        else:
            folder = target.resolve()
            if folder.exists() and not folder.is_dir():
                raise LedgerError(f"{folder}: a ledger is a folder (database and art store inside), not a file")
            if not (folder / "ledger.db").is_file() and not create:
                raise LedgerError(f"no ledger at {given}")
            self.path = folder
            self._shown = str(folder)
            self._store = SqliteStore(folder)

    def __repr__(self) -> str:
        return f"Ledger({self._shown!r})"

    def close(self) -> None:
        """Close the handle's database connections (every thread's); a later read or write reopens."""
        self._store.close()

    def __enter__(self) -> "Ledger":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _assert_mounts(self, cfg: Path) -> None:
        """``mounts:`` sugar: assert the rows when they differ from what the ledger holds (A47, A54.3)."""
        mounts = _read_config(cfg).get("mounts") or {}
        if not isinstance(mounts, dict) or not mounts:
            return
        from .env import _toplevel, repo_name
        from .fn import refuse_mnt

        for prefix in mounts:
            refuse_mnt(str(prefix), f"{cfg} mounts:")
        top = _toplevel(str(cfg.parent))
        repo = repo_name(Path(top)) if top else cfg.parent.name
        rev = self.at()
        todo = []
        for prefix, root in mounts.items():
            s = f"db/mount/{prefix}"
            for p, o in (("db/root", str(root)), ("db/repo", repo)):
                if rev.get(s, p) != o:
                    todo.append((s, p, o))
        if todo:
            with self.transaction(by=f"config:{cfg}") as t:
                for s, p, o in todo:
                    t.add(s, p, o)

    def at(self, which: Union[int, str, None] = None) -> Rev:
        """A frozen view: ``None`` the top, an ``int`` (or digit string) a revision, ``"M.m.p"`` the latest revision whose
        ``db db/version`` row (the release, ``bump(t, "db")``) added that version, any other str the revision whose
        ``db db/tag`` row added that name."""
        top = self._store.top()
        if which is None:
            return Rev(self, top)
        if isinstance(which, bool):
            raise TypeError("at takes None, an int revision or a version string")
        if isinstance(which, str) and which.isdigit():
            which = int(which)
        if isinstance(which, int):
            if not 0 <= which <= top:
                raise KeyError(f"no revision {which}: the ledger runs 0..{top}")
            return Rev(self, which)
        if isinstance(which, str) and _VERSION.match(which):
            found = [r.rev for r in Rev(self, top).history("db", "db/version", which) if r.added]
            if not found:
                raise KeyError(f"no revision set the ledger version {which}")
            return found[-1]
        if isinstance(which, str) and which:
            found = [r.rev for r in Rev(self, top).history("db", "db/tag", which) if r.added]
            if found:
                return found[-1]
        raise TypeError(f"at takes None, an int revision, a version string M.m.p or a db/tag name, not {which!r}")

    def transaction(self, *, by: Union[str, Dict[str, Any]], lock: Optional[float] = None,
                    **preds: Any) -> Transaction:
        """A write set that becomes one revision on exit; use it only as ``with ... as t:``. Its
        ``db/tx/<rev>`` carries ``db/by``, ``db/time`` (UTC, every transaction) and the keywords.
        ``by`` is a non-empty ``str`` or a JSON ``dict`` (DAT 1024), read back as written."""
        return Transaction(self, by, lock, preds)


__all__ = ["Ledger", "ENV", "CONFIG", "OVERRIDE"]
