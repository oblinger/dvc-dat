"""``Transaction``: the write set of one ``with L.transaction(...)``, one revision on exit.

``add`` and ``remove`` append rows and read nothing; ``v.seal(t)`` seals a
``Value`` into an immutable subject and the bracket (``t[s, p] = o``,
``t[s] = {...}``, ``del``) is a read-then-write helper over ``add``/``remove``;
those two read through ``t.base``. Everything that must see the transaction's
own rows is checked at commit, inside the write lock, against the state the
new revision would have (the rows are inserted, read back through the open
write transaction, and rolled back on a refusal): ``Exists`` (a write on a
sealed subject's own predicates), the ``db/alias`` target check (A18, A45)
and the ``db/type`` check (A36, A44). Rows land in body order, then the
transaction's own ``db/tx/<rev>`` rows (A50).
"""

from __future__ import annotations

import ctypes
import datetime as _dt
import json
import signal
import tempfile
import threading
import time as _time
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .codec import canonical, encode_plain, hash_text, parse_ref, ref_text, refuse_scalar, sha256, show, strip_hint, tag
from .errors import Exists, LockTimeout, SealBroken, Undeclared
from .value import Value, dotted

if TYPE_CHECKING:
    from .fn import Fn
    from .ledger import Ledger
    from .rev import Rev

#: What ``(db, db/format)`` says: the software format, written by a ledger's first transaction.
FORMAT = "dvc-dat-ledger/1"

#: A sealed subject's own predicates (besides its preds, named by its ``db/preds`` row).
SEAL_PREDICATES = frozenset({"db/value", "db/kind", "db/provenance", "db/preds", "db/fn", "db/keys", "db/sealed-at"})


def is_seal_predicate(p: str, frozen: Sequence[str]) -> bool:
    return p in SEAL_PREDICATES or p.startswith("db/trace/") or p in frozen


def attr(obj: Any, path: str) -> Any:
    """Walk a dotted path over dicts, dataclasses and records; ``KeyError`` at the first missing step."""
    if not isinstance(path, str) or not path:
        raise TypeError(f"a path is a non-empty dotted str, not {path!r}")
    cur = obj
    for step in path.split("."):
        if isinstance(cur, Mapping):
            if step not in cur:
                raise KeyError(f"{path!r}: no {step!r}")
            cur = cur[step]
        elif isinstance(cur, (list, tuple)) and step.lstrip("-").isdigit():
            try:
                cur = cur[int(step)]
            except IndexError:
                raise KeyError(f"{path!r}: no {step!r}") from None
        else:
            try:
                cur = getattr(cur, step)
            except AttributeError:
                raise KeyError(f"{path!r}: no {step!r}") from None
    return cur


class _Op:
    __slots__ = ("s", "p", "o", "added", "seal_of", "pred")

    def __init__(self, s: str, p: str, o: str, added: bool, seal_of: Optional[str] = None,
                 pred: bool = False) -> None:
        self.s, self.p, self.o, self.added, self.seal_of, self.pred = s, p, o, added, seal_of, pred


def _name(x: Any, what: str) -> str:
    if not isinstance(x, str) or not x:
        raise TypeError(f"{what} is a non-empty str, not {x!r}")
    return x


def check_provenance(provenance: Optional[str]) -> str:
    """A hand seal's provenance: a non-empty str, ``seal`` by default, never ``eval:``."""
    if provenance is None:
        return "seal"
    if not isinstance(provenance, str) or not provenance:
        raise TypeError(f"provenance is a str, not {provenance!r}")
    if provenance.startswith("eval:"):
        raise ValueError(f"provenance {provenance!r}: eval: provenance is written by eval alone")
    return provenance


def code_token(rev: "Rev", repo: str, env_commit: Optional[str]) -> str:
    """The ``code/<repo>`` trace item: ``<version row>+<env commit 8>``, ``+<env commit 8>`` with no
    version row (A53). The commit is always the environment's: the commit the code ran at, whatever
    commit the ``code/<repo>`` row pins its version to (6.2.0)."""
    v = rev.get(f"code/{repo}", "version")
    return f"{v or ''}+{(env_commit or '')[:8]}"


class Transaction:
    """The write set open under one ``with L.transaction(...)``."""

    def __init__(self, ledger: "Ledger", by: str, lock: Optional[float], preds: Dict[str, Any]) -> None:
        self._ledger = ledger
        self._by = _name(by, "by")
        if lock is not None and (isinstance(lock, bool) or not isinstance(lock, (int, float)) or lock <= 0):
            raise TypeError(f"lock is a positive number of seconds, not {lock!r}")
        if "time" in preds:
            raise TypeError("time= is gone (6.2.0): every transaction is stamped db/time; drop the keyword")
        self._lock = lock
        #: A placeholder for ``db/tx/<rev>``, rewritten at commit.
        self.tx = f"db/tx/pending-{uuid.uuid4().hex[:12]}"
        self._preds: List[Tuple[str, str]] = []
        for k, v in preds.items():
            if k.startswith("db/"):
                raise TypeError(f"{k!r}: a transaction keyword is user vocabulary, never db/")
            refuse_scalar(v)
            plain = encode_plain(v)
            if plain is None:
                raise TypeError(f"transaction keyword {k!r} is a str or JSON document, not {type(v).__name__}")
            self._preds.append((k, plain))
        self._ops: List[_Op] = []
        self._state = "new"
        self._base: Optional["Rev"] = None
        self._rev: Optional["Rev"] = None
        self._pending: Dict[int, Tuple[Value, str]] = {}
        self._finalize: List[Tuple[Value, str, Dict[str, str], Optional[str]]] = []
        self._fns: set = set()
        #: Values this body froze, with their preds before (``None``: sealed by ``v.seal()`` before).
        self._frozen: List[Tuple[Value, Optional[Dict[str, Any]]]] = []
        self._to_store: List[Value] = []
        self._created: List[Any] = []
        self._cm: Any = None
        self._w: Any = None
        self._timer: Any = None
        self._old_handler: Any = None
        self._t0 = 0.0

    # -- fields ---------------------------------------------------------------

    @property
    def base(self) -> "Rev":
        """The top when the transaction opened; under ``lock=`` it stays the top until exit."""
        if self._base is None:
            raise RuntimeError("a transaction has no base until its with block is entered")
        return self._base

    @property
    def rev(self) -> "Rev":
        """The revision the exit wrote."""
        if self._rev is None:
            raise RuntimeError(f"transaction is {self._state}: it has no rev")
        return self._rev

    # -- the with -------------------------------------------------------------

    def __enter__(self) -> "Transaction":
        if self._state != "new":
            raise RuntimeError("a transaction is entered once")
        if self._lock is not None:
            t0 = _time.monotonic()
            self._cm = self._ledger._store.writer(self._lock, locked=True)
            self._w = self._cm.__enter__()
            left = self._lock - (_time.monotonic() - t0)
            if left <= 0:
                self._cm.__exit__(LockTimeout, LockTimeout(), None)
                raise LockTimeout(f"write lock had only after {self._lock}s")
            try:
                self._base = self._ledger.at()      # under the lock, before the body's clock starts
            except BaseException as e:
                self._cm.__exit__(type(e), e, e.__traceback__)
                raise
            self._t0 = _time.monotonic()
            self._arm(left)
        else:
            self._base = self._ledger.at()
        self._state = "open"
        return self

    def _arm(self, seconds: float) -> None:
        msg = f"lock={self._lock}: the body ran past its limit; nothing written"
        if threading.current_thread() is threading.main_thread():
            def handler(signum: int, frame: Any) -> None:
                raise LockTimeout(msg)
            self._old_handler = signal.signal(signal.SIGALRM, handler)
            signal.setitimer(signal.ITIMER_REAL, seconds)
        else:
            tid = threading.get_ident()

            def fire() -> None:
                ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), ctypes.py_object(LockTimeout))
            self._timer = threading.Timer(seconds, fire)
            self._timer.daemon = True
            self._timer.start()

    def _disarm(self) -> None:
        if self._old_handler is not None:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self._old_handler)
            self._old_handler = None
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def __exit__(self, et: Any, ev: Any, tb: Any) -> bool:
        self._disarm()
        if et is None and self._lock is not None and _time.monotonic() - self._t0 > self._lock:
            ev = LockTimeout(f"lock={self._lock}: the body ran past its limit; nothing written")
            self._abandon()
            self._cm.__exit__(LockTimeout, ev, None)
            raise ev
        if et is not None:
            self._abandon()
            if self._cm is not None:
                self._cm.__exit__(et, ev, tb)
            return False
        self._state = "committing"
        try:
            if self._cm is not None:
                try:
                    rev = self._write(self._w)
                except BaseException as e:
                    self._cm.__exit__(type(e), e, e.__traceback__)
                    raise
                self._cm.__exit__(None, None, None)
            else:
                with self._ledger._store.writer(30.0, locked=False) as w:
                    rev = self._write(w)
        except BaseException:
            self._abandon()
            raise
        self._rev = self._ledger.at(rev)
        self._finish()
        self._state = "committed"
        return False

    def _abandon(self) -> None:
        """Nothing was written: unseal every value this body froze (A43) and drop bytes it stored."""
        from .value import _EMPTY

        self._state = "abandoned"
        for value, old in self._frozen:
            value.subject = None
            value.trace = _EMPTY
            value.__dict__.pop("_ledger", None)
            if old is None:
                continue            # sealed by v.seal() before this body: sealed still, saved nowhere
            value.sealed = False
            value.sealed_at = None
            value.__dict__["_preds"] = old
            value.__dict__.pop("_hash", None)
        for path in self._created:
            try:
                path.unlink()
            except OSError:
                pass
        self._created = []

    def _store_all(self) -> None:
        """The bytes of every seal, written at commit so bytes and rows land together (or neither).

        One value at a time, one part at a time: each part is hardlinked or streamed into the art
        store (``put_path``), never read whole; the encoding (a manifest, for a ``Dat``) is checked
        against the sealed hash before anything of the value is written."""
        art = self._ledger._store.art
        for v in self._to_store:
            data = v._stored_bytes()
            if sha256(data) != v.hash:
                raise ValueError(f"{type(v).__name__}.encode is not deterministic: two calls gave two hashes")
            for h, source in v._stored_parts():
                if art.put_path(source, h):
                    self._created.append(art.path(h))
            if not art.exists(v.hash):
                art.put(data)
                self._created.append(art.path(v.hash))

    def _finish(self) -> None:
        from .rev import Ref

        top = self._rev
        art = self._ledger._store.art
        records = []
        for value, subject, trace, loaded_as in self._finalize:
            r = Ref(top, subject)
            sealed_at = r.sealed_at or top
            stamp, h = value.sealed_at, value.hash        # the hash of the bytes stored, not of the live object
            value._provenance(subject=subject, rev=sealed_at, trace=trace, preds=r.preds)
            value.sealed_at = stamp
            value.__dict__["_hash"] = h
            value._after_seal(art)
            local = value.__dict__.pop("_local", None)
            if local and local.get("entry"):
                records.append(local["entry"])
        if records:
            from .kept import Kept
            from .sandbox import unguarded

            with unguarded():
                for entry in records:
                    Kept().drop(entry)          # saved: the seal record (and its kept bytes' claim) goes

    def _write(self, w: Any) -> int:
        from .rev import Rev

        rev = w.next_rev()
        txs = f"db/tx/{rev}"
        store = self._ledger._store
        with store.reading_through(w):
            before = Rev(self._ledger, rev - 1)
            dropped = {op.seal_of for op in self._ops
                       if op.seal_of and op.p == "db/value" and before._held(op.seal_of, "db/value")}
        rows: List[Tuple[str, str, str, bool]] = []
        kept: List[_Op] = []
        for op in self._ops:
            if op.seal_of in dropped:
                continue            # sealed meanwhile by another writer: idempotent
            s = txs if op.s == self.tx else op.s
            o = "str:" + txs if op.o == "str:" + self.tx else op.o
            rows.append((s, op.p, o, op.added))
            kept.append(op)
        if rev == 1:
            rows.append(("db", "db/format", "str:" + FORMAT, True))
        rows.append((txs, "db/by", "str:" + self._by, True))
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows.append((txs, "db/time", "str:" + stamp, True))
        rows.extend((txs, k, o, True) for k, o in self._preds)
        self._store_all()
        w.insert(rev, rows)
        with store.reading_through(w):
            self._validate(Rev(self._ledger, rev), kept)
        for op in kept:
            if op.added and op.p == "db/index" and op.s.startswith("db/pred/") and op.o == "str:true":
                w.create_index(op.s[len("db/pred/"):])
        return rev

    def _validate(self, R: "Rev", ops: List[_Op]) -> None:
        from .rev import Ref, type_ok

        frozen: Dict[str, Optional[List[str]]] = {}

        def own(s: str) -> Optional[List[str]]:
            if s not in frozen:
                if R._held(s, "db/value"):
                    held = R._held(s, "db/preds")
                    frozen[s] = json.loads(show(held[0].obj)) if held else []
                else:
                    frozen[s] = None
            return frozen[s]
        for op in ops:
            if op.seal_of is None:
                names = own(op.s)
                if names is not None and is_seal_predicate(op.p, names):
                    verb = "add" if op.added else "remove"
                    raise Exists(f"{op.s[:12]}… is sealed: {op.p!r} is one of its own predicates, written once "
                                 f"({verb} refused); annotate with another predicate, or seal anew and re-point")
            if op.p == "db/alias" and op.added:
                if R._held(op.s, "db/value"):
                    raise TypeError(f"{op.s[:16]!r} holds its own db/value: a name is never a sealed subject; "
                                    "alias another name")
                target = show(op.o)
                if Ref(R, target).hash is None:
                    raise TypeError(f"{op.s!r} db/alias {target!r}: an alias names a value, and {target!r} holds "
                                    "no db/value row (after its own alias chain)")
            if op.added and not op.p.startswith("db/"):
                decl = R._type(op.p)
                if decl is not None and not type_ok(self._ledger, decl, op.o):
                    raise TypeError(f"{op.p!r} is declared db/type {decl!r}; {op.s[:24]!r} was given "
                                    f"{tag(op.o)}:{show(op.o)[:40]!r}; nothing written")
                if op.pred and decl is None and tag(op.o) != "str":
                    what = "a list or dict" if tag(op.o) == "json" else "a Value"
                    raise TypeError(f"pred {op.p!r} is a one pred with no db/type: {what} is refused at the seal "
                                    f"(declare db/cardinality many, or db/type json or a class)")

    # -- verbs ----------------------------------------------------------------

    def _open(self, verb: str) -> None:
        if self._state != "open":
            raise RuntimeError(f"transaction is {self._state}: {verb} goes inside `with L.transaction(...) as t:`")

    def _encode(self, o: Any) -> str:
        from .rev import Ref

        if isinstance(o, Value):
            raise TypeError(f"add takes a str, a JSON document or a Ref, not a {type(o).__name__}: bytes enter "
                            "the ledger by v.seal(t) alone")
        if isinstance(o, Ref):
            if o.hash is None:
                raise TypeError(f"a Ref row object names a sealed value; {o.name!r} holds none")
            return ref_text(o._cls, o.hash, o.subject)
        refuse_scalar(o)
        plain = encode_plain(o)
        if plain is None:
            raise TypeError(f"a row object is a str, a JSON document or a Ref, not {type(o).__name__}")
        return plain

    def add(self, subject: str, predicate: str, object: Any) -> None:
        """Append one row; the predicate's cardinality, at read time, decides what it means."""
        self._open("add")
        _name(subject, "subject")
        _name(predicate, "predicate")
        if predicate == "db/value":
            raise TypeError("db/value rows are written by v.seal alone")
        o = self._encode(object)
        if predicate == "db/alias" and tag(o) != "str":
            raise TypeError("a db/alias row's object is the subject it names, a str")
        self._ops.append(_Op(subject, predicate, o, True))

    def remove(self, subject: str, predicate: str, object: Any) -> None:
        """Append one remove row: out of the set on a many predicate, the tombstone on a one predicate."""
        self._open("remove")
        _name(subject, "subject")
        _name(predicate, "predicate")
        self._ops.append(_Op(subject, predicate, self._encode(object), False))

    # -- declarations as the body sees them: t.base plus this transaction's own rows ---------------

    def _decl_now(self, p: str, which: str) -> Optional[str]:
        for op in reversed(self._ops):
            if op.s == f"db/pred/{p}" and op.p == which:
                return show(op.o) if op.added else None
        if which == "db/cardinality":
            return self.base._card(p)
        return self.base._type(p)

    def _card_now(self, p: str) -> str:
        from .rev import fixed_one

        return "one" if fixed_one(p) else ("many" if self._decl_now(p, "db/cardinality") == "many" else "one")

    # -- sealing --------------------------------------------------------------

    def _value_text(self, v: Any, what: str) -> str:
        from .kept import SealedRef
        from .rev import Ref

        if isinstance(v, SealedRef):
            if v.hash is None:
                raise TypeError(f"{what}: {v!r} held no value when sealed")
            if v.subject is None:
                self._by_name(v, v.hash, what)
            return v.text
        if isinstance(v, Ref):
            if v.hash is None:
                raise TypeError(f"{what}: {v.name!r} holds no value")
            return ref_text(v._cls, v.hash)
        if v.subject is None and id(v) not in self._pending:
            raise ValueError(f"{what}: an unsaved {type(v).__name__}; save it first (a typed pred is an edge "
                             "to a sealed value)")
        return ref_text(dotted(type(v)), v.hash)

    def _encode_preds(self, value: Value) -> Tuple[List[Tuple[str, str]], Dict[str, Any]]:
        """The pred rows of a seal and the canonical form that enters the subject hash (A23, A30)."""
        from .kept import SealedRef
        from .rev import Ref

        declared = type(value)._ledger_preds
        extra = [k for k in value.preds if k not in declared]
        if extra:
            raise Undeclared(f"{', '.join(map(repr, extra))}: not a pred of {dotted(type(value))} "
                             f"(@ledger_class(preds={declared!r}))")
        rows: List[Tuple[str, str]] = []
        canon: Dict[str, Any] = {}

        def scalar(k: str, v: Any) -> str:
            if isinstance(v, (Value, Ref, SealedRef)):
                return self._value_text(v, f"pred {k!r}")
            if isinstance(v, str):
                return "str:" + v
            if isinstance(v, (bool, int, float)):
                return "str:" + str(v)
            raise TypeError(f"pred {k!r}: a pred value is a str (an int, float or bool is coerced), "
                            f"not {type(v).__name__}")
        for k, v in value.preds.items():
            if self._card_now(k) == "many":
                members = list(v) if isinstance(v, (list, tuple)) else [v]
                texts = []
                for m in members:
                    t = scalar(k, m)
                    if t not in texts:
                        texts.append(t)
                rows.extend((k, t) for t in texts)
                canon[k] = sorted(texts)
            elif isinstance(v, (list, tuple, dict)):
                if self._decl_now(k, "db/type") != "json":
                    raise TypeError(f"pred {k!r}: a {type(v).__name__} under a one pred; declare "
                                    f"(db/pred/{k}, db/cardinality, many) or (db/pred/{k}, db/type, json)")
                text = encode_plain(list(v) if isinstance(v, tuple) else v)
                assert text is not None
                rows.append((k, text))
                canon[k] = text
            else:
                text = scalar(k, v)
                rows.append((k, text))
                canon[k] = text
        return rows, canon

    def _by_name(self, d: Any, h: str, what: str) -> str:
        """The subject of a dep sealed before it was saved, found by the name it was to be saved under."""
        from .rev import Ref

        name = d.name if hasattr(d, "text") else d.__dict__.get("_loaded_as")
        if name is None:
            raise ValueError(f"{what} {d!r} is sealed but saved nowhere: save it first (v.seal(t))")
        held = Ref(self._ledger.at(), name)
        if held.hash is None:
            raise ValueError(f"{what} {name!r} is sealed but saved nowhere: save it first (v.seal(t))")
        if held.hash != h:
            raise ValueError(f"{what} {name!r} is {held.hash[:12]}… on the ledger; it was sealed against "
                             f"{h[:12]}…")
        assert held.subject is not None
        return held.subject

    def _dep_items(self, deps: Sequence[Any], trace: Dict[str, str]) -> None:
        from .fn import Fn
        from .kept import SealedFn, SealedRef
        from .rev import Ref

        pending = {s: v.hash for v, s in self._pending.values()}
        for d in deps:
            if isinstance(d, (Fn, SealedFn)):
                self._ensure_fn(d)
                trace["fn"] = d.subject
                continue
            name = None
            if isinstance(d, SealedRef):
                h, text, name = d.hash, d.text, d.name
                if h is None:
                    raise ValueError(f"dep {d!r} has no sealed value")
                subj = d.subject if d.subject is not None else self._by_name(d, h, "dep")
            elif isinstance(d, Ref):
                subj, h, text = d.subject, d.hash, (d._text() if d.hash else None)
                if d.name and d.name != subj:
                    name = d.name
            elif isinstance(d, Value):
                subj, h = d.subject, d.hash
                if id(d) in self._pending:
                    subj = self._pending[id(d)][1]
                elif not d.sealed:
                    raise ValueError(f"dep {d!r} is unsealed: seal it first")
                elif subj is None:
                    subj = self._by_name(d, h, "dep")
                text = ref_text(dotted(type(d)), h)
                name = d.__dict__.get("_loaded_as")
            else:
                raise TypeError(f"a dep is a Value, a Ref or an Fn, not {type(d).__name__}")
            if subj is None or h is None or text is None:
                raise ValueError(f"dep {d!r} has no sealed value")
            if pending.get(subj) != h:
                held = Ref(self._ledger.at(), subj).hash
                if held != h:
                    raise ValueError(f"dep {subj[:12]}…: its hash is not the value the ledger holds there")
            trace[text] = text
            if name:
                trace[f"{name} db/alias"] = text

    def _env_items(self, trace: Dict[str, str], repos: Optional[Sequence[str]] = None, env: Any = None) -> None:
        from .env import current_env

        env = env if env is not None else current_env()
        for repo in (env.code if repos is None else repos):
            trace[f"code/{repo}"] = code_token(self.base, repo, env.code[repo].commit if repo in env.code else None)
        trace["uv.lock"] = env.lock
        trace["platform"] = env.platform

    def _seal_value(self, value: Value, *, deps: Sequence[Any] = (), alias: Optional[str] = None,
                    provenance: Optional[str] = None) -> str:
        """``value.seal(t)``: seal into the immutable subject ``<hash of (trace, preds, bytes)>``; return it.

        On this line the seal freezes ``preds`` (read-only), and sets ``sealed``, ``subject`` and
        ``trace``; only ``rev`` waits for the commit. A seal refused here, or a transaction abandoned
        later (a body exception, a refusal at commit), leaves the value unsealed with its preds a plain
        dict (A43).
        """
        self._open("seal")
        if not isinstance(value, Value):
            raise TypeError(f"seal takes a Value, not {type(value).__name__} (wrap it: Pickled(obj))")
        if value.subject is not None:
            raise ValueError(f"{value!r} is sealed already; a different value is a new object")
        local = value.__dict__.get("_local")
        env = None
        extra: List[Tuple[str, str]] = []
        if local is not None:
            if deps or provenance is not None:
                raise TypeError(f"deps and provenance were fixed by v.seal() at {value.sealed_at}; "
                                "save with v.seal(t) alone")
            if not local["kept"] and sha256(value.encode()) != local["hash"]:
                raise SealBroken(f"{type(value).__name__} sealed at {value.sealed_at}: its bytes changed since; "
                                 "seal a new value (or seal with keep=True to keep the bytes)")
            deps, provenance, env = local["deps"], local["provenance"], local["env"]
            extra.append(("db/sealed-at", "str:" + str(value.sealed_at)))
        provenance = check_provenance(provenance)
        if alias is not None:
            _name(alias, "alias")
        pred_rows, canon = self._encode_preds(value)
        trace: Dict[str, str] = {}
        self._dep_items(deps, trace)
        self._env_items(trace, env=env)
        vtext = ref_text(dotted(type(value)), value.hash)
        subject = hash_text(canonical({"trace": trace, "preds": canon, "value": vtext}))
        self._seal(value, subject, trace, provenance, pred_rows, extra, alias)
        self._freeze(value, subject, trace)
        return subject

    def _freeze(self, value: Value, subject: str, trace: Dict[str, str]) -> None:
        """The seal fixes subject, trace and preds now; the revision is assigned at commit (Q25 (D))."""
        from types import MappingProxyType
        from .value import FrozenPreds

        h = value.hash
        if value.sealed:
            self._frozen.append((value, None))
        else:
            self._frozen.append((value, dict(value.preds)))
            value.__dict__["_preds"] = FrozenPreds(value.preds)
            value.sealed_at = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        value.subject = subject
        value.trace = MappingProxyType(dict(trace))
        value.sealed = True
        value.__dict__["_hash"] = h
        value.__dict__["_ledger"] = self._ledger

    def _seal(self, value: Value, subject: str, trace: Dict[str, str], provenance: str,
              pred_rows: List[Tuple[str, str]], extra: List[Tuple[str, str]], alias: Optional[str]) -> None:
        h = value.hash
        already = any(s == subject for _v, s in self._pending.values())
        if not already:
            self._to_store.append(value)
        self._pending[id(value)] = (value, subject)
        self._finalize.append((value, subject, dict(trace), None))
        if not already and not self.base._held(subject, "db/value"):
            ops: List[Tuple[str, str, bool]] = [
                ("db/value", ref_text(dotted(type(value)), h), False),
                ("db/kind", "str:" + dotted(type(value)), False),
                ("db/provenance", "str:" + provenance, False),
                ("db/preds", "json:" + canonical(list(type(value)._ledger_preds)), False)]
            ops += [(p, o, False) for p, o in extra]
            ops += [(f"db/trace/{k}", "str:" + v, False) for k, v in sorted(trace.items())]
            ops += [(p, o, True) for p, o in pred_rows]
            for p, o, is_pred in ops:
                self._ops.append(_Op(subject, p, o, True, seal_of=subject, pred=is_pred))
        if alias is not None:
            self._ops.append(_Op(alias, "db/alias", "str:" + subject, True))

    def _ensure_fn(self, f: "Fn") -> None:
        if f.subject in self._fns:
            return
        self._fns.add(f.subject)
        if self.base._held(f.subject, "db/name"):
            return
        for p, o in f._rows():
            self._ops.append(_Op(f.subject, p, o, True))

    # -- the bracket ----------------------------------------------------------

    @staticmethod
    def _exact(s: Any) -> str:
        _name(s, "subject")
        if "*" in s:
            raise TypeError(f"{s!r}: bracket writes take exact subjects; globs live on all and refs")
        return s

    def __setitem__(self, key: Any, value: Any) -> None:
        """``t[s, p] = o``: an ``add`` on a one predicate. ``t[s] = {...}``: make the user rows equal (A34, A43)."""
        self._open("a bracket write")
        if isinstance(key, tuple):
            if len(key) != 2:
                raise TypeError("a bracket write is t[s, p] = o or t[s] = {...}")
            s, p = self._exact(key[0]), _name(key[1], "predicate")
            if p.startswith("db/"):
                raise TypeError(f"{p!r}: machinery is not written through the bracket; use add")
            if self._card_now(p) == "many":
                raise TypeError(f"t[s, p] = o writes one predicates only; {p!r} has cardinality many "
                                "(use add, or t[s] = {...} with a list)")
            self.add(s, p, value)
            return
        s = self._exact(key)
        if not isinstance(value, dict):
            raise TypeError(f"t[s] = record takes a dict, not {type(value).__name__}")
        base = self.base
        current = base._record_of(s)
        for p, o in value.items():
            if not isinstance(p, str) or not p:
                raise TypeError(f"a record key is a non-empty str, not {p!r}")
            if p.startswith("db/"):
                if p not in current or current[p] != o:
                    raise TypeError(f"{p!r}: a db/ key differing from the current row; machinery is not "
                                    "written through the bracket")
        for p in [q for q in current if not q.startswith("db/") and q not in value]:
            for h in base._held(s, p):
                self._ops.append(_Op(s, p, h.obj, False))
        for p, o in value.items():
            if p.startswith("db/"):
                continue
            held = [h.obj for h in base._held(s, p)]
            if self._card_now(p) == "many":
                want = [self._encode(m) for m in (o if isinstance(o, list) else [o])]
                for h in held:
                    if strip_hint(h) not in [strip_hint(w) for w in want]:
                        self._ops.append(_Op(s, p, h, False))
                for w in want:
                    if strip_hint(w) not in [strip_hint(h) for h in held]:
                        self._ops.append(_Op(s, p, w, True))
            else:
                w = self._encode(o)
                if not held or strip_hint(held[0]) != strip_hint(w):
                    self._ops.append(_Op(s, p, w, True))

    def __delitem__(self, key: Any) -> None:
        """``del t[s, p]``: retract what ``p`` holds on ``s``. ``del t[s]``: every user row; ``db/`` rows survive."""
        self._open("a bracket delete")
        if isinstance(key, tuple):
            if len(key) != 2:
                raise TypeError("del takes t[s, p] or t[s]")
            s, p = self._exact(key[0]), _name(key[1], "predicate")
            if p.startswith("db/"):
                raise TypeError(f"{p!r}: machinery is not retracted through the bracket; use remove")
            preds = [p]
        else:
            s = self._exact(key)
            preds = [q for q in self.base._record_of(s) if not q.startswith("db/")]
        for p in preds:
            for h in self.base._held(s, p):
                self._ops.append(_Op(s, p, h.obj, False))


def scratch_folder(prefix: str = "ledger-work-") -> str:
    return tempfile.mkdtemp(prefix=prefix)


__all__ = ["Transaction", "attr", "code_token", "parse_ref"]
