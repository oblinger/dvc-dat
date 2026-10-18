"""``Ledger``: the store handle. It opens, it gives views (``at``), it makes transactions."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml

from .errors import Multiple
from .rev import Rev
from .store import Store
from .txn import Transaction

#: The environment variable naming the ledger: a SQLite file, or a folder holding ``ledger2.db``.
ENV = "DAT_LEDGER"
CONFIG = ".datconfig.yaml"
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def _db_path(p: Union[str, Path]) -> Path:
    path = Path(p).expanduser()
    return path / "ledger2.db" if path.is_dir() or not path.suffix else path


def _from_config(start: Path) -> Optional[Path]:
    for folder in (start, *start.parents):
        cfg = folder / CONFIG
        if cfg.is_file():
            data = yaml.safe_load(cfg.read_text()) or {}
            led = data.get("ledger") if isinstance(data, dict) else None
            if isinstance(led, str) and led:
                p = Path(led).expanduser()
                return p if p.is_absolute() else folder / p
    return None


class Ledger:
    """One logical store of quads ``(rev, subject, predicate, object)``."""

    def __init__(self, path: Union[str, Path]) -> None:
        self.path = _db_path(path)
        self._store = Store(self.path)
        self._values: Dict[Any, Any] = {}

    def __repr__(self) -> str:
        return f"Ledger({str(self.path)!r})"

    @classmethod
    def open(cls, profile: Optional[str] = None) -> "Ledger":
        """The ledger at ``profile`` (a path), else ``DAT_LEDGER``, else ``.datconfig.yaml`` ``ledger:``."""
        if profile is not None:
            return cls(profile)
        env = os.environ.get(ENV)
        if env:
            return cls(env)
        found = _from_config(Path.cwd().resolve())
        if found is None:
            raise FileNotFoundError(f"no ledger: no profile given, {ENV} unset, and no {CONFIG} with a "
                                    f"'ledger:' path in {Path.cwd()} or above")
        return cls(found)

    def at(self, which: Union[int, str, None] = None) -> Rev:
        """A frozen view: ``None`` the top, an ``int`` (or digit string) a revision, ``"M.m.p"`` a ledger version."""
        top = self._store.top()
        if which is None:
            return Rev(self, top)
        if isinstance(which, str) and which.isdigit():
            which = int(which)
        if isinstance(which, bool):
            raise TypeError("at takes None, an int revision or a version string")
        if isinstance(which, int):
            if not 0 <= which <= top:
                raise KeyError(f"no revision {which}: the ledger runs 0..{top}")
            return Rev(self, which)
        if isinstance(which, str) and _VERSION.match(which):
            found = Rev(self, top)["ledger", "version", which]
            return found
        raise TypeError(f"at takes None, an int revision or a version string M.m.p, not {which!r}")

    def transaction(self, *, by: str, lock: Optional[float] = None, time: bool = False,
                    **preds: Any) -> Transaction:
        """A write set that becomes one revision on exit; use it only as ``with ... as t:``."""
        return Transaction(self, by, lock, time, preds)


__all__ = ["Ledger", "ENV", "Multiple"]
