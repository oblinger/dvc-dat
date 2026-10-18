"""The as-of fold: what a run of rows on one ``(subject, predicate)`` holds, by cardinality.

``one`` (the default): the latest ``add`` wins; a ``remove`` of the value
currently held leaves no value (a tombstone), a ``remove`` of any other value
changes nothing. ``many``: the set of adds not since removed, each member
ordered by the revision of its latest ``add``. Rows arrive in (rev, ord) order.
"""

from __future__ import annotations

from typing import List, NamedTuple, Sequence

#: Built-in predicates whose cardinality is fixed at ``one``; a declaration on them is ignored.
BUILTIN_ONE = frozenset({
    "cardinality", "index", "doc", "version", "format", "commit", "value", "kind", "provenance",
    "by", "time", "fn", "name", "module", "sha", "modules", "mounts", "mode", "root", "salt",
})


class Held(NamedTuple):
    obj: str
    rev: int
    ord: int


def fold(rows: Sequence[tuple], card: str) -> List[Held]:
    """The held objects of rows ``(rev, ord, s, p, obj, added)`` on one (s, p), ordered by asserting (rev, ord)."""
    if card == "many":
        members: dict = {}
        for r in rows:
            if r[5]:
                members.pop(r[4], None)
                members[r[4]] = Held(r[4], r[0], r[1])
            else:
                members.pop(r[4], None)
        return sorted(members.values(), key=lambda h: (h.rev, h.ord))
    cur = None
    for r in rows:
        if r[5]:
            cur = Held(r[4], r[0], r[1])
        elif cur is not None and cur.obj == r[4]:
            cur = None
    return [] if cur is None else [cur]


def cardinality_of(rows: Sequence[tuple]) -> str:
    """The cardinality the rows of ``(ledger/pred/<p>, cardinality, …)`` declare: ``many`` or ``one``."""
    held = fold(rows, "one")
    return "many" if held and held[0].obj == "str:many" else "one"
