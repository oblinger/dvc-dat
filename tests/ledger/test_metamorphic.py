"""Metamorphic relations. A read at revision N does not change after later writes;
``since=`` windows equal the log and partition it; the fold does not depend on the order of
transactions that touch distinct (subject, predicate) pairs."""

import tempfile
from pathlib import Path

import hypothesis.strategies as st
from hypothesis import given, settings

from dvc_dat.ledger import Ledger

SUBJECTS = ["a", "b", "c"]
PREDS = ["x", "y", "z"]
OBJS = ["1", "2", "3"]
SETTINGS = settings(max_examples=60, deadline=None, derandomize=True, database=None)

quad = st.tuples(st.booleans(), st.sampled_from(SUBJECTS), st.sampled_from(PREDS), st.sampled_from(OBJS))
history = st.lists(st.lists(quad, max_size=3), min_size=1, max_size=8)
cards = st.dictionaries(st.sampled_from(PREDS), st.sampled_from(["many", "one"]))


def fresh():
    d = tempfile.TemporaryDirectory()
    return d, Ledger(Path(d.name) / "m", create=True)


def write(L, txs):
    for ops in txs:
        with L.transaction(by="agent") as t:
            for added, s, p, o in ops:
                (t.add if added else t.remove)(s, p, o)


def declare(L, cardmap):
    with L.transaction(by="agent") as t:
        for p, c in cardmap.items():
            t.add(f"db/pred/{p}", "db/cardinality", c)


def battery(rev):
    """Every read on a Rev that the spec names, as one comparable record."""
    out = {"all": rev.all(), "id": rev.id}
    for s in SUBJECTS:
        out[s] = rev.all(s)
        for p in PREDS:
            try:
                one = ("ok", rev[s, p])
            except KeyError:
                one = ("none",)
            except TypeError:
                one = ("many",)
            out[s, p] = (rev.all(s, p), one, [r.id for o in OBJS for r in rev.all(s, p, o)],
                         [(s, p, o) in rev for o in OBJS])
    for p in PREDS:
        out["refs", p] = [r.subject for r in rev.refs(where={p: None})]
        out["select", p] = rev.select((p,), where={p: None})
    return out


@SETTINGS
@given(cardmap=cards, before=history, after=history)
def test_a_read_at_n_is_unchanged_by_later_writes(cardmap, before, after):
    d, L = fresh()
    try:
        declare(L, cardmap)
        write(L, before)
        early = L.at()
        snap = battery(early)
        write(L, after)
        declare(L, {p: ("one" if c == "many" else "many") for p, c in cardmap.items()})
        assert battery(early) == snap
        assert battery(L.at(early.id)) == snap
    finally:
        d.cleanup()


distinct = st.lists(st.tuples(st.sampled_from(SUBJECTS), st.sampled_from(PREDS), st.sampled_from(OBJS)),
                    unique=True, min_size=1, max_size=12)


@SETTINGS
@given(triples=distinct, data=st.data())
def test_since_window_is_the_log_and_partitions(triples, data):
    """Add-only distinct triples under ``many``: a window's fold is exactly the log's rows in it."""
    d, L = fresh()
    try:
        declare(L, {p: "many" for p in PREDS})
        start = L.at().id
        for tr in triples:
            with L.transaction(by="agent") as t:
                t.add(*tr)
        top = L.at().id
        a = data.draw(st.integers(start, top))
        b = data.draw(st.integers(a, top))
        c = data.draw(st.integers(b, top))
        log = [x for x in [(r[2], r[3], L.at(top)._decode(r[4])) for r in L._store.rows(b, after=a)] if not x[0].startswith("db/tx/")]
        strip = lambda rows: [r for r in rows if not r[0].startswith("db/tx/")]  # noqa: E731
        assert strip(L.at(b).all(since=L.at(a))) == log
        assert L.at(c).all(since=L.at(a)) == L.at(b).all(since=L.at(a)) + L.at(c).all(since=L.at(b))
        assert L.at(c).all(since=L.at(c)) == []
    finally:
        d.cleanup()


DISJOINT = [[(True, "a", "x", "1"), (True, "a", "x", "2"), (False, "a", "x", "1")],
            [(True, "b", "y", "2"), (True, "b", "y", "3")],
            [(True, "c", "z", "3"), (True, "a", "y", "1"), (False, "c", "z", "3"), (True, "c", "z", "1")]]


@SETTINGS
@given(order=st.permutations(list(range(3))), cardmap=cards)
def test_fold_is_invariant_under_reordering_distinct_transactions(order, cardmap):
    """Transactions on disjoint (s, p) pairs, adds and removes, any cardinality: any order, one state."""
    def run(seq):
        d, L = fresh()
        try:
            declare(L, cardmap)
            write(L, [DISJOINT[i] for i in seq])
            rev = L.at()
            rows = sorted(r for r in rev.all() if not r[0].startswith("db/tx/"))
            return rows, {p: sorted(r.subject for r in rev.refs(where={p: None})) for p in PREDS}
        finally:
            d.cleanup()

    assert run(order) == run(range(3))


@SETTINGS
@given(order=st.permutations(list(range(4))))
def test_fold_is_invariant_with_fixed_objects(order):
    txs = [[("a", "x", "1")], [("b", "y", "2"), ("b", "z", "3")], [("c", "x", "1")], [("a", "z", "2")]]

    def run(seq):
        d, L = fresh()
        try:
            for i in seq:
                with L.transaction(by="agent") as t:
                    for tr in txs[i]:
                        t.add(*tr)
            rev = L.at()
            return sorted(r for r in rev.all() if not r[0].startswith("db/tx/"))
        finally:
            d.cleanup()

    assert run(order) == run(range(4))


def test_cardinality_flip_refolds_earlier_rows_for_reads_at_or_after_it(L):
    with L.transaction(by="t") as t:
        t.add("s", "tag", "red")
    with L.transaction(by="t") as t:
        t.add("s", "tag", "blue")
    before = L.at()
    with L.transaction(by="t") as t:
        t.add("db/pred/tag", "db/cardinality", "many")
    after = L.at()
    assert before["s", "tag"] == "blue"
    assert after.all("s", "tag") == ["red", "blue"]
    with L.transaction(by="t") as t:
        t.add("db/pred/tag", "db/cardinality", "one")
    assert L.at()["s", "tag"] == "blue"
    assert after.all("s", "tag") == ["red", "blue"]
