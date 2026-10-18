"""``Rev``, a frozen view of the ledger at one revision, and ``Ref``, one value at one moment.

Every read lives on ``Rev``. A read folds the rows at or before the revision
by the predicate's cardinality as of that revision (``fold``); a pattern
fixing all three positions reads the history instead (the revisions that
asserted the triple, superseded or not).
"""

from __future__ import annotations

import importlib
import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

from .codec import canonical, encode_plain, key_text, parse_ref, short
from .errors import Multiple, Unindexed
from .fold import BUILTIN_ONE, Held, cardinality_of, fold
from .value import Value

if TYPE_CHECKING:
    from .fn import Fn
    from .ledger import Ledger

_NONE = "<none>"


def token(obj: Any) -> str:
    """A read's result as one comparable string: what a trace item stores."""
    if obj is None:
        return _NONE
    if isinstance(obj, str):
        return obj
    if isinstance(obj, (dict, list)) and not _has_refs(obj):
        return "json:" + canonical(obj)
    if isinstance(obj, Ref):
        return obj.hash or ("ref:" + obj.subject)
    if isinstance(obj, Rev):
        return str(obj.id)
    if isinstance(obj, (list, tuple)):
        return "h:" + short(canonical([token(x) for x in obj]))
    return "h:" + short(repr(obj))


def _has_refs(obj: Any) -> bool:
    if isinstance(obj, (Ref, Rev, tuple)):
        return True
    if isinstance(obj, dict):
        return any(_has_refs(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_refs(v) for v in obj)
    return False


def _class(name: str) -> type:
    parts = name.split(".")
    for i in range(len(parts) - 1, 0, -1):
        try:
            obj: Any = importlib.import_module(".".join(parts[:i]))
        except ImportError:
            continue
        try:
            for a in parts[i:]:
                obj = getattr(obj, a)
        except AttributeError:
            continue
        if isinstance(obj, type):
            return obj
    raise ImportError(f"value class {name!r} does not import (renamed or moved? a rename needs an alias row)")


class Rev:
    """A frozen view of the ledger as of revision ``id``."""

    def __init__(self, ledger: "Ledger", id: int, _rec: Optional[Dict[str, str]] = None) -> None:
        self.ledger = ledger
        self.id = id
        self._rec = _rec
        self._cards: Dict[str, str] = {}

    # -- identity -------------------------------------------------------------

    @property
    def tx(self) -> str:
        """``ledger/tx/<id>``: the subject carrying this revision's transaction provenance."""
        return f"ledger/tx/{self.id}"

    def __repr__(self) -> str:
        return f"Rev({self.id})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Rev) and other.ledger is self.ledger and other.id == self.id

    def __hash__(self) -> int:
        return hash((id(self.ledger), self.id))

    def __lt__(self, other: "Rev") -> bool:
        return self.id < other.id

    def __le__(self, other: "Rev") -> bool:
        return self.id <= other.id

    def __gt__(self, other: "Rev") -> bool:
        return self.id > other.id

    def __ge__(self, other: "Rev") -> bool:
        return self.id >= other.id

    def _plain(self) -> "Rev":
        return self if self._rec is None else self.ledger.at(self.id)

    # -- the fold -------------------------------------------------------------

    @property
    def _store(self) -> Any:
        return self.ledger._store

    def _card(self, p: str) -> str:
        c = self._cards.get(p)
        if c is None:
            if p in BUILTIN_ONE:
                c = "one"
            else:
                c = cardinality_of(self._store.rows(self.id, subject=f"ledger/pred/{p}", predicate="cardinality"))
            self._cards[p] = c
        return c

    def _after(self, since: Optional["Rev"]) -> int:
        if since is None:
            return 0
        if not isinstance(since, Rev):
            raise TypeError(f"since is a Rev, not {type(since).__name__}")
        return since.id

    def _held(self, s: str, p: str, after: int = 0) -> List[Held]:
        return fold(self._store.rows(self.id, subject=s, predicate=p, after=after), self._card(p))

    def _held_rows(self, after: int = 0, *, subject: Optional[str] = None, predicate: Optional[str] = None,
                   prefix: Optional[str] = None) -> List[Tuple[str, str, Held]]:
        """Every held ``(s, p, held)`` among the rows selected, ordered by asserting (rev, ord)."""
        groups: Dict[Tuple[str, str], list] = {}
        for r in self._store.rows(self.id, subject=subject, predicate=predicate, prefix=prefix, after=after):
            groups.setdefault((r[2], r[3]), []).append(r)
        out = []
        for (s, p), rows in groups.items():
            for h in fold(rows, self._card(p)):
                out.append((s, p, h))
        out.sort(key=lambda x: (x[2].rev, x[2].ord))
        return out

    def _decode(self, text: str, row_subject: str) -> Any:
        tag, _, rest = text.partition(":")
        if tag == "str":
            return rest
        if tag == "json":
            return json.loads(rest)
        if tag == "ref":
            cls, h, subj = parse_ref(text)
            return Ref._from_row(self._plain(), subj or row_subject, h, cls)
        raise ValueError(f"row object {text[:60]!r}: unknown tag")

    def _matcher(self, o: Any):
        """A predicate on stored object strings: does this row hold ``o``."""
        if isinstance(o, (Ref, Value)):
            h = o.hash
            subj = o.subject

            def m(text: str) -> bool:
                if not text.startswith("ref:"):
                    return False
                _c, rh, rs = parse_ref(text)
                return rh == h if h else rs == subj
            return m
        plain = encode_plain(o)
        if plain is None:
            plain = "str:" + key_text(o)
        return lambda text: text == plain

    # -- recording (inside eval) ---------------------------------------------

    def _record(self, item: str, value: str) -> None:
        if self._rec is not None:
            self._rec[item] = value

    def _record_query(self, method: str, args: Sequence[Any], kwargs: Dict[str, Any], result: Any) -> None:
        if self._rec is None:
            return
        if method in ("getitem", "get") and len(args) == 2 and not kwargs.get("since"):
            s, p = args
            if p == "version":
                item = s
                if s.startswith("code/"):
                    self._record(s, self._code_token(s))
                    return
            else:
                item = f"{s}#{p}"
            self._record(item, token(result))
            return
        spec = canonical([method, [token(a) for a in args],
                          {k: token(v) if not isinstance(v, (dict, tuple)) else
                           ({kk: token(vv) for kk, vv in v.items()} if isinstance(v, dict) else list(v))
                           for k, v in sorted(kwargs.items()) if v is not None}])
        self._record("q:" + spec, token(result))

    # -- row reads ------------------------------------------------------------

    def _pattern(self, pattern: Sequence[Any], after: int) -> List[Any]:
        n = len(pattern)
        if n > 3:
            raise TypeError(f"a pattern fixes at most 3 positions, not {n}")
        for i, x in enumerate(pattern[:2]):
            if not isinstance(x, str) or not x:
                raise TypeError(f"position {i + 1} of a pattern is a non-empty str, not {x!r}")
        if n == 0:
            return [(s, p, self._decode(h.obj, s)) for s, p, h in self._held_rows(after)]
        if n == 1:
            return [(p, self._decode(h.obj, s)) for s, p, h in self._held_rows(after, subject=pattern[0])]
        if n == 2:
            s, p = pattern
            return [self._decode(h.obj, s) for h in self._held(s, p, after)]
        s, p, o = pattern
        m = self._matcher(o)
        revs: List[int] = []
        for r in self._store.rows(self.id, subject=s, predicate=p, after=after):
            if r[5] and m(r[4]) and r[0] not in revs:
                revs.append(r[0])
        return [self.ledger.at(i) for i in revs]

    @staticmethod
    def _key(key: Any) -> Tuple[Any, ...]:
        if isinstance(key, str):
            return (key,)
        if isinstance(key, tuple) and 1 <= len(key) <= 3:
            return key
        raise TypeError(f"a lookup is a str or a 2- or 3-tuple, not {key!r}")

    def __getitem__(self, key: Any) -> Any:
        """Exactly one match of a 1-, 2- or 3-position pattern; ``KeyError`` (none) or ``Multiple`` (several)."""
        pattern = self._key(key)
        found = self._pattern(pattern, 0)
        if not found:
            raise KeyError(f"no match for {pattern!r} at rev {self.id}")
        if len(found) > 1:
            raise Multiple(f"{len(found)} matches for {pattern!r} at rev {self.id}")
        self._record_query("getitem", pattern, {}, found[0])
        return found[0]

    def get(self, *pattern: Any, default: Any = None, since: Optional["Rev"] = None) -> Any:
        """At most one match: none -> ``default``, several -> ``Multiple``."""
        if not 1 <= len(pattern) <= 3:
            raise TypeError(f"get takes 1 to 3 pattern positions, not {len(pattern)}")
        found = self._pattern(pattern, self._after(since))
        if len(found) > 1:
            raise Multiple(f"{len(found)} matches for {pattern!r} at rev {self.id}")
        out = found[0] if found else default
        self._record_query("get", pattern, {"since": since}, None if not found else out)
        return out

    def all(self, *pattern: Any, since: Optional["Rev"] = None) -> list:
        """Every match, by asserting revision. ``since`` keeps only rows asserted in ``(since, id]``."""
        out = self._pattern(pattern, self._after(since))
        self._record_query("all", pattern, {"since": since}, out)
        return out

    def __contains__(self, triple: Any) -> bool:
        """Whether the triple is held (by the fold) at this revision."""
        if not (isinstance(triple, tuple) and len(triple) == 3):
            raise TypeError("`in` takes a (subject, predicate, object) triple")
        s, p, o = triple
        m = self._matcher(o)
        out = any(m(h.obj) for h in self._held(s, p))
        self._record_query("contains", triple, {}, "true" if out else "false")
        return out

    # -- subject reads --------------------------------------------------------

    def _queryable(self, pred: str) -> None:
        if "." not in pred:
            return
        if any(h.obj == "str:true" for h in self._held(f"ledger/pred/{pred}", "index")):
            return
        if self._store.read("SELECT 1 FROM quads WHERE predicate = ? AND rev <= ? LIMIT 1", (pred, self.id)):
            return
        raise Unindexed(f"{pred!r} is not declared indexed (ledger/pred/{pred} index true) and no row has it "
                        f"at rev {self.id}")

    @staticmethod
    def _prefix(s: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """``(exact, prefix)`` for an ``s=`` constraint."""
        if s is None:
            return None, None
        if not isinstance(s, str) or not s:
            raise TypeError(f"s is a non-empty str, not {s!r}")
        if "*" in s[:-1]:
            raise ValueError(f"s={s!r}: a glob is a prefix, 'run/0-2-2/*'; a wildcard anywhere else is refused")
        if s.endswith("*"):
            return None, s[:-1]
        return s, None

    def _subjects(self, s: Any, where: Optional[Dict[str, Any]], attrs: Dict[str, Any],
                  since: Optional["Rev"]) -> List[str]:
        after = self._after(since)
        exact, prefix = self._prefix(s)
        cons: List[Tuple[str, Any]] = [("fn" if k == "fn" else f"kwargs.{k}", v) for k, v in attrs.items()]
        if where is not None:
            if not isinstance(where, dict):
                raise TypeError("where is a dict of predicate -> value (None: any value)")
            cons.extend(where.items())
        for p, _v in cons:
            self._queryable(p)
        order: Dict[str, Tuple[int, int]] = {}
        if not cons:
            for subj, _p, h in self._held_rows(after, subject=exact, prefix=prefix):
                order.setdefault(subj, (h.rev, h.ord))
            return sorted(order, key=lambda x: (order[x], x))
        p0, v0 = cons[0]
        m0 = None if v0 is None else self._matcher(v0)
        for subj, _p, h in self._held_rows(after, subject=exact, predicate=p0, prefix=prefix):
            if m0 is None or m0(h.obj):
                order[subj] = max(order.get(subj, (0, 0)), (h.rev, h.ord))
        out = []
        for subj in order:
            ok = True
            for p, v in cons[1:]:
                held = self._held(subj, p, after)
                m = None if v is None else self._matcher(v)
                if not any(m is None or m(h.obj) for h in held):
                    ok = False
                    break
            if ok:
                out.append(subj)
        return sorted(out, key=lambda x: (order[x], x))

    @staticmethod
    def _one(found: list, one: bool, what: str) -> Any:
        if not one:
            return found
        if not found:
            raise KeyError(f"{what}: no subject matched")
        if len(found) > 1:
            raise Multiple(f"{what}: {len(found)} subjects matched")
        return found[0]

    def refs(self, *, s: Optional[str] = None, where: Optional[Dict[str, Any]] = None, one: bool = False,
             since: Optional["Rev"] = None, **attrs: Any) -> Any:
        """The subjects satisfying every constraint, each a ``Ref`` at this revision."""
        found = [Ref(self._plain(), x) for x in self._subjects(s, where, attrs, since)]
        self._record_query("refs", (), {"s": s, "where": where, "since": since, **attrs}, found)
        return self._one(found, one, "refs")

    def _column(self, subj: str, key: str) -> Any:
        pred = key
        if "." not in key and key != "fn" and self._held(subj, f"kwargs.{key}"):
            pred = f"kwargs.{key}"
        held = self._held(subj, pred)
        if self._card(pred) == "many":
            return [self._decode(h.obj, subj) for h in held]
        return self._decode(held[-1].obj, subj) if held else None

    def select(self, keys: Tuple[str, ...], *, s: Optional[str] = None, where: Optional[Dict[str, Any]] = None,
               one: bool = False, since: Optional["Rev"] = None, **attrs: Any) -> Any:
        """Each matching subject's values for ``keys``, as a tuple in that order."""
        if isinstance(keys, str) or not isinstance(keys, (tuple, list)) or not keys:
            raise TypeError(f"keys is a non-empty tuple of predicate names, not {keys!r}")
        for k in keys:
            if "." in k:
                self._queryable(k)
        found = [tuple(self._column(x, k) for k in keys) for x in self._subjects(s, where, attrs, since)]
        self._record_query("select", tuple(keys), {"s": s, "where": where, "since": since, **attrs}, found)
        return self._one(found, one, "select")

    def load(self, subject: str) -> Value:
        """``Ref(self, subject).load()``: the one read that fetches bytes."""
        r = Ref(self._plain(), subject)
        v = r.load()
        self._record("dat:" + subject, r.hash or _NONE)
        return v

    def load_fn(self, name: str) -> "Fn":
        """The revision function ``name`` resolves to here; loads, does not call."""
        from .fn import load_fn

        return load_fn(self, name)

    def eval(self, name: str, *, memo: Any = True, **keys: Any) -> Optional[Value]:
        """``load_fn(name)(memo=memo, **keys)``; ``name`` is a dotted string only."""
        if not isinstance(name, str):
            raise TypeError("eval takes a dotted name; the object form is the Fn itself, called")
        return self.load_fn(name)(memo=memo, **keys)

    # -- the present value of a trace item -----------------------------------

    def _code_token(self, subject: str) -> str:
        v = self._plain().get(subject, "version")
        c = self._plain().get(subject, "commit")
        if v is None and c is None:
            return _NONE
        return f"{v or ''}+{c}" if c is not None else str(v)

    def _present(self, item: str, env: Any = None) -> str:
        from .fn import current_env

        plain = self._plain()
        if item == "fn":
            raise ValueError("the fn item is compared by _matches")
        if item in ("uv.lock", "platform"):
            env = env or current_env(None)
            return env.lock if item == "uv.lock" else env.platform
        if item.startswith("dat:"):
            name = item[4:]
            at = plain
            base, sep, n = name.rpartition("@")
            if sep and n.isdigit():
                name, at = base, self.ledger.at(int(n))
            return Ref(at, name).hash or _NONE
        if item.startswith("eval:"):
            body = item[5:]
            i = body.index("{")
            got = plain.eval(body[:i], memo="get", **json.loads(body[i:]))
            return got.hash if got is not None else _NONE
        if item.startswith("q:"):
            method, args, kwargs = json.loads(item[2:])
            return token(plain._requery(method, args, kwargs))
        if "#" in item:
            s, _, p = item.rpartition("#")
            return token(plain.get(s, p))
        if item.startswith("code/"):
            return self._code_token(item)
        return token(plain.get(item, "version"))

    def _requery(self, method: str, args: List[Any], kwargs: Dict[str, Any]) -> Any:
        if "since" in kwargs:
            kwargs["since"] = self.ledger.at(int(kwargs["since"]))
        if method == "getitem":
            return self[tuple(args)]
        if method == "get":
            return self.get(*args, **kwargs)
        if method == "all":
            return self.all(*args, **kwargs)
        if method == "contains":
            return "true" if tuple(args) in self else "false"
        if method == "refs":
            return self.refs(**kwargs)
        if method == "select":
            return self.select(tuple(args), **kwargs)
        raise ValueError(f"unknown recorded query {method!r}")

    def _matches(self, trace: Dict[str, str]) -> bool:
        from .fn import current_env, fn_name_of

        env = None
        if "fn" in trace:
            try:
                f = self._plain().load_fn(fn_name_of(trace["fn"]))
            except ImportError:
                return False
            if f.subject != trace["fn"]:
                return False
            env = f.env
        env = env or current_env(None)
        return all(self._present(k, env) == v for k, v in trace.items() if k != "fn")


class Ref:
    """A reference to one value at one moment: ``Ref(rev, subject)``, fixed when made."""

    __slots__ = ("rev", "subject", "hash", "_cls", "_target")

    def __init__(self, rev: Rev, subject: str) -> None:
        if not isinstance(rev, Rev):
            raise TypeError(f"Ref(rev, subject): rev is a Rev, not {type(rev).__name__}")
        if not isinstance(subject, str) or not subject:
            raise TypeError(f"Ref(rev, subject): subject is a non-empty str, not {subject!r}")
        rev = rev._plain()
        held = rev._held(subject, "value")
        h = cls = target = None
        if held:
            text = held[-1].obj
            if text.startswith("ref:"):
                cls, h, target = parse_ref(text)
        self._set(rev, subject, h, cls, target)

    def _set(self, rev: Rev, subject: str, h: Optional[str], cls: Optional[str], target: Optional[str]) -> None:
        object.__setattr__(self, "rev", rev)
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "hash", h)
        object.__setattr__(self, "_cls", cls)
        object.__setattr__(self, "_target", target if target != subject else None)

    @classmethod
    def _from_row(cls, rev: Rev, subject: str, h: Optional[str], cname: Optional[str]) -> "Ref":
        r = cls.__new__(cls)
        r._set(rev, subject, h, cname, None)
        return r

    def __setattr__(self, k: str, v: Any) -> None:
        raise AttributeError("a Ref is frozen")

    @property
    def type(self) -> Optional[type]:
        """The ``Value`` subclass that decodes the bytes; ``None`` for a subject with no value."""
        return None if self._cls is None else _class(self._cls)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Ref):
            return False
        if self.hash is not None or other.hash is not None:
            return self.hash == other.hash
        return self.subject == other.subject and self.rev.id == other.rev.id

    def __hash__(self) -> int:
        return hash(self.hash) if self.hash is not None else hash((self.subject, self.rev.id))

    def __repr__(self) -> str:
        return f"Ref({self.rev.id}, {self.subject!r})"

    def __reduce__(self) -> Any:
        raise TypeError("a Ref is bound to an open ledger and does not pickle")

    def load(self) -> Value:
        """Fetch the bytes, decode them by ``type``, restore the provenance from the subject's rows."""
        return self._load(self.rev)

    def _load(self, rev: Rev) -> Value:
        """``load``, with ``rev`` (the revision the value is handed back under) as the value's ``rev``."""
        if self.hash is None:
            raise KeyError(f"{self.subject!r} has no value at rev {self.rev.id}")
        target = self._target or self.subject
        key = (self.hash, target, self.rev.id, rev.id)
        cache = self.rev.ledger._values
        if key in cache:
            return cache[key]
        store = self.rev.ledger._store.art
        cls = self.type
        assert cls is not None
        v = cls.decode(store.get(self.hash), store)
        if not isinstance(v, Value):
            raise TypeError(f"{cls.__name__}.decode returned {type(v).__name__}, not a Value")
        rows = self.rev._held_rows(subject=target)
        sealed = any(p == "provenance" for _s, p, _h in rows)
        trace = {p[len("trace."):]: self.rev._decode(h.obj, target) for _s, p, h in rows if p.startswith("trace.")}
        v._provenance(subject=target, rev=rev, trace=trace, sealed=sealed)
        cache[key] = v
        return v
