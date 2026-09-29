"""``Ledger``, ``Batch`` and ``Ledger.open``: the change log beside the dat.

A dat is space, the ledger is time. The ledger is one append-only table of
events ``(added, rev, subject, predicate, object)`` under dense,
commit-ordered revs; every write is a transaction, every read a function of
a rev. ``Ledger`` holds every method; a backend supplies the primitives
(``rev``, ``_events``, ``_fold``, ``_has_rev``, ``_commit``) and the
whereabouts pair. The shipped backend is SQLite (:mod:`dvc_dat.ledger.sql`),
whose SQL base a consumer subclasses for another database.
"""

from __future__ import annotations

import datetime as _dt
import importlib
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, ClassVar, Dict, List, Optional, Sequence, Tuple, Type

import yaml

from .codec import decode_text, encode_value
from .ref import Event, Ref, Rev
from .shelf import LocalShelf, Shelf
from .types import ART_TYPES, Artifact

#: The file a profile is looked for under, from the working directory up; never in a spec.
PROFILE_NAME = "ledger.profile.yaml"

#: The environment variable naming a SQLite file, or a folder holding ``ledger.db``.
ENV = "DAT_LEDGER"

_builtin_type = type  # `save` takes a keyword named `type`

#: A raw row: ``(rev, subject, predicate, object string, added)``.
Row = Tuple[int, str, str, str, bool]


def _name(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{what} is a non-empty str, not {value!r}")
    return value


@dataclass(frozen=True)
class Op:
    """One write inside a transaction, its object already encoded."""

    kind: str  # "add" | "remove" | "assign"
    subject: str
    predicate: str
    object: str


class Batch:
    """A transaction in progress: ``assign``, ``add`` and ``remove`` without ``by``, written on exit under one rev."""

    def __init__(self, ledger: "Ledger", by: str) -> None:
        self._ledger = ledger
        self._by = _name(by, "by")
        self._ops: List[Op] = []
        self._blobs: Dict[str, bytes] = {}
        self._rev: Optional[Rev] = None
        self._state = "new"

    def _op(self, kind: str, subject: str, predicate: str, obj: Any) -> None:
        if self._state != "open":
            raise RuntimeError(f"transaction is {self._state}: {kind} goes inside the with block")
        text, blob = encode_value(obj)
        if blob is not None:
            self._blobs[text[len("blob:"):]] = blob
        self._ops.append(Op(kind, _name(subject, "subject"), _name(predicate, "predicate"), text))

    def assign(self, subject: str, predicate: str, object: Any) -> None:
        self._op("assign", subject, predicate, object)

    def add(self, subject: str, predicate: str, object: Any) -> None:
        self._op("add", subject, predicate, object)

    def remove(self, subject: str, predicate: str, object: Any) -> None:
        self._op("remove", subject, predicate, object)

    @property
    def rev(self) -> Rev:
        """The transaction's rev, once the block has exited cleanly."""
        if self._rev is None:
            raise RuntimeError(f"transaction is {self._state}: it has no rev")
        return self._rev

    def __enter__(self) -> "Batch":
        if self._state != "new":
            raise RuntimeError("a transaction is entered once")
        self._state = "open"
        return self

    def __exit__(self, et: Optional[Type[BaseException]], ev: Optional[BaseException],
                 tb: Optional[TracebackType]) -> None:
        if et is not None:
            self._state = "abandoned"
            return
        self._state = "committing"
        self._rev = self._ledger._commit(self._ops, self._by, self._blobs)
        self._state = "committed"


class Ledger(ABC):
    """The change log: one append-only table of events under dense, commit-ordered revs."""

    #: The ledger ``Ledger.open`` last returned; what a ``Ref`` resolves through.
    default: ClassVar[Optional["Ledger"]] = None

    _shelf: Shelf

    # -- backend primitives -------------------------------------------------

    @abstractmethod
    def rev(self) -> Rev:
        """The rev of the newest transaction; zero on an empty ledger."""

    @abstractmethod
    def _events(self, subject: Optional[str], predicate: Optional[str], obj: Optional[str],
                tx: Optional[Rev], upto: Rev) -> List[Row]:
        """The log filtered by column, at or below ``upto``, oldest first and in written order."""

    @abstractmethod
    def _fold(self, subject: Optional[str], predicate: Optional[str], obj: Optional[str], at: Rev) -> List[Row]:
        """The state at ``at``: the newest event per triple, kept when added, ordered by rev then written order."""

    @abstractmethod
    def _has_rev(self, rev: Rev) -> bool:
        """Whether a transaction has this rev."""

    @abstractmethod
    def _commit(self, ops: Sequence[Op], by: str, blobs: Dict[str, bytes]) -> Rev:
        """Write ``ops`` plus ``tx/<rev> by`` and ``date`` under one new rev, all or nothing."""

    @abstractmethod
    def _set_whereabouts(self, hash: str, region: str) -> None:
        """Record that ``region`` holds the bytes of ``hash`` (status, updated in place)."""

    @abstractmethod
    def _whereabouts(self, hash: str) -> List[str]:
        """The regions recorded as holding ``hash``."""

    @classmethod
    def from_profile(cls, profile: Dict[str, Any], folder: Path, shelf: Optional[Shelf]) -> "Ledger":
        """The ledger a profile mapping describes; ``folder`` is the profile's own, ``shelf`` from its ``art``."""
        raise NotImplementedError(f"{cls.__name__} cannot be opened from a profile")

    @staticmethod
    def _today() -> _dt.date:
        """The day a transaction is stamped with: UTC, so every box agrees."""
        return _dt.datetime.now(_dt.timezone.utc).date()

    # -- helpers ------------------------------------------------------------

    def _at(self, rev: Optional[Rev]) -> Rev:
        current = self.rev()
        if rev is None:
            return current
        if isinstance(rev, bool) or not isinstance(rev, int) or rev < 0:
            raise ValueError(f"a rev is a non-negative int, not {rev!r}")
        if rev > current:
            raise ValueError(f"rev {rev} is above the newest, {current}")
        return rev

    def _fetch_blob(self, h: str) -> bytes:
        return self._shelf.path(h).read_bytes()

    def _size(self, rid: str) -> Optional[int]:
        e = self._shelf.head(rid)
        return None if e is None else e.size

    def _decode(self, text: str) -> Any:
        return decode_text(text, self._fetch_blob, self._size)

    def _event(self, row: Row) -> Event:
        return Event(row[0], row[1], row[2], self._decode(row[3]), bool(row[4]))

    @staticmethod
    def _enc(obj: Any) -> Optional[str]:
        return None if obj is None else encode_value(obj)[0]

    @staticmethod
    def _opt(value: Optional[str], what: str) -> Optional[str]:
        return None if value is None else _name(value, what)

    # -- artifact access ----------------------------------------------------

    def save(self, obj: Any, *, type: Type[Artifact], name: Optional[str] = None) -> Ref:
        """Store ``obj`` encoded by ``type``; the ``Ref`` out. Writes no triple."""
        if not (isinstance(type, _builtin_type) and issubclass(type, Artifact) and type is not Artifact):
            raise ValueError(f"save's type is an artifact type ({', '.join(sorted(ART_TYPES))}), not {type!r}")
        entry = self._shelf.put(type.source(obj), type.token, name)
        return Ref(name or entry.hash, hash=entry.hash, type=type, size=entry.size)

    def ref(self, rid: str) -> Optional[Ref]:
        """The ``Ref`` a name or hash names in this ledger's store, or ``None``."""
        entry = self._shelf.head(_name(rid, "rid"))
        if entry is None:
            return None
        return Ref(rid, hash=entry.hash, type=ART_TYPES[entry.type], size=entry.size)

    def load(self, rid: str) -> Any:
        """The object a rid names, decoded by its type; ``FileNotFoundError`` when no store holds it."""
        r = self.ref(rid)
        if r is None:
            raise FileNotFoundError(f"artifact {rid!r}: no store reachable from here holds it")
        return self._load_ref(r)

    def _path_ref(self, r: Ref) -> Path:
        return self._shelf.path(r.hash or r.name)

    def _load_ref(self, r: Ref) -> Any:
        if r.kind == "node":
            return self.get_spec(r.name)
        if r.kind != "art":
            raise ValueError(f"{r!r} is a dat: it loads through Dat.manager, not the ledger")
        return r.type.decode(self._path_ref(r))

    # -- update -------------------------------------------------------------

    def transaction(self, *, by: str) -> Batch:
        """A context manager whose exit writes every event under one rev, all or nothing."""
        return Batch(self, by)

    def add(self, subject: str, predicate: str, object: Any, *, by: str) -> Rev:
        """Add one object to what the predicate holds on the subject."""
        with self.transaction(by=by) as tx:
            tx.add(subject, predicate, object)
        return tx.rev

    def remove(self, subject: str, predicate: str, object: Any, *, by: str) -> Rev:
        """Remove one object from what the predicate holds; removing what is not held is not an error."""
        with self.transaction(by=by) as tx:
            tx.remove(subject, predicate, object)
        return tx.rev

    # -- access -------------------------------------------------------------

    def query(self, subject: Optional[str] = None, predicate: Optional[str] = None, object: Any = None, *,
              rev: Optional[Rev] = None, tx: Optional[Rev] = None) -> List[Event]:
        """The event log filtered by any column, as of ``rev``; ``tx`` keeps one transaction. Oldest first."""
        s, p, o = self._opt(subject, "subject"), self._opt(predicate, "predicate"), self._enc(object)
        top = self._at(rev)
        if tx is not None:
            tx = self._at(tx)
            if not self._has_rev(tx):
                raise KeyError(f"no transaction has rev {tx}")
        return [self._event(r) for r in self._events(s, p, o, tx, top)]

    # -- derived helpers ----------------------------------------------------

    def assign(self, subject: str, predicate: str, object: Any, *, by: str) -> Rev:
        """Assignment: the predicate now holds this one object (removals of every held one, then an addition)."""
        with self.transaction(by=by) as tx:
            tx.assign(subject, predicate, object)
        return tx.rev

    def held(self, subject: Optional[str] = None, predicate: Optional[str] = None, object: Any = None, *,
             rev: Optional[Rev] = None) -> List[Event]:
        """Every triple held at ``rev`` matching the parts given, as the event that added it; by rev."""
        s, p, o = self._opt(subject, "subject"), self._opt(predicate, "predicate"), self._enc(object)
        return [self._event(r) for r in self._fold(s, p, o, self._at(rev))]

    def history(self, subject: str, predicate: str, object: Any = None, *,
                rev: Optional[Rev] = None) -> List[Event]:
        """``query(subject, predicate, object, rev=rev)``: every event on them, oldest first."""
        return self.query(_name(subject, "subject"), _name(predicate, "predicate"), object, rev=rev)

    def last(self, subject: str, predicate: str, *, rev: Optional[Rev] = None) -> Any:
        """The object last added under the predicate and not since removed; ``None`` when nothing is held."""
        rows = self._fold(_name(subject, "subject"), _name(predicate, "predicate"), None, self._at(rev))
        return self._decode(rows[-1][3]) if rows else None

    def objects(self, subject: str, predicate: str, *, rev: Optional[Rev] = None) -> List[Any]:
        """Every object the predicate holds, in the order they were last added."""
        rows = self._fold(_name(subject, "subject"), _name(predicate, "predicate"), None, self._at(rev))
        return [self._decode(r[3]) for r in rows]

    def subjects(self, predicate: str, object: Any, *, rev: Optional[Rev] = None) -> List[str]:
        """Every subject holding ``object`` under ``predicate`` at ``rev``: the reverse lookup, by rev."""
        o = encode_value(object)[0]
        rows = self._fold(None, _name(predicate, "predicate"), o, self._at(rev))
        return list(dict.fromkeys(r[1] for r in rows))

    def get_spec(self, subject: str, *, rev: Optional[Rev] = None) -> Dict[str, Any]:
        """``last`` for every predicate the subject holds anything under, as one dict; ``{}`` for none."""
        newest: Dict[str, str] = {}
        for r in self._fold(_name(subject, "subject"), None, None, self._at(rev)):
            newest[r[2]] = r[3]  # rows ascend, so the last written per predicate wins
        return {p: self._decode(newest[p]) for p in sorted(newest)}

    def set_spec(self, subject: str, mapping: Dict[str, Any], *, by: str) -> Rev:
        """The reverse of ``get_spec``: one ``assign`` per key, under one rev; keys not named are untouched."""
        if not isinstance(mapping, dict):
            raise ValueError(f"set_spec takes a dict, not {type(mapping).__name__}")
        with self.transaction(by=by) as tx:
            for predicate, obj in mapping.items():
                tx.assign(subject, predicate, obj)
        return tx.rev

    def exists(self, subject: str, predicate: str, object: Any, *, rev: Optional[Rev] = None) -> bool:
        """Whether the triple is held at ``rev``."""
        o = encode_value(object)[0]
        return bool(self._fold(_name(subject, "subject"), _name(predicate, "predicate"), o, self._at(rev)))

    def date(self, rev: Rev) -> _dt.date:
        """The day transaction ``rev`` was written: ``last("tx/<rev>", "date")``."""
        at = self._at(rev)
        day = self.last(f"tx/{at}", "date", rev=at)
        if not isinstance(day, str):
            raise KeyError(f"no transaction has rev {rev}")
        return _dt.date.fromisoformat(day)

    # -- static -------------------------------------------------------------

    @staticmethod
    def open(profile: Optional[Path] = None) -> "Ledger":
        """The ledger ``profile`` names, else ``DAT_LEDGER``'s SQLite file, else the nearest ``ledger.profile.yaml``.

        The ledger returned becomes ``Ledger.default``.
        """
        from .sql import SqliteLedger

        led: Ledger
        env = os.environ.get(ENV)
        if profile is not None:
            led = _from_profile(Path(profile))
        elif env:
            path = Path(env).expanduser()
            led = SqliteLedger(path / "ledger.db" if path.is_dir() else path)
        else:
            found = profile_path()
            if found is None:
                raise FileNotFoundError(
                    f"no ledger: no profile given, {ENV} is not set (a SQLite file or folder), "
                    f"and no {PROFILE_NAME} in {Path.cwd()} or above")
            led = _from_profile(found)
        Ledger.default = led
        return led

    @staticmethod
    def encode(object: Any) -> str:
        """The row's string for a value (``blob:`` gives the hash; the write puts the bytes)."""
        return encode_value(object)[0]

    @staticmethod
    def decode(text: str) -> Any:
        """A row's object as the Python value it encodes; a blob fetched through ``Ledger.default``."""
        d = Ledger.default
        return decode_text(text, d._fetch_blob if d else None, d._size if d else None)


def profile_path(start: Optional[Path] = None) -> Optional[Path]:
    """The nearest ``ledger.profile.yaml``: in ``start`` (the working directory) or a folder above it."""
    here = Path(start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        candidate = folder / PROFILE_NAME
        if candidate.is_file():
            return candidate
    return None


def _backend_class(name: str) -> Type[Ledger]:
    from .sql import SqliteLedger

    if name == "sqlite":
        return SqliteLedger
    module, _, attr = name.rpartition(".")
    if not module:
        raise ValueError(f"a ledger backend is 'sqlite' or a dotted class name, not {name!r}")
    try:
        cls = getattr(importlib.import_module(module), attr)
    except (ImportError, AttributeError) as e:
        raise ValueError(f"ledger backend {name!r} does not import: {e}") from None
    if not (isinstance(cls, type) and issubclass(cls, Ledger)):
        raise ValueError(f"ledger backend {name!r} is not a Ledger subclass")
    return cls


def _from_profile(path: Path) -> Ledger:
    if not path.is_file():
        raise FileNotFoundError(f"no ledger profile at {path}")
    prof = yaml.safe_load(path.read_text()) or {}
    if not isinstance(prof, dict):
        raise ValueError(f"{path}: a ledger profile is a YAML mapping")
    cls = _backend_class(str(prof.get("backend", "sqlite")))
    art = prof.get("art")
    shelf = None if art is None else LocalShelf(
        _relative(path.parent, str(art)), str(prof.get("region", "local")))
    return cls.from_profile(prof, path.parent, shelf)


def _relative(folder: Path, value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else folder / p
