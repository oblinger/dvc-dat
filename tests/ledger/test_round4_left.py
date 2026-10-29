"""Ledger latent bugs left open from deep scan round 4 (Tink's 31-item list, 2026-10-27): a recorded query
that no longer parses, a post-commit hook that raises, a value class defined in a function, a transaction
keyword against its db/type."""

import pytest

import round4_kinds as K
from dvc_dat.ledger.txn import Transaction


def write(L, *triples, **kw):
    with L.transaction(by="t", **kw) as t:
        for s, p, o in triples:
            t.add(s, p, o)


def test_a_dependency_item_that_does_not_parse_is_a_miss_not_a_crash(coded):
    write(coded, ("q:stuff", "p", "a"))
    K.CALLS.clear()
    assert coded.at().run("round4_kinds.reads", s="q:stuff", p="p").obj == {"o": "a"}
    write(coded, ("q:stuff", "p", "b"))
    assert coded.at().run("round4_kinds.reads", s="q:stuff", p="p").obj == {"o": "b"}


def test_a_post_commit_hook_that_raises_leaves_the_transaction_committed(L, monkeypatch):
    def boom(self):
        raise RuntimeError("hook")
    monkeypatch.setattr(Transaction, "_finish", boom)
    before = L.at().id
    with pytest.raises(RuntimeError, match="hook"):
        with L.transaction(by="t") as t:
            t.add("a", "b", "c")
    assert t._state == "committed" and t.rev.id == before + 1 and L.at()["a", "b"] == "c"


def test_a_value_class_defined_in_a_function_is_refused_at_the_seal(coded):
    with pytest.raises(TypeError, match="defined inside a function"):
        coded.at().run("round4_kinds.local_value", n=2)


def test_a_transaction_keyword_is_checked_against_its_db_type(L):
    write(L, ("db/pred/note", "db/type", "json"))
    before = L.at().id
    with pytest.raises(TypeError, match="db/type"):
        write(L, ("x", "y", "z"), note="plain")
    assert L.at().id == before
    write(L, ("x", "y", "z"), note={"k": 1})
    assert L.at()[f"db/tx/{L.at().id}", "note"] == {"k": 1}
