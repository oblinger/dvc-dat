"""Several ``Ledger`` handles on one ledger in one process (SVP 1468, R0001): a declaration written
through one handle is what every other handle's next read answers; an earlier ``Rev`` keeps its own."""

import threading

import pytest

from dvc_dat.ledger import Ledger
from dvc_dat.ledger.store import index_name


def _open(L):
    return Ledger(L.path)


def _card(rev):
    return len(rev.all("flip/s", "flipc"))


def _typed(rev):
    try:
        return rev["flip/t", "flipt"]
    except TypeError:
        return TypeError


@pytest.fixture
def flips(L):
    with L.transaction(by="setup") as t:
        t.add("db/pred/flipc", "db/cardinality", "many")
        t.add("flip/s", "flipc", "x")
        t.add("flip/s", "flipc", "y")
        t.add("db/pred/flipt", "db/type", "str")
        t.add("flip/t", "flipt", "hello")
    return L


def test_a_flip_on_one_handle_is_the_next_read_on_every_other(flips):
    A = flips
    others = [_open(A) for _ in range(3)]
    before = [h.at() for h in others]
    assert all(_card(r) == 2 and _typed(r) == "hello" for r in before)
    for card, typ, n, got in (("one", "json", 1, TypeError), ("many", "str", 2, "hello")):
        with A.transaction(by=f"flip {card}", lock=10) as t:
            t.add("db/pred/flipc", "db/cardinality", card)
            t.add("db/pred/flipt", "db/type", typ)
        for h in others:
            rev = h.at()
            assert rev.id == t.rev.id
            assert _card(rev) == n and _typed(rev) == got
    assert all(_card(r) == 2 and _typed(r) == "hello" for r in before)     # an earlier Rev keeps its answer


def test_a_flip_is_seen_by_another_handle_in_another_thread(flips):
    A, B = flips, _open(flips)
    _card(B.at())                       # B's reader connection in this thread is open and warm
    seen = {}

    def other():
        seen["first"] = _card(B.at())
        flipped.wait(10)
        rev = B.at()
        seen["after"] = (rev.id, _card(rev))
    flipped = threading.Event()
    th = threading.Thread(target=other)
    th.start()
    with A.transaction(by="flip", lock=10) as t:
        t.add("db/pred/flipc", "db/cardinality", "one")
    flipped.set()
    th.join(10)
    assert seen == {"first": 2, "after": (t.rev.id, 1)}
    assert _card(B.at()) == 1


def test_an_index_declared_on_one_handle_is_listed_by_another(L):
    B = _open(L)
    assert index_name("idx") not in B._store.index_names()
    with L.transaction(by="index") as t:
        t.add("db/pred/idx", "db/index", "true")
        t.add("ix/s", "idx", "v")
    assert index_name("idx") in B._store.index_names()
    assert B.at().get("ix/s", "idx") == "v"
