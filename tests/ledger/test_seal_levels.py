"""``seal=`` on a run and ``v.seal(x)`` on its result (DAT 1028): get, draft, sealed, saved (L or t).

Every run carries its trace on the result, so a draft or a locally sealed result saved later is the
memo entry the memoised run writes, and the next identical call hits."""

import pytest

from dvc_dat.ledger import NotEvaluated, Ref, Value
from ledger_kinds import CALLS
from test_memo import world  # noqa: F401  (the fixture)

KEYS = dict(game="G1")


def fn(L):
    return L.at().ns.load("ledger_kinds.cut")


def entry_rows(L, subject):
    r = L.at()
    return r[subject, "db/fn"], r[subject, "db/keys"], r[subject, "db/provenance"]


def test_get_never_runs(world):
    assert fn(world)(seal="get", **KEYS) is None and CALLS.get("cut", 0) == 0
    saved = fn(world)(**KEYS)
    assert fn(world)(seal="get", **KEYS).subject == saved.subject and CALLS["cut"] == 1


def test_a_draft_keeps_nothing_and_carries_its_trace(world):
    top = world.at().id
    d = fn(world)(seal=False, **KEYS)
    assert not d.sealed and d.subject is None and world.at().id == top
    assert d.dependencies["fn"] == "ledger_kinds.cut" and d.dependencies["code"].startswith("db/code/")
    assert d.dependencies["code/testrepo"] == "abc1234" and "game/G1 home" in d.dependencies
    fn(world)(seal=False, **KEYS)
    assert CALLS["cut"] == 2                                       # recomputes
    assert fn(world)(seal="get", **KEYS) is None


def test_sealed_is_local_and_off_the_ledger(world):
    top = world.at().id
    k = fn(world)(seal=True, **KEYS)
    assert k.sealed and k.subject is None and world.at().id == top and len(k.hash) == 64
    with pytest.raises(TypeError):
        k.preds["game"] = "G9"                                      # frozen
    assert "fn" in k.dependencies
    fn(world)(**KEYS)
    assert CALLS["cut"] == 2                                       # the next call recomputes


def test_saved_to_the_ledger_hits_and_the_default_is_the_fns_ledger(world):
    a = fn(world)(seal=world, **KEYS)
    assert a.subject and entry_rows(world, a.subject) == ("ledger_kinds.cut", {"game": "G1", "version": "1.0.0"},
                                                         "eval:unsandboxed")
    b = fn(world)(**KEYS)
    assert b.subject == a.subject and CALLS["cut"] == 1


def test_saved_into_a_transaction_lands_with_it(world):
    with world.transaction(by="review") as t:
        saved = fn(world)(seal=t, **KEYS)
        assert saved.subject is not None and saved.rev is None    # fixed now; the revision at commit
        t[saved.subject, "status"] = "reviewed"
    r = world.at()
    assert r[saved.subject, "status"] == "reviewed" and r[saved.subject, "db/fn"] == "ledger_kinds.cut"
    assert saved.rev is not None and saved.rev.id == r.id
    assert fn(world)(**KEYS).subject == saved.subject and CALLS["cut"] == 1


def test_an_abandoned_transaction_saves_nothing(world):
    with pytest.raises(RuntimeError):
        with world.transaction(by="t") as t:
            v = fn(world)(seal=t, **KEYS)
            raise RuntimeError("no")
    assert v.subject is None and not v.sealed
    assert fn(world)(seal="get", **KEYS) is None
    v.seal(world)                                                    # the trace survived: save it now
    assert fn(world)(**KEYS).subject == v.subject and CALLS["cut"] == 1


def test_a_draft_sealed_later_to_the_ledger_is_the_memo_entry(world):
    d = fn(world)(seal=False, **KEYS)
    s = d.seal(world)
    assert s == d.subject and entry_rows(world, s)[0] == "ledger_kinds.cut"
    assert world.at()[s, "db/provenance"] == "eval:unsandboxed"
    assert "ledger_kinds.py" in world.at()[d.dependencies["code"], "db/modules"]
    assert fn(world)(**KEYS).subject == s and CALLS["cut"] == 1    # a hit
    assert fn(world)(seal="get", **KEYS).subject == s


def test_the_same_entry_whichever_way_it_was_saved(world):
    d = fn(world)(seal=False, **KEYS)
    s = d.seal(world)
    a = world.at().load(s)
    assert dict(a.dependencies) == dict(d.dependencies)
    assert fn(world)(seal=world, **KEYS).subject == s and CALLS["cut"] == 1


def test_a_draft_sealed_later_into_t_takes_the_name(world):
    d = fn(world)(seal=False, **KEYS)
    with world.transaction(by="t") as t:
        d.seal(t, name="cuts/G1")
    assert Ref(world.at(), "cuts/G1").subject == d.subject and d.name == "cuts/G1"
    assert fn(world)(**KEYS).subject == d.subject and CALLS["cut"] == 1


def test_a_locally_sealed_result_saved_later_hits(world):
    k = fn(world)(seal=True, **KEYS)
    h = k.hash
    with world.transaction(by="t") as t:
        k.seal(t, name="video/G1/clip")
    assert k.hash == h and world.at()[k.subject, "db/sealed-at"] == k.sealed
    assert fn(world)(**KEYS).subject == k.subject and CALLS["cut"] == 1


def test_a_late_save_checks_the_code(world, envbox):
    d = fn(world)(seal=False, **KEYS)
    envbox.code(commit="def5678")                                   # moved on since the run
    with pytest.raises(NotEvaluated, match="ran at testrepo abc1234"):
        d.seal(world)
    envbox.code(commit="abc1234", dirty=True)                      # back, but dirty now
    with pytest.raises(NotEvaluated, match="uncommitted"):
        d.seal(world)
    dirty = fn(world)(seal=False, game="G2")                       # ran dirty
    envbox.code(dirty=False)
    with pytest.raises(NotEvaluated, match="ran on a checkout"):
        dirty.seal(world)
    assert d.subject is None and fn(world)(seal="get", **KEYS) is None
    d.seal(world)                                                  # clean, at the trace's commit
    assert fn(world)(**KEYS).subject == d.subject


def test_seal_false_and_get_on_an_object_are_type_errors(world):
    d = fn(world)(seal=False, **KEYS)
    for x in (False, "get"):
        with pytest.raises(TypeError, match="nothing to do to an object"):
            d.seal(x)
    with pytest.raises(TypeError):
        d.seal(None)


def test_a_bad_seal_value_names_the_accepted_ones(world, tmp_path):
    for x in (None, 1, "yes", "memo"):
        with pytest.raises(ValueError, match="'get', False, True, a Ledger or an open Transaction"):
            fn(world)(seal=x, **KEYS)
    with pytest.raises(TypeError):
        world.at().run("ledger_kinds.cut", memo=True, **KEYS)      # memo is no control option now
    assert CALLS.get("cut", 0) == 0


def test_a_transaction_or_ledger_elsewhere_is_refused(world, tmp_path, backend):
    import backends

    other = backends.make(backend, tmp_path / "other")
    with pytest.raises(ValueError, match="other than the one it was loaded from"):
        fn(world)(seal=other, **KEYS)
    with other.transaction(by="t") as t:
        with pytest.raises(ValueError, match="another ledger"):
            fn(world)(seal=t, **KEYS)
    d = fn(world)(seal=False, **KEYS)
    with pytest.raises(ValueError, match="its memo entry goes there"):
        d.seal(other)


def test_a_run_result_takes_no_hand_deps(world):
    d = fn(world)(seal=False, **KEYS)
    with pytest.raises(TypeError, match="carries its trace"):
        d.seal(provenance="mine")
    with pytest.raises(TypeError, match="carries its trace"):
        d.seal(world, provenance="mine")


def test_a_hand_built_value_seals_as_before(world):
    v = Value.Blob({"x": 1})
    s = v.seal(world)
    r = world.at()
    deps = {p for _s, p, _h in r._held_rows(subject=s) if p.startswith("db/deps/")}
    assert deps == {"db/deps/code/testrepo", "db/deps/platform"}
    assert r.get(s, "db/fn") is None and r[s, "db/provenance"] == "seal"


def test_a_body_sealed_result_is_refused_at_every_saving_level(world):
    f = world.at().ns.load("ledger_kinds.sealed_early")
    for x in (True, world):
        with pytest.raises(TypeError, match="run seals its own"):
            f(seal=x, game="G1")
    with world.transaction(by="t") as t:
        with pytest.raises(TypeError, match="run seals its own"):
            f(seal=t, game="G1")
    assert f(seal=False, game="G1").sealed                         # a draft: returned as the body left it


def test_the_seal_record_of_a_run_result_carries_its_trace(world):
    from dvc_dat.ledger.fn import RunTrace
    from dvc_dat.ledger.kept import Kept

    k = fn(world)(seal=True, **KEYS)
    run = k.__dict__["_run"]
    recs = [e["run"] for e in Kept().listing() if e.get("run")]
    assert [RunTrace.from_record(r) for r in recs] == [run]
