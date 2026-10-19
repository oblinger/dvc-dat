"""The as-of fold: what the rows on one ``(subject, predicate)`` hold, by cardinality.

Rows arrive in ``(rev, ord)`` order, ``ord`` the place in the transaction body
(A50). ``one`` (the default): the latest ``add`` wins; re-adding the held
object changes nothing, its revision included (A12); a ``remove`` of the held
object leaves nothing (a tombstone); a ``remove`` of any other changes
nothing. ``many``: a set; each member at its earliest add not since removed,
members in that order; re-adding a present member keeps its place, a remove
then re-add moves it to the end (Q27).
"""

from __future__ import annotations

from typing import List, NamedTuple, Sequence


class Held(NamedTuple):
    obj: str
    rev: int
    ord: int


def fold(rows: Sequence[tuple], card: str) -> List[Held]:
    """The held objects of rows ``(rev, ord, s, p, obj, added)`` on one (s, p)."""
    if card == "many":
        members: dict = {}
        for r in rows:
            if r[5]:
                if r[4] not in members:
                    members[r[4]] = Held(r[4], r[0], r[1])
            else:
                members.pop(r[4], None)
        return sorted(members.values(), key=lambda h: (h.rev, h.ord))
    cur = None
    for r in rows:
        if r[5]:
            if cur is None or cur.obj != r[4]:
                cur = Held(r[4], r[0], r[1])
        elif cur is not None and cur.obj == r[4]:
            cur = None
    return [] if cur is None else [cur]
