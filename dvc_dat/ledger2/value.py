"""``Value``: everything the ledger holds and hands back, with its provenance on it.

A subclass says how it becomes bytes (``encode``) and back (``decode``). The
provenance half (``subject``, ``rev``, ``trace``, ``sealed``) is set by
``Transaction.seal``, ``Fn.__call__`` and ``Ref.load``; a subclass's own
``__init__`` need not call ``super().__init__``. Shipped subclasses:
``Pickled`` (any pickleable object), ``Table`` (a pandas frame as parquet),
``Dat`` (a folder, encoded as its content manifest).
"""

from __future__ import annotations

import io
import json
import os
import pickle
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Dict, Mapping, Optional

from .codec import canonical, sha256

if TYPE_CHECKING:
    from .rev import Rev
    from .store import ArtStore

_EMPTY: Mapping[str, str] = MappingProxyType({})


class Value:
    """The object itself, with its provenance on it."""

    #: Item name -> version or hash: what producing a value read.
    Trace: ClassVar[Any] = Mapping[str, str]

    subject: Optional[str] = None
    rev: Optional["Rev"] = None
    trace: Mapping[str, str] = _EMPTY
    sealed: bool = False

    def encode(self) -> bytes:
        """The bytes to store."""
        raise NotImplementedError(f"{type(self).__name__} does not say how it encodes")

    @classmethod
    def decode(cls, data: bytes, store: "ArtStore") -> "Value":
        """The object from its bytes."""
        raise NotImplementedError(f"{cls.__name__} does not say how it decodes")

    def _parts(self) -> Dict[str, bytes]:
        """Further bytes, by hash, that ``decode`` will fetch from the store (a folder's files)."""
        return {}

    @property
    def hash(self) -> str:
        """sha256 of ``encode()``; fixed once sealed."""
        cached = self.__dict__.get("_hash")
        if cached is not None:
            return cached
        h = sha256(self.encode())
        if self.sealed:
            self.__dict__["_hash"] = h
        return h

    def matches(self, rev: "Rev") -> bool:
        """Every trace item at its value at ``rev``: the hit test."""
        return rev._matches(dict(self.trace))

    def diff(self, other: "Value") -> Dict[str, tuple]:
        """The trace items whose values differ: item -> (mine, theirs); ``None`` where one lacks it."""
        out = {}
        for k in sorted(set(self.trace) | set(other.trace)):
            a, b = self.trace.get(k), other.trace.get(k)
            if a != b:
                out[k] = (a, b)
        return out

    def same_as(self, other: Optional["Value"]) -> bool:
        """``hash == other.hash``; ``False`` for ``None``."""
        return other is not None and self.hash == other.hash

    def _provenance(self, *, subject: Optional[str], rev: Optional["Rev"], trace: Mapping[str, str],
                    sealed: bool) -> None:
        self.subject = subject
        self.rev = rev
        self.trace = MappingProxyType(dict(trace))
        self.sealed = sealed
        self.__dict__.pop("_hash", None)


def dotted(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


class Pickled(Value):
    """Any pickleable object; ``obj`` is the object."""

    def __init__(self, obj: Any) -> None:
        self.obj = obj

    def encode(self) -> bytes:
        return pickle.dumps(self.obj, protocol=4)

    @classmethod
    def decode(cls, data: bytes, store: "ArtStore") -> "Pickled":
        return cls(pickle.loads(data))

    def __repr__(self) -> str:
        return f"Pickled({self.obj!r})"


class Table(Value):
    """A pandas DataFrame, stored as parquet (needs ``pyarrow``)."""

    def __init__(self, table: Any) -> None:
        self.table = table

    def encode(self) -> bytes:
        return self.table.to_parquet(index=True)

    @classmethod
    def decode(cls, data: bytes, store: "ArtStore") -> "Table":
        import pandas as pd

        return cls(pd.read_parquet(io.BytesIO(data)))


class Dat(Value):
    """A folder: encodes as its content manifest, ``{"files": {relpath: sha256}}``; the files go to the store."""

    def __init__(self, path: Any) -> None:
        self.path = Path(path)

    def _files(self) -> Dict[str, bytes]:
        out = {}
        for root, _dirs, names in os.walk(self.path):
            for n in names:
                p = Path(root, n)
                out[p.relative_to(self.path).as_posix()] = p.read_bytes()
        return out

    def encode(self) -> bytes:
        return canonical({"files": {k: sha256(v) for k, v in sorted(self._files().items())}}).encode()

    def _parts(self) -> Dict[str, bytes]:
        return {sha256(v): v for v in self._files().values()}

    @classmethod
    def decode(cls, data: bytes, store: "ArtStore") -> "Dat":
        manifest = json.loads(data.decode())
        dest = store.root / "dats" / sha256(data).split(":", 1)[1][:16]
        for rel, h in manifest["files"].items():
            p = dest / rel
            if not p.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(store.get(h))
        dest.mkdir(parents=True, exist_ok=True)
        return cls(dest)
