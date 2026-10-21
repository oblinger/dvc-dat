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
from typing import TYPE_CHECKING, Any, ClassVar, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple

from .codec import canonical, sha256

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
        """The object from its bytes. A subclass whose ``decode`` also accepts ``name=`` is passed the
        name it is loaded by (an alias), or ``None`` when loaded by its subject."""
        raise NotImplementedError(f"{cls.__name__} does not say how it decodes")

    def _parts(self) -> Iterable["Part"]:
        """Further bytes that ``decode`` will fetch from the store (a folder's files), as
        ``(sha256, source)``: a ``Path``, or a zero-arg opener returning a binary stream. Streamed into
        the store one at a time; never held in memory whole."""
        return ()

    def _after_seal(self, store: "ArtStore") -> None:
        """Hook run once the value is sealed (a ``Dat`` moves to its stored folder)."""

    def seal(self, to: Any = None, *, keep: bool = False, deps: Iterable[Any] = (), alias: Optional[str] = None,
             provenance: Optional[str] = None, by: Optional[str] = None) -> str:
        """Fix the value's identity; with a transaction or a ledger, save it too.

        ``v.seal()`` writes to no ledger: it freezes ``preds``, fixes the bytes' hash, ``deps``,
        ``provenance``, the environment and the time, writes them as a seal record in this machine's
        kept folder (``kept``; a later process reopens a sealed ``Dat`` from it with
        ``Dat.sealed_at_path``), and returns the hash. With ``keep=True`` it also copies the bytes
        into the kept cache, so the source may change.
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
        from .kept import Kept, SealedFn, SealedRef, env_record, preds_record, ref_record
        from .rev import Ref
        from .sandbox import unguarded
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
            if not isinstance(d, (Value, Ref, Fn, SealedRef, SealedFn)):
                raise TypeError(f"a dep is a Value, a Ref or an Fn, not {type(d).__name__}")
        stamp = _now()
        env = current_env()
        record: Dict[str, Any] = {"preds": preds_record(self.preds), "deps": [ref_record(d) for d in deps]}
        data = self.encode()
        h = sha256(data)
        record.update(hash=h, kind=dotted(type(self)), sealed_at=stamp, path=self._seal_path(),
                      provenance=provenance, env=env_record(env), bytes=self._seal_bytes(data))
        with unguarded():                       # the ledger's own write, also inside a sandboxed body
            entry = Kept().seal(record, data if keep else None, self._parts() if keep else ())
        self._forget()              # the hash is fixed: a later check (SealBroken) hashes the source anew
        self.__dict__["_local"] = {"hash": h, "deps": deps, "provenance": provenance, "env": env,
                                   "kept": keep, "entry": entry}
        self.__dict__["_preds"] = FrozenPreds(self.preds)
        self.__dict__["_hash"] = h
        self.sealed_at = stamp
        self.sealed = True
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
        self.sealed_at = record["sealed_at"]
        self.sealed = True

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

            raise SealBroken(f"{type(self).__name__} sealed at {self.sealed_at}: its kept bytes were purged and "
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
        return f"<{type(self).__name__} {'sealed, saved nowhere' if self.sealed else 'unsealed'}>"


def _now() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    """A folder: encodes as its content manifest, ``{"files": {relpath: sha256}}``; the files go to the store.

    Each file is hashed in 1 MiB blocks and never held in memory; the per-file hashes are cached
    on the object, keyed by each file's (size, mtime, inode), so ``encode``, ``_parts`` and a save
    walk the folder but hash a file once. The files of a saved or loaded ``Dat`` are hardlinks
    into the art store where the filesystem allows: write a new folder, never edit one in place.
    """

    def __init__(self, path: Any) -> None:
        self.path = Path(path)

    def _walk(self) -> Iterator[Tuple[str, Path]]:
        """``(relpath, path)`` of every file in the value, in sorted order (``__pycache__`` skipped)."""
        for root, dirs, names in os.walk(self.path):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for n in sorted(names):
                p = Path(root, n)
                yield p.relative_to(self.path).as_posix(), p

    def _manifest(self) -> Dict[str, str]:
        """``{relpath: sha256}`` of the folder, rehashing only files whose (size, mtime, inode) moved."""
        from .store import file_sha

        cache = self.__dict__.get("_shas") or {}
        new: Dict[str, Tuple[tuple, str]] = {}
        for rel, p in self._walk():
            st = p.stat()
            sig = (st.st_size, st.st_mtime_ns, st.st_ino, st.st_dev)
            hit = cache.get(rel)
            new[rel] = (sig, hit[1] if hit is not None and hit[0] == sig else file_sha(p))
        self.__dict__["_shas"] = new
        return {rel: h for rel, (_sig, h) in sorted(new.items())}

    def _forget(self) -> None:
        self.__dict__.pop("_shas", None)

    def _seal_path(self) -> Optional[str]:
        return str(self.path.resolve())

    def _seal_bytes(self, data: bytes) -> int:
        return sum(sig[0] for sig, _h in (self.__dict__.get("_shas") or {}).values())

    @classmethod
    def sealed_at_path(cls, path: Any, *, name: Optional[str] = None) -> Optional["Dat"]:
        """The ``Dat`` sealed last at the folder ``path`` by ``v.seal()`` in any process and not saved
        since, reopened from its seal record (``kept``); ``None`` when no record names the folder.

        ``v.seal(t)`` on it saves it exactly as the sealing process would have: the same subject (its
        deps, provenance, environment and time are the record's), ``SealBroken`` when a byte of the
        folder changed since unless kept, the kept bytes when kept. The object is made as ``kind(path)``,
        ``kind`` the class the record names (a subclass of this one). ``name`` is the alias it will be
        saved under: a value sealed with it as a dep before it is saved binds the dep through that
        name at its own save, which refuses until the name holds these bytes.
        """
        import importlib

        from .kept import Kept

        record = Kept().for_path(path)
        if record is None:
            return None
        mod, _, attr = record["kind"].rpartition(".")
        try:
            kind = getattr(importlib.import_module(mod), attr)
        except (ImportError, AttributeError, ValueError):
            raise ImportError(f"{path}: sealed as {record['kind']}, which does not import") from None
        if not (isinstance(kind, type) and issubclass(kind, cls)):
            raise TypeError(f"{path}: sealed as {record['kind']}, not a {cls.__name__}")
        obj = kind(Path(record["path"]))       # a Dat is made from its folder, as by hand
        obj._reopen(record, name)
        return obj

    def _present(self) -> bool:
        """Is the folder this value was loaded into still there, the same folder (a stat)?"""
        import stat

        try:
            st = self.path.stat()
        except OSError:
            return False
        return stat.S_ISDIR(st.st_mode) and self.__dict__.get("_dir_id") in (None, (st.st_dev, st.st_ino))

    def encode(self) -> bytes:
        return canonical({"files": self._manifest()}).encode()

    def _parts(self) -> List["Part"]:
        seen: Dict[str, Path] = {}
        manifest = self._manifest()
        for rel, p in self._walk():
            seen.setdefault(manifest[rel], p)
        return list(seen.items())

    @classmethod
    def kind_ok(cls, kind: str) -> bool:
        """Does a folder whose ``_spec_`` names ``dat.kind`` ``kind`` load as this class (beside the
        class its ``db/value`` row names)? Default: the class's dotted name or its bare name."""
        return kind in (dotted(cls), cls.__name__)

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
    def _materialise(data: bytes, store: "ArtStore", name: Optional[str] = None) -> Path:
        """The folder of a manifest, under ``<store root>/dats/``: at ``<name>`` when a name is given,
        else at the manifest hash's first 16 hex. Files are placed by ``store.get_to`` (hardlinks on
        the same filesystem); a named folder holding other content is replaced."""
        from .sandbox import unguarded             # the store's own write, also inside a sandboxed body

        manifest = json.loads(data.decode())
        files: Dict[str, str] = manifest["files"]
        if name is not None:
            parts = Path(name).parts
            if not parts or Path(name).is_absolute() or any(x in ("..", ".", "") for x in parts):
                raise ValueError(f"a Dat loaded as {name!r}: a name is a relative path without . or ..")
            dest = store.root / "dats" / Path(*parts)
        else:
            dest = store.root / "dats" / sha256(data)[:16]
        with unguarded():
            if name is not None and dest.exists() and not _holds(dest, files, store):
                import shutil

                old = dest.with_name(f"{dest.name}.old-{os.getpid()}-{id(data):x}")
                dest.rename(old)
                shutil.rmtree(old, ignore_errors=True)
            for rel, h in files.items():
                p = dest / rel
                if not p.exists():
                    store.get_to(h, p)
            dest.mkdir(parents=True, exist_ok=True)
        return dest

    @classmethod
    def decode(cls, data: bytes, store: "ArtStore", *, name: Optional[str] = None) -> "Dat":
        obj = cls.__new__(cls)
        obj.path = cls._materialise(data, store, name)
        return obj

    def _after_seal(self, store: "ArtStore") -> None:
        self._forget()
        self.path = self._materialise(store.get(self.hash), store)       # the manifest as stored


def _holds(dest: Path, files: Mapping[str, str], store: "ArtStore") -> bool:
    """Does the folder hold exactly these files with these hashes (a linked file is checked by inode)?"""
    from .store import file_sha

    found = set()
    for root, _dirs, names in os.walk(dest):
        for n in names:
            found.add(Path(root, n).relative_to(dest).as_posix())
    if found != set(files):
        return False
    for rel, h in files.items():
        p, blob = dest / rel, store.path(h)
        try:
            if os.path.samefile(p, blob):
                continue
        except OSError:
            pass
        if file_sha(p) != h:
            return False
    return True
