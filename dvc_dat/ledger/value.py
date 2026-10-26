"""``Value``: everything the ledger holds and hands back, with its provenance on it.

A subclass says how it becomes bytes (``encode``) and back (``decode``) and,
with ``@ledger_class(preds=...)``, which pred names its values may carry.
``preds`` is a plain dict while the value is unsealed, filled by whoever builds
it; the seal (``v.seal(t)`` or an ``run``) freezes it into a
read-only mapping and fixes ``subject``, ``rev`` and ``dependencies`` (Q25 (D)). A
subclass's own ``__init__`` need not call ``super().__init__``. Shipped
subclasses: ``Value.Blob`` (any Python object, pickled), ``Value.Table`` (parquet), and
``dvc_dat.core.Dat`` (a dat: its folder, encoded as its content manifest, DAT 1038).
"""

from __future__ import annotations

import io
import pickle
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Dict, Iterable, Mapping, Optional, Tuple, Union

from .codec import sha256

if TYPE_CHECKING:
    from .rev import Rev
    from .store import ArtStore, Part

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
    Dependencies: ClassVar[Any] = Mapping[str, str]
    #: The pred names a kind declares (``@ledger_class``); none by default.
    _ledger_preds: ClassVar[tuple] = ()

    subject: Optional[str] = None
    rev: Optional["Rev"] = None
    dependencies: Mapping[str, str] = _EMPTY
    #: The seal's moment, UTC ``YYYY-MM-DDTHH:MM:SSZ``, once the identity is fixed by ``v.seal()`` or a save;
    #: ``None`` while unsealed, so it reads as the boolean too.
    sealed: Optional[str] = None

    def __init__(self, *, name: Optional[str] = None) -> None:
        if name is not None:
            self.name = name

    @property
    def name(self) -> Optional[str]:
        """The value's one name (Q36): an alias, relative to the data folder, not part of its identity.

        Saved: the alias naming it at the head (the latest written), else ``None``. Unsaved: the name a
        save will give it. Setting it on a saved value moves its name in a revision of its own (a name
        names one value; a value has one name), and a ``Dat``'s folder is rebuilt at the new name."""
        if self.subject is not None:
            ledger = self.rev.ledger if self.rev is not None else self.__dict__.get("_ledger")
            if ledger is not None:
                from .rev import name_of

                return name_of(ledger.at(), self.subject)
        return self.__dict__.get("_name")

    @name.setter
    def name(self, value: Optional[str]) -> None:
        if value is not None:
            check_name(value)
        if self.subject is None:
            self.__dict__["_name"] = value
            return
        ledger = self.rev.ledger if self.rev is not None else self.__dict__.get("_ledger")
        if ledger is None:
            raise ValueError(f"{self!r}: saved, but its ledger is not known here")
        self._rename(ledger, value)

    def _rename(self, ledger: Any, name: Optional[str]) -> None:
        """Make ``name`` this saved value's one name (``None``: unname it); a ``Dat`` moves to its folder."""
        from .rev import name_of

        head = ledger.at()
        assert self.subject is not None
        others = [n for n in head._aliases_of(self.subject) if n != name]
        owns = name is None or (name_of(head, self.subject) == name
                                and any(h.obj == "str:" + self.subject for h in head._held(name, "db/alias")))
        if others or not owns:
            with ledger.transaction(by="name") as t:
                t._name_value(self.subject, name)
        if name is not None:
            self._at_name(ledger._store.art, name)

    def _at_name(self, store: "ArtStore", name: str) -> None:
        """Hook: a named value's place on disk (a ``Dat``'s folder at its name)."""

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
        """The object from its bytes. A subclass whose ``decode`` also accepts ``name=`` is passed the
        name it is loaded by (an alias), or ``None`` when loaded by its subject."""
        raise NotImplementedError(f"{cls.__name__} does not say how it decodes")

    def _parts(self) -> Iterable["Part"]:
        """Further bytes that ``decode`` will fetch from the store (a folder's files), as
        ``(sha256, source)``: a ``Path``, or a zero-arg opener returning a binary stream. Streamed into
        the store one at a time; never held in memory whole."""
        return ()

    def _after_seal(self, store: "ArtStore", name: Optional[str] = None) -> None:
        """Hook run once the value is sealed (a ``Dat`` moves to its stored folder, at its name if named)."""

    def _pred_names(self) -> Tuple[str, ...]:
        """The pred names this value may carry: its class's ``@ledger_class(preds=...)`` (a ``Dat`` adds
        its folder's own)."""
        return tuple(type(self)._ledger_preds)

    def _sealable(self) -> None:
        """Hook: refuse a value that may not be sealed as it stands (a ``Dat`` never saved)."""

    def seal(self, to: Any = True, *, keep: bool = False, deps: Iterable[Any] = (), name: Optional[str] = None,
             provenance: Optional[str] = None, by: Optional[Union[str, Dict[str, Any]]] = None) -> str:
        """Fix the value's identity; with a transaction or a ledger, save it too. ``to`` takes what
        ``seal=`` on a run takes (DAT 1028), so ``f(seal=x)`` and a later ``v.seal(x)`` end in one place.

        ``v.seal()`` (``v.seal(True)``) writes to no ledger: it freezes ``preds``, fixes the bytes' hash,
        ``deps``, ``provenance``, the environment and the time, writes them as a seal record in this
        machine's kept folder (``kept``; a later process reopens a sealed ``Dat`` from it with
        ``Dat.sealed_at_path``), and returns the hash. With ``keep=True`` it also copies the bytes
        into the kept cache, so the source may change.
        ``to`` a ``Transaction`` saves into it: the subject is ``<hash of (dependencies, preds, bytes)>``
        and lands with that revision or not at all. ``to`` a ``Ledger`` opens and commits a
        one-value transaction of its own, written ``by`` (a ``str`` or a JSON ``dict``; default: the
        provenance, else ``seal``).
        Saving a value sealed earlier saves the state it was sealed in (its deps, provenance and
        environment), and refuses with ``SealBroken`` when its bytes changed since, unless kept.
        A run's result (``seal=False`` or ``True``) carries its trace: saving it writes the memo entry
        the run would have, so the next identical call hits, after the code check (``NotEvaluated``).
        ``v.seal(False)`` and ``v.seal("get")`` are ``TypeError``: nothing to do to an object.
        """
        from .ledger import Ledger
        from .txn import Transaction

        if to is True:
            if name is not None or by is not None:
                raise TypeError("name= and by= name a ledger write; v.seal() writes none (v.seal(t, name=...))")
            return self._seal_here(keep, tuple(deps), provenance)
        if to is False or (isinstance(to, str) and to == "get"):
            raise TypeError(f"v.seal({to!r}): {to!r} is a run's seal= level (keep nothing; look up); there is "
                            "nothing to do to an object. v.seal() seals here; v.seal(t) or v.seal(L) saves")
        if keep:
            raise TypeError("keep= is v.seal()'s; a save stores the bytes in the art store")
        if isinstance(to, Transaction):
            if by is not None:
                raise TypeError("by= names the writer of a transaction seal opens; this one is open already")
            return to._seal_value(self, deps=tuple(deps), name=name, provenance=provenance)
        if isinstance(to, Ledger):
            local = self.__dict__.get("_local")
            run = self.__dict__.get("_run")
            default = (f"eval:{run.name}" if run is not None else None) or (local and local["provenance"]) or "seal"
            with to.transaction(by=by if by is not None else provenance or default) as t:
                return t._seal_value(self, deps=tuple(deps), name=name, provenance=provenance)
        raise TypeError(f"seal takes True (the default), a Transaction or a Ledger, not {type(to).__name__}")

    def _seal_here(self, keep: bool, deps: tuple, provenance: Optional[str]) -> str:
        from .env import current_env
        from .errors import Undeclared
        from .fn import Fn
        from .kept import Kept, SealedFn, SealedRef, env_record, preds_record, ref_record
        from .rev import Ref
        from .sandbox import unguarded
        from .txn import check_provenance

        if self.subject is not None:
            raise ValueError(f"{self!r} is saved already; a different value is a new object")
        if self.sealed:
            raise ValueError(f"{self!r} is sealed already (at {self.sealed}); a different value is a new object")
        run = self.__dict__.get("_run")
        if run is not None and (deps or provenance is not None):
            raise TypeError(f"a run's result carries its trace ({run.name}); deps= and provenance= are a "
                            "hand seal's")
        provenance = check_provenance(provenance)
        self._sealable()
        declared = self._pred_names()
        extra = [k for k in self.preds if k not in declared]
        if extra:
            raise Undeclared(f"{', '.join(map(repr, extra))}: not a pred of {dotted(type(self))} "
                             f"(@ledger_class(preds={declared!r}))")
        for d in deps:
            if isinstance(d, Value) and not d.sealed:
                raise ValueError(f"dep {d!r} is unsealed: seal it first")
            if not isinstance(d, (Value, Ref, Fn, SealedRef, SealedFn)):
                raise TypeError(f"a dep is a Value, a Ref or an Fn, not {type(d).__name__}")
        stamp = _now()
        env = current_env()
        record: Dict[str, Any] = {"preds": preds_record(self.preds), "deps": [ref_record(d) for d in deps]}
        data = self.encode()
        h = sha256(data)
        record.update(hash=h, kind=dotted(type(self)), sealed_at=stamp, path=self._seal_path(),
                      provenance=provenance, env=env_record(env), bytes=self._seal_bytes(data))
        if run is not None:
            record["run"] = run.record()
        with unguarded():                       # the ledger's own write, also inside a sandboxed body
            entry = Kept().seal(record, data if keep else None, self._parts() if keep else ())
        self._forget()              # the hash is fixed: a later check (SealBroken) hashes the source anew
        self.__dict__["_local"] = {"hash": h, "deps": deps, "provenance": provenance, "env": env,
                                   "kept": keep, "entry": entry}
        self.__dict__["_preds"] = FrozenPreds(self.preds)
        self.__dict__["_hash"] = h
        self.sealed = stamp
        return h

    def _seal_path(self) -> Optional[str]:
        """The folder a seal record names (a ``Dat``'s); ``None`` for a value held in memory."""
        return None

    def _seal_bytes(self, data: bytes) -> int:
        """The size a seal record lists: of the encoding, for a value held in memory."""
        return len(data)

    def _reopen(self, record: Dict[str, Any], name: Optional[str]) -> None:
        """Make this object the value a seal record describes, sealed as the sealing process left it."""
        from .kept import env_from, preds_from, ref_from

        self.__dict__["_preds"] = FrozenPreds(preds_from(record["preds"]))
        self.__dict__["_local"] = {"hash": record["hash"], "deps": tuple(ref_from(d) for d in record["deps"]),
                                   "provenance": record["provenance"], "env": env_from(record["env"]),
                                   "kept": bool(record["kept"]), "entry": record["entry"]}
        self.__dict__["_hash"] = record["hash"]
        if name is not None:
            self.__dict__["_loaded_as"] = name
        if record.get("run") is not None:
            from .fn import RunTrace, attach_run

            attach_run(self, RunTrace.from_record(record["run"]))
        self.sealed = record["sealed_at"]

    def _kept(self) -> Optional[Dict[str, Any]]:
        """The kept entry of a ``v.seal(keep=True)``; ``None`` when the bytes were not kept, or were purged
        and the source still hashes to the sealed bytes; ``SealBroken`` when purged and the source changed."""
        local = self.__dict__.get("_local")
        if not (local and local["kept"]):
            return None
        from .kept import Kept

        try:
            return Kept().entry(local["entry"])
        except KeyError:
            if sha256(self.encode()) == local["hash"]:
                return None
            from .errors import SealBroken

            raise SealBroken(f"{type(self).__name__} sealed at {self.sealed}: its kept bytes were purged and "
                             "the source changed since; seal a new value") from None

    def _stored_bytes(self) -> bytes:
        """The encoding a save stores: the kept bytes when ``v.seal(keep=True)`` kept them, else ``encode()``."""
        e = self._kept()
        if e is not None:
            from .kept import Kept

            return Kept().get(e["hash"])
        return self.encode()

    def _stored_parts(self) -> Iterable["Part"]:
        """The parts a save stores: the kept blobs when kept, else ``_parts()``."""
        e = self._kept()
        if e is not None:
            from .kept import Kept

            k = Kept()
            return [(h, k.blob(h)) for h in e["parts"]]
        return self._parts()

    def _forget(self) -> None:
        """Drop whatever the subclass cached while encoding (a ``Dat``'s per-file hashes)."""

    def _present(self) -> bool:
        """Is a loaded value still what it was loaded as? (A ``Dat`` checks its folder is still there.)"""
        return True

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
        """Every dependency item at its value at ``rev``: the hit test; consults the memo only, never runs."""
        from .trace import trace_matches

        return trace_matches(rev, dict(self.dependencies))

    def diff(self, other: "Value") -> Dict[str, tuple]:
        """The dependency items whose values differ: item -> (mine, theirs), ``None`` where one lacks it."""
        out = {}
        for k in sorted(set(self.dependencies) | set(other.dependencies)):
            a, b = self.dependencies.get(k), other.dependencies.get(k)
            if a != b:
                out[k] = (a, b)
        return out

    def same_as(self, other: Optional["Value"]) -> bool:
        """``hash == other.hash``; ``False`` for ``None``."""
        return other is not None and self.hash == other.hash

    def _provenance(self, *, subject: str, rev: "Rev", dependencies: Mapping[str, str], preds: Mapping[str, Any],
                    loaded_as: Optional[str] = None) -> None:
        self.__dict__.pop("_hash", None)
        self.subject = subject
        self.rev = rev
        self.dependencies = MappingProxyType(dict(dependencies))
        if not self.sealed:                         # loaded: the seal's moment is on the ledger
            self.sealed = (rev.get(subject, "db/sealed-at") if rev is not None and subject else None) \
                or (rev.get(rev.tx, "db/time") if rev is not None else None) or "sealed"
        self.__dict__["_preds"] = FrozenPreds(preds)
        self.__dict__["_loaded_as"] = loaded_as
        self.__dict__.pop("_name", None)            # saved: the name is the ledger's now

    def _label(self) -> Optional[str]:
        """What it prints as (DAT 1036): its name at the head, else ``#`` + the hash's first 8;
        ``None`` for a draft, which has no identity yet."""
        if not self.sealed:
            return None
        ledger = self.rev.ledger if self.rev is not None else self.__dict__.get("_ledger")
        if self.subject and ledger is not None:
            from .rev import display_name

            return display_name(ledger, self.subject)
        return "#" + self.hash[:8]

    def _saved(self) -> bool:
        ledger = self.rev.ledger if self.rev is not None else self.__dict__.get("_ledger")
        return bool(self.sealed and self.subject and ledger is not None)

    def __repr__(self) -> str:
        """``<Video video/G1>`` saved, ``<Video sealed #2db69ce1>`` sealed locally, ``<Video draft>``."""
        label = self._label()
        if label is None:
            return f"<{type(self).__name__} draft>"
        return f"<{type(self).__name__} {label if self._saved() else 'sealed ' + label}>"

    def __str__(self) -> str:
        """The bare label (``video/G1``, ``#2db69ce1``); a draft has none and prints as its repr."""
        label = self._label()
        return repr(self) if label is None else label


def _now() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_name(name: Any) -> str:
    """A name is a non-empty relative path without ``.`` or ``..`` parts (an absolute path names nothing)."""
    if not isinstance(name, str) or not name:
        raise TypeError(f"a name is a non-empty str, not {name!r}")
    parts = Path(name).parts
    if Path(name).is_absolute() or any(x in ("..", ".", "") for x in parts):
        raise ValueError(f"{name!r}: a name is a relative path (to the data folder) without . or ..")
    return name


def dotted(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def takes_name(cls: type) -> bool:
    """Does ``cls.decode`` accept ``name=`` (a keyword named ``name``, or ``**kwargs``)?"""
    import inspect

    try:
        params = inspect.signature(cls.decode).parameters.values()       # type: ignore[attr-defined]
    except (TypeError, ValueError):
        return False
    return any(q.kind is q.VAR_KEYWORD or (q.name == "name" and q.kind in (q.KEYWORD_ONLY, q.POSITIONAL_OR_KEYWORD))
               for q in params)


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


class Blob(Value):
    """Any pickleable object; ``obj`` is the object. Declares no preds (A16)."""

    def __init__(self, obj: Any, *, name: Optional[str] = None) -> None:
        self.obj = obj
        super().__init__(name=name)

    def encode(self) -> bytes:
        return pickle.dumps(self.obj, protocol=4)

    @classmethod
    def decode(cls, data: bytes, store: "ArtStore") -> "Blob":
        return cls(pickle.loads(data))


class Table(Value):
    """A table stored as parquet: a ``pyarrow.Table`` or a pandas ``DataFrame`` (decodes to pyarrow)."""

    def __init__(self, table: Any, *, name: Optional[str] = None) -> None:
        self.table = table
        super().__init__(name=name)

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


Blob.__qualname__ = "Value.Blob"
Table.__qualname__ = "Value.Table"
Value.Blob = Blob      # type: ignore[attr-defined]
Value.Table = Table    # type: ignore[attr-defined]
