"""``Ledger``: the store handle. One constructor (A49), ``at`` for views, ``transaction`` for writes.

A ledger is a folder holding the database and the art store (A54.2), or a
Postgres DSN ``postgresql://…?art=<folder>`` (``pgstore``); its location is
either. ``Ledger(location)`` opens it; ``Ledger()`` finds it (``DAT_LEDGER``, else the
nearest ``.datconfig.yaml`` with a ``ledger:`` key at or above the working
directory, A37, A44); ``create=True`` is the one act that makes a ledger
(``Ledger(location, create=True)``), or a project in the working directory
(``Ledger(create=True)``: ``.datconfig.yaml`` with ``ledger: .dat/ledger``).
Without it nothing is ever created.
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
DEFAULT = ".dat/ledger"
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def _read_config(cfg: Path) -> Dict[str, Any]:
    data = yaml.safe_load(cfg.read_text()) or {}
    return data if isinstance(data, dict) else {}


def _walk_up(start: Path) -> Tuple[Optional[Path], List[Path]]:
    searched = []
    for folder in (start, *start.parents):
        searched.append(folder)
        cfg = folder / CONFIG
        if cfg.is_file():
            led = _read_config(cfg).get("ledger")
            if isinstance(led, str) and led:
                return cfg, searched
    return None, searched


def _relative(cfg: Path, led: str) -> Path:
    p = Path(led).expanduser()
    return p if p.is_absolute() else (cfg.parent / p)


class Ledger:
    """One logical store of quads ``(rev, subject, predicate, object)``."""

    def __init__(self, location: Union[str, Path, None] = None, *, create: bool = False) -> None:
        """Open the ledger at ``location``: a folder or a DSN (a ``Path``, or a ``str`` that is not a DSN, is a
        folder); ``None`` finds it (``DAT_LEDGER``, else ``.datconfig.yaml`` ``ledger:``)."""
        self._values: Dict[Any, Any] = {}
        cfg: Optional[Path] = None
        given: Any = location
        target: Union[str, Path]
        base = Path.cwd()                   # where a DSN's relative art= resolves
        if location is None and create:
            if os.environ.get(ENV):
                raise ValueError(f"Ledger(create=True) makes a project in the working directory, but {ENV} is "
                                 "set: ambiguous; unset it, or pass the location")
            cfg = Path.cwd() / CONFIG
            data = _read_config(cfg) if cfg.is_file() else {}
            led = data.get("ledger")
            if not (isinstance(led, str) and led):
                text = cfg.read_text() if cfg.is_file() else ""
                if text and not text.endswith("\n"):
                    text += "\n"
                cfg.write_text(text + f"ledger: {DEFAULT}\n")
                led = DEFAULT
            base = cfg.parent
            target = led if is_dsn(led) else _relative(cfg, led)
            given = target
        elif location is None:
            env = os.environ.get(ENV)
            if env:
                given = env
                target = env if is_dsn(env) else Path(env).expanduser()
            else:
                cfg, searched = _walk_up(Path.cwd().resolve())
                if cfg is None:
                    raise LedgerError(f"no ledger: {ENV} unset and no {CONFIG} with a 'ledger:' key in "
                                      + ", ".join(str(s) for s in searched) + " (Ledger(create=True) makes one)")
                led = _read_config(cfg)["ledger"]
                base = cfg.parent
                target = led if is_dsn(led) else _relative(cfg, led)
                given = target
        else:
            target = location if is_dsn(location) else Path(location).expanduser()
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
        if cfg is not None and location is None and not create:
            self._assert_mounts(cfg)

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
        """A frozen view: ``None`` the top, an ``int`` (or digit string) a revision, ``"M.m.p"`` a ledger version."""
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
            found = [r.rev for r in Rev(self, top).history("db", "version", which) if r.added]
            if not found:
                raise KeyError(f"no revision set the ledger version {which}")
            return found[-1]
        raise TypeError(f"at takes None, an int revision or a version string M.m.p, not {which!r}")

    def transaction(self, *, by: Union[str, Dict[str, Any]], lock: Optional[float] = None,
                    **preds: Any) -> Transaction:
        """A write set that becomes one revision on exit; use it only as ``with ... as t:``. Its
        ``db/tx/<rev>`` carries ``db/by``, ``db/time`` (UTC, every transaction) and the keywords.
        ``by`` is a non-empty ``str`` or a JSON ``dict`` (DAT 1024), read back as written."""
        return Transaction(self, by, lock, preds)


__all__ = ["Ledger", "ENV", "CONFIG"]
