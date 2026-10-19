"""``Value``: everything the ledger holds and hands back, with its provenance on it.

A subclass says how it becomes bytes (``encode``) and back (``decode``) and,
with ``@ledger_class(preds=...)``, which pred names its values may carry.
``preds`` is a plain dict while the value is unsealed, filled by whoever builds
it; the seal (``Transaction.add_value`` or an ``eval``) freezes it into a
read-only mapping and fixes ``subject``, ``rev`` and ``trace`` (Q25 (D)). A
subclass's own ``__init__`` need not call ``super().__init__``. Shipped
subclasses: ``Pickled`` (any pickleable object), ``Table`` (parquet), ``Dat``
(a folder, encoded as its content manifest).
"""

from __future__ import annotations

import io
import json
import os
import pickle
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Dict, Iterable, Mapping, Optional

from .codec import canonical, sha256

if TYPE_CHECKING:
    from .rev import Rev
    from .store import ArtStore

_EMPTY: Mapping[str, str] = MappingProxyType({})


class FrozenPreds(dict):
    """A sealed value's preds: a dict that refuses every change (``TypeError``)."""

    def _refuse(self, *a: Any, **k: Any) -> None:
        raise TypeError("cannot modify a sealed value's preds")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _refuse  # type: ignore

    def __ior__(self, other: Any) -> "FrozenPreds":  # type: ignore[override]
        self._refuse()
        return self


class Value:
    """The object itself, with its provenance on it."""

    #: Item name -> version or hash: what producing a value read.
    Trace: ClassVar[Any] = Mapping[str, str]
    #: The pred names a kind declares (``@ledger_class``); none by default.
    _ledger_preds: ClassVar[tuple] = ()

    subject: Optional[str] = None
    rev: Optional["Rev"] = None
    trace: Mapping[str, str] = _EMPTY
    sealed: bool = False

    @property
    def preds(self) -> Dict[str, Any]:
        """A plain dict until sealed; a read-only mapping after."""
        d = self.__dict__.get("_preds")
        if d is None:
            d = self.__dict__["_preds"] = {}
        return d

    @preds.setter
    def preds(self, value: Any) -> None:
        if self.sealed:
            raise TypeError("cannot modify a sealed value's preds")
        self.__dict__["_preds"] = dict(value)

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

    def _after_seal(self, store: "ArtStore") -> None:
        """Hook run once the value is sealed (a ``Dat`` moves to its stored folder)."""

    @property
    def hash(self) -> str:
        """The hex sha256 of ``encode()``; fixed once sealed."""
        cached = self.__dict__.get("_hash")
        if cached is not None:
            return cached
        h = sha256(self.encode())
        if self.sealed:
            self.__dict__["_hash"] = h
        return h

    def matches(self, rev: "Rev") -> bool:
        """Every trace item at its value at ``rev``: the hit test; consults the memo only, never runs."""
        from .trace import trace_matches

        return trace_matches(rev, dict(self.trace))

    def diff(self, other: "Value") -> Dict[str, tuple]:
        """The trace items whose values differ: item -> (mine, theirs), ``None`` where one lacks it."""
        out = {}
        for k in sorted(set(self.trace) | set(other.trace)):
            a, b = self.trace.get(k), other.trace.get(k)
            if a != b:
                out[k] = (a, b)
        return out

    def same_as(self, other: Optional["Value"]) -> bool:
        """``hash == other.hash``; ``False`` for ``None``."""
        return other is not None and self.hash == other.hash

    def _provenance(self, *, subject: str, rev: "Rev", trace: Mapping[str, str], preds: Mapping[str, Any],
                    loaded_as: Optional[str] = None) -> None:
        self.__dict__.pop("_hash", None)
        self.subject = subject
        self.rev = rev
        self.trace = MappingProxyType(dict(trace))
        self.sealed = True
        self.__dict__["_preds"] = FrozenPreds(preds)
        self.__dict__["_loaded_as"] = loaded_as

    def __repr__(self) -> str:
        ledger = self.rev.ledger if self.rev is not None else self.__dict__.get("_ledger")
        if self.sealed and self.subject and ledger is not None:
            from .rev import display_name

            return display_name(ledger, self.subject)
        return f"<{type(self).__name__} unsealed>"


def dotted(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def ledger_class(*, preds: Iterable[str] = ()):
    """Class decorator: the pred names a ``Value`` subclass's values may carry (Q22); writes nothing."""
    names = tuple(preds)
    for n in names:
        if not isinstance(n, str) or not n or n.startswith("db/"):
            raise TypeError(f"a pred name is a non-empty str outside db/, not {n!r}")

    def deco(cls: type) -> type:
        if not (isinstance(cls, type) and issubclass(cls, Value)):
            raise TypeError(f"@ledger_class goes on a Value subclass, not {cls!r}")
        cls._ledger_preds = names
        return cls
    return deco


class Pickled(Value):
    """Any pickleable object; ``obj`` is the object. Declares no preds (A16)."""

    def __init__(self, obj: Any) -> None:
        self.obj = obj

    def encode(self) -> bytes:
        return pickle.dumps(self.obj, protocol=4)

    @classmethod
    def decode(cls, data: bytes, store: "ArtStore") -> "Pickled":
        return cls(pickle.loads(data))

    def __repr__(self) -> str:
        return super().__repr__() if self.sealed else f"Pickled({self.obj!r})"


class Table(Value):
    """A table stored as parquet: a ``pyarrow.Table`` or a pandas ``DataFrame`` (decodes to pyarrow)."""

    def __init__(self, table: Any) -> None:
        self.table = table

    def encode(self) -> bytes:
        import pyarrow as pa
        import pyarrow.parquet as pq

        t = self.table if isinstance(self.table, pa.Table) else pa.Table.from_pandas(self.table)
        buf = io.BytesIO()
        pq.write_table(t, buf)
        return buf.getvalue()

    @classmethod
    def decode(cls, data: bytes, store: "ArtStore") -> "Table":
        import pyarrow.parquet as pq

        return cls(pq.read_table(io.BytesIO(data)))


class Dat(Value):
    """A folder: encodes as its content manifest, ``{"files": {relpath: sha256}}``; the files go to the store."""

    def __init__(self, path: Any) -> None:
        self.path = Path(path)

    def _files(self) -> Dict[str, bytes]:
        out = {}
        for root, dirs, names in os.walk(self.path):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for n in sorted(names):
                p = Path(root, n)
                out[p.relative_to(self.path).as_posix()] = p.read_bytes()
        return out

    def encode(self) -> bytes:
        return canonical({"files": {k: sha256(v) for k, v in sorted(self._files().items())}}).encode()

    def _parts(self) -> Dict[str, bytes]:
        return {sha256(v): v for v in self._files().values()}

    @staticmethod
    def _materialise(data: bytes, store: "ArtStore") -> Path:
        manifest = json.loads(data.decode())
        dest = store.root / "dats" / sha256(data)[:16]
        for rel, h in manifest["files"].items():
            p = dest / rel
            if not p.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(store.get(h))
        dest.mkdir(parents=True, exist_ok=True)
        return dest

    @classmethod
    def decode(cls, data: bytes, store: "ArtStore") -> "Dat":
        obj = cls.__new__(cls)
        obj.path = cls._materialise(data, store)
        return obj

    def _after_seal(self, store: "ArtStore") -> None:
        self.path = self._materialise(self.encode(), store)
