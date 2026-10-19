"""``Ledger``: the store handle. One constructor (A49), ``at`` for views, ``transaction`` for writes.

A ledger is a folder holding the database and the art store (A54.2).
``Ledger(path)`` opens it; ``Ledger()`` finds it (``DAT_LEDGER``, else the
nearest ``.datconfig.yaml`` with a ``ledger:`` key at or above the working
directory, A37, A44); ``create=True`` is the one act that makes a ledger
(``Ledger(path, create=True)``), or a project in the working directory
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

    def __init__(self, path: Union[str, Path, None] = None, *, create: bool = False) -> None:
        self._values: Dict[Any, Any] = {}
        cfg: Optional[Path] = None
        given: Any = path
        if path is None and create:
            if os.environ.get(ENV):
                raise ValueError(f"Ledger(create=True) makes a project in the working directory, but {ENV} is "
                                 "set: ambiguous; unset it, or pass the path")
            cfg = Path.cwd() / CONFIG
            data = _read_config(cfg) if cfg.is_file() else {}
            led = data.get("ledger")
            if not (isinstance(led, str) and led):
                text = cfg.read_text() if cfg.is_file() else ""
                if text and not text.endswith("\n"):
                    text += "\n"
                cfg.write_text(text + f"ledger: {DEFAULT}\n")
                led = DEFAULT
            folder = _relative(cfg, led)
            given = folder
        elif path is None:
            env = os.environ.get(ENV)
            if env:
                given = env
                folder = Path(env).expanduser()
            else:
                cfg, searched = _walk_up(Path.cwd().resolve())
                if cfg is None:
                    raise LedgerError(f"no ledger: {ENV} unset and no {CONFIG} with a 'ledger:' key in "
                                      + ", ".join(str(s) for s in searched) + " (Ledger(create=True) makes one)")
                folder = _relative(cfg, _read_config(cfg)["ledger"])
                given = folder
        else:
            folder = Path(path).expanduser()
        folder = folder.resolve()
        if folder.exists() and not folder.is_dir():
            raise LedgerError(f"{folder}: a ledger is a folder (database and art store inside), not a file")
        if not (folder / "ledger.db").is_file() and not create:
            raise LedgerError(f"no ledger at {given}")
        self.path = folder
        self._store: Store = SqliteStore(folder)
        if cfg is not None and path is None and not create:
            self._assert_mounts(cfg)

    def __repr__(self) -> str:
        return f"Ledger({str(self.path)!r})"

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
            found = Rev(self, top).asserted("db", "version", which)
            if not found:
                raise KeyError(f"no revision set the ledger version {which}")
            return found[-1]
        raise TypeError(f"at takes None, an int revision or a version string M.m.p, not {which!r}")

    def transaction(self, *, by: str, lock: Optional[float] = None, time: bool = False,
                    **preds: Any) -> Transaction:
        """A write set that becomes one revision on exit; use it only as ``with ... as t:``."""
        return Transaction(self, by, lock, time, preds)


__all__ = ["Ledger", "ENV", "CONFIG"]
