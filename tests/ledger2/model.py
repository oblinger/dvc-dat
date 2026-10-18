"""The reference model: the ledger's read semantics as a plain list of quads, independent of the backend.

A history is a list of rows ``(rev, ord, s, p, o, added)`` with ``o`` a plain
string. Every read is a function of the rows at or before a revision R (and
after ``since``), folded per (s, p) by the cardinality ``ledger/pred/<p>``
declares as of R: ``one`` keeps the latest add (a remove of exactly that value
clears it), ``many`` keeps every add not since removed.
"""

BUILTIN_ONE = {"cardinality", "index", "doc", "version", "format", "commit", "value", "kind", "provenance",
               "by", "time", "fn", "name", "module", "sha", "modules", "mounts", "mode", "root", "salt"}


class Model:
    def __init__(self):
        self.rows = []
        self.top = 0

    def commit(self, by, ops):
        """``ops``: ``(added, s, p, o)``; the revision writes ``ledger/tx/<rev> by`` first."""
        self.top += 1
        self.rows.append((self.top, 0, f"ledger/tx/{self.top}", "by", by, True))
        for i, (added, s, p, o) in enumerate(ops, start=1):
            self.rows.append((self.top, i, s, p, o, added))
        return self.top

    def _state(self, R, after, card_of):
        state = {}                      # (s, p) -> {o: (rev, ord)}
        for rev, ord_, s, p, o, added in self.rows:
            if not after < rev <= R:
                continue
            held = state.setdefault((s, p), {})
            if card_of(p) == "one":
                if added:
                    held.clear()
                    held[o] = (rev, ord_)
                elif o in held:
                    held.clear()
            elif added:
                held.pop(o, None)
                held[o] = (rev, ord_)
            else:
                held.pop(o, None)
        return state

    def card(self, p, R):
        if p in BUILTIN_ONE:
            return "one"
        st = self._state(R, 0, lambda q: "one")
        held = st.get((f"ledger/pred/{p}", "cardinality"), {})
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
        """What ``Rev.all(*pattern)`` returns: the unfixed positions (a 3-pattern: asserting revisions)."""
        n = len(pattern)
        if n == 3:
            s, p, o = pattern
            revs = []
            for rev, _o, s2, p2, o2, added in self.rows:
                if after < rev <= R and added and (s2, p2, o2) == (s, p, o) and rev not in revs:
                    revs.append(rev)
            return revs
        hs = self.held(R, after)
        if n == 0:
            return [(s, p, o) for s, p, o, _r, _o in hs]
        if n == 1:
            return [(p, o) for s, p, o, _r, _o in hs if s == pattern[0]]
        return [o for s, p, o, _r, _o in hs if (s, p) == pattern]

    def subjects(self, R, pred, obj=None, after=0):
        """The subjects with a held row ``(s, pred, obj)`` (``obj=None``: any)."""
        return sorted({s for s, p, o, _r, _o in self.held(R, after) if p == pred and (obj is None or o == obj)})
