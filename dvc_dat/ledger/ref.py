"""``Ref``, ``Event``, ``Rev``, ``Value``: the ledger's plain-data records."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple, Type, Union

from ..core import Dat
from .types import Artifact, Node

#: A revision number: the id of a transaction.
Rev = int

#: What an object decodes to: a ``str``, a JSON document, or a ``Ref``.
Value = Union[str, Dict[str, Any], List[Any], "Ref"]


@dataclass(frozen=True, eq=False)
class Ref:
    """A reference to something the ledger's store holds: an artifact, a dat, or a subject.

    Plain data. ``type`` says which: a subclass of :class:`~dvc_dat.ledger.types.Artifact`,
    of ``dvc_dat.Dat``, or :class:`~dvc_dat.ledger.types.Node` (the default, so
    ``Ref("game/G7")`` names a subject). ``load`` and ``load_path`` are the
    fetch, through ``Ledger.default`` (an artifact or a subject) or
    ``Dat.manager`` (a dat).

    Two refs are equal when they point at the same thing: an artifact with a
    hash by its type and hash (so a ref saved under a given name equals the
    one read back from a row, which carries the hash), anything else by its
    type and name. ``size`` never takes part.
    """

    name: str
    hash: Optional[str] = None
    type: Type[Any] = Node
    size: Optional[int] = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError(f"a Ref's name is a non-empty str, not {self.name!r}")
        if not isinstance(self.type, type) or not (
            self.type is Node or issubclass(self.type, (Artifact, Dat))
        ):
            raise ValueError(f"a Ref's type is an Artifact class, a Dat class or Node, not {self.type!r}")
        if self.type is Artifact:
            raise ValueError("a Ref's type is a concrete artifact type (json, file, ckpt, video, …)")
        if self.hash is not None and not (isinstance(self.hash, str) and self.hash.startswith("sha256:")):
            raise ValueError(f"a Ref's hash is 'sha256:<hex>', not {self.hash!r}")

    @property
    def kind(self) -> str:
        """``"art"``, ``"dat"`` or ``"node"``: the row prefix this reference encodes under."""
        if self.type is Node:
            return "node"
        if issubclass(self.type, Artifact):
            return "art"
        return "dat"

    def _key(self) -> Tuple[str, Type[Any], str]:
        if self.kind == "art" and self.hash is not None:
            return ("art", self.type, self.hash)
        return (self.kind, self.type, self.name)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Ref) and self._key() == other._key()

    def __hash__(self) -> int:
        return hash(self._key())

    def __repr__(self) -> str:
        if self.type is Node:
            return f"Ref({self.name!r})"
        tname = getattr(self.type, "token", "") or self.type.__name__
        return f"Ref({self.name!r}, type={tname})"

    def load(self) -> Any:
        """The fetch, decoded by ``type``; ``FileNotFoundError`` when this store does not reach it."""
        if self.kind == "dat":
            return Dat.manager.load(self.name)
        return _default()._load_ref(self)

    def load_path(self, dest: Optional[Path] = None) -> Path:
        """The fetch as a place on disk: the store's own copy, or a copy at ``dest``. A subject has none."""
        if self.kind == "node":
            raise ValueError(f"{self!r} is a subject: it has no path")
        if self.kind == "dat":
            src = Path(Dat.manager.load_path(self.name))
        else:
            src = _default()._path_ref(self)
        if dest is None:
            return src
        dest = Path(dest)
        if src.is_dir():
            shutil.copytree(src, dest, dirs_exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
        return dest


def _default() -> Any:
    from .core import Ledger

    if Ledger.default is None:
        raise FileNotFoundError("no default ledger: a Ref resolves through Ledger.default, set by Ledger.open()")
    return Ledger.default


class Event(NamedTuple):
    """One row: the transaction's rev, the triple, and whether it was added or removed."""

    rev: Rev
    subject: str
    predicate: str
    object: Any  # a Value; `Any` because a NamedTuple field cannot hold the forward Union
    added: bool
