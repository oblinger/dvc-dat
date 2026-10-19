"""The reference model: the ledger's read semantics as a plain list of quads, independent of the backend.

A history is a list of rows ``(rev, ord, s, p, o, added)`` with ``o`` a plain
string; within a revision the body's rows come first, in body order, then the
transaction's own ``db/tx/<rev> db/by`` row (A50). Every read is a function of
the rows at or before a revision R (and after ``since``), folded per (s, p) by
the cardinality ``db/pred/<p> db/cardinality`` declares as of R:

``one``
    the latest add wins; re-adding the held object keeps its revision (A12);
    a remove of exactly the held object clears it.
``many``
    a set: each member at its earliest add not since removed (Q27).
"""


FORMAT = "dvc-dat-ledger/1"   # (db, db/format), written by the first transaction


def fixed_one(p):
    return p.startswith("db/") or p in ("version", "commit")


class Model:
    def __init__(self):
        self.rows = []
        self.top = 0

    def commit(self, by, ops):
        """``ops``: ``(added, s, p, o)``; the revision ends with ``db/tx/<rev> db/by``."""
        self.top += 1
        for i, (added, s, p, o) in enumerate(ops):
            self.rows.append((self.top, i, s, p, o, added))
        n = len(ops)
        if self.top == 1:
            self.rows.append((1, n, "db", "db/format", FORMAT, True))
            n += 1
        self.rows.append((self.top, n, f"db/tx/{self.top}", "db/by", by, True))
        return self.top

    def _state(self, R, after, card_of):
        state = {}                      # (s, p) -> {o: (rev, ord)}
        for rev, ord_, s, p, o, added in self.rows:
            if not after < rev <= R:
                continue
            held = state.setdefault((s, p), {})
            if card_of(p) == "one":
                if added:
                    if o not in held:
                        held.clear()
                        held[o] = (rev, ord_)
                elif o in held:
                    held.clear()
            elif added:
                held.setdefault(o, (rev, ord_))
            else:
                held.pop(o, None)
        return state

    def card(self, p, R):
        if fixed_one(p):
            return "one"
        st = self._state(R, 0, lambda q: "one")
        held = st.get((f"db/pred/{p}", "db/cardinality"), {})
        return "many" if list(held) == ["many"] else "one"

    def held(self, R, after=0):
        """``[(s, p, o, rev, ord)]`` held at R, ordered by asserting (rev, ord)."""
        cards = {}

        def card_of(p):
            if p not in cards:
                cards[p] = self.card(p, R)
            return cards[p]
        out = [(s, p, o, ro[0], ro[1]) for (s, p), held in self._state(R, after, card_of).items()
               for o, ro in held.items()]
        return sorted(out, key=lambda x: (x[3], x[4]))

    def pattern(self, R, pattern, after=0):
        """What ``Rev.all(*pattern)`` returns: the unfixed positions (a 3-pattern: the held row's revision)."""
        n = len(pattern)
        hs = self.held(R, after)
        if n == 3:
            return [r for s, p, o, r, _o in hs if (s, p, o) == pattern]
        if n == 0:
            return [(s, p, o) for s, p, o, _r, _o in hs]
        if n == 1:
            return [(p, o) for s, p, o, _r, _o in hs if s == pattern[0]]
        return [o for s, p, o, _r, _o in hs if (s, p) == pattern]

    def asserted(self, R, s, p, o):
        revs = []
        for rev, _o, s2, p2, o2, added in self.rows:
            if rev <= R and added and (s2, p2, o2) == (s, p, o) and rev not in revs:
                revs.append(rev)
        return revs

    def subjects(self, R, p, o=None, after=0):
        """Sorted subjects holding ``p`` (any object, or ``o``) at R."""
        return sorted({s for s, p2, o2, _r, _o in self.held(R, after) if p2 == p and (o is None or o2 == o)})
