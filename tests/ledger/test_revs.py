"""SVP 245: present code over past revisions. ``L.revs`` names a set of revisions by label; ``rev.run`` at each is
today's run; the result's ``db/at`` row, ``v.at``, is the revision it read, ``v.rev`` the one that saved it.

The sweep runs over a tiny repo ``revrepo`` (package ``revpkg``), a counting function in it, the environment reporting
the checkout live, so an edit and a commit of the module is a change of code."""

import importlib
import subprocess
import sys
from types import SimpleNamespace

import pytest

import backends
import dvc_dat.ledger.txn as txn_mod
import ledger_kinds
from dvc_dat.ledger import Exists, Ledger, NotClean, Rev, Value, bump, set_env_provider
from dvc_dat.ledger.env import Env, code_at
from dvc_dat.ledger.ledger import period_starts

METRIC = '''
import ledger_kinds
from dvc_dat import dat


@dat.fn
def rate(rev, *, game: str) -> float:
    ledger_kinds.CALLS["rate"] = ledger_kinds.CALLS.get("rate", 0) + 1
    return int(rev[f"game/{game}", "shots"]) / 2
'''


def stamped(L, monkeypatch, stamps):
    """One revision per stamp, stamped so; the row ``x a <i>`` in each."""
    for i, s in enumerate(stamps):
        monkeypatch.setattr(txn_mod, "stamp", lambda s=s: s)
        with L.transaction(by="t") as t:
            t.add("x", "a", str(i))


def ids(found):
    return {label: rev.id for label, rev in found.items()}


# -- L.revs ----------------------------------------------------------------------------------------------------

MONTHS = ["2026-01-10T12:00:00Z",       # rev 1
          "2026-02-10T12:00:00Z",       # rev 2
          "2026-02-20T12:00:00Z",       # rev 3
          "2026-04-10T12:00:00Z"]       # rev 4


def test_revs_a_month_is_the_latest_revision_stamped_at_or_before_its_start(L, monkeypatch):
    stamped(L, monkeypatch, MONTHS)
    found = L.revs("month")
    assert ids(found) == {"2026-02": 1, "2026-03": 3, "2026-04": 3}         # 2026-01 starts before the first stamp
    assert all(type(r) is Rev for r in found.values())
    assert found["2026-03"].id == L.at("2026-03-01").id


def test_revs_a_span_names_periods_and_omits_those_before_the_first_stamp(L, monkeypatch):
    stamped(L, monkeypatch, MONTHS)
    assert ids(L.revs("month", since="2025-11", until="2026-03")) == {"2026-02": 1, "2026-03": 3}
    assert ids(L.revs("month", since="2025-11-01", until="2026-03-01")) == {"2026-02": 1, "2026-03": 3}


def test_revs_a_bound_may_be_any_at_argument(L, monkeypatch):
    stamped(L, monkeypatch, MONTHS)
    with L.transaction(by="t") as t:
        t.add("db", "db/tag", "mark")
    assert ids(L.revs([1, 2, 3, 4], since=2, until="3")) == {"2": 2, "3": 3}
    assert ids(L.revs([1, 2, 3, 4], since="2026-02-15")) == {"3": 3, "4": 4}
    assert ids(L.revs([1, 2, 3, 4], until="2026-02-15")) == {"1": 1, "2": 2}
    assert ids(L.revs([1, 5], since="mark")) == {"5": 5}
    assert ids(L.revs("month", since=2, until=3)) == {}                     # a revision bounds by its stamp
    assert ids(L.revs("month", since=1, until=3)) == {"2026-02": 1}


def test_revs_day_and_week(L, monkeypatch):
    stamped(L, monkeypatch, ["2026-11-02T06:00:00Z", "2026-11-03T06:00:00Z", "2026-11-10T06:00:00Z"])
    assert ids(L.revs("day", until="2026-11-05")) == {"2026-11-03": 1, "2026-11-04": 2, "2026-11-05": 2}
    assert ids(L.revs("week")) == {"2026-W46": 2}                           # Monday 2026-11-09; W45's is before rev 1


@pytest.mark.parametrize("zone,expected", [
    (None, {"2026-11": 1, "2026-12": 1, "2027-01": 2}),
    ("America/Los_Angeles", {"2026-11": 1, "2026-12": 2, "2027-01": 2}),     # Dec 1 starts at 08:00Z there
])
def test_revs_periods_read_the_display_zone(L, monkeypatch, zone, expected):
    stamps = ["2026-11-01T00:00:00Z", "2026-12-01T06:00:00Z", "2027-01-02T00:00:00Z"]
    for i, s in enumerate(stamps):
        monkeypatch.setattr(txn_mod, "stamp", lambda s=s: s)
        with L.transaction(by="t") as t:
            t.add("x", "a", str(i))
            if zone is not None and i == len(stamps) - 1:
                t.add("db", "db/timezone", zone)
    assert ids(L.revs("month")) == expected


def test_revs_release_and_tag_one_per_add_labelled_by_it(L):
    with L.transaction(by="t", lock=10) as t:
        bump(t, "db")
    with L.transaction(by="t") as t:
        t.add("x", "a", "1")
        t.add("db", "db/tag", "first")
    with L.transaction(by="t", lock=10) as t:
        bump(t, "db", "minor", confirm=lambda old, new: True)
        t.add("db", "db/tag", "second")
    releases = L.revs("release")
    assert len(releases) == 2 and [L.at(v).id for v in releases] == [r.id for r in releases.values()]
    assert ids(L.revs("tag")) == {"first": L.at("first").id, "second": L.at("second").id}
    assert ids(L.revs("tag", until=L.at("first").id)) == {"first": L.at("first").id}
    last = list(releases)[-1]
    assert list(L.revs("release", since=releases[last].id)) == [last]


def test_revs_an_iterable_of_at_arguments_keeps_its_order_and_may_share_a_revision(L, monkeypatch):
    stamped(L, monkeypatch, MONTHS)
    assert ids(L.revs([3, "2026-02-15", "1"])) == {"3": 3, "2026-02-15": 2, "1": 1}
    assert ids(L.revs(iter([2, "2"]))) == {"2": 2}
    assert ids(L.revs([2, "2026-02-15"])) == {"2": 2, "2026-02-15": 2}
    with pytest.raises(KeyError):
        L.revs([99])


@pytest.mark.parametrize("which", ["2026-11", "quarter", b"tag", 7, None])
def test_revs_refuses_any_other_selector(L, which):
    with pytest.raises(TypeError, match="iterable of at arguments"):
        L.revs(which)


def test_revs_on_a_ledger_with_nothing_stamped_or_tagged(tmp_path):
    L = Ledger(tmp_path / "empty", create=True)
    assert L.revs("month") == {} and L.revs("release") == {} and L.revs("tag") == {}


def test_revs_writes_nothing(L, monkeypatch):
    stamped(L, monkeypatch, MONTHS)
    top = L.at().id
    L.revs("month")
    assert L.at().id == top


def test_period_starts_cross_a_year():
    import datetime as dt

    assert list(period_starts("month", dt.date(2025, 12, 31), dt.date(2026, 2, 1))) == [
        ("2025-12", dt.date(2025, 12, 1)), ("2026-01", dt.date(2026, 1, 1)), ("2026-02", dt.date(2026, 2, 1))]
    assert [w for w, _d in period_starts("week", dt.date(2026, 12, 30), dt.date(2027, 1, 5))] == ["2026-W53", "2027-W01"]


# -- db/at and v.at --------------------------------------------------------------------------------------------

@pytest.fixture
def world(tmp_path, monkeypatch, backend):
    repo = tmp_path / "revrepo"
    (repo / "revpkg").mkdir(parents=True)
    (repo / "revpkg/__init__.py").write_text('__version__ = "1.0.0"\n')
    (repo / "revpkg/metric.py").write_text(METRIC)
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main"]
    run = lambda *a: subprocess.run([*git, *a], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()   # noqa: E731
    run("init", "-q")
    run("add", ".")
    run("commit", "-q", "-m", "one")
    monkeypatch.syspath_prepend(str(repo))
    for m in [m for m in sys.modules if m == "revpkg" or m.startswith("revpkg.")]:
        del sys.modules[m]
    import revpkg.metric
    old = set_env_provider(lambda: Env({"revrepo": code_at(str(repo))}, "test-platform"))
    L = backends.make(backend, tmp_path / "ledger")
    for shots in ("10", "10", "20"):                          # revs 1, 2, 3: the row moves once (set twice is one row)
        with L.transaction(by="t") as t:
            t["game/G1", "shots"] = shots
    ledger_kinds.CALLS.clear()
    yield SimpleNamespace(L=L, repo=repo, git=run, module=revpkg.metric)
    set_env_provider(old)


def sweep(w, **keys):
    return {label: rev.run("revpkg.metric.rate", **keys) for label, rev in w.L.revs([1, 2, 3]).items()}


def test_a_sweep_runs_once_per_distinct_read_set_and_hits_the_second_time(world):
    first = sweep(world, game="G1")
    assert {k: v.obj for k, v in first.items()} == {"1": 5.0, "2": 5.0, "3": 10.0}
    assert ledger_kinds.CALLS["rate"] == 2                          # rev 2 read what rev 1 read
    assert first["1"].at.id == 1 and first["3"].at.id == 3
    assert first["2"].at.id == 1 and first["2"].subject == first["1"].subject   # the entry computed at 1
    assert first["1"].rev.id > 3 and first["3"].rev.id > first["1"].rev.id      # sealed at the top, not where it read
    top = world.L.at().id
    again = sweep(world, game="G1")
    assert ledger_kinds.CALLS["rate"] == 2 and world.L.at().id == top
    assert {k: (v.subject, v.at.id) for k, v in again.items()} == {k: (v.subject, v.at.id) for k, v in first.items()}


def test_the_row_is_read_back_and_stays_out_of_the_subject_and_the_trace(world):
    v = world.L.at(1).run("revpkg.metric.rate", game="G1")
    top = world.L.at()
    assert top[v.subject, "db/at"] == "1" and "db/at" not in " ".join(v.dependencies)
    world.L._values.clear()
    assert top.load(v.subject).at.id == 1 and v.matches(world.L.at(2))
    assert top.load(v.subject).at.ledger is world.L


def test_a_changed_module_misses_and_the_first_entry_stays(world):
    old = sweep(world, game="G1")
    (world.repo / "revpkg/metric.py").write_text(METRIC.replace("/ 2", "/ 4.0"))
    world.git("commit", "-q", "-am", "two")
    importlib.reload(world.module)
    new = sweep(world, game="G1")
    assert ledger_kinds.CALLS["rate"] == 4
    assert new["1"].obj == 2.5 and new["1"].subject != old["1"].subject and new["1"].at.id == 1
    assert world.L.at().load(old["1"].subject).obj == 5.0


def test_clean_at_an_old_revision_still_refuses(world):
    sweep(world, game="G1")                     # the first clean run writes the clock, after rev 1
    with pytest.raises(NotClean, match="rev 1 names no db/repo/revrepo db/commit"):
        world.L.at(1).run("revpkg.metric.rate", game="G1", clean=True)
    world.L.at().run("revpkg.metric.rate", game="G1", clean=True)   # at the top the checkout is the row's commit
    (world.repo / "revpkg/metric.py").write_text(METRIC + "# two\n")
    world.git("commit", "-q", "-am", "two")
    with pytest.raises(NotClean, match="the checkout is at"):
        world.L.at(world.L.at().id).run("revpkg.metric.rate", game="G1", clean=True)


def test_a_draft_carries_it_and_a_late_save_writes_it(world):
    draft = world.L.at(1).run("revpkg.metric.rate", game="G1", seal=False)
    assert draft.rev is None and draft.at.id == 1 and draft.at.ledger is world.L
    world.L.at().run("revpkg.metric.rate", game="G1", seal=False)
    draft.seal(world.L)
    assert draft.rev is not None and draft.at.id == 1
    assert world.L.at()[draft.subject, "db/at"] == "1"


def test_a_local_seal_carries_it_across_the_seal_record(world):
    local = world.L.at(1).run("revpkg.metric.rate", game="G1", seal=True)
    assert local.subject is None and local.at.id == 1
    local.seal(world.L)
    assert world.L.at()[local.subject, "db/at"] == "1"


def test_a_draft_of_a_held_entry_reads_the_row_it_found(world):
    """The subject hashes no revision: the 2nd save of a data-identical run writes nothing, and ``at`` says the row."""
    world.L.at(1).run("revpkg.metric.rate", game="G1")
    draft = world.L.at(2).run("revpkg.metric.rate", game="G1", seal=False)
    assert draft.at.id == 2
    draft.seal(world.L)
    assert draft.at.id == 1


def test_a_seal_into_a_transaction_has_at_before_and_after_commit(world):
    with world.L.transaction(by="t") as t:
        v = world.L.at(1).run("revpkg.metric.rate", game="G1", seal=t)
        assert v.rev is None and v.at.id == 1
    assert v.rev is not None and v.at.id == 1


def test_a_hand_seal_has_none(world):
    v = Value.Blob({"a": 1})
    assert v.at is None
    v.seal(world.L)
    assert v.at is None and world.L.at().load(v.subject).at is None


def test_the_row_cannot_be_retracted(world):
    v = world.L.at(1).run("revpkg.metric.rate", game="G1")
    with pytest.raises(Exists, match="is sealed: 'db/at'"):
        with world.L.transaction(by="t") as t:
            t.remove(v.subject, "db/at", "1")


def test_last_rev_is_the_last_row_of_a_pattern_removes_included(tmp_path):
    """SVP 1521 A2: the revision of the last matching row at or before the view, as ``history`` gives it."""
    from dvc_dat.ledger import Ledger

    L = Ledger(tmp_path / "led", create=True)
    with L.transaction(by="t") as t:
        t.add("game/G1", "home", "A")
    one = L.at().id
    with L.transaction(by="t") as t:
        t.add("game/G2", "home", "B")
    with L.transaction(by="t") as t:
        t.add("game/G1", "away", "C")
    three = L.at().id
    with L.transaction(by="t") as t:
        t.remove("game/G1", "home", "A")
    four = L.at().id
    with L.transaction(by="t") as t:
        t.add("other", "x", "y")
    assert L.at().last_rev("game/G1").id == four                   # a remove is a row
    assert L.at(three).last_rev("game/G1").id == three             # bounded by the view, not the top
    assert L.at(three).last_rev("game/G1", "home").id == one       # the same pattern rules as get
    assert L.at().last_rev("game/G1", "home", "A").id == four
    assert L.at().last_rev("game/*").id == four                    # a glob
    assert L.at().last_rev("game/G1").id == L.at().history("game/G1")[-1].rev.id
    assert L.at(one).last_rev("game/G2") is None
    assert L.at(one).last_rev("game/G2", default=7) == 7
    assert L.at(three).last_rev("game/G1", since=L.at(three)) is None
    assert type(L.at().last_rev("game/G1")).__name__ == "Rev" and L.at().last_rev("game/G1").ledger is L
