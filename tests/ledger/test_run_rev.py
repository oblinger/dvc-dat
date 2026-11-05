"""SVP 1521: a dat's run function sees the revision it was run against, and a run records every value and run it
reaches through any ``Rev``, on any ledger.

``dat.run_rev`` is ``<ledger>@<rev>`` in the run sub-dat's results; ``dat.at`` the ``Rev`` it names, recording during
the run and plain after; the manager's namespace is at the run's revision, as in the sandbox worker. A read through
a ``Rev`` that records nothing joins the run as a ``foreign:`` item: provenance, never in the hit test.
"""

import pickle

import pytest

import ledger_kinds
from dvc_dat import Dat, DatManager
from dvc_dat.ledger import Ledger, LedgerNamespace, Ref, Rev, Value
from dvc_dat.ledger.codec import ref_text
from dvc_dat.ledger.named import ledger_named, rev_named
from dvc_dat.ledger.trace import FOREIGN, current_run, foreign_of, trace_matches
from dvc_dat.ledger.value import dotted


@pytest.fixture
def world(tmp_path):
    """The default dat world in this test's folder; the one before it restored after."""
    from dvc_dat import core

    before = core._default_manager
    Dat.manager = DatManager(dat_folders=[str(tmp_path / "data")])
    yield Dat.manager
    core._default_manager = before
    if before is not None:
        Dat.manager = before


@pytest.fixture
def games(tmp_path):
    """Another ledger, SQLite, holding two named values and a raw row."""
    other = Ledger(tmp_path / "games", create=True)
    with other.transaction(by="test") as t:
        Value.Blob({"game": 1}).seal(t, name="G1")
        Value.Blob({"mine": True}).seal(t, name="mine")
        t.add("game/G1", "home", "BOS")
    return other


def homed(L):
    with L.transaction(by="test") as t:
        t.add("game/G1", "home", "NYC")
    return L


def foreign(v):
    """``(at, name, ref)`` of each ``foreign:`` item of a value's trace."""
    return sorted((b["at"], b["name"], r) for k, r in v.dependencies.items() if (b := foreign_of(k)) is not None)


# -- dat.run_rev and dat.at ------------------------------------------------------------------------------------

def blob(L, name):
    with L.transaction(by="test") as t:
        Value.Blob({"at": name}).seal(t, name=name)
    return L.at()


SPEC = {"dat": {"do": "ledger_kinds.reads_at", "kwargs": {"name": "seed"}}}


def test_run_rev_names_the_ledger_and_the_revision_beside_run_at(coded, world):
    rev = blob(coded, "seed")
    v = rev.run(SPEC)
    results = v.run.get_results()
    at = Dat.get(results, "dat.run_rev")
    assert at == f"{coded._store.name}@{rev.id}" and Dat.get(results, "dat.run_at")
    assert v.get_results()["out"] == {"at": "seed"} and v.get_results()["rev"] == rev.id


def test_run_rev_is_set_before_the_function_runs_and_outside_the_hash(coded, world):
    rev = blob(coded, "seed")
    v = rev.run(SPEC)
    assert v.get_results()["seen"] == f"{coded._store.name}@{rev.id}"       # read in the body
    assert "run_rev" not in (v.path / "_spec_.yaml").read_text()
    assert "run_rev" not in (v.path / "_result_.yaml").read_text() and "run_rev" in (v.path / "run/_result_.yaml").read_text()
    from dvc_dat.core import _hash_dat

    assert _hash_dat(v.path, v.get_results()) == Dat.get(v.get_results(), "dat.sha256")


def test_dat_at_records_during_the_run_and_is_plain_after(coded, world):
    """A read through ``dat.at`` is a trace item, so a memo hit is sound: moving the name is a miss."""
    rev = blob(coded, "seed")
    v = rev.run(SPEC)
    assert v.get_results()["recording"] is True
    assert "seed db/alias" in v.dependencies and not foreign(v)
    assert isinstance(v.at, Rev) and v.at._rec is None and v.at.id == rev.id and v.at.ledger is coded
    n = ledger_kinds.CALLS.get("reads_at", 0)
    assert rev.run(SPEC).hash == v.hash                                     # a hit: nothing read differs
    moved = blob(coded, "other")
    with coded.transaction(by="test") as t:
        t.add("seed", "db/alias", moved.get("other", "db/alias"))
    assert trace_matches(coded.at(), dict(v.dependencies)) is False
    assert ledger_kinds.CALLS.get("reads_at", 0) == n


def test_dat_at_of_a_draft_and_of_a_loaded_dat(coded, world):
    rev = blob(coded, "seed")
    draft = rev.run(SPEC, seal=False)
    assert draft.at.id == rev.id and draft.at._rec is None
    assert pickle.loads(pickle.dumps(draft)).at.id == rev.id                # the attribute does not pickle; the run names it
    saved = rev.run(SPEC)
    Dat.manager._dat_cache.clear()
    loaded = Ref(coded.at(), saved.subject).load()
    assert loaded.at.id == rev.id and loaded.at.ledger is coded


def test_dat_at_outside_a_ledger_is_refused(world):
    plain = Dat.manager.run({"dat": {"do": "ledger_kinds.build_table", "kwargs": {"n": 2}}})
    assert Dat.get(plain.run.get_results(), "dat.run_rev", None) is None
    with pytest.raises(ValueError, match="ran on no ledger"):
        plain.at


def test_a_nested_plain_dat_is_run_against_the_same_revision(coded, world):
    rev = blob(coded, "seed")
    v = rev.run({"dat": {"do": "ledger_kinds.runs_plain_inside"}})
    assert v.get_results()["inner"] == f"{coded._store.name}@{rev.id}"


def test_rev_named_finds_a_ledger_by_name(games, tmp_path):
    assert ledger_named("games") is games
    r = rev_named("games@1")
    assert r.ledger is games and r.id == 1 and r._rec is None
    with pytest.raises(ValueError):
        rev_named("games")
    with pytest.raises(KeyError):
        rev_named("games@99")


# -- an unsandboxed dat reads names at the pinned revision (fix) -------------------------------------------------

def test_an_unsandboxed_dat_reads_names_at_the_pinned_revision_not_the_head(coded, tmp_path):
    """``fn.py`` ran the dat under ``Dat.manager.ns`` at the head while ``alias_reads`` recorded the pinned
    revision, so the entry claimed a revision its body did not read."""
    from dvc_dat import core

    before = core._default_manager
    Dat.manager = DatManager(dat_folders=[str(tmp_path / "data")], ns=LedgerNamespace(coded))
    try:
        rev = blob(coded, "seed")
        blob(coded, "later")
        assert coded.at().id > rev.id
        v = rev.run({"dat": {"do": "ledger_kinds.reads_mounted"}})
        assert v.get_results()["rev"] == rev.id
        assert Dat.manager.ns.rev().id == coded.at().id                     # after the run: the head again
    finally:
        core._default_manager = before
        if before is not None:
            Dat.manager = before


def test_a_config_namespace_is_bound_to_the_run_whatever_ledger_it_opens(coded, tmp_path):
    from dvc_dat import core

    (tmp_path / ".datconfig.yaml").write_text(f"ledger: {tmp_path / 'other'}\n")
    Ledger(tmp_path / "other", create=True)
    before = core._default_manager
    Dat.manager = DatManager(dat_folders=[str(tmp_path / "data")], ns=LedgerNamespace(config=tmp_path / ".datconfig.yaml"))
    try:
        rev = blob(coded, "seed")
        assert rev.run({"dat": {"do": "ledger_kinds.reads_mounted"}}).get_results()["rev"] == rev.id
    finally:
        core._default_manager = before
        if before is not None:
            Dat.manager = before


# -- the read hook ------------------------------------------------------------------------------------------------

def test_a_read_on_another_ledger_is_an_item_with_ledger_rev_name_and_hash(coded, games):
    rev = homed(coded).at()
    v = rev.run("ledger_kinds.reads_foreign", where=str(games.path), name="G1")
    h = Ref(games.at(), "G1")
    assert foreign(v) == [(f"games@{games.at().id}", "G1", ref_text(h._cls, h.hash))]
    assert "game/G1 home" in v.dependencies                                 # the recording Rev's reads as before
    assert all(k.startswith(FOREIGN) or " " in k or k in ("code", "fn") or k.startswith(("code/", "platform"))
               for k in v.dependencies)


def test_a_foreign_item_survives_the_ledger_and_is_in_no_hit_test(coded, games):
    """Q2 (A): a name moving on another ledger does not invalidate a memo hit."""
    rev = homed(coded).at()
    a = rev.run("ledger_kinds.reads_foreign", where=str(games.path), name="G1")
    n = ledger_kinds.CALLS["reads_foreign"]
    assert trace_matches(coded.at(), dict(a.dependencies)) is True
    with games.transaction(by="test") as t:
        Value.Blob({"game": 2}).seal(t, name="G1")
    again = rev.run("ledger_kinds.reads_foreign", where=str(games.path), name="G1")
    assert again.hash == a.hash and again.subject == a.subject and ledger_kinds.CALLS["reads_foreign"] == n
    loaded = Ref(coded.at(), a.subject).load()
    assert foreign(loaded) == foreign(a)                                    # on the ledger, as rows


def test_a_read_on_the_runs_own_ledger_through_a_plain_rev_is_recorded_too(coded):
    homed(coded)
    with coded.transaction(by="test") as t:
        Value.Blob({"game": 7}).seal(t, name="G7")
    v = coded.at().run("ledger_kinds.reads_foreign", where=str(coded.path), name="G7")
    assert [n for _a, n, _r in foreign(v)] == ["G7"] and "G7 db/alias" not in v.dependencies


def test_raw_triples_on_another_ledger_are_not_tracked(coded, games):
    v = homed(coded).at().run("ledger_kinds.reads_row_only", where=str(games.path))
    assert v.obj == {"home": "BOS"} and foreign(v) == []


def test_a_value_key_loaded_through_its_ref_adds_nothing_but_a_foreign_ref_key_does(coded, games):
    with coded.transaction(by="test") as t:
        Value.Blob({"mine": 1}).seal(t, name="clip")
    v = coded.at().run("ledger_kinds.reads_key", clip=Ref(coded.at(), "clip"))
    assert foreign(v) == []
    w = coded.at().run("ledger_kinds.reads_key", clip=Ref(games.at(), "G1"))
    assert [n for _a, n, _r in foreign(w)] == ["G1"]


def test_a_run_on_another_ledger_is_an_item_and_keeps_its_own_reads(coded, games):
    with coded.transaction(by="test") as t:
        t.add("x", "y", "z")
    with games.transaction(by="test") as t:
        t.add("db/repo/testrepo/ledger_kinds", "db/version", "1.0.0")
        t.add("db/repo/testrepo", "db/commit", "abc1234")
    v = coded.at().run("ledger_kinds.runs_foreign", where=str(games.path), n=4)
    [(at, name, ref)] = foreign(v)
    assert at.startswith("games@") and name.startswith("eval:ledger_kinds.doubled{")
    inner = games.at().run("ledger_kinds.doubled", n=4)
    assert ref == ref_text(dotted(type(inner)), inner.hash) and inner.obj == {"n": 8}


def test_nested_runs_each_see_their_own_reads(coded, games):
    rev = homed(coded).at()
    v = rev.run("ledger_kinds.reads_foreign_nested", where=str(games.path), name="G1")
    assert [n for _a, n, _r in foreign(v)] == ["mine"]
    inner = rev.run("ledger_kinds.reads_foreign", where=str(games.path), name="G1")
    assert [n for _a, n, _r in foreign(inner)] == ["G1"]
    assert any(k.startswith("eval:ledger_kinds.reads_foreign{") for k in v.dependencies)


def test_a_thread_the_body_started_reads_for_the_run(coded, games):
    v = homed(coded).at().run("ledger_kinds.reads_foreign_in_threads", where=str(games.path), name="G1")
    assert v.obj == {"seen": {"game": 1}} and [n for _a, n, _r in foreign(v)] == ["G1"]


def test_outside_a_run_nothing_is_recorded(games):
    assert current_run() is None
    assert games.at().load("G1").obj == {"game": 1}
    assert current_run() is None


def test_a_memo_hit_inside_a_run_is_not_a_foreign_read(coded, envbox):
    """The ledger's own reads (a nested hit, a seal) go through ``Ref._load``: only the ``eval:`` item."""
    rev = homed(coded).at()
    rev.run("ledger_kinds.doubled", n=3)
    v = coded.at().run("ledger_kinds.calls_doubled", n=3)
    assert foreign(v) == [] and any(k.startswith("eval:ledger_kinds.doubled{") for k in v.dependencies)


def test_a_foreign_item_never_reads_as_a_row(coded):
    assert foreign_of('foreign:{"at":"a@1","name":"b"}') == {"at": "a@1", "name": "b"}
    assert foreign_of('foreign:{"at":"a@1","name":"b"} home') is None
    assert foreign_of("foreign:x y") is None
    with coded.transaction(by="test") as t:
        t.add("foreign:x", "y", "z")
    assert trace_matches(coded.at(), {"foreign:x y": "w"}) is False         # a row read, judged as one
