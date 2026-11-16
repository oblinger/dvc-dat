"""SVP 1738: a value too large for a row is spilled to the art store, transparently; ``db/spill-threshold`` and
``db/max-fact`` per ledger."""

import pytest

from dvc_dat.ledger import FactTooLarge, Ledger, Ref, Spilled
from dvc_dat.ledger.codec import sha256
from dvc_dat.ledger.spill import DEFAULT_THRESHOLD, FLOOR, MAX_FACT, SPILL_THRESHOLD
from dvc_dat.ledger.store import ArtStore
from ledger_kinds import Video

BIG = {"rows": [{"i": i, "text": "x" * 40} for i in range(2000)]}      # ~100 KB as JSON
BIG_STR = "y" * (DEFAULT_THRESHOLD + 10)


def stored(L, s, p):
    """The row's object as stored."""
    rows = L._store.rows(L._store.top(), subject=s, predicate=p)
    return rows[-1][4]


def art_files(L):
    root = L._store.art.root / "sha256"
    return sorted(p.name for p in root.rglob("*") if p.is_file()) if root.exists() else []


def setting(L, p, n):
    with L.transaction(by="t") as t:
        t.add("db", p, str(n))


@pytest.fixture
def opens(monkeypatch):
    """The hashes the art store opened for reading."""
    seen = []
    real = ArtStore.open

    def counting(self, h):
        seen.append(h)
        return real(self, h)
    monkeypatch.setattr(ArtStore, "open", counting)
    return seen


def test_a_value_at_or_under_the_threshold_is_inline(L):
    setting(L, SPILL_THRESHOLD, 200)
    exact = "a" * (200 - len("str:"))           # its tagged text is exactly 200 bytes
    with L.transaction(by="t") as t:
        t.add("x", "small", exact)
        t.add("x", "doc", {"k": "v"})
    assert stored(L, "x", "small") == "str:" + exact and stored(L, "x", "doc") == 'json:{"k":"v"}'
    assert art_files(L) == []


def test_a_value_over_the_threshold_spills_and_reads_back(L):
    with L.transaction(by="t") as t:
        t.add("x", "big", BIG)
        t.add("x", "long", BIG_STR)
    text = stored(L, "x", "big")
    assert text.startswith("spill:json:") and len(text) < 100
    _s, tag, h, size = text.split(":")
    assert tag == "json" and int(size) > DEFAULT_THRESHOLD and L._store.art.exists(h)
    assert stored(L, "x", "long").startswith("spill:str:")
    head = L.at()
    assert head["x", "big"] == BIG and head.get("x", "big") == BIG and head["x", "long"] == BIG_STR


def test_identical_bytes_are_stored_once(L):
    with L.transaction(by="t") as t:
        t.add("a", "big", BIG)
    with L.transaction(by="t") as t:
        t.add("b", "big", BIG)
        t.add("c", "other", BIG)
    assert stored(L, "a", "big") == stored(L, "b", "big") == stored(L, "c", "other")
    assert len(art_files(L)) == 1


def test_over_max_fact_is_refused_naming_size_limit_and_ledger_and_writes_nothing(L):
    setting(L, MAX_FACT, 1000)
    top = L._store.top()
    value = "z" * 2000
    with pytest.raises(FactTooLarge, match=rf"2004 bytes.*{L._store.name}.*1000 bytes"):
        with L.transaction(by="t") as t:
            t.add("x", "ok", "fine")
            t.add("x", "huge", value)
    assert L._store.top() == top and L.at().get("x", "ok") is None and art_files(L) == []


def test_max_fact_at_or_under_the_threshold_never_spills(L):
    setting(L, SPILL_THRESHOLD, 500)
    setting(L, MAX_FACT, 500)
    with L.transaction(by="t") as t:
        t.add("x", "at", "q" * 496)                  # 500 bytes: inline
    assert stored(L, "x", "at") == "str:" + "q" * 496
    with pytest.raises(FactTooLarge):
        with L.transaction(by="t") as t:
            t.add("x", "over", "q" * 497)            # 501 bytes: over both, refused, never spilled
    setting(L, MAX_FACT, 300)                        # under the threshold: the same
    with pytest.raises(FactTooLarge):
        with L.transaction(by="t") as t:
            t.add("x", "mid", "q" * 400)
    assert art_files(L) == []


def test_reads_that_list_return_the_reference_and_fetch_nothing(L, opens):
    with L.transaction(by="t") as t:
        t.add("game/G1", "big", BIG)
        t.add("game/G1", "team", "home")
    head = L.at()
    (got,) = head.all("game/G1", "big")
    assert isinstance(got, Spilled) and got.tag == "json" and got.size > DEFAULT_THRESHOLD
    assert got.hash == stored(L, "game/G1", "big").split(":")[2]
    assert isinstance(head["game/G1"]["big"], Spilled)
    assert isinstance(head.all("game/*", "big")[0][1], Spilled)
    assert isinstance(head.select(("big", "team"), s="game/*")[0][0], Spilled)
    assert isinstance(head.history("game/G1", "big")[0].object, Spilled)
    assert opens == []
    assert got.load() == BIG and len(opens) == 1


def test_a_query_matches_a_spilled_value_only_whole_by_hash_without_fetching(L, opens):
    with L.transaction(by="t") as t:
        t.add("game/G1", "big", BIG)
        t.add("game/G2", "big", {"other": 1})
    head = L.at()
    assert [r.subject for r in head.refs(where={"big": BIG})] == ["game/G1"]
    assert [r.subject for r in head.refs(big=BIG)] == ["game/G1"]
    assert ("game/G1", "big", BIG) in head and head["game/G1", "big", BIG] == head
    assert head.refs(where={"big": {"rows": []}}) == []
    assert opens == []


def test_remove_and_record_writes_find_a_spilled_value(L):
    with L.transaction(by="t") as t:
        t.add("x", "big", BIG)
    with L.transaction(by="t") as t:
        t.remove("x", "big", BIG)
    assert L.at().get("x", "big") is None
    setting(L, SPILL_THRESHOLD, 10 ** 9)             # stored inline, then removed under a lower threshold
    with L.transaction(by="t") as t:
        t.add("y", "big", BIG)
    assert stored(L, "y", "big").startswith("json:")
    setting(L, SPILL_THRESHOLD, DEFAULT_THRESHOLD)
    with L.transaction(by="t") as t:
        t.remove("y", "big", BIG)
    assert L.at().get("y", "big") is None
    with L.transaction(by="t") as t:
        t.add("z", "big", BIG)
    top = L._store.top()
    with L.transaction(by="t", lock=10) as t:
        t["z"] = t.previous_rev["z"]                 # the record rewritten as it is: nothing moves
    assert L.at()["z", "big"] == BIG and L.at()["z", "big", BIG].id == top


def test_transaction_keywords_and_seal_preds_spill(L):
    v = Video(b"frames")
    v.preds["game"] = BIG_STR
    with L.transaction(by="t", why=BIG_STR) as t:
        v.seal(t, name="video/G1")
    assert stored(L, f"db/tx/{L._store.top()}", "why").startswith("spill:str:")
    assert stored(L, v.subject, "game").startswith("spill:str:")
    back = Ref(L.at(), "video/G1")
    assert back.preds["game"] == BIG_STR and isinstance(dict(back.preds.items())["game"], Spilled)
    assert L.at().load("video/G1").preds["game"] == BIG_STR


def test_the_settings_are_checked_at_add(L):
    for s, p, o in (("x", SPILL_THRESHOLD, "1000"), ("db", SPILL_THRESHOLD, "64k"), ("db", MAX_FACT, "-1"),
                    ("db", SPILL_THRESHOLD, str(FLOOR - 1))):
        with pytest.raises(ValueError, match=p):
            with L.transaction(by="t") as t:
                t.add(s, p, o)
    setting(L, MAX_FACT, 0)                          # a ledger of empty facts is legal
    with L.transaction(by="t") as t:
        t.add("db/pred/note", "db/cardinality", "many")       # machinery is never judged


def test_a_copy_carries_a_spilled_pred_and_the_destination_judges_it(tmp_path):
    a, b = Ledger(tmp_path / "a", create=True), Ledger(tmp_path / "b", create=True)
    v = Video(b"frames")
    v.preds["game"] = BIG_STR
    with a.transaction(by="t") as t:
        v.seal(t)
    b.at().copy(v, safe=False)
    h = stored(a, v.subject, "game").split(":")[2]
    assert stored(b, v.subject, "game") == stored(a, v.subject, "game") and b._store.art.exists(h)
    assert Ref(b.at(), v.subject).preds["game"] == BIG_STR
    c = Ledger(tmp_path / "c", create=True)          # it would not spill here: written inline
    setting(c, SPILL_THRESHOLD, 10 ** 9)
    c.at().copy(v, safe=False)
    assert stored(c, v.subject, "game") == "str:" + BIG_STR and art_files(c) == [v.hash]
    d = Ledger(tmp_path / "d", create=True)          # too large here: refused, nothing written
    setting(d, MAX_FACT, 1000)
    top = d._store.top()
    with pytest.raises(FactTooLarge):
        d.at().copy(v, safe=False)
    assert d._store.top() == top


def test_a_spilled_object_read_on_one_ledger_adds_to_another(tmp_path):
    a, b = Ledger(tmp_path / "a", create=True), Ledger(tmp_path / "b", create=True)
    with a.transaction(by="t") as t:
        t.add("x", "big", BIG)
    (got,) = a.at().all("x", "big")
    with b.transaction(by="t") as t:
        t.add("y", "big", got)
    assert b.at()["y", "big"] == BIG and stored(b, "y", "big") == stored(a, "x", "big")


def test_spilled_bytes_go_to_the_values_uri_and_come_back_on_a_miss(L, tmp_path):
    shared = tmp_path / "shared"
    with L.transaction(by="t") as t:
        t.add("db", "db/values", f"file://{shared}")
    with L.transaction(by="t") as t:
        t.add("x", "big", BIG)
    h = stored(L, "x", "big").split(":")[2]
    assert sha256((shared / "sha256" / h[:2] / h).read_bytes()) == h
    L._store.art.path(h).unlink()
    assert L.at()["x", "big"] == BIG and L._store.art.exists(h)
