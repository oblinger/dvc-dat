"""``@dat.warm`` (SVP 250 A7): a process-level memo keyed by the canonical hash of the arguments, bounded by bytes."""

import pytest

from dvc_dat import dat
from dvc_dat.ledger import Ref, Value
from dvc_dat.ledger.warm import Warm, size_of


@pytest.fixture
def store():
    w = Warm(max_bytes=10_000)
    yield w
    w.clear()


def test_the_same_arguments_compute_once(store):
    calls = []

    @store
    def twice(x, y=2):
        calls.append((x, y))
        return {"v": x * y}
    assert twice(3) == {"v": 6} and twice(3, 2) == {"v": 6} and twice(x=3) == {"v": 6}
    assert twice(3, y=3) == {"v": 9}
    assert calls == [(3, 2), (3, 3)]
    assert store.stats()["hits"] == 2 and store.stats()["misses"] == 2 and store.stats()["entries"] == 2
    assert twice.__wrapped__(3) == {"v": 6} and len(calls) == 3        # the function itself, unwarmed


def test_dat_warm_is_the_process_store():
    @dat.warm
    def one(n: int):
        return [n] * n
    before = dat.warm.stats()["hits"]
    one(4)
    one(4)
    assert dat.warm.stats()["hits"] == before + 1 and getattr(one, "__dat_warm__", False)


def test_values_key_by_hash_refs_by_subject_and_the_rest_by_canonical(L, store):
    calls = []

    @store
    def load(v, spec):
        calls.append(1)
        return len(calls)
    with L.transaction(by="t") as t:
        a = Value.Blob(b"same")
        a.seal(t, name="a")
        b = Value.Blob(b"same")
        b.seal(t, name="b")                                            # the same bytes: the same key
    assert load(a, {"k": [1, 2]}) == load(b, {"k": [1, 2]}) == 1
    assert load(a, {"k": [1, 3]}) == 2
    r = Ref(L.at(), "a")
    assert load(r, {"k": [1, 2]}) == 3 and load(r, {"k": [1, 2]}) == 3
    assert load(L.at(), 1) == 4 and load(L.at(), 1) == 4 and load(L, 1) == 5
    with pytest.raises(TypeError, match="unsealed"):
        load(Value.Blob(b"draft"), {})
    with pytest.raises(TypeError, match="no warm key"):
        load(a, {1, 2})
    with pytest.raises(TypeError, match="no warm key"):
        load(a, float("nan"))


def test_the_store_is_an_lru_by_bytes():
    w = Warm(max_bytes=size_of(b"x" * 100) * 2 + 1)

    @w
    def blob(n):
        return bytes([n]) * 100
    blob(1)
    blob(2)
    assert w.stats()["entries"] == 2
    blob(1)                                                            # recently used: survives
    blob(3)                                                            # evicts 2
    assert w.stats()["entries"] == 2 and w.stats()["bytes"] <= w.max_bytes
    assert w.stats()["hits"] == 1
    blob(1)
    assert w.stats()["hits"] == 2
    blob(2)
    assert w.stats()["misses"] == 4

    @w
    def huge(n):
        return bytes(n)
    assert len(huge(10_000)) == 10_000 and w.stats()["entries"] == 2   # over the budget: returned, not kept
    w.clear()
    assert w.stats() == {"entries": 0, "bytes": 0, "max_bytes": w.max_bytes, "hits": 2, "misses": 5}


def test_a_class_is_refused():
    with pytest.raises(TypeError):
        dat.warm(int)
