"""Rerunnability (SVP 250): ``t.pin`` tags and pushes a value's commit to a bare remote, ``rev.rerun`` runs the
function again at the tag, from a fresh clone that never held the commit, in a fresh interpreter.

A tiny repo ``pinrepo`` (package ``pinpkg``, ``__version__`` declared so a clean run moves the ``db/repo/pinrepo
db/commit`` clock) with a bare remote beside it; the environment provider reports the checkout live, so a
commit, a squash or a switch to a clone shows at once.
"""

import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest

import backends
from dvc_dat.ledger import Differed, Head, NotPinned, Rerun, Rev, Value, set_env_provider
from dvc_dat.ledger.env import Env, code_at, platform_record, platform_tag
from dvc_dat.ledger.pin import (DIFFERED_DETERMINISTIC, DIFFERED_NONDETERMINISTIC, PINNED, REPRODUCED, RERUN,
                                RERUNNABLE, tag_of)
from dvc_dat.ledger.sandbox import shutdown

JOBS = textwrap.dedent('''
    import random

    from dvc_dat import dat
    from dvc_dat.ledger import Value


    @dat.fn
    def double(rev, *, n: int) -> dict:
        return {"n": 2 * n}


    @dat.fn(reproducible="exact")
    def stable(rev, *, n: int) -> dict:
        return {"n": n + 1}


    @dat.fn(reproducible=False)
    def noisy(rev, *, n: int) -> dict:
        return {"r": random.random(), "n": n}


    @dat.fn(reproducible="exact")
    def liar(rev, *, n: int) -> dict:
        return {"r": random.random(), "n": n}


    @dat.fn
    def home(rev, *, game: str) -> dict:
        return {"home": rev[f"game/{game}", "home"]}


    @dat.fn
    def chain(rev, *, base: Value) -> dict:
        return {"n": base.obj["n"] * 10, "home": rev["game/G1", "home"]}


    def _make():
        @dat.fn
        def inner(rev, *, n: int) -> dict:
            return {"n": n}
        return inner


    made = _make()
''')

PKG = {"pinpkg/__init__.py": '__version__ = "1.0.0"\n', "pinpkg/jobs.py": JOBS}


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main",
                           *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _provide(repo):
    set_env_provider(lambda: Env({"pinrepo": code_at(str(repo))}, platform_tag(), record=platform_record()))


@pytest.fixture
def world(tmp_path, monkeypatch, backend):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "remote.git")
    repo = tmp_path / "pinrepo"
    for rel, text in PKG.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "one")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "-u", "origin", "main")
    git(repo, "checkout", "-q", "-b", "feat")                       # the run's commit lives on a branch
    (repo / "pinpkg" / "jobs.py").write_text(JOBS + "\n# feat\n")
    git(repo, "commit", "-q", "-am", "two")
    git(repo, "push", "-q", "-u", "origin", "feat")
    monkeypatch.syspath_prepend(str(repo))
    for m in [m for m in sys.modules if m == "pinpkg" or m.startswith("pinpkg.")]:
        del sys.modules[m]
    import pinpkg.jobs  # noqa: F401
    old = set_env_provider(None)
    _provide(repo)
    L = backends.make(backend, tmp_path / "ledger")
    with L.transaction(by="t", lock=10) as t:
        t["game/G1"] = {"home": "lakers"}
    yield SimpleNamespace(L=L, repo=repo, remote=remote, tmp=tmp_path, commit=git(repo, "rev-parse", "HEAD"))
    shutdown()
    set_env_provider(old)


def run(w, name, **kw):
    return w.L.at().run(f"pinpkg.jobs.{name}", **kw)


def squash_and_collect(w):
    """The branch squash-merged and deleted, its commit collected on the remote: what the tag must survive."""
    git(w.repo, "checkout", "-q", "main")
    git(w.repo, "merge", "-q", "--squash", "feat")
    git(w.repo, "commit", "-q", "-m", "squash")
    git(w.repo, "branch", "-D", "feat")
    git(w.repo, "push", "-q", "origin", "main", ":feat")
    git(w.remote, "reflog", "expire", "--expire=now", "--all")
    git(w.remote, "gc", "-q", "--prune=now")


def fresh_clone(w, name="clone"):
    """A checkout made before any pin: it never held the branch's commit and knows no tag."""
    clone = w.tmp / name
    git(w.tmp, "clone", "-q", "--no-tags", "--no-local", str(w.remote), name)   # reachable objects only
    _provide(clone)
    return clone


# -- pin ------------------------------------------------------------------------------------------------------

def test_pin_tags_pushes_and_writes_the_rows(world):
    w = world
    v = run(w, "double", n=2)
    tag = tag_of(w.commit)
    head = w.L.at()
    assert isinstance(head, Head) and isinstance(head, Rev) and not hasattr(w.L.at(0), "pin")
    assert head.pin(v) == tag
    assert git(w.remote, "rev-parse", f"refs/tags/{tag}^{{commit}}") == w.commit, "pushed before pin returned"
    top = w.L.at()
    assert top[f"db/repo/pinrepo/{w.commit[:12]}", PINNED] == tag
    assert top[v.subject, RERUNNABLE] == "true"
    assert top[top.tx, "db/by"].startswith("human:")


def test_one_push_per_commit_and_no_row_twice(world):
    w = world
    v = run(w, "double", n=2)
    w.L.at().pin(v)
    git(w.repo, "remote", "set-url", "origin", str(w.tmp / "nowhere.git"))   # any push now fails
    u = run(w, "double", n=3)
    with w.L.transaction(by="t") as t:
        assert t.pin(u) == tag_of(w.commit)                           # the tag is there: no push, no error
    top = w.L.at()
    assert top[u.subject, RERUNNABLE] == "true"
    assert len(top.history(f"db/repo/pinrepo/{w.commit[:12]}", PINNED)) == 1
    before = len(top.history(v.subject))
    top.pin(v)
    assert len(w.L.at().history(v.subject)) == before, "a pinned value adds no row"


def test_a_refused_push_raises_and_writes_nothing(world):
    w = world
    v = run(w, "double", n=2)
    git(w.repo, "remote", "set-url", "origin", str(w.tmp / "nowhere.git"))
    top = w.L.at().id
    with pytest.raises(NotPinned, match="push"):
        w.L.at().pin(v)
    assert w.L.at().id == top
    assert git(w.repo, "tag", "-l", "dat/*") == "", "the local tag goes with the failed push"
    assert git(w.remote, "tag", "-l", "dat/*") == ""


def test_a_hand_seal_and_an_unknown_commit_are_refused(world):
    w = world
    with w.L.transaction(by="t") as t:
        b = Value.Blob({"x": 1})
        b.seal(t)
    with pytest.raises(NotPinned, match="not a run's result"):
        w.L.at().pin(b)
    v = run(w, "double", n=2)
    squash_and_collect(w)                                             # the commit is gone from every branch
    fresh_clone(w)
    with pytest.raises(NotPinned, match="unknown"):
        w.L.at().pin(v)
    assert w.L.at().get(v.subject, RERUNNABLE) is None


def test_a_function_not_importable_by_its_name_is_refused(world):
    w = world
    m = run(w, "made", n=1)                                           # a closure bound to a module attribute
    with pytest.raises(NotPinned, match="top-level"):
        w.L.at().pin(m)


def test_recursive_asserts_the_inputs_too(world):
    w = world
    d = run(w, "double", n=2)
    c = run(w, "chain", base=d)
    w.L.at().pin(c)
    top = w.L.at()
    assert top[c.subject, RERUNNABLE] == "true" and top.get(d.subject, RERUNNABLE) is None
    top.pin(c, recursive=True)
    top = w.L.at()
    assert top[c.subject, RERUNNABLE] == "recursive" and top[d.subject, RERUNNABLE] == "recursive"
    top.pin(c)                                                        # never downgrades
    assert w.L.at()[c.subject, RERUNNABLE] == "recursive"


# -- rerun ----------------------------------------------------------------------------------------------------

def test_rerun_reproduces_from_a_fresh_clone_after_the_branch_is_squashed_and_collected(world):
    w = world
    v = run(w, "double", n=2)
    with pytest.raises(NotPinned, match="not pinned"):
        w.L.at().rerun(v)
    w.L.at().pin(v)
    squash_and_collect(w)
    clone = fresh_clone(w)
    assert subprocess.run(["git", "cat-file", "-e", f"{w.commit}^{{commit}}"], cwd=clone).returncode != 0
    out = w.L.at().rerun(v)
    assert isinstance(out, Rerun) and out.outcome == REPRODUCED and out.reproduced
    assert out.hash == out.expected == v.hash and out.reproducible is None and out.tag == tag_of(w.commit)
    assert out.worktree.is_dir() and git(out.worktree, "rev-parse", "HEAD") == w.commit
    assert str(out.worktree).startswith(str(w.L.path)), "the worktree lives under the ledger"
    again = w.L.at().rerun(v)
    assert again.worktree == out.worktree and again.reproduced     # reused, not fetched again



def test_a_value_run_at_a_past_revision_reruns_at_the_revision_it_read(world):
    """SVP 245: the rows moved after the run; the rerun reads ``db/at``, not the revision that saved it."""
    w = world
    read = w.L.at().id
    with w.L.transaction(by="t") as t:
        t["game/G1", "home"] = "celtics"
    v = w.L.at(read).run("pinpkg.jobs.home", game="G1")
    assert v.obj == {"home": "lakers"} and v.at.id == read and v.rev.id > read + 1
    w.L.at().pin(v)
    assert w.L.at().rerun(v).outcome == REPRODUCED


def test_the_three_outcomes_and_the_deterministic_claim(world):
    w = world
    plain, stable, noisy, liar = (run(w, n, n=4) for n in ("double", "stable", "noisy", "liar"))
    head = w.L.at()
    assert head.ns.load("pinpkg.jobs.stable").reproducible == "exact"
    assert head.ns.load("pinpkg.jobs.noisy").reproducible is False
    assert head.ns.load("pinpkg.jobs.double").reproducible is None
    for v in (plain, stable, noisy, liar):
        head.pin(v)
    assert w.L.at().rerun(plain).outcome == REPRODUCED
    assert w.L.at().rerun(stable).outcome == REPRODUCED
    assert w.L.at().rerun(noisy).outcome == DIFFERED_NONDETERMINISTIC
    bad = w.L.at().rerun(liar)
    assert bad.outcome == DIFFERED_DETERMINISTIC and bad.reproducible == "exact" and bad.hash != bad.expected


def test_pin_with_rerun_records_the_outcome_and_a_deterministic_difference_is_the_one_error(world):
    w = world
    stable, liar = run(w, "stable", n=1), run(w, "liar", n=1)
    w.L.at().pin(stable, rerun=True)
    top = w.L.at()
    assert top[stable.subject, RERUN] == REPRODUCED and top[stable.subject, RERUNNABLE] == "true"
    before = top.id
    with pytest.raises(Differed):
        top.pin(liar, rerun=True)
    assert w.L.at().id == before and w.L.at().get(liar.subject, RERUNNABLE) is None


# -- sandboxed ------------------------------------------------------------------------------------------------

def mount(w):
    with w.L.transaction(by="t") as t:
        t.ns.mount("mnt.pj", root="pinpkg", repo="pinrepo")


def test_a_sandboxed_value_pins_and_reruns_in_the_worker(world):
    w = world
    mount(w)
    run(w, "double", n=1)                                             # a clean installed run moves the clock
    v = w.L.at().run("mnt.pj.jobs.stable", n=5)
    assert v.dependencies.get("code/pinrepo") is None and w.L.at()[v.subject, "db/provenance"] == "eval:sandbox"
    w.L.at().pin(v)
    assert w.L.at()[v.subject, RERUNNABLE] == "true"
    out = w.L.at().rerun(v)
    assert out.outcome == REPRODUCED and out.reproducible == "exact"


def test_a_sandboxed_run_from_a_dirty_checkout_is_refused(world):
    w = world
    mount(w)
    run(w, "double", n=1)                                             # the clock names HEAD
    (w.repo / "pinpkg" / "jobs.py").write_text(JOBS + "\n# feat\n# dirty\n")
    v = w.L.at().run("mnt.pj.jobs.double", n=7)                       # a sandboxed miss runs at HEAD, dirty
    with pytest.raises(NotPinned, match="dirty"):
        w.L.at().pin(v)
    assert w.L.at().get(v.subject, RERUNNABLE) is None
