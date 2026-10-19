"""The reference model. Hypothesis writes random histories of add / remove / cardinality
flips; every row read at every revision is checked against ``model.Model``: ``all`` at
every arity, ``[]``/``get`` (a ``many`` predicate refused by its declaration, Q26), ``in``,
``asserted``, ``rows`` and the where clause of ``refs``."""

import tempfile
from pathlib import Path

import hypothesis.strategies as st
from hypothesis import HealthCheck, settings
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, precondition, rule

from dvc_dat.ledger import Ledger
from model import Model

SUBJECTS = ["a", "b", "c"]
PREDS = ["x", "y", "z"]
OBJS = ["1", "2", "3"]

op = st.one_of(
    st.tuples(st.just("add"), st.sampled_from(SUBJECTS), st.sampled_from(PREDS), st.sampled_from(OBJS)),
    st.tuples(st.just("remove"), st.sampled_from(SUBJECTS), st.sampled_from(PREDS), st.sampled_from(OBJS)),
    st.tuples(st.just("card"), st.sampled_from(PREDS), st.sampled_from(["many", "one"])),
    st.tuples(st.just("uncard"), st.sampled_from(PREDS), st.sampled_from(["many", "one"])),
)


def as_quad(o):
    """``(added, s, p, obj)`` for one generated op."""
    if o[0] == "add":
        return (True, o[1], o[2], o[3])
    if o[0] == "remove":
        return (False, o[1], o[2], o[3])
    return (o[0] == "card", f"db/pred/{o[1]}", "db/cardinality", o[2])


def outcome(fn):
    try:
        return ("ok", fn())
    except KeyError:
        return ("none",)
    except TypeError:
        return ("many",)


def check_rev(L, model, R):
    """Every row read at revision R equals the model's answer."""
    rev = L.at(R)
    assert rev.all() == model.pattern(R, ())
    assert [(r.rev.id, r.subject, r.predicate, r.object, r.added) for r in rev.rows()] == \
        [(a, s, p, o, d) for a, _o, s, p, o, d in model.rows if a <= R]
    subjects = SUBJECTS + [f"db/pred/{p}" for p in PREDS]
    for s in subjects:
        assert rev.all(s) == model.pattern(R, (s,))
    for s in SUBJECTS:
        for p in PREDS:
            want = model.pattern(R, (s, p))
            assert rev.all(s, p) == want
            many = model.card(p, R) == "many"
            exp = ("many",) if many else ("none",) if not want else ("ok", want[0])
            assert outcome(lambda s=s, p=p: rev[s, p]) == exp
            if not many:
                assert rev.get(s, p, default="<d>") == (want[0] if want else "<d>")
            for o in OBJS:
                assert ((s, p, o) in rev) == (o in want)
                assert [r.id for r in rev.all(s, p, o)] == model.pattern(R, (s, p, o))
                assert [r.id for r in rev.asserted(s, p, o)] == model.asserted(R, s, p, o)
                held = model.pattern(R, (s, p, o))
                assert outcome(lambda: rev[s, p, o].id) == (("ok", held[0]) if held else ("none",))
    for p in PREDS:
        assert sorted(r.subject for r in rev.refs(where={p: None})) == model.subjects(R, p)
        for o in OBJS:
            assert sorted(r.subject for r in rev.refs(where={p: o})) == model.subjects(R, p, o)


class LedgerVsModel(RuleBasedStateMachine):
    @initialize()
    def setup(self):
        self.dir = tempfile.TemporaryDirectory()
        self.L = Ledger(Path(self.dir.name) / "m", create=True)
        self.model = Model()

    def teardown(self):
        self.dir.cleanup()

    @rule(ops=st.lists(op, min_size=0, max_size=4))
    def commit(self, ops):
        quads = [as_quad(o) for o in ops]
        with self.L.transaction(by="agent") as t:
            for added, s, p, o in quads:
                (t.add if added else t.remove)(s, p, o)
        rid = self.model.commit("agent", quads)
        assert t.rev.id == rid

    @invariant()
    def top_agrees(self):
        if hasattr(self, "model"):
            check_rev(self.L, self.model, self.model.top)

    @precondition(lambda self: hasattr(self, "model") and self.model.top > 1)
    @rule(data=st.data())
    def old_rev_agrees(self, data):
        R = data.draw(st.integers(0, self.model.top))
        check_rev(self.L, self.model, R)
        a = data.draw(st.integers(0, R))
        assert self.L.at(R).all(since=self.L.at(a)) == self.model.pattern(R, (), after=a)
        for s in SUBJECTS:
            for p in PREDS:
                assert self.L.at(R).all(s, p, since=self.L.at(a)) == self.model.pattern(R, (s, p), after=a)
        for p in PREDS:
            got = sorted(r.subject for r in self.L.at(R).refs(where={p: None}, since=self.L.at(a)))
            assert got == self.model.subjects(R, p, after=a)


LedgerVsModel.TestCase.settings = settings(max_examples=100, stateful_step_count=20, deadline=None,
                                           derandomize=True, database=None,
                                           suppress_health_check=[HealthCheck.too_slow])
TestLedgerVsModel = LedgerVsModel.TestCase
