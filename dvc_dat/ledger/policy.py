"""The memo policy (SVP 1474): what of a platform record a memo lookup compares.

A memo entry stores the full platform record of the machine its function ran on (``env.platform_record``,
the ``platform/record`` dependency item); a lookup hits an entry only when
``policy(stored record) == policy(current record)``. A policy is a function from a record to a ``str``;
a field it reads that the record lacks (``KeyError``: an entry written before the record existed holds
only ``platform``) is a miss, never a hit.

The ledger names its policy in one row, ``(db, db/memo-policy, <name>)``, written by a new ledger's first
transaction as ``platform``; a ledger without the row reads ``platform``. Changing the policy is a new row at
a later revision (``t.add("db", "db/memo-policy", "card")``); every handle reads the policy at the top, so
every entry, old or new, is judged by the policy in force at the lookup. Built-ins:

``platform``
    the default: the ``platform`` field, ``<os>-<machine>-py<X.Y>``, exactly the pre-1474 item.
``card``
    ``platform`` plus ``card`` and ``driver``.

``register_policy(name, fn)`` adds one in code; the triple stores the name, so every process that looks
up under it must register it first (an unregistered name is ``LedgerError`` at the lookup).
``deterministic=True`` on a call adds ``card`` and ``driver`` to whatever the policy compares.

The index: each store handle keeps ``subject -> policy(stored record)`` for every memo entry, stamped with
the policy (name and function) it was built under. A lookup compares the stamp with the policy in force,
rebuilds once on a mismatch, and otherwise only adds the entries sealed since. It is a pre-filter only:
every candidate it passes is still judged in full by the hit test.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from .codec import canonical, show
from .errors import LedgerError

if TYPE_CHECKING:
    from .rev import Rev

Policy = Callable[[Mapping[str, Any]], str]

#: The row naming a ledger's memo policy: ``(SUBJECT, PREDICATE, <name>)``.
SUBJECT = "db"
PREDICATE = "db/memo-policy"
DEFAULT = "platform"
#: What ``deterministic=True`` adds to the policy's comparison.
DETERMINISTIC = ("card", "driver")


def _platform(r: Mapping[str, Any]) -> str:
    return str(r["platform"])


def _card(r: Mapping[str, Any]) -> str:
    return canonical([r["platform"], r["card"], r["driver"]])


POLICIES: Dict[str, Policy] = {"platform": _platform, "card": _card}
BUILT_IN = frozenset(POLICIES)


def register_policy(name: str, fn: Policy) -> None:
    """Make ``fn`` (record -> ``str``) the memo policy named ``name``, for a ``(db, db/memo-policy, name)`` row
    to select; a built-in name is refused. Registering a name again replaces it (the index rebuilds)."""
    if not isinstance(name, str) or not name:
        raise TypeError(f"a policy name is a non-empty str, not {name!r}")
    if name in BUILT_IN:
        raise ValueError(f"{name!r} is a built-in memo policy; register yours under another name")
    if not callable(fn):
        raise TypeError(f"a policy is a function from a platform record to a str, not {fn!r}")
    POLICIES[name] = fn


def policy_at(top: "Rev") -> Tuple[str, Policy]:
    """The policy in force at ``top``: its name (the row, else ``platform``) and its function."""
    held = top._held(SUBJECT, PREDICATE)
    name = show(held[0].obj) if held else DEFAULT
    fn = POLICIES.get(name)
    if fn is None:
        raise LedgerError(f"the ledger's memo policy is {name!r} ({SUBJECT} {PREDICATE}), which no code in this "
                          f"process registered (built-in: {', '.join(sorted(BUILT_IN))}; register_policy)")
    return name, fn


def judge(fn: Policy, rec: Optional[Mapping[str, Any]], widen: Sequence[str] = ()) -> Optional[str]:
    """``fn(rec)`` with the ``widen`` fields appended; ``None`` when the record lacks what is read."""
    if rec is None:
        return None
    try:
        key = fn(rec)
        if widen:
            key = canonical([key, *[rec[f] for f in widen]])
    except KeyError:
        return None
    return key


@dataclass
class MemoIndex:
    """``keys``: memo entry subject -> its stored record under ``stamp``'s policy, through revision ``upto``."""

    stamp: Optional[Tuple[str, Policy]] = None
    upto: int = 0
    keys: Dict[str, Optional[str]] = field(default_factory=dict)
    builds: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


_INDEXES_LOCK = threading.Lock()


def memo_index(ledger: Any) -> MemoIndex:
    """The index the ledger handle's store keeps."""
    store = ledger._store
    with _INDEXES_LOCK:
        idx = getattr(store, "_memo_index", None)
        if idx is None:
            idx = MemoIndex()
            store._memo_index = idx
    return idx


def reduced(top: "Rev", name: str, fn: Policy) -> Dict[str, Optional[str]]:
    """The index, current through ``top``: rebuilt when its stamp is not ``(name, fn)``, else extended."""
    from .env import RECORD_ITEM, stored_record

    idx = memo_index(top.ledger)
    with idx.lock:
        if idx.stamp is None or idx.stamp[0] != name or idx.stamp[1] is not fn or top.id < idx.upto:
            idx.stamp, idx.upto, idx.keys = (name, fn), 0, {}
            idx.builds += 1
        if top.id > idx.upto:
            traces: Dict[str, Dict[str, str]] = {}
            for p in ("db/deps/platform", "db/deps/" + RECORD_ITEM):
                for r in top._store.rows(top.id, predicate=p, after=idx.upto):
                    if r[5]:
                        traces.setdefault(r[2], {})[p[len("db/deps/"):]] = r[4].partition(":")[2]
            for s, trace in traces.items():
                idx.keys[s] = judge(fn, stored_record(trace))
            idx.upto = top.id
        return idx.keys
