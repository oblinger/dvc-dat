"""``Transaction``: the write set of one ``with L.transaction(...)``, one revision on exit.

``add`` and ``remove`` append rows and read nothing; ``seal`` freezes a
``Value`` into an immutable subject, reading the snapshot ``base`` to check its
deps and find the predicates declared indexed. The ``Exists`` check (an add on
a sealed subject's own predicates) runs at commit, inside the write lock.
"""

from __future__ import annotations

import ctypes
import datetime as _dt
import signal
import threading
import time as _time
import uuid
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .codec import canonical, check_scalar, encode_plain, key_text, ref_text, short
from .errors import Exists, LockTimeout
from .value import Pickled, Value, dotted

if TYPE_CHECKING:
    from .fn import Fn
    from .ledger import Ledger
    from .rev import Rev

#: Predicates a seal writes once; a later add or remove on one of them raises ``Exists``.
SEAL_PREDICATES = frozenset({"value", "kind", "provenance", "fn"})
SEAL_PREFIXES = ("trace.", "kwargs.", "result.")


def is_seal_predicate(p: str) -> bool:
    return p in SEAL_PREDICATES or p.startswith(SEAL_PREFIXES)


def index_text(v: Any) -> Optional[str]:
    """Q5 (A): an indexed attribute's text; ``None`` for a value with no text form."""
    if isinstance(v, (dict, list)):
        try:
            return canonical(v)
        except (TypeError, ValueError):
            return None
    try:
        return key_text(v)
    except TypeError:
        return None


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
    __slots__ = ("s", "p", "o", "added", "seal_of")

    def __init__(self, s: str, p: str, o: str, added: bool, seal_of: Optional[str] = None) -> None:
        self.s, self.p, self.o, self.added, self.seal_of = s, p, o, added, seal_of


def _name(x: Any, what: str) -> str:
    if not isinstance(x, str) or not x:
        raise TypeError(f"{what} is a non-empty str, not {x!r}")
    return x


class Transaction:
    """The write set open under one ``with L.transaction(...)``."""

    def __init__(self, ledger: "Ledger", by: str, lock: Optional[float], time: bool,
                 preds: Dict[str, Any]) -> None:
        self._ledger = ledger
        self._by = _name(by, "by")
        if lock is not None and (isinstance(lock, bool) or not isinstance(lock, (int, float)) or lock <= 0):
            raise TypeError(f"lock is a positive number of seconds, not {lock!r}")
        if not isinstance(time, bool):
            raise TypeError("time=True stamps the wall clock; no value may be passed in")
        self._lock = lock
        self._time = time
        #: A placeholder for ``ledger/tx/<rev>``, rewritten at commit.
        self.tx = f"ledger/tx/pending-{uuid.uuid4().hex[:12]}"
        self._preds: List[Tuple[str, str]] = []
        self._ops: List[_Op] = []
        for k, v in preds.items():
            self._preds.append((k, self._encode(v)))
        self._state = "new"
        self._base: Optional["Rev"] = None
        self._rev: Optional["Rev"] = None
        self._pending: Dict[int, Tuple[Value, str]] = {}   # id(value) -> (value, subject)
        self._finalize: List[Tuple[Value, str, Dict[str, str], Optional["Rev"]]] = []
        self._fns: set = set()
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
            self._t0 = _time.monotonic()
            self._arm(left)
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
            et, ev, tb = LockTimeout, LockTimeout(f"lock={self._lock}: the body ran past its limit"), None
            self._state = "abandoned"
            self._cm.__exit__(et, ev, tb)
            raise ev
        if et is not None:
            self._state = "abandoned"
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
            self._state = "abandoned"
            raise
        self._rev = self._ledger.at(rev)
        for value, subject, trace, made in self._finalize:
            value._provenance(subject=subject, rev=made if made is not None else self._base,
                              trace=trace, sealed=True)
        self._state = "committed"
        return False

    def _write(self, w: Any) -> int:
        rev = w.next_rev()
        txs = f"ledger/tx/{rev}"
        rows: List[Tuple[str, str, str, bool]] = [(txs, "by", "str:" + self._by, True)]
        if self._time:
            rows.append((txs, "time", "str:" + _dt.datetime.now(_dt.timezone.utc).isoformat(), True))
        rows.extend((txs, k, o, True) for k, o in self._preds)
        sealed_cache: Dict[str, bool] = {}

        def sealed_before(s: str) -> bool:
            if s not in sealed_cache:
                sealed_cache[s] = any(r[3] == "provenance" and r[5] for r in w.rows(s))
            return sealed_cache[s]

        seal_subjects = {op.seal_of for op in self._ops if op.seal_of}
        dropped = {s for s in seal_subjects if sealed_before(s)}   # sealed meanwhile: idempotent
        for op in self._ops:
            if op.seal_of is not None:
                if op.seal_of in dropped:
                    continue
            elif is_seal_predicate(op.p) and (op.s in seal_subjects or sealed_before(op.s)):
                raise Exists(f"{op.s!r} is sealed: {op.p!r} is one of its own predicates, written once "
                             "(annotate it with any other predicate)")
            s = txs if op.s == self.tx else op.s
            o = "str:" + txs if op.o == "str:" + self.tx else op.o
            rows.append((s, op.p, o, op.added))
        w.insert(rev, rows)
        return rev

    # -- verbs ----------------------------------------------------------------

    def _open(self, verb: str) -> None:
        if self._state != "open":
            raise RuntimeError(f"transaction is {self._state}: {verb} goes inside `with L.transaction(...) as t:`")

    def _store_value(self, v: Value) -> str:
        art = self._ledger._store.art
        for _h, data in v._parts().items():
            art.put(data)
        return art.put(v.encode())

    def _encode(self, o: Any, predicate: str = "") -> str:
        from .rev import Ref

        # `value` is always an artifact Ref (what `load` reads): there a str or JSON document is
        # wrapped in Pickled like any other object, never stored as a plain row.
        plain = None if predicate == "value" else encode_plain(o)
        if plain is not None:
            return plain
        check_scalar(o)
        if isinstance(o, Ref):
            return ref_text(o._cls, o.hash, o._target or o.subject)
        if not isinstance(o, Value):
            o = Pickled(o)
        h = self._store_value(o)
        subject = None
        if id(o) in self._pending:
            subject = self._pending[id(o)][1]
        elif o.sealed:
            subject = o.subject
        return ref_text(dotted(type(o)), h, subject)

    def add(self, subject: str, predicate: str, object: Any) -> None:
        """Append one row; the predicate's cardinality, at read time, decides what it means."""
        self._open("add")
        self._ops.append(_Op(_name(subject, "subject"), _name(predicate, "predicate"),
                             self._encode(object, predicate), True))

    def remove(self, subject: str, predicate: str, object: Any) -> None:
        """Append one remove row: out of the set on a many predicate, the tombstone on a single one."""
        self._open("remove")
        self._ops.append(_Op(_name(subject, "subject"), _name(predicate, "predicate"),
                             self._encode(object, predicate), False))

    def seal(self, value: Value, *, deps: Sequence[Any] = ()) -> str:
        """Freeze ``value`` into the immutable subject ``<kind>/<hash of (trace, bytes hash)>``; return it."""
        from .fn import Fn, current_env
        from .rev import Ref

        self._open("seal")
        if not isinstance(value, Value):
            raise TypeError(f"seal takes a Value, not {type(value).__name__} (wrap it: Pickled(obj))")
        base = self.base
        trace: Dict[str, str] = {}
        pending = {s: v.hash for v, s in self._pending.values()}
        for d in deps:
            if isinstance(d, Fn):
                self._ensure_fn(d)
                trace["fn"] = d.subject
                continue
            if isinstance(d, Ref):
                subj, h, at = d.subject, d.hash, d.rev
            elif isinstance(d, Value):
                subj, h, at = d.subject, d.hash, d.rev
                if subj is None and id(d) in self._pending:
                    subj, at = self._pending[id(d)][1], None
            else:
                raise TypeError(f"a dep is a Value, a Ref or an Fn, not {type(d).__name__}")
            if subj is None or h is None:
                raise ValueError(f"dep {d!r} has no subject or no value: load it, or seal it first")
            if pending.get(subj) != h:
                held = Ref(at if at is not None else base, subj).hash
                if held != h:
                    raise ValueError(f"dep {subj!r}: its hash {h} is not the value the ledger holds ({held})")
            trace[f"dat:{subj}" if at is None or at.id == base.id else f"dat:{subj}@{at.id}"] = h
        env = current_env(None)
        for repo in env.code:
            trace[f"code/{repo}"] = base._code_token(f"code/{repo}")
        trace["uv.lock"] = env.lock
        trace["platform"] = env.platform
        subject = f"{type(value).__name__}/{short(canonical({'trace': trace, 'hash': value.hash}))}"
        return self._seal(value, subject, trace, "seal", [], None)

    def _ensure_fn(self, f: "Fn") -> None:
        if f.subject in self._fns:
            return
        self._fns.add(f.subject)
        if self.base._held(f.subject, "sha"):
            return
        rows = [("name", f.name), ("module", str(f.module) if f.module else ""), ("sha", f.sha),
                ("modules", {f._module_name: f.sha}), ("mode", f.mode)]
        if f.env.mounts is not None:
            rows.append(("mounts", f.env.mounts))
        for p, o in rows:
            self._ops.append(_Op(f.subject, p, self._encode(o), True))

    def _seal(self, value: Value, subject: str, trace: Dict[str, str], provenance: str,
              extra: List[Tuple[str, str]], made: Optional["Rev"], keys: Optional[Dict[str, Any]] = None) -> str:
        base = self.base
        h = self._store_value(value)
        already = any(s == subject for _v, s in self._pending.values())
        self._pending[id(value)] = (value, subject)
        self._finalize.append((value, subject, dict(trace), made))
        if already or base._held(subject, "provenance"):
            return subject
        ops = [("value", ref_text(dotted(type(value)), h, None)), ("kind", "str:" + type(value).__name__),
               ("provenance", "str:" + provenance)]
        ops += [(f"trace.{k}", "str:" + v) for k, v in sorted(trace.items())]
        ops += extra
        written = {p for p, _o in ops}
        record = {"kwargs": keys or {}, "result": value.obj if isinstance(value, Pickled) else value}
        for s, _p, held in base._held_rows(predicate="index", prefix="ledger/pred/"):
            p = s[len("ledger/pred/"):]
            if held.obj != "str:true" or p in written:
                continue
            try:
                text = index_text(attr(record, p))
            except KeyError:
                continue
            if text is not None:
                ops.append((p, "str:" + text))
                written.add(p)
        for p, o in ops:
            self._ops.append(_Op(subject, p, o, True, seal_of=subject))
        return subject
