"""``rev.reduce``: a ``@dat.reduce_fn`` over a set of inputs, each step a memo entry keyed by the sorted set,
the next ask merging the results of disjoint subsets already reduced (``accs``) and adding the rest (``more``)."""

import subprocess
import sys
import textwrap

import backends
import pytest

import ledger_kinds
from dvc_dat import dat
from dvc_dat.ledger import Value, set_env_provider
from dvc_dat.ledger.fn import reduce_sources
from dvc_dat.ledger.recipes import reduced_from
from dvc_dat.ledger.sandbox import shutdown
from ledger_kinds import CALLS, MERGED, STEPS

COUNT = "ledger_kinds.count"


@pytest.fixture
def world(coded):
    CALLS.clear()
    STEPS.clear()
    MERGED.clear()
    return coded


def steps():
    return CALLS.get("count", 0)


def test_five_then_six_is_one_step_over_the_extra_and_matches_fresh(world):
    rev = world.at()
    five = rev.reduce(COUNT, over=list("abcde"))
    assert steps() == 1 and STEPS[-1] == list("abcde") and MERGED[-1] == [] and five.obj == dict.fromkeys("abcde", 1)
    six = world.at().reduce(COUNT, over=list("fabcde"))
    assert steps() == 2 and STEPS[-1] == ["f"] and MERGED[-1] == [list("abcde")]
    top = world.at()
    assert top[six.subject, "db/reduce/from"] == [five.subject] and top[six.subject, "db/reduce/more"] == ["f"]
    assert top[five.subject, "db/reduce/from"] == [] and top[five.subject, "db/reduce/more"] == list("abcde")
    assert top[six.subject, "db/keys"] == {"over": list("abcdef"), "tag": "t"}
    assert top[top.tx, "db/by"] == f"reduce:{COUNT}"
    again = world.at().reduce(COUNT, over=list("abcdef"))               # an exact hit: nothing runs
    assert steps() == 2 and again.subject == six.subject
    fresh = world.at().reduce(COUNT, over=list("abcdef"), fresh=True)
    assert steps() == 3 and STEPS[-1] == list("abcdef") and MERGED[-1] == []
    assert world.at()[fresh.subject, "db/reduce/from"] == []
    assert fresh.same_as(six)


def test_two_disjoint_partials_merge_in_one_step_with_more_empty_and_match_fresh(world):
    ab = world.at().reduce(COUNT, over=["a", "b"])
    cd = world.at().reduce(COUNT, over=["c", "d"])
    both = world.at().reduce(COUNT, over=list("dcba"))
    assert steps() == 3 and STEPS[-1] == [] and MERGED[-1] == [["c", "d"], ["a", "b"]]     # a tie: newest first
    top = world.at()
    assert top[both.subject, "db/reduce/from"] == sorted([ab.subject, cd.subject])
    assert top[both.subject, "db/reduce/more"] == []
    assert sorted(k.rpartition(":")[2] for k in both.dependencies if k.startswith("ref:")) == sorted([ab.hash, cd.hash])
    fresh = world.at().reduce(COUNT, over=list("abcd"), fresh=True)
    assert STEPS[-1] == list("abcd") and fresh.same_as(both) and fresh.hash == both.hash


def test_two_partials_plus_extras(world):
    ab = world.at().reduce(COUNT, over=["a", "b"])
    cde = world.at().reduce(COUNT, over=["c", "d", "e"])
    out = world.at().reduce(COUNT, over=list("abcdefg"))
    assert STEPS[-1] == ["f", "g"] and MERGED[-1] == [["c", "d", "e"], ["a", "b"]]
    assert world.at()[out.subject, "db/reduce/from"] == sorted([ab.subject, cde.subject])
    assert out.obj == dict.fromkeys("abcdefg", 1)
    assert world.at().reduce(COUNT, over=list("abcdefg"), fresh=True).same_as(out)


def test_overlapping_partials_only_a_disjoint_set_is_picked_greedily(world):
    abc = world.at().reduce(COUNT, over=["a", "b", "c"])
    world.at().reduce(COUNT, over=["c", "d"])
    de = world.at().reduce(COUNT, over=["d", "e"])
    world.at().reduce(COUNT, over=["b", "f"])
    out = world.at().reduce(COUNT, over=list("abcdefg"))
    # abc (largest); then the size-2 ties newest first: bf overlaps abc, de is disjoint, cd overlaps both
    assert MERGED[-1] == [["a", "b", "c"], ["d", "e"]] and STEPS[-1] == ["f", "g"]
    assert world.at()[out.subject, "db/reduce/from"] == sorted([abc.subject, de.subject])
    assert out.obj == dict.fromkeys("abcdefg", 1)                       # nothing counted twice
    assert world.at().reduce(COUNT, over=list("abcdefg"), fresh=True).same_as(out)


def test_a_function_breaking_the_law_differs_from_fresh(world):
    world.at().reduce("ledger_kinds.count_calls", over=list("abcde"))
    six = world.at().reduce("ledger_kinds.count_calls", over=list("fabcde"))
    fresh = world.at().reduce("ledger_kinds.count_calls", over=list("abcdef"), fresh=True)
    assert six.obj["calls"] == 2 and fresh.obj["calls"] == 1 and not fresh.same_as(six)
    world.at().reduce("ledger_kinds.count_calls", over=["x", "y"])
    merged = world.at().reduce("ledger_kinds.count_calls", over=list("abcdefxy"))
    fresh = world.at().reduce("ledger_kinds.count_calls", over=list("abcdefxy"), fresh=True)
    assert merged.obj["calls"] == 3 and not fresh.same_as(merged)


def test_order_is_no_second_entry(world):
    a = world.at().reduce(COUNT, over=list("abc"))
    b = world.at().reduce(COUNT, over=("c", "a", "b"))
    assert b.subject == a.subject and steps() == 1


def test_the_largest_subset_wins_and_a_removed_input_is_a_hit(world):
    world.at().reduce(COUNT, over=list("ab"))
    abc = world.at().reduce(COUNT, over=list("abc"))
    world.at().reduce(COUNT, over=list("ad"))                          # overlaps abc: not picked beside it
    abcd = world.at().reduce(COUNT, over=list("abcd"))
    assert STEPS[-1] == ["d"] and world.at()[abcd.subject, "db/reduce/from"] == [abc.subject]
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
    cd = world.at().reduce(COUNT, over=list("cd"))
    draft = world.at().reduce(COUNT, over=list("abcde"), seal=False)
    assert STEPS[-1] == ["e"] and len(MERGED[-1]) == 2 and not draft.sealed and draft.subject is None
    draft.seal(world)
    top = world.at()
    assert top[draft.subject, "db/reduce/from"] == sorted([ab.subject, cd.subject])
    assert top[draft.subject, "db/reduce/more"] == ["e"]
    n = steps()
    assert world.at().reduce(COUNT, over=list("abcde")).subject == draft.subject and steps() == n


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
    assert STEPS[-1] == ["G3"] and world.at()[three.subject, "db/reduce/from"] == [two.subject]
    g3 = world.at().load("games/G3")
    refs = sorted(k.rpartition(":")[2] for k in three.dependencies if k.startswith("ref:"))
    assert refs == sorted([g1.hash, g2.hash, g3.hash, two.hash])        # the acc, G3, and the acc's own inputs
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
    assert world.at()[abc.subject, "db/reduce/from"] == [ab.subject] and abc.dependencies["game/a n"] == "1"
    with world.transaction(by="t", lock=10) as t:
        t["game/c"] = {"n": "30"}
    moved_c = world.at().reduce("ledger_kinds.tally", over=["a", "b", "c"])
    assert moved_c.obj == {"a": "1", "b": "2", "c": "30"}
    assert world.at()[moved_c.subject, "db/reduce/from"] == [ab.subject]
    with world.transaction(by="t", lock=10) as t:
        t["game/a"] = {"n": "10"}
    n = CALLS["tally"]
    moved_a = world.at().reduce("ledger_kinds.tally", over=["a", "b", "c"])        # a was in an acc, two steps down
    assert CALLS["tally"] == n + 1 and moved_a.obj == {"a": "10", "b": "2", "c": "30"}
    assert world.at()[moved_a.subject, "db/reduce/from"] == []


def test_an_acc_whose_dependency_changed_is_not_picked_beside_one_that_holds(world):
    with world.transaction(by="t", lock=10) as t:
        for g in "abcd":
            t[f"game/{g}"] = {"n": g}
    ab = world.at().reduce("ledger_kinds.tally", over=["a", "b"])
    world.at().reduce("ledger_kinds.tally", over=["c", "d"])
    with world.transaction(by="t", lock=10) as t:
        t["game/c"] = {"n": "C"}
    n = CALLS["tally"]
    out = world.at().reduce("ledger_kinds.tally", over=list("abcd"))
    assert CALLS["tally"] == n + 1 and out.obj == {"a": "a", "b": "b", "c": "C", "d": "d"}
    top = world.at()
    assert top[out.subject, "db/reduce/from"] == [ab.subject] and top[out.subject, "db/reduce/more"] == ["c", "d"]


def test_the_from_rows_and_the_why_line(world):
    ab = world.at().reduce(COUNT, over=["a", "b"])
    cd = world.at().reduce(COUNT, over=["c", "d"])
    out = world.at().reduce(COUNT, over=list("abcde"))
    top = world.at()
    first = sorted([ab.subject, cd.subject])
    assert top[out.subject, "db/reduce/from"] == first
    assert reduced_from(top, ab.subject) == 'reduced from: (none); more: "a", "b"'
    assert reduced_from(top, out.subject) == f'reduced from: #{first[0][:8]}, #{first[1][:8]}; more: "e"'
    assert reduced_from(top, top.load(ab.subject).subject) is not None
    # a row from before steps merged several accs: a bare subject, or none
    assert reduce_sources(ab.subject) == [ab.subject] and reduce_sources("none") == []
    assert reduce_sources("[]") == [] and reduce_sources(list(reversed(first))) == first
    with pytest.raises(TypeError):
        reduce_sources(3)


def test_why_prints_the_merged_accs(world, tmp_path, monkeypatch, capsys):
    from dvc_dat.ledger import recipes

    world.at().reduce(COUNT, over=["a", "b"])
    world.at().reduce(COUNT, over=["c", "d"])
    out = world.at().reduce(COUNT, over=list("abcd"))
    with world.transaction(by="t") as t:
        t.add("table", "db/alias", out.subject)
    monkeypatch.setattr(recipes, "Ledger", lambda: world)
    monkeypatch.setattr(recipes, "import_checkout", lambda: None)
    recipes.why(["table"])
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert line.startswith("reduced from: #") and line.count("#") == 2 and line.endswith("more: (none)")


def test_refusals(world):
    with pytest.raises(ValueError, match="twice"):
        world.at().reduce(COUNT, over=["a", "b", "a"])
    with pytest.raises(TypeError, match="reserved"):
        world.at().reduce(COUNT, over=["a"], more=["b"])
    with pytest.raises(TypeError, match="reserved"):
        world.at().reduce(COUNT, over=["a"], accs=[])
    with pytest.raises(TypeError, match="sequence"):
        world.at().reduce(COUNT, over="abc")
    with pytest.raises(TypeError, match="reduce function"):
        world.at().run(COUNT, accs=[], more=["a"])
    with pytest.raises(TypeError, match="reduce_fn"):
        world.at().reduce("ledger_kinds.cut", over=["G1"])
    with pytest.raises(TypeError):
        world.at().reduce(COUNT, over=["a"], nope=1)
    assert steps() == 0


def test_the_decorators_refuse_a_reduce_function_marked_wrong():
    with pytest.raises(TypeError, match="missing: accs"):
        @dat.reduce_fn
        def no_accs(rev, *, more: list) -> dict: ...
    with pytest.raises(TypeError, match="missing: more"):
        @dat.reduce_fn
        def no_more(rev, *, accs: list) -> dict: ...
    with pytest.raises(TypeError, match="takes acc; .* accs"):
        @dat.reduce_fn
        def old(rev, *, acc, accs, more: list) -> dict: ...
    with pytest.raises(TypeError, match="takes acc; .* accs"):
        @dat.reduce_fn(reproducible=True)
        def old_shape(rev, *, acc, more: list) -> dict: ...
    with pytest.raises(TypeError, match="missing: accs, more"):
        @dat.reduce_fn
        def by_args(rev, *args, **kw) -> dict: ...
    with pytest.raises(TypeError, match="return annotation"):
        @dat.reduce_fn
        def bare(rev, *, accs, more): ...
    with pytest.raises(TypeError, match="mark it @dat.reduce_fn"):
        @dat.fn
        def plain(rev, *, accs, more: list) -> dict: ...
    with pytest.raises(TypeError, match="mark it @dat.reduce_fn"):
        @dat.fn
        def plain_old(rev, *, acc, more: list) -> dict: ...

    @dat.reduce_fn(reproducible="exact")
    def good(rev, accs, more, *, tag: str = "t") -> dict:
        return {"n": len(more)}

    @dat.fn
    def takes_more(rev, *, more: int) -> dict:                         # more alone is any key
        return {}
    assert dat.fn_mark(good).reduce and dat.fn_mark(good).reproducible == "exact"
    assert not dat.fn_mark(takes_more).reduce and good(None, [], [1, 2]) == {"n": 2}


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
    assert STEPS[-1] == list("abcdef") and world.at()[six.subject, "db/reduce/from"] == []
    assert old.load(five.subject).obj == dict.fromkeys("abcde", 1)


# -- sandboxed: a mounted reduce in a real checkout --------------------------------------------------------------

REDUCER = textwrap.dedent('''
    from dvc_dat import dat

    @dat.reduce_fn
    def total(rev, *, accs, more: list) -> dict:
        out = {"steps": []}
        for acc in sorted(accs, key=lambda a: a.obj["steps"]):
            out["steps"] = out["steps"] + acc.obj["steps"]
            out.update({k: v for k, v in acc.obj.items() if k != "steps"})
        out["steps"] = out["steps"] + [sorted(x if isinstance(x, str) else x.obj["game"] for x in more)]
        for x in more:
            name = x if isinstance(x, str) else x.obj["game"]
            out[name] = 1
        return out
''')

MISMARKED = textwrap.dedent('''
    from dvc_dat import dat

    @dat.fn
    def total(rev, *, accs, more: list) -> dict:
        return {}
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
    (repo / "red/bad.py").write_text(MISMARKED)
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
    assert six.obj["steps"] == [list("abcde"), ["G1"]] and L.at()[six.subject, "db/reduce/from"] == [five.subject]
    draft = L.at().reduce("mnt.red.fns.total", over=list("abcdef"), seal=False)
    assert draft.obj["steps"] == [list("abcde"), ["f"]]
    old = L.at()
    (repo / "red/fns.py").write_text(REDUCER + "\nX = 1\n")              # the module edited
    again = L.at().reduce("mnt.red.fns.total", over=[*"abcde", g1])
    assert again.obj["steps"] == [["G1", "a", "b", "c", "d", "e"]] and L.at()[again.subject, "db/reduce/from"] == []
    assert old.load(six.subject).obj["steps"] == [list("abcde"), ["G1"]]
    assert L.at().reduce("mnt.red.fns.total", over=[*"abcde", g1], seal="get").subject == again.subject


def test_a_mounted_reduce_merges_two_accs_in_the_worker(red):
    L, _repo = red
    ab = L.at().reduce("mnt.red.fns.total", over=["a", "b"])
    with L.transaction(by="t") as t:
        Value.Blob({"game": "G1"}).seal(t, name="games/G1")
    g1 = L.at().load("games/G1")
    cg = L.at().reduce("mnt.red.fns.total", over=["c", g1])
    out = L.at().reduce("mnt.red.fns.total", over=["a", "b", "c", g1, "d"])
    assert out.obj["steps"] == [["G1", "c"], ["a", "b"], ["d"]] and L.at()[out.subject, "db/provenance"] == "eval:sandbox"
    top = L.at()
    assert top[out.subject, "db/reduce/from"] == sorted([ab.subject, cg.subject])
    assert top[out.subject, "db/reduce/more"] == ["d"]
    refs = {k.rpartition(":")[2] for k in out.dependencies if k.startswith("ref:")}
    assert {ab.hash, cg.hash, g1.hash} <= refs
    with pytest.raises(TypeError, match="mark it @dat.reduce_fn"):
        L.at().reduce("mnt.red.bad.total", over=["a"])
