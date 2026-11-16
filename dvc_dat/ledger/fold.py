"""The as-of fold: what the rows on one ``(subject, predicate)`` hold, by cardinality.

Rows arrive in ``(rev, ord)`` order, ``ord`` the place in the transaction body
(A50). ``one`` (the default): the latest ``add`` wins; re-adding the held
object changes nothing, its revision included (A12); a ``remove`` of the held
object leaves nothing (a tombstone); a ``remove`` of any other changes
nothing. ``many``: a set; each member at its earliest add not since removed,
members in that order; re-adding a present member keeps its place, a remove
then re-add moves it to the end (Q27).

An object stored as a ``spill:`` reference (SVP 1738) is the same object as its inline text (``codec.same``), so a
remove or re-add written under another spill threshold still finds it.
"""

from __future__ import annotations

from typing import List, NamedTuple, Sequence

from .codec import is_spill, same, spill_text


class Held(NamedTuple):
    obj: str
    rev: int
    ord: int


def fold(rows: Sequence[tuple], card: str) -> List[Held]:
    """The held objects of rows ``(rev, ord, s, p, obj, added)`` on one (s, p)."""
    if card == "many":
        sizes = {int(r[4].rpartition(":")[2]) for r in rows if is_spill(r[4])}

        def key(text: str) -> str:
            """A member's key: a plain text the size of some spill is keyed by its spill form."""
            if not sizes or is_spill(text) or text.startswith("ref:") or len(text.encode("utf-8")) not in sizes:
                return text
            return spill_text(text)
        members: dict = {}
        for r in rows:
            k = key(r[4])
            if r[5]:
                if k not in members:
                    members[k] = Held(r[4], r[0], r[1])
            else:
                members.pop(k, None)
        return sorted(members.values(), key=lambda h: (h.rev, h.ord))
    cur = None
    for r in rows:
        if r[5]:
            if cur is None or not same(cur.obj, r[4]):
                cur = Held(r[4], r[0], r[1])
        elif cur is not None and same(cur.obj, r[4]):
            cur = None
    return [] if cur is None else [cur]
