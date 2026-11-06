"""``Value``: everything the ledger holds and hands back, with its provenance on it.

A subclass says how it becomes bytes (``encode`` writes them to a binary stream the store opens) and
back (``decode`` reads them from one), never holding them whole (DAT 240), and,
with ``@ledger_class(preds=...)``, which pred names its values may carry.
``preds`` is a plain dict while the value is unsealed, filled by whoever builds
it; the seal (``v.seal(t)`` or an ``run``) freezes it into a
read-only mapping and fixes ``subject``, ``rev`` and ``dependencies`` (Q25 (D)). A
subclass's own ``__init__`` need not call ``super().__init__``. Shipped
subclasses: ``Value.Blob`` (any Python object, pickled), ``Value.Table`` (parquet), and
``dvc_dat.core.Dat`` (a dat: its folder, encoded as its content manifest, DAT 1038).
"""

from __future__ import annotations

import pickle
import re
import shutil
from pathlib import Path
from types import MappingProxyType
from typing import IO, TYPE_CHECKING, Any, ClassVar, Dict, Iterable, Mapping, Optional, Tuple, Union

from .codec import hash_sink

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
    """The object itself, with its provenance on it.

    Every subclass's encoding is deterministic and lossless. Deterministic: equal values encode to the same
    bytes, in any process on any machine. Lossless: ``decode`` of those bytes gives back an equal value, so
    encoding it again gives the same bytes. A worker shares no memory with its caller, so a value crosses by
    being encoded and decoded; and ``hash`` is the sha256 of ``encode``, so these decide whether a value rebuilt
    on each call hits a memo and whether two machines agree on its identity. A new subclass has a test that
    encode, decode, encode gives the same bytes. Changing a class's encoding moves the hash of everything stored
    under it, so it is a migration, never a fix: the shipped classes' known failures are ``xfail(strict=True)`` in
    ``tests/ledger/test_value_encoding.py``.
    """

    Dependencies: ClassVar[Any] = Mapping[str, str]
    """The type of ``dependencies``, for annotations: item name to version or hash."""
    #: The pred names a kind declares (``@ledger_class``); none by default.
    _ledger_preds: ClassVar[tuple] = ()
    #: Relative-path suffixes of the subdats a seal declines by default (SVP 241); ``seal(skip=)`` adds to them.
    skip_subdats: ClassVar[Tuple[str, ...]] = ()
    """Relative-path suffixes of the subdats a seal declines by default; ``seal(skip=)`` adds to them, ``skip=()`` clears them."""

    subject: Optional[str] = None
    """The 64-hex subject the value was saved under.

    ``None`` until saved, including when sealed by ``seal()`` alone.
    """
    rev: Optional["Rev"] = None
    """The revision that saved the value; set at commit or by ``load``."""
    dependencies: Mapping[str, str] = _EMPTY
    """What producing it read: item name to version or hash.

    Empty for a hand-built value until saved; a run's result carries its trace here at every ``seal=`` level. See
    [Value Provenance][value-provenance].
    """
    sealed: Optional[str] = None
    """The seal's moment, UTC ``YYYY-MM-DDTHH:MM:SSZ``, or ``None`` while unsealed.

    So ``if v.sealed:`` reads as the boolean too. The identity is fixed by ``v.seal()`` (saved nowhere yet,
    ``subject`` ``None``) or by a save (printed in a zone by [`rev.show_time`][dvc_dat.ledger.Rev.show_time]). A time
    rather than a revision because a seal can precede any ledger; the revision is ``rev``, set at the save.
    """

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
        """Make ``name`` this saved value's one name (``None``: unname it), the alias tree under it moved in the
        same transaction, so ``<name>/<relpath>`` stays true of each subdat; a ``Dat`` moves to its folder."""
        from .rev import name_of

        head = ledger.at()
        assert self.subject is not None
        others = [n for n in head._aliases_of(self.subject) if n != name]
        owns = name is None or (name_of(head, self.subject) == name
                                and any(h.obj == "str:" + self.subject for h in head._held(name, "db/alias")))
        tree = head._alias_tree(self.subject, name)
        if others or not owns or tree:
            with ledger.transaction(by="name") as t:
                t._name_value(self.subject, name)
                for target, new in tree:
                    t._name_value(target, new)
        if name is not None:
            self._at_name(ledger._store.art, name)

    def _at_name(self, store: "ArtStore", name: str) -> None:
        """Hook: a named value's place on disk (a ``Dat``'s folder at its name)."""

    @property
    def preds(self) -> Dict[str, Any]:
        """A plain ``dict`` while unsealed, a read-only ``FrozenPreds`` once sealed.

        Assignable as a whole while unsealed; every mutator of the sealed ``FrozenPreds`` is ``TypeError``. Each pred
        is a ``str``, number, bool, list, ``Value`` or ``Ref``, and its name must be declared by the class's
        ``@ledger_class`` (``Undeclared`` at the seal).
        """
        d = self.__dict__.get("_preds")
        if d is None:
            d = self.__dict__["_preds"] = {}
        return d

    @preds.setter
    def preds(self, value: Any) -> None:
        if self.sealed:
            raise TypeError("cannot modify a sealed value's preds")
        self.__dict__["_preds"] = dict(value)

    def encode(self, out: IO[bytes]) -> None:
        """Write the bytes to store to ``out``, once, forward, returning nothing (DAT 240).

        Abstract: every ``Value`` subclass must implement it (``NotImplementedError`` otherwise). ``out`` is a sink
        the store opens, a write-only binary stream that hashes and counts what passes and refuses ``seek``
        (``io.UnsupportedOperation``), so no value is held whole in memory to be sealed. ``pickle.dump``,
        ``pq.write_table`` and ``np.save`` write to it as to a file.

        A save encodes once: into a staged file in the art folder, whose hash is the value's, which the upload sends
        and the commit links into place.

        **Deterministic:** equal values write the same bytes, in any process on any machine. Two calls on one value
        that differ make a value sealed by ``v.seal()`` ``SealBroken`` at its save, and ``hash`` decides whether a
        value rebuilt on each call hits a memo and whether two machines agree on its identity. A new subclass has a
        test that encode, decode, encode gives the same bytes. Changing a class's encoding moves the hash of
        everything stored under it, so it is a migration, never a fix.

        Where the shipped classes fall short today, each ``xfail(strict=True)`` in
        ``tests/ledger/test_value_encoding.py``: ``Value.Blob``, on a dict's insertion order, a set's order (across
        ``PYTHONHASHSEED``, and after a decode) and a repeated object versus an equal copy; ``Value.Table``, on
        chunking (a table over 131072 rows does not re-encode the same), schema metadata and the pyarrow version;
        ``Dat``, on the key order of its spec; ``Code`` has no ``decode``.

        A test that wants the bytes passes ``io.BytesIO()``.
        """
        raise NotImplementedError(f"{type(self).__name__} does not say how it encodes")

    @classmethod
    def decode(cls, src: IO[bytes], store: "ArtStore") -> "Value":
        """The object from its bytes, read from ``src`` (a binary read stream, seekable).

        Abstract: every ``Value`` subclass must implement it (``NotImplementedError`` otherwise). ``src`` is the
        stored bytes as a binary read stream: a real, seekable file (``ArtStore.open``). A subclass whose ``decode``
        also accepts ``name=`` is passed the name it is loaded by (an alias), or ``None`` when loaded by its subject.

        **Lossless:** it gives back a value equal to the one encoded, so encoding that value again writes the same
        bytes. A worker shares no memory with its caller, so a value crosses by being encoded and decoded, and a loss
        here changes behavior when an execution moves.

        A value held only in memory is five lines: ``encode(self, out): torch.save(self.t, out)``, ``decode(cls, src,
        store): return cls(torch.load(src))``.
        """
        raise NotImplementedError(f"{cls.__name__} does not say how it decodes")

    def _encoded_hash(self) -> str:
        """The hex sha256 of ``encode``, written into a sink that keeps nothing."""
        s = hash_sink()
        self.encode(s)
        return s.hash

    def _parts(self) -> Iterable["Part"]:
        """Further bytes that ``decode`` will fetch from the store (a folder's files), as
        ``(sha256, source)``: a ``Path``, or a zero-arg opener returning a binary stream. Streamed into
        the store one at a time; never held in memory whole."""
        return ()

    @classmethod
    def _stored_hashes(cls, store: "ArtStore", h: str) -> Iterable[str]:
        """The parts of the value stored under ``h``, read off the store: what a copy carries beside the encoding,
        never decoded. A class with ``_parts`` says here where they are recorded."""
        if cls._parts is not Value._parts:
            raise NotImplementedError(f"{cls.__name__} has parts and does not say how they are found (_stored_hashes)")
        return ()

    def _after_seal(self, store: "ArtStore", name: Optional[str] = None) -> None:
        """Hook run once the value is sealed (a ``Dat`` moves to its stored folder, at its name if named)."""

    def _pred_names(self) -> Tuple[str, ...]:
        """The pred names this value may carry: its class's ``@ledger_class(preds=...)`` (a ``Dat`` adds
        its folder's own)."""
        return tuple(type(self)._ledger_preds)

    def _sealable(self) -> None:
        """Hook: refuse a value that may not be sealed as it stands (a ``Dat`` never saved)."""

    def _subdats(self) -> Iterable[Tuple[str, "Value"]]:
        """Hook: ``(relpath, value)`` of each value a seal of this one seals with it (a ``Dat``'s subdats)."""
        return ()

    def seal(self, to: Any = True, *, keep: bool = False, deps: Iterable[Any] = (), name: Optional[str] = None,
             provenance: Optional[str] = None, by: Optional[Union[str, Dict[str, Any]]] = None,
             skip: Optional[Iterable[str]] = None) -> str:
        """Fix the value's identity; with a transaction or a ledger, save it too.

        ``to`` takes what ``seal=`` on a run takes (DAT 1028), so ``f(seal=x)`` and a later ``v.seal(x)`` end in one
        place.

        ``v.seal()`` (``v.seal(True)``) writes to no ledger: it freezes ``preds``, fixes the bytes' hash, ``deps``,
        ``provenance``, the environment and the time, writes them as a seal record in this machine's kept folder
        (``kept``; a later process reopens a sealed ``Dat`` from it with ``Dat.sealed_at_path``), and returns the
        hash. With ``keep=True`` it also copies the bytes into the kept cache, so the source may change. ``to`` a
        ``Transaction`` (``v.seal(t)``) saves into it: the subject is ``<hash of (dependencies, preds, bytes)>`` and
        lands with that revision or not at all. ``to`` a ``Ledger`` (``v.seal(L)``) opens and commits a one-value
        transaction of its own, written ``by`` (a ``str`` or a JSON ``dict``, as on
        [`transaction`][dvc_dat.ledger.Ledger.transaction]; default: the provenance, else ``seal``). ``name=`` writes
        ``(alias, db/alias, subject)`` beside it. Saving a value sealed earlier saves the state it was sealed in (its
        deps, provenance and environment), and refuses with ``SealBroken`` when its bytes changed since, unless kept.
        A run's result (``seal=False`` or ``True``) carries its trace: saving it writes the memo entry the run would
        have, so the next identical call hits, after the code check of [Running][running] (``NotEvaluated``);
        ``deps=`` and ``provenance=`` on it are ``TypeError``. ``v.seal(False)`` and ``v.seal("get")`` are
        ``TypeError``: nothing to do to an object. A provenance beginning ``eval:`` is ``ValueError``; a second seal
        is ``ValueError``.

        A save of a ``Dat`` seals the subdats in its folder tree in the same transaction (SVP 241), as
        [Subdats][subdats]: each its own value, named ``<name>/<relpath>``, depending on this one, with its
        provenance, and a row ``(<subject>, db/subdat/<relpath>, <ref to it>)``. ``skip`` names relative-path suffixes
        to decline, on top of the class's ``skip_subdats`` (``viz`` declines ``viz/`` and ``run/viz/``; a plain folder
        named declines every subdat under it): a declined subdat stays on disk, stores no byte, and its row says
        ``str:declined``. ``skip=()`` declines nothing, the class's ``skip_subdats`` included; ``skip`` on
        ``v.seal()`` is ``TypeError``, and so is a bare ``str``. See [Versioning][versioning].
        """
        from .ledger import Ledger
        from .txn import Transaction

        if to is True:
            if name is not None or by is not None or skip is not None:
                raise TypeError("name=, by= and skip= name a ledger write; v.seal() writes none "
                                "(v.seal(t, name=...))")
            return self._seal_here(keep, tuple(deps), provenance)
        if to is False or (isinstance(to, str) and to == "get"):
            raise TypeError(f"v.seal({to!r}): {to!r} is a run's seal= level (keep nothing; look up); there is "
                            "nothing to do to an object. v.seal() seals here; v.seal(t) or v.seal(L) saves")
        if keep:
            raise TypeError("keep= is v.seal()'s; a save stores the bytes in the art store")
        if isinstance(to, Transaction):
            if by is not None:
                raise TypeError("by= names the writer of a transaction seal opens; this one is open already")
            return to._seal_value(self, deps=tuple(deps), name=name, provenance=provenance, skip=skip)
        if isinstance(to, Ledger):
            local = self.__dict__.get("_local")
            run = self.__dict__.get("_run")
            default = (f"eval:{run.name}" if run is not None else None) or (local and local["provenance"]) or "seal"
            with to.transaction(by=by if by is not None else provenance or default) as t:
                return t._seal_value(self, deps=tuple(deps), name=name, provenance=provenance, skip=skip)
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
        check_loadable(self)
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
        kept = Kept()
        with unguarded():                       # the ledger's own write, also inside a sandboxed body
            with (kept.sink() if keep else hash_sink()) as sink:
                self.encode(sink)
        h = sink.hash
        record.update(hash=h, kind=dotted(type(self)), sealed_at=stamp, path=self._seal_path(),
                      provenance=provenance, env=env_record(env), bytes=self._seal_bytes(sink.size))
        if run is not None:
            record["run"] = run.record()
        with unguarded():
            entry = kept.seal(record, keep, self._parts() if keep else ())
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

    def _seal_bytes(self, size: int) -> int:
        """The size a seal record lists: of the encoding (``size`` bytes), for a value held in memory."""
        return size

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
            if self._encoded_hash() == local["hash"]:
                return None
            from .errors import SealBroken

            raise SealBroken(f"{type(self).__name__} sealed at {self.sealed}: its kept bytes were purged and "
                             "the source changed since; seal a new value") from None

    def _write_stored(self, out: IO[bytes]) -> None:
        """Write the encoding a save stores to ``out``: the kept bytes, in blocks, when ``v.seal(keep=True)``
        kept them, else ``encode(out)``."""
        e = self._kept()
        if e is not None:
            from .kept import Kept
            from .store import BLOCK

            with open(Kept().blob(e["hash"]), "rb") as f:
                shutil.copyfileobj(f, out, BLOCK)
            return
        self.encode(out)

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
        """The hex sha256 of what ``encode`` writes; cached once sealed.

        Computed into a sink that keeps nothing. After a save, the stored bytes' hash, whatever the live object holds.
        """
        cached = self.__dict__.get("_hash")
        if cached is not None:
            return cached
        h = self._encoded_hash()
        if self.sealed:
            self.__dict__["_hash"] = h
        return h

    @property
    def at(self) -> Optional["Rev"]:
        """The revision the value's run read (SVP 245): its ``db/at`` row.

        ``rev`` is where it was saved, ``at`` what it was computed from, so a run at ``L.at(412)`` saved at 902 has
        ``v.at.id == 412``, ``v.rev.id == 902``. A draft's comes from its trace. A memo hit hands back the entry it
        found, whose ``at`` is the revision that entry ran at. ``None`` for a hand seal and for a [copy][copying],
        whose row stays on its origin. A ``Dat`` reads the same revision off its run sub-dat, ``ValueError`` when it
        ran on no ledger.
        """
        if self.rev is not None and self.subject is not None:
            from .fn import AT

            held = self.rev.get(self.subject, AT)
            return None if held is None else self.rev.ledger.at(int(held))
        run = self.__dict__.get("_run")
        if run is None or run.at is None:
            return None
        from .ledger import opened_at

        return opened_at(run.ledger).at(run.at)

    def matches(self, rev: "Rev") -> bool:
        """Every dependency item at its value at ``rev``: the hit test.

        Consults the memo only, never runs.
        """
        from .trace import trace_matches

        return trace_matches(rev, dict(self.dependencies))

    def diff(self, other: "Value") -> Dict[str, tuple]:
        """The dependency items whose values differ: item -> ``(mine, theirs)``, ``None`` where one lacks it."""
        out = {}
        for k in sorted(set(self.dependencies) | set(other.dependencies)):
            a, b = self.dependencies.get(k), other.dependencies.get(k)
            if a != b:
                out[k] = (a, b)
        return out

    def same_as(self, other: Optional["Value"]) -> bool:
        """``self.hash == other.hash``; ``False`` for ``None``."""
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


def stamp() -> str:
    """This moment as the ledger stores it (``db/time``, ``sealed``): UTC, ISO 8601 to the second,
    ``2026-11-01T21:03:22Z``."""
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shown_in(text: str, zone: Any) -> str:
    """A stored UTC stamp as it prints in ``zone``: ISO 8601 with the zone's offset
    (``2026-11-01T14:03:22-07:00``); in UTC it is the stamp unchanged."""
    import datetime as _dt

    if getattr(zone, "key", None) == "UTC":
        return text
    return _dt.datetime.fromisoformat(text).astimezone(zone).isoformat(timespec="seconds")


#: A moment named by an ISO 8601 prefix (SVP 1507): a date, then optionally the hour, minute and second; a
#: single space may replace ``T``; with a time, an optional zone suffix ``Z`` or ``+hh:mm`` / ``-hh:mm``.
_MOMENT = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2})(?::(\d{2})(?::(\d{2}))?)?(Z|[+-]\d{2}:\d{2})?)?")


def is_moment(text: Any) -> bool:
    """Whether ``text`` has the form of a moment ``Ledger.at`` reads (``2026-11-02``, ``2026-11-02T14:30Z``),
    valid calendar or not; a ``db/tag`` of this form is refused."""
    return isinstance(text, str) and _MOMENT.fullmatch(text) is not None


def moment(text: str, zone: Any) -> Any:
    """The UTC ``datetime`` a moment names: the START of its span (``2026-11-02`` is 00:00, ``2026-11-02T01``
    is exactly 01:00), read in ``zone`` unless it carries ``Z`` or an offset. A local time a DST change makes
    ambiguous or skips is read with ``fold=0``: the earlier of two, and a skipped one at the offset before the
    change. ``ValueError`` on a form that is not a moment or a field out of range."""
    import datetime as _dt

    m = _MOMENT.fullmatch(text) if isinstance(text, str) else None
    if m is None:
        raise ValueError(f"not a moment, an ISO 8601 prefix such as '2026-11-02' or '2026-11-02T14:30': {text!r}")
    y, mo, d, h, mi, s, z = m.groups()
    if z is None:
        tz = zone
    elif z == "Z":
        tz = _dt.timezone.utc
    else:
        sign = -1 if z[0] == "-" else 1
        hh, mm = int(z[1:3]), int(z[4:6])
        if hh > 23 or mm > 59:
            raise ValueError(f"moment {text!r}: the offset {z} is out of range")
        tz = _dt.timezone(sign * _dt.timedelta(hours=hh, minutes=mm))
    try:
        local = _dt.datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0), int(s or 0), tzinfo=tz, fold=0)
    except ValueError as e:
        raise ValueError(f"moment {text!r}: {e}") from None
    return local.astimezone(_dt.timezone.utc)


def stored_moment(text: str) -> Any:
    """A stored stamp (``db/time``) as a UTC ``datetime``: ``2026-11-01T21:03:22Z``, or the offset form
    ``2026-11-01T14:03:22-07:00`` that 2.44.0 to 2.46.x wrote."""
    import datetime as _dt

    return _dt.datetime.fromisoformat(text).astimezone(_dt.timezone.utc)


#: The display-zone setting (SVP 1505 Q2): the row ``db db/timezone <IANA name>``; absent, UTC.
TIMEZONE = "db/timezone"


def zone_named(subject: str, name: Any) -> Any:
    """The ``ZoneInfo`` a ``db/timezone`` row names; ``ValueError`` on a subject other than ``db`` or a name
    that is not an IANA zone."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    if subject != "db":
        raise ValueError(f"{TIMEZONE} is the ledger's display zone, a row of the subject db, not {subject!r}")
    if not (isinstance(name, str) and name):
        raise ValueError(f"db {TIMEZONE}: an IANA zone name such as 'America/Los_Angeles', not {name!r}")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"db {TIMEZONE}: {name!r} is not an IANA zone name (such as 'America/Los_Angeles' "
                         "or 'UTC')") from None


def _now() -> str:
    """A seal with no ledger: UTC."""
    return stamp()


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


def check_loadable(value: "Value") -> None:
    """Refuse at the seal a value whose class no load can find: one defined inside a function."""
    if "<" in type(value).__qualname__:
        raise TypeError(f"{dotted(type(value))}: a value class defined inside a function seals but never loads "
                        "back; define it at module level")


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
        """A value whose bytes are ``obj`` pickled.

        A value function whose return annotation is not a ``Value`` subclass has its result wrapped in one.
        """
        self.obj = obj
        """The wrapped object."""
        super().__init__(name=name)

    def encode(self, out: IO[bytes]) -> None:
        """Pickle ``obj`` to the sink, protocol 4."""
        pickle.dump(self.obj, out, protocol=4)

    @classmethod
    def decode(cls, src: IO[bytes], store: "ArtStore") -> "Blob":
        """Build the value from its pickled bytes."""
        return cls(pickle.load(src))


class Table(Value):
    """A table stored as parquet: a ``pyarrow.Table`` or a pandas ``DataFrame`` (decodes to pyarrow)."""

    def __init__(self, table: Any, *, name: Optional[str] = None) -> None:
        """A value whose bytes are ``table`` as parquet.

        ``table`` is a ``pyarrow.Table`` or a pandas ``DataFrame``.
        """
        self.table = table
        """The wrapped table; a ``pyarrow.Table`` after a load."""
        super().__init__(name=name)

    def encode(self, out: IO[bytes]) -> None:
        """Write the table to the sink as parquet, a ``DataFrame`` converted first."""
        import pyarrow as pa
        import pyarrow.parquet as pq

        t = self.table if isinstance(self.table, pa.Table) else pa.Table.from_pandas(self.table)
        pq.write_table(t, out)

    @classmethod
    def decode(cls, src: IO[bytes], store: "ArtStore") -> "Table":
        """Build the value from its parquet bytes; the table is a ``pyarrow.Table``."""
        import pyarrow.parquet as pq

        return cls(pq.read_table(src))


Blob.__qualname__ = "Value.Blob"
Table.__qualname__ = "Value.Table"
Value.Blob = Blob      # type: ignore[attr-defined]
Value.Table = Table    # type: ignore[attr-defined]
