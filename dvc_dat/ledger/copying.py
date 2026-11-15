"""``copy`` (SVP 251): a value, or a reference to one, moved onto another ledger with the same hash.

``t.copy(*values, deep=False, safe=True, rerunnable=False, skip=None)`` is on the destination's transaction, since every write
goes through the transaction on the ledger written; ``L.at().copy(v)`` is the head form (``Head``). A value is a
sealed ``Value`` or a ``Ref``: each knows its ledger, which a name does not.

A copy writes the value's bytes to the destination's store if absent (dedupe by hash, never decoded), its subject
rows, its provenance rows (the ``db/code/<hash 16>`` item, the declarations of its preds, its mount, the commit of its
run as ``(<value>, db/commit, <sha>)``, since one revision's clock cannot carry several commits), its one name, and
``(<value>, db/copied-from, <ledger>@<rev>)``. The per-ledger rows ``db/at``, ``db/rerunnable``, ``db/rerun``
and an earlier ``db/copied-from`` stay behind. The subject is the source's, so a second copy adds nothing.

A copy follows the value's subdats (SVP 241, 252): each ``db/subdat/<relpath>`` row's child is copied with it, and
the child's subdats in turn, all in this revision. ``skip`` declines some, by relative-path suffix from the copied
value (``Transaction.copy``): a declined child is not copied, and the parent's row for it here becomes the global
reference ``str:<ledger>@<rev>:<child subject>`` to the original (SVP 239's ``load`` grammar), which ``dat.load``
reads on that ledger. A ``str:declined`` row, or such a reference, travels as it is. The rows are outside the
parent's hash, so what happens to its subdats never moves it.

``deep``
    copies the value's inputs recursively until values with no inputs, whatever their ledgers. Without it they stay
    where they are, referenced by hash through the origin row and the ``foreign:`` items. It does not override
    ``skip``: a subdat is no input.
``safe``
    reads each ledger's lifetime on the root ledger (``lifetime_of``), so a ledger gone or offline is still judged:
    an input on a ledger below the destination's is copied, by the same
    rule; one at or above is referenced. A plain copy never looks. It keeps only the spec of a value that can be
    rerun instead (``_Plan.rederivable``): no bytes, ``(<value>, db/spec-only, true)``, its commit's ``db/pinned`` row
    beside it, and no memo hit there until a run brings the bytes. ``deep`` asks for every byte, so it overrides that.
    A source's ``db/rerunnable`` claim is asserted again here. ``NotCopied``, nothing written, when an input cannot be
    found. A plain copy of a rerunnable value promises nothing at the destination.
``rerunnable``
    asserts the claim here after the copy, as ``t.pin`` would (SVP 250 A9): the commit pinned, the function importable,
    every input found.
``skip``
    relative-path suffixes of the subdats to leave on their ledger, as ``seal(skip=)`` takes them (``declined_by``):
    ``None`` is ``SKIP``, ``("run",)``; ``()`` follows every subdat; any other adds to ``SKIP``.

Inputs are the run's value keys, every value its trace read, and its ``foreign:`` items (SVP 1521).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Tuple

from .claim import EXACT, claim_of, unconditional
from .codec import show
from .errors import LedgerError, NotCopied, NotPinned
from .fn import AT, ledger_key, mounts_at
from .named import rev_named
from .pin import (PINNED, RERUN, RERUNNABLE, assert_claim, check_input, foreign_inputs, holder_of, inputs_in, run_of,
                  value_inputs)
from .trace import rev_text
from .txn import SUBDAT, declined_by
from .value import Value

if TYPE_CHECKING:
    from .rev import Rev
    from .txn import Transaction

#: The row of root's registry that declares a ledger's lifetime (SVP 1516 A1, SVP 251 Q1, Q3 (B)):
#: ``(ledger/<name>, ledger/lifetime, <word>)`` on the root ledger, written once by whatever creates the ledger.
LIFETIME = "ledger/lifetime"
#: Lifetimes, lowest first: ``permanent`` always reachable, ``archival`` kept in principle and nothing may depend on
#: it, ``transient`` known to be trashed. A timeless assertion about the ledger, never its state today.
LIFETIMES = ("transient", "archival", "permanent")
COPIED_FROM = "db/copied-from"
SPEC_ONLY = "db/spec-only"
COMMIT = "db/commit"
#: The rows of a value that are about the ledger holding it, not about the value.
LEFT_BEHIND = frozenset({AT, RERUNNABLE, RERUN, COPIED_FROM, SPEC_ONLY, COMMIT})
#: The subdats a copy leaves on their ledger by default (SVP 252): a run is provenance, recomputable.
SKIP = ("run",)


def lifetime_of(ledger: Any) -> str:
    """The lifetime root's registry declares for ``ledger``: the row ``(ledger/<name>, ledger/lifetime, <word>)`` on
    the root ledger (``ledgers.root``), ``<name>`` the ledger's folder or database, read at root's head. Read there,
    not on the ledger, so a ledger that is gone or offline is still judged (SVP 251 Q3 (B)). ``NotCopied`` when root
    does not open, or declares none, more than one, or a word outside ``LIFETIMES``: ``safe`` compares what is
    declared, and guesses nothing."""
    from .ledger import ROOT
    from .named import ledgers

    name = ledger._store.name
    try:
        root = ledgers[ROOT]
    except (LedgerError, KeyError) as e:
        raise NotCopied(f"safe reads ledger {name}'s lifetime on the root ledger, which does not open: {e}") from None
    words = root.at().all(f"ledger/{name}", LIFETIME)
    if len(words) > 1:
        raise NotCopied(f"root ({root._store.name}) declares more than one lifetime for ledger {name} "
                        f"({', '.join(repr(w) for w in words)}): a lifetime is written once and never changes")
    word = words[0] if words else None
    if word not in LIFETIMES:
        raise NotCopied(f"ledger {name} declares {'no lifetime' if word is None else repr(word)}: safe reads the row "
                        f"(ledger/{name}, {LIFETIME}, permanent|archival|transient) on the root ledger "
                        f"({root._store.name})")
    return str(word)


def rank(ledger: Any) -> int:
    return LIFETIMES.index(lifetime_of(ledger))


def source_of(value: Any, dest: Any) -> Tuple["Rev", str]:
    """``(the revision to read it at, its subject)``: a ``Ref``'s own revision, a ``Value``'s ledger at its head."""
    from .rev import Ref

    if isinstance(value, Ref):
        if value.subject is None or value.hash is None:
            raise NotCopied(f"{value.name!r} holds no value at rev {value.rev.id}")
        rev, subject = value.rev._plain(), value.subject
    elif isinstance(value, Value):
        ledger = value.rev.ledger if value.rev is not None else value.__dict__.get("_ledger")
        if value.subject is None or ledger is None:
            raise NotCopied(f"an unsaved {type(value).__name__}: save it first (v.seal(t)); only a value on a ledger "
                            "is copied")
        rev, subject = ledger.at(), value.subject
    else:
        raise TypeError(f"copy takes a sealed Value or a Ref, each of which knows its ledger, not "
                        f"{type(value).__name__}")
    if ledger_key(rev.ledger) == ledger_key(dest):
        raise NotCopied(f"{subject[:12]}… is on {dest._store.name} already")
    return rev, subject


def inputs(rev: "Rev", subject: str) -> List[Tuple["Rev", str]]:
    """``(a revision holding it, its subject)`` of each input of ``subject``; ``NotCopied`` for one not found."""
    out: List[Tuple["Rev", str]] = []
    keys, trace = inputs_in(rev, subject)
    for text in value_inputs(keys, trace):
        holder = holder_of(rev, text)
        if holder is None:
            raise NotCopied(f"{subject[:12]}…: its input {text[:40]}… is on no ledger here")
        out.append((rev, holder))
    for at, text in foreign_inputs(trace):
        try:
            other = rev_named(at, rev.ledger)
            holder = holder_of(other, text)
        except (LedgerError, KeyError) as e:
            raise NotCopied(f"{subject[:12]}…: its input {text[:40]}… at {at} cannot be found: {e}") from None
        if holder is None:
            raise NotCopied(f"{subject[:12]}…: {at} holds no {text[:40]}…")
        out.append((other, holder))
    return out


@dataclass
class Item:
    """One value to write: where it is read, and whether only its spec comes."""

    rev: "Rev"
    subject: str
    spec: bool
    #: ``db/subdat/<relpath>`` -> the global reference written here instead, for each subdat ``skip`` declines.
    away: Dict[str, str] = field(default_factory=dict)


class _Plan:
    """Everything a copy writes, found before anything is: a refusal writes nothing."""

    def __init__(self, t: "Transaction", deep: bool, safe: bool, skip: Tuple[str, ...]) -> None:
        self.t, self.deep, self.safe, self.skip = t, deep, safe, skip
        self.dest = ledger_key(t._ledger)
        self.floor = rank(t._ledger) if safe else 0
        self.items: Dict[str, Item] = {}
        self.fits: Dict[Tuple[str, str], bool] = {}

    def add(self, rev: "Rev", subject: str, base: str = "") -> None:
        """``subject`` read at ``rev``, its subdats, and the inputs ``deep`` or ``safe`` bring; ``base`` is its
        relpath from the copied value when it is a subdat, what ``skip`` is matched against."""
        if subject in self.items:
            return
        spec = rev._spec_only_at(subject) or (self.safe and not self.deep and self.rederivable(rev, subject))
        item = self.items[subject] = Item(rev, subject, spec)
        for rel, child in rev._subdat_children(subject):
            if declined_by(base + rel, self.skip):
                item.away[SUBDAT + rel] = f"str:{rev_text(rev)}:{child}"
            else:
                self.add(rev, child, f"{base}{rel}/")
        if not (self.deep or self.safe):
            return
        for irev, isub in inputs(rev, subject):
            if ledger_key(irev.ledger) != self.dest and (self.deep or rank(irev.ledger) < self.floor):
                self.add(irev, isub)

    def rederivable(self, rev: "Rev", subject: str) -> bool:
        """Can this value's bytes be left behind: an unconditional clause reaching ``True`` or better, its commit
        pinned, and every input safe in turn: on a permanent ledger, or rederivable itself. A claim only conditional
        on a predicate has no fallback, since that environment may not exist later. Unknown and ``False``: no."""
        key = (ledger_key(rev.ledger), subject)
        if key not in self.fits:
            self.fits[key] = self._rederivable(rev, subject)
        return self.fits[key]

    def _rederivable(self, rev: "Rev", subject: str) -> bool:
        level = unconditional(claim_of(rev, subject))
        if level is not True and level != EXACT:
            return False
        try:
            run = run_of(rev, subject)
        except NotPinned:
            return False
        if rev.ledger.at().get(run.pin_subject, PINNED) != run.tag:
            return False
        return all(lifetime_of(r.ledger) == "permanent" or self.rederivable(r, s) for r, s in inputs(rev, subject))


def _rows(rev: "Rev", subject: str) -> List[Tuple[str, str]]:
    return [(p, h.obj) for _s, p, h in rev._held_rows(subject=subject)]


def _declare(t: "Transaction", rev: "Rev", preds: Iterable[str]) -> None:
    """The cardinality and type of each pred, so the rows read here as they read there."""
    from .txn import _Op

    top = t._snapshot()
    for p in preds:
        s = f"db/pred/{p}"
        for w in ("db/cardinality", "db/type"):
            mine = rev._held(s, w)
            if not mine:
                continue
            held = top._held(s, w)
            if held and held[0].obj != mine[0].obj:
                raise NotCopied(f"{p!r} is declared {w} {show(mine[0].obj)} there and {show(held[0].obj)} here")
            if not held and not any(op.s == s and op.p == w for op in t._ops):
                t._ops.append(_Op(s, w, mine[0].obj, True))


def _mounts(t: "Transaction", rev: "Rev", name: str) -> None:
    """The mount a sandboxed function ran under, so its run is read here as there; a prefix held here stays."""
    from .fn import MNT
    from .txn import _Op

    inner = name[len(MNT) + 1:]
    top = mounts_at(t._snapshot())
    for prefix in mounts_at(rev):
        if (inner == prefix or inner.startswith(prefix + ".")) and prefix not in top:
            s = f"db/mount/{prefix}"
            for p, o in _rows(rev, s):
                if not any(op.s == s and op.p == p for op in t._ops):
                    t._ops.append(_Op(s, p, o, True))


def _write(t: "Transaction", item: Item) -> None:
    """One value's rows, and its bytes unless only its spec comes, into ``t``."""
    from .fn import MNT
    from .rev import Ref, name_of
    from .txn import _Op

    rev, subject = item.rev, item.subject
    top = t._snapshot()
    if subject in t._copied or (top._held(subject, "db/value") and (item.spec or not top._spec_only_at(subject))):
        return
    t._copied.add(subject)
    rows = _rows(rev, subject)
    held = dict(rows)
    code = show(held["db/deps/code"]) if "db/deps/code" in held else None
    if code is not None:
        t._ensure_code(code, [(p, o) for p, o in _rows(rev, code)])
    fn = show(held["db/fn"]) if "db/fn" in held else ""
    if fn.startswith(MNT + "."):
        _mounts(t, rev, fn)
    _declare(t, rev, sorted({p for p, _o in rows if not p.startswith("db/")}))
    add = [(p, item.away.get(p, o), not p.startswith("db/")) for p, o in rows if p not in LEFT_BEHIND]
    add.append((COPIED_FROM, "str:" + rev_text(rev), False))
    try:
        add.append((COMMIT, "str:" + run_of(rev, subject).commit, False))
    except NotPinned:
        pass                                    # a hand seal, or code no commit vouches for
    if item.spec:
        add.append((SPEC_ONLY, "str:true", False))
    if not top._held(subject, "db/value"):
        for p, o, pred in add:
            t._ops.append(_Op(subject, p, o, True, seal_of=subject, pred=pred))
    if not item.spec:
        ref = Ref(rev, subject)
        t._copies.append((subject, rev.ledger._store.art, ref._fetch(), [ref.hash, *ref._stored_hashes()]))
    name = name_of(rev, subject)
    if name is not None:
        t._name_value(subject, name)


def _claims(t: "Transaction", plan: _Plan, new: Dict[str, Any], safe: bool) -> None:
    """The claims the copied values make here: a source's, again under ``safe``; those in ``new``, checked
    already, as ``rerunnable`` asks."""
    for item in plan.items.values():
        held = item.rev.get(item.subject, RERUNNABLE)
        if (safe and held) or item.spec:
            run = run_of(item.rev, item.subject)
            assert_claim(t, t._snapshot(), run, held if held else None, pin_only=not held)
        if item.subject in new:
            assert_claim(t, t._snapshot(), new[item.subject], held or "true", push=True)


def skipped(skip: Optional[Iterable[str]]) -> Tuple[str, ...]:
    """The suffixes a copy declines: ``None`` is ``SKIP``, ``()`` none, any other adds to ``SKIP`` (SVP 241's rule)."""
    if isinstance(skip, str):
        raise TypeError(f"skip takes relative-path suffixes, a tuple or list, not the str {skip!r}")
    if skip is None:
        return SKIP
    entries = tuple(skip)
    for e in entries:
        if not isinstance(e, str) or not e.strip("/"):
            raise TypeError(f"a skip entry is a non-empty relative path, not {e!r}")
    return () if not entries else (*SKIP, *entries)


def copy(t: "Transaction", values: Tuple[Any, ...], *, deep: bool, safe: bool, rerunnable: bool,
         skip: Optional[Iterable[str]] = None) -> List[str]:
    """``Transaction.copy``: see the module doc. The subjects of ``values``, in order."""
    t._open("copy")
    for name, flag in (("deep", deep), ("safe", safe), ("rerunnable", rerunnable)):
        if not isinstance(flag, bool):
            raise TypeError(f"{name} is True or False, not {flag!r}")
    if not values:
        raise TypeError("copy takes at least one value")
    plan = _Plan(t, deep, safe, skipped(skip))
    named: List[str] = []
    for v in values:
        rev, subject = source_of(v, t._ledger)
        plan.add(rev, subject)
        named.append(subject)
    new = {s: check_input(plan.items[s].rev, s) for s in named} if rerunnable else {}
    mark = len(t._ops), len(t._copies), set(t._copied)
    try:
        for item in plan.items.values():
            _write(t, item)
        _claims(t, plan, new, safe)
    except BaseException:                       # a refusal writes nothing, whatever the body does with it
        del t._ops[mark[0]:], t._copies[mark[1]:]
        t._copied = mark[2]
        raise
    return named


__all__ = ["copy", "lifetime_of", "LIFETIME", "LIFETIMES", "COPIED_FROM", "SPEC_ONLY"]
