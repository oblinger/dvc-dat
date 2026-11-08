"""``Rev``, a frozen view of the ledger at one revision; ``Ref``, one value at one moment; ``Row``.

Every read lives on ``Rev``. The row reads (``[]``, ``get``, ``all``, ``in``)
fold the rows at or before the revision by each predicate's cardinality as of
that revision, at every arity (Q19); ``history`` takes the same pattern and
walks history unfolded, removes included. The subject reads (``refs``, ``values``,
``value``, ``select``, ``load``, ``run``) treat the store as a table whose
rows are subjects. No pattern read decodes a ``ref:`` object: it comes back a
``Ref``, unloaded (Q35). Inside a value function the ``Rev`` handed to the body
traces what it reads into the value's dependencies (``dependencies``).
"""

from __future__ import annotations

import importlib
import json
from typing import TYPE_CHECKING, Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

from .codec import canonical, encode_plain, is_hash, parse_ref, ref_text, show, strip_hint, tag
from .errors import AliasLoop, Multiple, Unindexed
from .fn import OWN
from .fold import Held, fold
from .value import TIMEZONE, FrozenPreds, Value, dotted, shown_in, takes_name, zone_named

if TYPE_CHECKING:
    from .namespace import LedgerNamespace
    from .ledger import Ledger
    from .pin import Rerun

ALIAS_HOPS = 8
_OMIT = object()
NONE_TOKEN = "<none>"


FIXED_MANY = frozenset({"db/tag"})


def fixed_one(p: str) -> bool:
    """Every ``db/`` predicate's cardinality is fixed at ``one`` (the clocks ``db/version`` and ``db/commit``
    among them) but ``db/tag``, fixed at ``many``; a bare predicate, ``version`` and ``commit`` included, is
    the user's (DAT 1052 Q3)."""
    return p.startswith("db/") and p not in FIXED_MANY


#: The predicates whose object is a stored UTC stamp, printed in the display zone (``Rev.show_time``).
TIME_PREDICATES = frozenset({"db/time", "db/sealed-at"})


class Row(NamedTuple):
    """A single row in the ledger: revision, subject, predicate, object, and ``added`` (false on a remove, A48)."""

    rev: "Rev"
    """The revision that wrote the row."""
    subject: str
    """The row's subject."""
    predicate: str
    """The row's predicate."""
    object: Any
    """The row's object, decoded from its tagged text ([Storage][storage])."""
    added: bool
    """``True`` for an add, ``False`` for a remove."""

    def __repr__(self) -> str:
        """``<Row subject predicate object rev=N +>``: the triple, the revision that wrote it, ``+`` added or ``-`` removed."""
        obj = self.object
        if isinstance(obj, Ref):
            text = obj._text()
        elif isinstance(obj, (dict, list)):
            text = canonical(obj)
        elif self.predicate in TIME_PREDICATES and isinstance(obj, str):
            text = self.rev.show_time(obj)
        else:
            text = str(obj)
        return f"<Row {self.subject} {self.predicate} {text} rev={self.rev.id} {'+' if self.added else '-'}>"

    __str__ = __repr__


def class_named(ledger: "Ledger", name: str) -> type:
    """The class a dotted name resolves to, following ``db/kind/<old> db/moved`` rows at the head (A19)."""
    head = ledger.at()
    seen = {name}
    while True:
        moved = head._held(f"db/kind/{name}", "db/moved")
        if not moved:
            break
        name = show(moved[-1].obj)
        if name in seen:
            raise ImportError(f"db/moved rows form a cycle at {name!r}")
        seen.add(name)
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
    raise ImportError(f"value class {name!r} does not import, and no db/kind/{name} db/moved row says "
                      "where it went")


def kind_names(ledger: "Ledger", kind: Any, rev: "Rev") -> List[str]:
    """``kind=``: a class or dotted name, plus every earlier name a ``db/moved`` chain leads from (A32)."""
    if isinstance(kind, type):
        kind = dotted(kind)
    if not isinstance(kind, str) or not kind:
        raise TypeError(f"kind is a Value class or its dotted name, not {kind!r}")
    names = [kind]
    frontier = [kind]
    while frontier:
        n = frontier.pop()
        for s in rev._store.subjects(rev.id, predicate="db/moved", obj="str:" + n, prefix="db/kind/"):
            old = s[len("db/kind/"):]
            if old not in names and any(h.obj == "str:" + n for h in rev._held(s, "db/moved")):
                names.append(old)
                frontier.append(old)
    return names


def name_of(rev: "Rev", subject: str) -> Optional[str]:
    """A value's one name at ``rev`` (Q36): the ``db/alias`` naming it written latest; ``None`` if none."""
    best = None
    for n in rev._aliases_of(subject):
        h = rev._held(n, "db/alias")[0]
        if best is None or (h.rev, h.ord) > best[0]:
            best = ((h.rev, h.ord), n)
    return best[1] if best else None


def display_name(ledger: "Ledger", subject: str) -> str:
    """A value's label: its name at the head, else ``#`` + the hash's first 8, like a short git sha
    (Q36, DAT 1036)."""
    name = name_of(ledger.at(), subject)
    if name is not None:
        return name
    return "#" + subject[:8] if is_hash(subject) else subject


class Rev:
    """A frozen view of the ledger as of revision ``id``."""

    def __init__(self, ledger: "Ledger", id: int, _rec: Optional[Dict[str, str]] = None) -> None:
        self.ledger = ledger
        """The ledger this view reads."""
        self.id = id
        """The revision number this view reads as of; revision 0 is the empty ledger."""
        self._rec = _rec
        self._cards: Dict[str, str] = {}

    # -- identity -------------------------------------------------------------

    @property
    def tx(self) -> str:
        """``db/tx/<id>``: the subject holding this revision's ``db/by``, ``db/time`` and transaction keywords."""
        return f"db/tx/{self.id}"

    def __repr__(self) -> str:
        return f"Rev({self.id})"

    # -- the display zone (SVP 1505 Q2) ----------------------------------------------------------------------

    @property
    def timezone(self) -> Any:
        """The zone this revision prints times in, as a ``ZoneInfo``, UTC when none is set.

        The ``(db, db/timezone, <IANA name>)`` row as of this revision names it (SVP 1505 Q2). Stamps are stored UTC
        and never move; the setting decides only how they print, so any revision may add, change or remove it
        (``t.add("db", "db/timezone", "America/Los_Angeles")``). The clock built-ins of ``rev.ns.expand`` are in it
        too ([Expansion][expansion-nsexpand]).
        """
        from zoneinfo import ZoneInfo

        held = self._held("db", TIMEZONE) if self.id else []
        return zone_named("db", show(held[0].obj)) if held else ZoneInfo("UTC")

    def show_time(self, stamp: str) -> str:
        """A stored UTC stamp as this revision prints it, in its ``timezone``: ISO 8601 with the zone's offset.

        Applies to ``db/time``, ``db/sealed-at`` and ``v.sealed``: ``2026-11-01T14:03:22-07:00``; with no
        ``db/timezone`` row the stamp is unchanged. A ``Row`` of ``db/time`` or ``db/sealed-at`` prints this way in
        its own revision's zone, and ``just history`` in the head's.
        """
        return shown_in(stamp, self.timezone)

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
        return self if self._rec is None else Rev(self.ledger, self.id)

    # -- the fold -------------------------------------------------------------

    @property
    def _store(self) -> Any:
        return self.ledger._store

    def _card(self, p: str) -> str:
        c = self._cards.get(p)
        if c is None:
            c = "many" if p in FIXED_MANY else "one"
            if not fixed_one(p) and p not in FIXED_MANY:
                held = fold(self._store.rows(self.id, subject=f"db/pred/{p}", predicate="db/cardinality"), "one")
                c = "many" if held and held[0].obj == "str:many" else "one"
            self._cards[p] = c
        return c

    def _type(self, p: str) -> Optional[str]:
        held = self._held(f"db/pred/{p}", "db/type")
        return show(held[0].obj) if held else None

    @staticmethod
    def _after(since: Optional["Rev"]) -> int:
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

    def _decode(self, text: str) -> Any:
        t, _, rest = text.partition(":")
        if t == "str":
            return rest
        if t == "json":
            return json.loads(rest)
        if t == "ref":
            return Ref._from_text(self._plain(), text)
        raise ValueError(f"row object {text[:60]!r}: unknown tag")

    def _check_type(self, p: str, text: str) -> None:
        decl = self._type(p)
        if decl is not None and not type_ok(self.ledger, decl, text):
            raise TypeError(f"{p!r} is declared db/type {decl!r} at rev {self.id}; the stored object is "
                            f"{tag(text)}:{show(text)[:40]!r} (the loose reads, all and rev[s], return it)")

    def _subdat_children(self, subject: str) -> List[Tuple[str, str]]:
        """``(relpath, child subject)`` of each sealed subdat of ``subject`` (its ``db/subdat/`` rows)."""
        out = []
        for _s, p, h in self._held_rows(subject=subject):
            if p.startswith("db/subdat/") and tag(h.obj) == "ref":
                child = parse_ref(h.obj)[2]
                if child:
                    out.append((p[len("db/subdat/"):], child))
        return out

    def _alias_tree(self, subject: str, name: Optional[str]) -> List[Tuple[str, Optional[str]]]:
        """``(value, its new name)`` for the aliases under ``subject``'s name when that name becomes ``name``
        (``None``: unnamed): every alias with prefix ``<old>/``, each keeping its tail. With no old name, its
        subdats by their rows, named ``<name>/<relpath>`` for the first time."""
        old = name_of(self, subject)
        if old == name:
            return []
        if old is not None:
            return [(show(h.obj), None if name is None else name + s[len(old):])
                    for s, _p, h in self._held_rows(predicate="db/alias", prefix=old + "/")]

        def named(s: str, at: str) -> List[Tuple[str, Optional[str]]]:
            return [x for rel, child in self._subdat_children(s)
                    for x in [(child, f"{at}/{rel}"), *named(child, f"{at}/{rel}")]]
        return named(subject, name) if name is not None else []

    def _aliases_of(self, subject: str) -> List[str]:
        out = []
        for s in self._store.subjects(self.id, predicate="db/alias", obj="str:" + subject):
            if any(h.obj == "str:" + subject for h in self._held(s, "db/alias")):
                out.append(s)
        return out

    def _record_row(self, item: str, text: Optional[str]) -> None:
        if self._rec is not None:
            self._rec[item] = NONE_TOKEN if text is None else strip_hint(text) if text.startswith("ref:") \
                else show(text)

    def _record(self, item: str, value: str) -> None:
        if self._rec is not None:
            self._rec[item] = value

    def _record_run(self, item: str, value: str) -> None:
        """A run reached through this ``Rev``: its ``eval:`` item, or on a ``Rev`` that records nothing the
        current run's ``foreign:`` item (``trace.note_read``); a lookup that found nothing read nothing."""
        if self._rec is not None:
            self._rec[item] = value
        elif value != NONE_TOKEN:
            from .trace import note_read

            note_read(self, item, value)

    def _record_call(self, call: str, args: Sequence[Any], since: Optional["Rev"], result: Any) -> None:
        if self._rec is not None:
            from .trace import call_item, token

            self._rec[call_item(call, args, since)] = token(result)

    # -- row reads ------------------------------------------------------------

    @staticmethod
    def _glob(s: Any) -> Tuple[Optional[str], Optional[str]]:
        """``(exact, prefix)`` of a subject position."""
        if not isinstance(s, str) or not s:
            raise TypeError(f"a subject is a non-empty str, not {s!r}")
        if "*" in s[:-1]:
            raise ValueError(f"{s!r}: a glob is a prefix, 'run/0-2-2/*'; a wildcard anywhere else is refused")
        if s.endswith("*"):
            return None, s[:-1]
        return s, None

    @staticmethod
    def _objtext(o: Any) -> str:
        """The stored text a pattern's object position compares by (a ref without its hint)."""
        if isinstance(o, Ref):
            return o._text()
        if isinstance(o, Value):
            if o.subject is None:
                raise ValueError("an unsaved Value is in no row")
            return ref_text(dotted(type(o)), o.hash)
        plain = encode_plain(o)
        if plain is None:
            raise TypeError(f"a row object is a str, JSON document or Ref, not {type(o).__name__}")
        return plain

    def _pattern(self, pattern: Sequence[Any], after: int) -> List[Any]:
        n = len(pattern)
        if n > 3:
            raise TypeError(f"a pattern fixes at most 3 positions, not {n}")
        if n == 0:
            return [(s, p, self._decode(h.obj)) for s, p, h in self._held_rows(after)]
        exact, prefix = self._glob(pattern[0])
        if n >= 2 and (not isinstance(pattern[1], str) or not pattern[1]):
            raise TypeError(f"a predicate is a non-empty str, not {pattern[1]!r}")
        if n == 1:
            rows = self._held_rows(after, subject=exact, prefix=prefix)
            if exact is not None:
                return [(p, self._decode(h.obj)) for s, p, h in rows]
            return [(s, p, self._decode(h.obj)) for s, p, h in rows]
        p = pattern[1]
        if n == 2:
            if exact is not None:
                return [self._decode(h.obj) for h in self._held(exact, p, after)]
            return [(s, self._decode(h.obj)) for s, _p, h in self._held_rows(after, predicate=p, prefix=prefix)]
        want = strip_hint(self._objtext(pattern[2]))
        if exact is not None:
            return [self.ledger.at(h.rev) for h in self._held(exact, p, after) if strip_hint(h.obj) == want]
        return [(s, self.ledger.at(h.rev)) for s, _p, h in self._held_rows(after, predicate=p, prefix=prefix)
                if strip_hint(h.obj) == want]

    def _record_of(self, s: str, after: int = 0) -> Dict[str, Any]:
        rec: Dict[str, Any] = {}
        first: Dict[str, Tuple[int, int]] = {}
        for _s, p, h in self._held_rows(after, subject=s):
            if p not in first:
                first[p] = (h.rev, h.ord)
            if self._card(p) == "many":
                rec.setdefault(p, []).append(self._decode(h.obj))
            else:
                rec[p] = self._decode(h.obj)
        return {p: rec[p] for p in sorted(rec, key=lambda q: first[q])}

    def _one(self, key: Tuple[Any, ...], after: int, strict_none: bool) -> Tuple[bool, Any]:
        """``(found, value)`` of a 1-, 2- or 3-position bracket read."""
        n = len(key)
        if not 1 <= n <= 3:
            raise TypeError(f"a bracket read fixes 1 to 3 positions, not {n}")
        s = key[0]
        if not isinstance(s, str) or not s:
            raise TypeError(f"a subject is a non-empty str, not {s!r}")
        if "*" in s:
            raise TypeError(f"{s!r}: bracket reads take exact subjects; globs live on all and refs")
        if n == 1:
            rec = self._record_of(s, after)
            return (bool(rec), rec)
        p = key[1]
        if not isinstance(p, str) or not p:
            raise TypeError(f"a predicate is a non-empty str, not {p!r}")
        if n == 2:
            if self._card(p) == "many":
                raise TypeError(f"{p!r} has cardinality many at rev {self.id}: one object is not its answer; "
                                f"use all({s!r}, {p!r})")
            held = self._held(s, p, after)
            if not held:
                return (False, None)
            self._check_type(p, held[0].obj)
            return (True, self._decode(held[0].obj))
        found = self._pattern(key, after)
        return (bool(found), found[0] if found else None)

    def __getitem__(self, key: Any) -> Any:
        """One match of a pattern: ``rev[s]`` the record, ``rev[s, p]`` one object, ``rev[s, p, o]`` a ``Rev``.

        ``rev[s]`` is the subject's record: a dict of predicate to object (a list for a ``many`` predicate); no rows
        is ``KeyError``. ``rev[s, p]`` is the one held object; nothing held is ``KeyError``, a ``many`` predicate
        ``TypeError`` naming ``all``, an object whose tag mismatches the predicate's ``db/type`` ``TypeError``.
        ``rev[s, p, o]`` is the revision of the held triple's earliest add not since removed; not held is
        ``KeyError``.
        """
        k = (key,) if isinstance(key, str) else key
        if not isinstance(k, tuple):
            raise TypeError(f"a bracket read is a str or a 2- or 3-tuple, not {key!r}")
        found, value = self._one(k, 0, True)
        if len(k) == 2:
            held = self._held(k[0], k[1]) if found else []
            self._record_row(f"{k[0]} {k[1]}", held[0].obj if held else None)
        else:
            self._record_call("getitem", k, None, value if found else None)
        if not found:
            what = "no rows" if len(k) == 1 else "nothing held" if len(k) == 2 else "not held (rows gives when)"
            raise KeyError(f"{k!r} at rev {self.id}: {what}")
        return value

    def get(self, *pattern: Any, default: Any = None, since: Optional["Rev"] = None) -> Any:
        """The ``[]`` read with ``default`` instead of ``KeyError`` on none.

        ``since`` keeps rows in ``(since, id]``: what one transaction wrote, or what moved between two releases.
        """
        after = self._after(since)
        found, value = self._one(tuple(pattern), after, False)
        if len(pattern) == 2 and since is None:
            held = self._held(pattern[0], pattern[1]) if found else []
            self._record_row(f"{pattern[0]} {pattern[1]}", held[0].obj if held else None)
        else:
            self._record_call("get", pattern, since, value if found else None)
        return value if found else default

    def all(self, *pattern: Any, since: Optional["Rev"] = None) -> list:
        """Every currently held match of the pattern (the fold), binding the open positions, in revision order.

        A prefix glob ``"game/*"`` binds the subject. Not checked against ``db/type`` (loose). More than three
        positions is ``TypeError``; a ``*`` anywhere but the end is ``ValueError``.
        """
        out = self._pattern(pattern, self._after(since))
        self._record_call("all", pattern, since, out)
        return out

    def __contains__(self, triple: Any) -> bool:
        """``(s, p, o) in rev``: whether the triple is held at this revision, by the same fold."""
        if not (isinstance(triple, tuple) and len(triple) == 3):
            raise TypeError("`in` takes a (subject, predicate, object) triple")
        s, p, o = triple
        want = strip_hint(self._objtext(o))
        out = any(strip_hint(h.obj) == want for h in self._held(s, p))
        self._record_call("in", triple, None, out)
        return out

    def history(self, *pattern: Any, since: Optional["Rev"] = None) -> List[Row]:
        """The history of a pattern, unfolded: every row that holds at or before this revision.

        Rows are in ``(rev, ord)`` order (A48); removes are included, and when ``since`` is given, only rows in
        ``(since, id]`` show. ``all`` is the same pattern folded.

        No pattern is the ledger as stored; ``history(s, p, o)`` with ``added`` true says when a triple was set. The
        trace records it under its call name ``rows``.
        """
        found = self._rows_of(pattern, since)
        revs: Dict[int, Rev] = {}
        out = []
        for r in found:
            rv = revs.get(r[0])
            if rv is None:
                rv = revs[r[0]] = Rev(self.ledger, r[0])
            out.append(Row(rv, r[2], r[3], rv._decode(r[4]), r[5]))
        self._record_call("rows", pattern, since, len(out))
        return out

    def last_rev(self, *pattern: Any, default: Any = None, since: Optional["Rev"] = None) -> Any:
        """The ``Rev`` of the last row matching the pattern at or before this revision, removes included, or ``default``
        with none: what ``history(*pattern)[-1].rev`` gives, without decoding a row; the pattern and ``since`` as
        ``history`` takes them (SVP 1521 A2).

        ``L.at(412).last_rev("game/G1").id`` is the revision that last touched those rows, 137, so ``G1@137`` names what
        ``G1`` was at 412. A read through a body's recording ``Rev`` is traced as the revision found, so a memo entry
        that asked holds only while the answer does; on another ledger it is a raw read, untracked.
        """
        found = self._rows_of(pattern, since)
        self._record_call("last_rev", pattern, since, found[-1][0] if found else None)
        return Rev(self.ledger, found[-1][0]) if found else default

    def _rows_of(self, pattern: Sequence[Any], since: Optional["Rev"]) -> List[Any]:
        """The stored rows of a pattern, unfolded (``history``, ``last_rev``)."""
        n = len(pattern)
        if n > 3:
            raise TypeError(f"a pattern fixes at most 3 positions, not {n}")
        exact = prefix = predicate = None
        if n >= 1:
            exact, prefix = self._glob(pattern[0])
        if n >= 2:
            if not isinstance(pattern[1], str) or not pattern[1]:
                raise TypeError(f"a predicate is a non-empty str, not {pattern[1]!r}")
            predicate = pattern[1]
        found = self._store.rows(self.id, subject=exact, predicate=predicate, prefix=prefix,
                                 after=self._after(since))
        if n == 3:
            want = strip_hint(self._objtext(pattern[2]))
            found = [r for r in found if strip_hint(r[4]) == want]
        return found

    # -- subject reads --------------------------------------------------------

    def _queryable(self, p: str) -> None:
        if "." not in p or p.startswith("db/"):
            return
        if self._store.subjects(self.id, subject=f"db/pred/{p}"):
            return
        if self._store.has_predicate(p, self.id):
            return
        raise Unindexed(f"{p!r}: no db/pred/{p} declaration and no row carries it at rev {self.id} (a typo?)")

    @staticmethod
    def _wanted(v: Any) -> Optional[str]:
        """The stored text a where entry matches (``None``: any object)."""
        if v is None:
            return None
        if getattr(v, "_is_ref", False):
            return str(v)
        if isinstance(v, bool) or isinstance(v, (int, float)):
            return "str:" + str(v)
        return strip_hint(Rev._objtext(v))

    def _constraints(self, kind: Any, fn: Any, where: Optional[Dict[str, Any]],
                     preds: Dict[str, Any]) -> List[Tuple[str, Optional[List[str]]]]:
        cons: List[Tuple[str, Optional[List[str]]]] = []
        items = list(preds.items())
        if where is not None:
            if not isinstance(where, dict):
                raise TypeError("where is a dict of predicate -> object (None: any object)")
            items += list(where.items())
        for p, v in items:
            if not isinstance(p, str) or not p:
                raise TypeError(f"a where key is a non-empty str, not {p!r}")
            self._queryable(p)
            w = self._wanted(v)
            cons.append((p, None if w is None else [w]))
        if kind is not None:
            cons.append(("db/kind", ["str:" + n for n in kind_names(self.ledger, kind, self)]))
        if fn is not None:
            if not isinstance(fn, str) or not fn:
                raise TypeError(f"fn is a dotted function name, not {fn!r}")
            cons.append(("db/fn", ["str:" + fn]))
        return cons

    def _subjects(self, s: Any, kind: Any, fn: Any, where: Optional[Dict[str, Any]], since: Optional["Rev"],
                  preds: Dict[str, Any]) -> List[str]:
        after = self._after(since)
        exact = prefix = None
        if s is not None:
            exact, prefix = self._glob(s)
        cons = self._constraints(kind, fn, where, preds)
        if cons:
            p, objs = cons[0]
            cands: List[str] = []
            for o in (objs or [None]):
                for c in self._store.subjects(self.id, predicate=p, obj=o, subject=exact, prefix=prefix,
                                              after=after):
                    if c not in cands:
                        cands.append(c)
        else:
            cands = self._store.subjects(self.id, subject=exact, prefix=prefix, after=after)
        out = []
        for c in cands:
            ok = True
            for p, objs in cons:
                held = [strip_hint(h.obj) for h in self._held(c, p, after)]
                if not held or (objs is not None and not any(o in held for o in objs)):
                    ok = False
                    break
            if ok and (cons or self._held_rows(after, subject=c)):
                out.append(c)
        return out

    def _query_record(self, s: Any, kind: Any, fn: Any, where: Optional[Dict[str, Any]], one: bool,
                      since: Optional["Rev"], preds: Dict[str, Any], subjects: List[str]) -> None:
        if self._rec is None:
            return
        from .trace import query_item

        name = query_item(self.ledger, s, kind, fn, where, one, since, preds, self)
        self._rec[name] = canonical(sorted(self._plain()._ref_text_of(x) for x in subjects))

    def _spec_only_at(self, subject: str) -> bool:
        held = self._held(subject, "db/value")
        return bool(held and self._held(subject, "db/spec-only")
                    and not self._store.art.exists(parse_ref(held[0].obj)[1]))

    def _ref_text_of(self, subject: str) -> str:
        held = self._held(subject, "db/value")
        return strip_hint(held[0].obj) if held else subject

    def refs(self, *, s: Any = None, kind: Any = None, fn: Any = None, where: Optional[Dict[str, Any]] = None,
             one: bool = False, since: Optional["Rev"] = None, **preds: Any) -> Any:
        """Returns a ``Ref`` to every subject matching the query, sealed value or not.

        ``refs``, ``values`` and ``value`` take the same query and pick the same subjects: a bare keyword names a pred
        (any member of a ``many`` pred); ``kind=`` a ``Value`` class or dotted name, following ``db/moved`` renames;
        ``fn=`` the producing function's dotted name; ``where={p: o}`` any predicate, ``None`` meaning any object;
        ``s`` an exact subject or a prefix glob; ``since`` keeps rows in ``(since, id]``.

        ``one=True`` returns the single match: none is ``KeyError``, several ``Multiple``. A dotted predicate neither
        declared nor on any row is ``Unindexed``.
        """
        plain = self._plain()
        subs = plain._subjects(s, kind, fn, where, since, preds)
        self._query_record(s, kind, fn, where, one, since, preds, subs)
        if one:
            if not subs:
                raise KeyError(f"no subject matches at rev {self.id}")
            if len(subs) > 1:
                raise Multiple(f"{describe(s, kind, fn, where, preds)} matches {len(subs)}: "
                               + ", ".join(display_name(self.ledger, x) for x in subs[:6]))
            return Ref(self, subs[0])
        return [Ref(self, x) for x in subs]

    def values(self, *, s: Any = None, kind: Any = None, fn: Any = None, where: Optional[Dict[str, Any]] = None,
               since: Optional["Rev"] = None, **preds: Any) -> List[Value]:
        """The values of ``refs``'s matching subjects, loaded, keeping only subjects that hold a sealed value."""
        plain = self._plain()
        subs = [x for x in plain._subjects(s, kind, fn, where, since, preds) if plain._held(x, "db/value")]
        self._query_record(s, kind, fn, where, False, since, preds, subs)
        out = [Ref(plain, x)._load() for x in subs]
        for v in out:
            self._record_value(v)
        return out

    def value(self, *, s: Any = None, kind: Any = None, fn: Any = None, where: Optional[Dict[str, Any]] = None,
              since: Optional["Rev"] = None, **preds: Any) -> Value:
        """Same as ``values``, but exactly one match: none is ``KeyError``, several ``Multiple``.

        The query is the same as ``refs``'s.
        """
        plain = self._plain()
        subs = [x for x in plain._subjects(s, kind, fn, where, since, preds) if plain._held(x, "db/value")]
        self._query_record(s, kind, fn, where, False, since, preds, subs)
        if not subs:
            raise KeyError(f"no sealed value matches at rev {self.id}")
        if len(subs) > 1:
            raise Multiple(f"{describe(s, kind, fn, where, preds)} matches {len(subs)}: "
                           + ", ".join(display_name(self.ledger, x) for x in subs[:6]))
        v = Ref(plain, subs[0])._load()
        self._record_value(v)
        return v

    def select(self, keys: Tuple[str, ...], *, s: Any = None, kind: Any = None, fn: Any = None,
               where: Optional[Dict[str, Any]] = None, one: bool = False, since: Optional["Rev"] = None,
               **preds: Any) -> Any:
        """Returns the chosen preds of every matching subject, without loading the value (the same query as ``refs``).

        Each match is a tuple of its objects for ``keys``, ``None`` where absent, a list for a ``many`` predicate.
        ``rev.select(("home", "away"), s="game/*")`` reads two preds of every game from the ledger alone, where
        ``values`` would fetch each value's bytes.

        ``keys`` not a non-empty tuple is ``TypeError``; ``one=True`` as in ``refs``.
        """
        if isinstance(keys, str) or not isinstance(keys, tuple) or not keys:
            raise TypeError(f"select takes a non-empty tuple of predicate names first, not {keys!r}")
        plain = self._plain()
        for k in keys:
            plain._queryable(k)
        subs = plain._subjects(s, kind, fn, where, since, preds)
        self._query_record(s, kind, fn, where, one, since, preds, subs)

        def row(x: str) -> tuple:
            out = []
            for k in keys:
                held = plain._held(x, k)
                if plain._card(k) == "many":
                    out.append([plain._decode(h.obj) for h in held])
                else:
                    out.append(plain._decode(held[0].obj) if held else None)
            return tuple(out)
        if one:
            if len(subs) != 1:
                raise (KeyError if not subs else Multiple)(f"{len(subs)} subjects match at rev {self.id}")
            return row(subs[0])
        return [row(x) for x in subs]

    def _record_value(self, v: Value, name: Optional[str] = None) -> None:
        text = ref_text(dotted(type(v)), v.hash)
        if self._rec is None:
            from .trace import note_read

            note_read(self, name or str(v.subject), text)
            return
        self._rec[text] = text
        if name is not None and name != v.subject:
            self._rec[f"{name} db/alias"] = text

    def load(self, subject: str) -> Value:
        """``Ref(rev, subject).load()``: the value under a subject or an alias, decoded, its provenance restored.

        An alias resolves; reading through one records the binding (A35).
        """
        return Ref(self, subject).load()

    @property
    def ns(self) -> "LedgerNamespace":
        """The ledger's namespace at this revision (DAT 1046, DAT 1051).

        It is the ``Namespace`` interface of [DAT Namespace
        API](https://github.com/oblinger/dvc-dat/blob/main/doc/DAT%20Design/DAT%20API/DAT%20Namespace%20API.md):
        ``rev.ns.load(name)`` is what the dotted ``name`` denotes here, ``rev.ns.mounts()`` the ``db/mount`` rows as
        ``{prefix: {"root": ..., "repo": ...}}``, ``rev.ns.expand(template, **vars)`` a template filled through these
        names in this revision's [display zone][dvc_dat.ledger.Rev.timezone] with ``{unique}`` counted against this
        revision ([Expansion][expansion-nsexpand]), and ``mount`` is ``TypeError`` (a transaction's
        [``t.ns``][dvc_dat.ledger.Transaction.ns] mounts).

        A mounted name is ``mnt.<prefix>...``: the ``db/mount/<prefix>`` rows as of the revision are walked longest
        prefix first for the name after ``mnt.``; under a mount the name is a path in the mount's tree, in the
        checkout discovery reports for its ``db/repo`` (none is ``NotEvaluated``): a ``.yaml``/``.yml``/``.json`` file
        is read and comes back a dict (a dotted tail below the file walks into it), a function in a ``.py`` file comes
        back its [``Fn``][fn-interface], read off the file and never imported in this process, and a module-level
        literal (``TABLE = {...}``) its value. A mounted prefix owns its names: one nothing answers to is
        ``ImportError``, a file and a module answering to one name ``KeyError``.

        A name not starting ``mnt.`` is never a mount and is imported (unsandboxed); ``mnt`` alone, or a ``mnt.`` name
        under no mount, is ``ImportError``. Imported, a ``@dat.fn`` comes back its ``Fn`` and anything else as itself.
        An ``Fn``'s ``kind`` is read off the function: ``"ledger"`` for a ``@dat.fn``, ``"dat"`` for an undecorated
        one, a dat's ``run`` function, which runs only through a spec ([``run``][dvc_dat.ledger.Rev.run]).

        In a project whose ``.datconfig.yaml`` names a ledger, ``Dat.manager.ns`` is this namespace at the head,
        ``mount`` refused; inside a sandboxed dat body it is this namespace at the run's revision (DAT 1047). See
        [Execution Semantics][execution-semantics].
        """
        from .namespace import LedgerNamespace

        return LedgerNamespace(rev=self, unguarded=True)

    def run(self, target: Any, /, *, seal: Any = OWN, clean: bool = False, path: Any = None,
            **kwargs: Any) -> Optional[Value]:
        """The result of ``target``, already sealed if one from the same code and memo key still holds.

        This is the API form of ``just run TARGET KEY=VALUE`` (DAT 1046); a miss runs the target and seals the result
        as the memo entry.

        ``target`` is a dotted name, resolved as by [``ns.load``][dvc_dat.ledger.Rev.ns], or a spec dict. A ledger
        function's name: its ``Fn`` runs with ``kwargs`` as its keys, which are its memo key. Anything else is a dat:
        a spec, a spec's name, or a dat's run function's name (the spec ``{dat: {do: <name>}}``), ``kwargs`` updating
        the spec's ``dat.kwargs``.

        A dat's memo key, ``db/keys``, is the spec with its ``dat.base`` merged, the kwargs merged, ``dat.kind`` set
        and every ``{}`` expanded once (dotted names through the ledger's namespace; undotted ones the expansion
        variables, ``dat.defaults`` overridden by ``dat.kwargs``, SVP 1508), ``dat.preds`` kept as its template
        (expanded when the dat is made and sealed as its preds), ``dat.name`` removed; ``db/fn`` is the run function's
        dotted name and ``db/returns`` the dat's class.

        A miss creates the dat in a work folder and runs it there (the machinery of ``Dat.manager.run``), then seals
        the folder the run function saved; a run that leaves its dat open is ``ValueError``. Where a miss runs is the
        function's: under a ``db/mount``, in the sandbox worker, imported there from the mounted tree and never in the
        calling process, confined, its code the modules it loaded, provenance ``eval:sandbox``, no ``code/<repo>``
        item (a dat's run function gets the caller's dat folders and art folder, its ``Dat.manager.ns`` a
        ``LedgerNamespace`` at this revision); installed, in this process, its code the static closure and the
        ``code/<repo>`` commit, which needs a clean checkout (``NotEvaluated``), provenance ``eval:unsandboxed``.

        ``seal``, ``clean`` and ``path`` behave as on [``Fn.__call__``][dvc_dat.ledger.Fn.__call__]; ``seal`` says
        where the result goes: by default, the hit, else run and save it as the memo entry; ``seal=False`` runs and
        keeps nothing; ``seal=True`` runs and seals locally; ``seal=t`` saves into an open transaction; ``seal="get"``
        returns the saved result or ``None`` and never runs ([Running][running]).

        ``clean=True`` requires the function's checkout to be clean (no uncommitted changes, and the HEAD at the
        commit of the latest clean run this revision records, its ``db/repo/<repo>`` row), else it raises
        ``NotClean``; by default a sandboxed function runs at HEAD, clean or dirty. A function claiming ``exact``
        (``@dat.fn(reproducible="exact")``) has its lookup match the card and driver too, on top of the ledger's memo
        policy ([Memoization and the platform][memoization-and-the-platform]).

        ``path`` names the result; a dat's name is ``path=``, else its spec's ``dat.name`` template (``{unique}``
        counting up in the data folder), else ``anonymous/Dat{unique}``, and a hit is handed back at its name, its
        folder a view there.

        A spec naming a ``@dat.fn`` in ``dat.do`` is ``TypeError``; a target that is neither a ``str`` nor a dict is
        ``TypeError``. The dat's recorded dependencies that are names on the ledger enter its trace as alias reads.
        See [Execution Semantics][execution-semantics] and [Value Provenance][value-provenance].
        """
        from .sandbox import unguarded

        with unguarded():                          # in a sandboxed body: the lookup and seal are the ledger's
            from .rundat import run

            return run(self, target, seal=seal, clean=clean, path=path, kwargs=kwargs)

    def rerun(self, value: Any) -> "Rerun":
        """Run the pinned function behind ``value`` again, at its tag, over its recorded keys, and compare the hash.

        This is a ``Rerun`` ([Rerunnability][rerunnability]) whose ``outcome`` is ``reproduced``,
        ``differed-as-allowed``, ``differed-nondeterministic`` or ``differed-deterministic``, read off the value's
        claim (SVP 250, SVP 251 Q2); it also carries ``hash``, ``expected``, ``reproducible`` (the level the value's
        claim gave it, [Reproducibility][reproducibility]), ``commit``, ``tag`` and ``worktree``.

        ``value`` is a sealed ``Value``, a ``Ref`` or a name. Its commit must be pinned on this ledger (``t.pin``),
        else ``NotPinned``; every input must still resolve here. A copied value runs at its origin
        (``db/copied-from``) while that ledger can be found, else here.

        The run is a fresh interpreter over a worktree at the tag under ``<ledger>/rerun/<commit12>/<repo>`` (a
        worktree of the checkout here when it holds the commit, else ``git clone --depth 1 --branch dat/<commit12>``
        from its remote; reused across reruns), synced from its ``uv.lock`` when it has one; a sandboxed function runs
        in that interpreter's worker. Nothing is written. See ``dvc_dat.ledger.pin``.
        """
        from .pin import rerun

        return rerun(self, value)


def default_by() -> str:
    """The ``db/by`` of a one-shot write through the head (``L.at().pin(v)``): ``human:<user>``."""
    import os

    return f"human:{os.environ.get('USER', 'user')}"


def _one_shot(name: str) -> Any:
    """``Head.<name>``: the ``Transaction`` method of that name, in a transaction of its own (SVP 250 A13): declared
    once, on ``Transaction``; here opened (``by=``, default ``default_by()``), called and committed."""
    import functools

    from .txn import Transaction

    method = getattr(Transaction, name)

    @functools.wraps(method)
    def call(self: "Head", *args: Any, by: Any = None, **kwargs: Any) -> Any:
        with self.ledger.transaction(by=by if by is not None else default_by()) as t:
            return method(t, *args, **kwargs)
    call.__doc__ = (f"``L.at().{name}(...)``: ``Transaction.{name}`` in a transaction of its own, committed on "
                    f"return (``by=`` names the writer, ``human:<user>`` by default).\n\n" + (method.__doc__ or ""))
    return call


class Head(Rev):
    """The top of the ledger, ``L.at()`` with no argument (SVP 250 A13): a ``Rev`` that is also a transaction.
    Every read is the ``Rev``'s; each transaction method listed in ``ONE_SHOT`` is here the one-shot form,
    opening a transaction, calling the method on it and committing: ``L.at().pin(value)``, ``L.at().copy(value)``."""

    ONE_SHOT = ("pin", "copy")

    def __repr__(self) -> str:
        return f"Head({self.id})"


for _name in Head.ONE_SHOT:
    setattr(Head, _name, _one_shot(_name))


def describe(s: Any, kind: Any, fn: Any, where: Optional[Dict[str, Any]], preds: Dict[str, Any]) -> str:
    """A where clause as ``k=v`` words, for a refusal's message."""
    parts = [f"{k}={v!r}" if not isinstance(v, str) else f"{k}={v}"
             for k, v in list(preds.items()) + list((where or {}).items())]
    if kind is not None:
        parts.insert(0, f"kind={dotted(kind) if isinstance(kind, type) else kind}")
    if fn is not None:
        parts.insert(0, f"fn={fn}")
    if s is not None:
        parts.insert(0, f"s={s}")
    return " ".join(parts) or "every subject"


def type_ok(ledger: "Ledger", decl: str, text: str) -> bool:
    """Does a stored object's tag satisfy a ``db/type`` declaration (``str``, ``json``, or a class)."""
    t = tag(text)
    if decl in ("str", "json"):
        return t == decl
    if t != "ref":
        return False
    cls, _h, _s = parse_ref(text)
    if cls == decl:
        return True
    try:
        return issubclass(class_named(ledger, cls), class_named(ledger, decl))
    except ImportError:
        return False


class Ref:
    """A reference to one value at one moment: ``Ref(rev, name)``, the alias chain resolved when made (Q30).

    Made from the recording ``Rev`` a value function's body holds, it keeps the recorder: resolving an
    alias records ``<name> db/alias``, ``load`` the ``ref:`` item, and ``preds``, ``aliases``,
    ``sealed_at`` and ``ref.rev[...]`` record like any other read (Eval § 5.3).
    """

    __slots__ = ("rev", "_given", "_subject", "_cls", "_hash", "_lazy", "_p")

    rev: "Rev"
    """The revision this reference reads through.

    The snapshot it was made from, so every answer it gives is as of that revision.
    """

    def __init__(self, rev: Rev, name: str) -> None:
        """A reference to whatever ``name`` (a subject or an alias) names at ``rev``.

        ``rev`` not a ``Rev`` or ``name`` not a non-empty ``str`` is ``TypeError``.
        """
        if not isinstance(rev, Rev):
            raise TypeError(f"Ref(rev, name): rev is a Rev, not {type(rev).__name__}")
        if not isinstance(name, str) or not name:
            raise TypeError(f"Ref(rev, name): name is a non-empty str, not {name!r}")
        plain = rev._plain()
        subject = name
        for _hop in range(ALIAS_HOPS + 1):
            held = plain._held(subject, "db/alias")
            if not held:
                break
            subject = show(held[0].obj)
        else:
            raise AliasLoop(f"{name!r}: the db/alias chain runs past {ALIAS_HOPS} hops (or loops) at rev {rev.id}")
        cls = h = None
        held = plain._held(subject, "db/value")
        if held:
            cls, h, _s = parse_ref(held[0].obj)
        self._init(rev, name, subject, cls, h, False)
        if subject != name:
            rev._record(f"{name} db/alias", ref_text(cls, h) if h else NONE_TOKEN)

    def _init(self, rev: Rev, name: str, subject: Optional[str], cls: Optional[str], h: Optional[str],
              lazy: bool) -> None:
        object.__setattr__(self, "rev", rev)
        object.__setattr__(self, "_p", rev._plain())
        object.__setattr__(self, "_given", name)
        object.__setattr__(self, "_subject", subject)
        object.__setattr__(self, "_cls", cls)
        object.__setattr__(self, "_hash", h)
        object.__setattr__(self, "_lazy", lazy)

    @classmethod
    def _from_text(cls, rev: Rev, text: str) -> "Ref":
        """A stored ``ref:``: its hint names the subject; hint-less, the subject resolves lazily (A28, A36)."""
        c, h, subj = parse_ref(text)
        r = cls.__new__(cls)
        r._init(rev, subj or "", subj, c, h, subj is None)
        return r

    @property
    def name(self) -> str:
        """The print name of this value: its alias at the head (the latest written), else ``#`` + the hash's first 8 hex.

        That ``#`` form is DAT 1036; this is also ``str(ref)``.

        Unique one way: a name points at one value at a time, and re-pointing it moves it to another value; a value
        may carry several names (``aliases``). ``subject`` is what the reference resolved to.
        """
        return str(self)

    def __setattr__(self, k: str, v: Any) -> None:
        raise AttributeError("a Ref is frozen")

    @property
    def subject(self) -> Optional[str]:
        """The value's subject: ``name`` with its alias chain resolved.

        For a stored hint-less reference, the latest entry holding those bytes as of ``rev``.
        """
        if self._lazy:
            p = self._p
            text = ref_text(self._cls, self._hash)
            best = None
            for s in p._store.subjects(p.id, predicate="db/value", obj=text):
                held = p._held(s, "db/value")
                if held and strip_hint(held[0].obj) == text and (best is None or held[0].rev >= best[1]):
                    best = (s, held[0].rev)
            object.__setattr__(self, "_subject", best[0] if best else None)
            object.__setattr__(self, "_given", best[0] if best else "")
            object.__setattr__(self, "_lazy", False)
        return self._subject

    @property
    def hash(self) -> Optional[str]:
        """The 64-hex sha256 of the value's bytes; ``None`` when the subject holds no value.

        Byte identity of two refs is ``a.hash == b.hash``.
        """
        return self._hash

    @property
    def type(self) -> Optional[type]:
        """The ``Value`` subclass that decodes the bytes, following ``db/moved`` renames.

        ``None`` with no value; a class that does not import is ``ImportError``.
        """
        return None if self._cls is None else class_named(self._p.ledger, self._cls)

    def _text(self) -> str:
        return ref_text(self._cls, self._hash) if self._hash else f"ref:?:{self.subject}"

    def _preds(self) -> FrozenPreds:
        s = self.subject
        if s is None:
            return FrozenPreds()
        return FrozenPreds({p: o for p, o in self._p._record_of(s).items() if not p.startswith("db/")})

    @property
    def preds(self) -> FrozenPreds:
        """The subject's non-``db/`` rows at ``rev``, annotations included.

        One view (A24); unchecked. A typed pred is an unloaded ``Ref``.
        """
        out = self._preds()
        self.rev._record_call("preds", (self._given,), None, dict(out))
        return out

    @property
    def aliases(self) -> List[str]:
        """Every ``db/alias`` name pointing at the subject as of ``rev`` (A25)."""
        s = self.subject
        out = [] if s is None else self._p._aliases_of(s)
        self.rev._record_call("aliases", (self._given,), None, sorted(out))
        return out

    def _sealed_at(self) -> Optional[Rev]:
        s = self.subject
        held = self._p._held(s, "db/value") if s else []
        return self._p.ledger.at(held[0].rev) if held else None

    @property
    def sealed_at(self) -> Optional[Rev]:
        """The revision of the subject's ``db/value`` row.

        The value was sealed into the ledger at or before ``rev``, since a reference made later can point at a value
        sealed earlier; ``None`` while the subject holds no value (A41).
        """
        out = self._sealed_at()
        self.rev._record_call("sealed_at", (self._given,), None, out)
        return out

    def __eq__(self, other: object) -> bool:
        """Equal by subject: a subject hashes its dependencies and preds too; same bytes is ``a.hash == b.hash``."""
        return isinstance(other, Ref) and self.subject == other.subject and \
            (self.subject is not None or self._text() == other._text())

    def __hash__(self) -> int:
        return hash(self.subject if self.subject is not None else self._text())

    def __str__(self) -> str:
        """The bare label: the name at the head, else ``#`` + the hash's first 8 (DAT 1036)."""
        s = self.subject
        if s is None:
            return "#" + (self._hash or "")[:8]
        return display_name(self._p.ledger, s)

    def __repr__(self) -> str:
        """``<Ref video/G1>``, ``<Ref #2db69ce1>`` (DAT 1036)."""
        return f"<Ref {self}>"

    def __reduce__(self) -> Any:
        raise TypeError("a Ref is bound to an open ledger and does not pickle")

    def _fetch(self) -> Any:
        """The fetch from the store the value's ``db/store`` row names (SVP 1511), for a miss in the local
        folder; ``None`` with no row, or ``folder``: the folder alone, as before."""
        from .remote import FOLDER, PREDICATE, fetcher

        held = self._p._held(self.subject, PREDICATE) if self.subject is not None else []
        name = show(held[0].obj) if held else FOLDER
        return None if name == FOLDER else fetcher(name, self._p.ledger._store.name)

    def load(self) -> Value:
        """Fetch the bytes from the art store and decode them by ``type``.

        Restores ``subject``, ``rev`` (the sealing revision), ``dependencies`` and ``preds``.

        Cached per ``(subject, rev, name)`` on the ``Ledger``: the same ``Value`` every time while it is still there,
        except a cached ``Dat`` whose folder was moved or replaced since is loaded afresh.

        A ``decode`` that accepts ``name=`` is passed the alias the ``Ref`` was made by, so a ``Dat`` loaded by an
        alias lands under ``art/dats/<alias>/``.

        Inside a run the read is recorded: a recording ``Rev``'s items, any other ``Rev``'s ``foreign:`` item.

        No value is ``KeyError``; a ``decode`` returning a non-``Value`` is ``TypeError``; a ``Dat`` whose ``_spec_``
        names a ``dat.kind`` the row's class does not accept is ``TypeError``.
        """
        v = self._load()
        self.rev._record_value(v, self._given)
        return v

    def _spec_only(self) -> bool:
        """A copy that holds the value's spec and not its bytes (SVP 251): a later run may have brought them."""
        return self._p._spec_only_at(self.subject) if self.subject is not None else False

    def _stored_hashes(self) -> List[str]:
        """The hashes of the bytes the value's encoding names, read off the store, never decoded (``copy``)."""
        cls = self.type
        assert cls is not None and self._hash is not None
        store = self._p.ledger._store.art
        with store.fetching(self._fetch()):
            return list(cls._stored_hashes(store, self._hash))

    def _load(self) -> Value:
        """``load`` unrecorded: the ledger's own read of a value (a memo hit, a query's result)."""
        s = self.subject
        if self._hash is None or s is None:
            raise KeyError(f"{self._given!r} has no value at rev {self.rev.id}")
        if self._spec_only():
            from .errors import SpecOnly

            raise SpecOnly(f"{self._given!r}: this ledger holds its spec alone, no bytes; rev.rerun makes it again, "
                           f"from {show(self._p._held(s, 'db/copied-from')[0].obj)}")
        ledger = self._p.ledger
        key = (s, self.rev.id, self._given)
        v = ledger._values.get(key)
        if v is not None and not v._present():
            v = None
        if v is None:
            store = ledger._store.art
            cls = self.type
            assert cls is not None
            loaded_as = self._given if self._given != s else None
            with store.fetching(self._fetch()), store.open(self._hash) as src:
                v = cls.decode(src, store, name=loaded_as) if takes_name(cls) else cls.decode(src, store)
            if not isinstance(v, Value):
                raise TypeError(f"{cls.__name__}.decode returned {type(v).__name__}, not a Value")
            from . import hooks

            if hooks.is_dat(v):                         # the row wins; the folder is checked against it
                kind = type(v).spec_kind(v.path)
                if kind is not None and kind != self._cls and not type(v).kind_ok(kind):
                    raise TypeError(f"{s[:12]}…: the db/value row names {self._cls}; the folder's _spec_ names "
                                    f"dat.kind {kind}")
                st = v.path.stat()
                v.__dict__["_dir_id"] = (st.st_dev, st.st_ino)
            rows = self._p._held_rows(subject=s)
            trace = {p[len("db/deps/"):]: show(h.obj) for _s, p, h in rows if p.startswith("db/deps/")}
            sealed_at = self._sealed_at()
            assert sealed_at is not None
            v._provenance(subject=s, rev=sealed_at, dependencies=trace, preds=self._preds(), loaded_as=loaded_as)
            v.__dict__["_hash"] = self._hash
            ledger._values[key] = v
        return v
