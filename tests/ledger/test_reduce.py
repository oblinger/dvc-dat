"""``rev.reduce`` (SVP 242): a reduce function over a set of inputs, each step a memo entry keyed by the sorted set,
the next ask reusing the largest subset already reduced."""

import subprocess
import sys
import textwrap

import backends
import pytest

import ledger_kinds
from dvc_dat.ledger import Value, set_env_provider
from dvc_dat.ledger.sandbox import shutdown
from ledger_kinds import CALLS, STEPS

COUNT = "ledger_kinds.count"


@pytest.fixture
def world(coded):
    CALLS.clear()
    STEPS.clear()
    return coded


def steps():
    return CALLS.get("count", 0)


def test_five_then_six_is_one_step_over_the_extra_and_matches_fresh(world):
    rev = world.at()
    five = rev.reduce(COUNT, over=list("abcde"))
    assert steps() == 1 and STEPS[-1] == list("abcde") and five.obj == dict.fromkeys("abcde", 1)
    six = world.at().reduce(COUNT, over=list("fabcde"))
    assert steps() == 2 and STEPS[-1] == ["f"]
    top = world.at()
    assert top[six.subject, "db/reduce/from"] == five.subject and top[six.subject, "db/reduce/more"] == ["f"]
    assert top[five.subject, "db/reduce/from"] == "none" and top[five.subject, "db/reduce/more"] == list("abcde")
    assert top[six.subject, "db/keys"] == {"over": list("abcdef"), "tag": "t"}
    assert top[top.tx, "db/by"] == f"reduce:{COUNT}"
    again = world.at().reduce(COUNT, over=list("abcdef"))               # an exact hit: nothing runs
    assert steps() == 2 and again.subject == six.subject
    fresh = world.at().reduce(COUNT, over=list("abcdef"), fresh=True)
    assert steps() == 3 and STEPS[-1] == list("abcdef") and world.at()[fresh.subject, "db/reduce/from"] == "none"
    assert fresh.same_as(six)


def test_a_function_breaking_the_law_differs_from_fresh(world):
    world.at().reduce("ledger_kinds.count_calls", over=list("abcde"))
    six = world.at().reduce("ledger_kinds.count_calls", over=list("fabcde"))
    fresh = world.at().reduce("ledger_kinds.count_calls", over=list("abcdef"), fresh=True)
    assert six.obj["calls"] == 2 and fresh.obj["calls"] == 1 and not fresh.same_as(six)


def test_order_is_no_second_entry(world):
    a = world.at().reduce(COUNT, over=list("abc"))
    b = world.at().reduce(COUNT, over=("c", "a", "b"))
    assert b.subject == a.subject and steps() == 1


def test_the_largest_subset_wins_and_a_removed_input_is_a_hit(world):
    world.at().reduce(COUNT, over=list("ab"))
    abc = world.at().reduce(COUNT, over=list("abc"))
    world.at().reduce(COUNT, over=list("ad"))                          # no subset of abcd larger than abc
    abcd = world.at().reduce(COUNT, over=list("abcd"))
    assert STEPS[-1] == ["d"] and world.at()[abcd.subject, "db/reduce/from"] == abc.subject
    n = steps()
    assert world.at().reduce(COUNT, over=list("abc")).subject == abc.subject and steps() == n
    other = world.at().reduce(COUNT, over=list("abcd"), tag="u")        # another key: its own chain
    assert STEPS[-1] == list("abcd") and other.subject != abcd.subject


def test_seal_get_never_runs(world):
    assert world.at().reduce(COUNT, over=list("ab"), seal="get") is None and steps() == 0
    ab = world.at().reduce(COUNT, over=list("ab"))
    assert world.at().reduce(COUNT, over=list("ba"), seal="get").subject == ab.subject
    assert world.at().reduce(COUNT, over=list("abc"), seal="get") is None and steps() == 1


def test_a_draft_carries_its_step_to_a_later_seal(world):
    ab = world.at().reduce(COUNT, over=list("ab"))
    draft = world.at().reduce(COUNT, over=list("abc"), seal=False)
    assert STEPS[-1] == ["c"] and not draft.sealed and draft.subject is None
    draft.seal(world)
    top = world.at()
    assert top[draft.subject, "db/reduce/from"] == ab.subject and top[draft.subject, "db/reduce/more"] == ["c"]
    n = steps()
    assert world.at().reduce(COUNT, over=list("abc")).subject == draft.subject and steps() == n


def test_values_and_refs_are_inputs_by_their_bytes(world):
    with world.transaction(by="t") as t:
        for g in ("G1", "G2", "G3"):
            Value.Blob({"game": g}).seal(t, name=f"games/{g}")
    rev = world.at()
    g1, g2 = rev.load("games/G1"), rev.load("games/G2")
    two = rev.reduce(COUNT, over=[g1, g2])
    assert two.obj == {"G1": 1, "G2": 1}
    assert sorted(k.rpartition(":")[2] for k in two.dependencies if k.startswith("ref:")) == sorted([g1.hash, g2.hash])
    from dvc_dat.ledger import Ref

    three = world.at().reduce(COUNT, over=[Ref(world.at(), "games/G3"), g2, g1])
    assert STEPS[-1] == ["G3"] and world.at()[three.subject, "db/reduce/from"] == two.subject
    g3 = world.at().load("games/G3")
    refs = sorted(k.rpartition(":")[2] for k in three.dependencies if k.startswith("ref:"))
    assert refs == sorted([g1.hash, g2.hash, g3.hash, two.hash])        # acc, G3, and acc's own inputs
    with world.transaction(by="t") as t:
        Value.Blob({"game": "G3", "v": 2}).seal(t, name="games/G3")       # new bytes: a new identity
    world.at().reduce(COUNT, over=[Ref(world.at(), "games/G3"), g2, g1])
    assert STEPS[-1] == ["G3"]                                           # {G1, G2} still the largest subset


def test_an_early_inputs_read_moving_fails_every_step_built_over_it(world):
    with world.transaction(by="t", lock=10) as t:
        for g, n in (("a", "1"), ("b", "2"), ("c", "3")):
            t[f"game/{g}"] = {"n": n}
    ab = world.at().reduce("ledger_kinds.tally", over=["a", "b"])
    abc = world.at().reduce("ledger_kinds.tally", over=["a", "b", "c"])
    assert world.at()[abc.subject, "db/reduce/from"] == ab.subject and abc.dependencies["game/a n"] == "1"
    with world.transaction(by="t", lock=10) as t:
        t["game/c"] = {"n": "30"}
    moved_c = world.at().reduce("ledger_kinds.tally", over=["a", "b", "c"])
    assert moved_c.obj == {"a": "1", "b": "2", "c": "30"} and world.at()[moved_c.subject, "db/reduce/from"] == ab.subject
    with world.transaction(by="t", lock=10) as t:
        t["game/a"] = {"n": "10"}
    n = CALLS["tally"]
    moved_a = world.at().reduce("ledger_kinds.tally", over=["a", "b", "c"])        # a was in acc, two steps down
    assert CALLS["tally"] == n + 1 and moved_a.obj == {"a": "10", "b": "2", "c": "30"}
    assert world.at()[moved_a.subject, "db/reduce/from"] == "none"


def test_refusals(world):
    with pytest.raises(ValueError, match="twice"):
        world.at().reduce(COUNT, over=["a", "b", "a"])
    with pytest.raises(TypeError, match="reserved"):
        world.at().reduce(COUNT, over=["a"], more=["b"])
    with pytest.raises(TypeError, match="sequence"):
        world.at().reduce(COUNT, over="abc")
    with pytest.raises(TypeError, match="reduce function"):
        world.at().run(COUNT, acc=None, more=["a"])
    with pytest.raises(TypeError, match="acc and more"):
        world.at().reduce("ledger_kinds.cut", over=["G1"])
    with pytest.raises(TypeError):
        world.at().reduce(COUNT, over=["a"], nope=1)
    assert steps() == 0


def test_a_body_that_reduces_records_the_ask_and_a_grown_set_misses(world):
    a = world.at().run("ledger_kinds.counts_inside", games=["a", "b"])
    item = 'eval:ledger_kinds.count{"over":["a","b"],"tag":"t"}'
    assert a.dependencies[item].startswith("ref:") and a.matches(world.at())
    assert world.at().run("ledger_kinds.counts_inside", games=["b", "a"]).obj == {"n": 2}
    b = world.at().run("ledger_kinds.counts_inside", games=["a", "b", "c"])
    assert b.obj == {"n": 3} and STEPS[-1] == ["c"]


def test_the_code_commit_moving_reduces_from_scratch_and_old_entries_stay(world, envbox):
    five = world.at().reduce(COUNT, over=list("abcde"))
    old = world.at()
    envbox.code(commit="def5678")
    six = world.at().reduce(COUNT, over=list("abcdef"))
    assert STEPS[-1] == list("abcdef") and world.at()[six.subject, "db/reduce/from"] == "none"
    assert old.load(five.subject).obj == dict.fromkeys("abcde", 1)


# -- sandboxed: a mounted reduce in a real checkout --------------------------------------------------------------

REDUCER = textwrap.dedent('''
    from dvc_dat import dat

    @dat.fn
    def total(rev, *, acc, more: list) -> dict:
        out = dict(acc.obj) if acc is not None else {"steps": []}
        out["steps"] = out["steps"] + [sorted(x if isinstance(x, str) else x.obj["game"] for x in more)]
        for x in more:
            name = x if isinstance(x, str) else x.obj["game"]
            out[name] = 1
        return out
''')


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def red(tmp_path, monkeypatch, backend):
    repo = tmp_path / "red-repo"
    (repo / "red").mkdir(parents=True)
    (repo / "pyproject.toml").write_text('[project]\nname = "red-repo"\nversion = "0.1.0"\n')
    (repo / "red/__init__.py").write_text("")
    (repo / "red/fns.py").write_text(REDUCER)
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "one")
    monkeypatch.syspath_prepend(str(repo))
    for m in [m for m in sys.modules if m == "red" or m.startswith("red.")]:
        del sys.modules[m]
    import red  # noqa: F401  (discovery sees the checkout)
    old = set_env_provider(None)
    L = backends.make(backend, tmp_path / "ledger")
    with L.transaction(by="t") as t:
        t.add("db/mount/red", "db/root", "red")
        t.add("db/mount/red", "db/repo", "red-repo")
    yield L, repo
    shutdown()
    set_env_provider(old)


def test_a_mounted_reduce_runs_in_the_worker_and_an_edit_reduces_from_scratch(red):
    L, repo = red
    five = L.at().reduce("mnt.red.fns.total", over=list("abcde"))
    assert five.obj["steps"] == [list("abcde")] and L.at()[five.subject, "db/provenance"] == "eval:sandbox"
    with L.transaction(by="t") as t:
        Value.Blob({"game": "G1"}).seal(t, name="games/G1")
    g1 = L.at().load("games/G1")
    six = L.at().reduce("mnt.red.fns.total", over=[*"abcde", g1])
    assert six.obj["steps"] == [list("abcde"), ["G1"]] and L.at()[six.subject, "db/reduce/from"] == five.subject
    draft = L.at().reduce("mnt.red.fns.total", over=list("abcdef"), seal=False)
    assert draft.obj["steps"] == [list("abcde"), ["f"]]
    old = L.at()
    (repo / "red/fns.py").write_text(REDUCER + "\nX = 1\n")              # the module edited
    again = L.at().reduce("mnt.red.fns.total", over=[*"abcde", g1])
    assert again.obj["steps"] == [["G1", "a", "b", "c", "d", "e"]] and L.at()[again.subject, "db/reduce/from"] == "none"
    assert old.load(six.subject).obj["steps"] == [list("abcde"), ["G1"]]
    assert L.at().reduce("mnt.red.fns.total", over=[*"abcde", g1], seal="get").subject == again.subject
