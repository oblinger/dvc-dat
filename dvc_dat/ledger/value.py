"""``Value``: everything the ledger holds and hands back, with its provenance on it.

A subclass says how it becomes bytes (``encode``) and back (``decode``) and,
with ``@ledger_class(preds=...)``, which pred names its values may carry.
``preds`` is a plain dict while the value is unsealed, filled by whoever builds
it; the seal (``v.seal(t)`` or an ``eval``) freezes it into a
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
    #: Identity fixed: by ``v.seal()`` (saved nowhere yet, ``subject`` ``None``) or by a save.
    sealed: bool = False
    #: When the seal happened (UTC, ``YYYY-MM-DDTHH:MM:SSZ``).
    sealed_at: Optional[str] = None

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

    def seal(self, to: Any = None, *, keep: bool = False, deps: Iterable[Any] = (), alias: Optional[str] = None,
             provenance: Optional[str] = None, by: Optional[str] = None) -> str:
        """Fix the value's identity; with a transaction or a ledger, save it too.

        ``v.seal()`` writes nothing: it freezes ``preds``, records the bytes' hash, ``deps``,
        ``provenance``, the environment and the time, and returns the hash. With ``keep=True`` it
        also copies the bytes into this machine's kept cache (``kept``), so the source may change.
        ``to`` a ``Transaction`` saves into it: the subject is ``<hash of (trace, preds, bytes)>``
        and lands with that revision or not at all. ``to`` a ``Ledger`` opens and commits a
        one-value transaction of its own, written ``by`` (default: the provenance, else ``seal``).
        Saving a value sealed earlier saves the state it was sealed in (its deps, provenance and
        environment), and refuses with ``SealBroken`` when its bytes changed since, unless kept.
        """
        from .ledger import Ledger
        from .txn import Transaction

        if to is None:
            if alias is not None or by is not None:
                raise TypeError("alias= and by= name a ledger write; v.seal() writes none (v.seal(t, alias=...))")
            return self._seal_here(keep, tuple(deps), provenance)
        if keep:
            raise TypeError("keep= is v.seal()'s; a save stores the bytes in the art store")
        if isinstance(to, Transaction):
            if by is not None:
                raise TypeError("by= names the writer of a transaction seal opens; this one is open already")
            return to._seal_value(self, deps=tuple(deps), alias=alias, provenance=provenance)
        if isinstance(to, Ledger):
            local = self.__dict__.get("_local")
            with to.transaction(by=by or provenance or (local and local["provenance"]) or "seal") as t:
                return t._seal_value(self, deps=tuple(deps), alias=alias, provenance=provenance)
        raise TypeError(f"seal takes a Transaction or a Ledger, or nothing, not {type(to).__name__}")

    def _seal_here(self, keep: bool, deps: tuple, provenance: Optional[str]) -> str:
        from .env import current_env
        from .errors import Undeclared
        from .fn import Fn
        from .kept import Kept
        from .rev import Ref
        from .txn import check_provenance

        if self.subject is not None:
            raise ValueError(f"{self!r} is saved already; a different value is a new object")
        if self.sealed:
            raise ValueError(f"{self!r} is sealed already (at {self.sealed_at}); a different value is a new object")
        provenance = check_provenance(provenance)
        declared = type(self)._ledger_preds
        extra = [k for k in self.preds if k not in declared]
        if extra:
            raise Undeclared(f"{', '.join(map(repr, extra))}: not a pred of {dotted(type(self))} "
                             f"(@ledger_class(preds={declared!r}))")
        for d in deps:
            if isinstance(d, Value) and not d.sealed:
                raise ValueError(f"dep {d!r} is unsealed: seal it first")
            if not isinstance(d, (Value, Ref, Fn)):
                raise TypeError(f"a dep is a Value, a Ref or an Fn, not {type(d).__name__}")
        stamp = _now()
        data = self.encode()
        h = sha256(data)
        kept = Kept().put(dotted(type(self)), data, self._parts().values(), stamp) if keep else None
        self.__dict__["_local"] = {"hash": h, "deps": deps, "provenance": provenance, "env": current_env(),
                                   "kept": kept}
        self.__dict__["_preds"] = FrozenPreds(self.preds)
        self.__dict__["_hash"] = h
        self.sealed_at = stamp
        self.sealed = True
        return h

    def _stored_bytes(self) -> bytes:
        """The encoding a save stores: the kept bytes when ``v.seal(keep=True)`` kept them, else ``encode()``."""
        local = self.__dict__.get("_local")
        if local and local["kept"]:
            from .kept import Kept

            return Kept().get(local["kept"])
        return self.encode()

    def _stored_parts(self) -> Dict[str, bytes]:
        local = self.__dict__.get("_local")
        if local and local["kept"]:
            from .kept import Kept

            k = Kept()
            return {h: k.get(h) for h in k.entry(local["kept"])["parts"]}
        return self._parts()

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


def _now() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    def spec_kind(path: Path) -> Optional[str]:
        """The ``dat.kind`` a folder's ``_spec_.yaml`` (or ``_spec_.json``) names, if any."""
        for name in ("_spec_.yaml", "_spec_.json"):
            p = Path(path) / name
            if p.is_file():
                import yaml

                spec = yaml.safe_load(p.read_text()) or {}
                dat = spec.get("dat") if isinstance(spec, dict) else None
                kind = dat.get("kind") if isinstance(dat, dict) else None
                return kind if isinstance(kind, str) else None
        return None

    @staticmethod
    def _materialise(data: bytes, store: "ArtStore") -> Path:
        from .sandbox import unguarded             # the store's own write, also inside a sandboxed body

        manifest = json.loads(data.decode())
        dest = store.root / "dats" / sha256(data)[:16]
        with unguarded():
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
        self.path = self._materialise(self._stored_bytes(), store)
