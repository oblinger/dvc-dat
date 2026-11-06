"""SVP 251: ``t.copy`` moves a value onto another ledger with the same hash; ``deep`` its inputs, ``safe`` what the
ledgers' lifetimes require, or only the spec of a value its claim lets be rerun.

Three SQLite ledgers, ``results`` (permanent), ``cold`` (archival) and ``do26`` (transient), and ``games`` (permanent)
for a read through another ``Rev``, each declaring its lifetime on the project's root ledger (``root: root``); a tiny
repo with a bare remote, so a claim can be pinned and a value rerun.
"""

import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest

from dvc_dat import dat, ledgers
from dvc_dat.ledger import Differed, Ledger, NotCopied, NotPinned, Ref, SpecOnly, Value, set_env_provider
from dvc_dat.ledger.claim import claim_of, claim_text, clauses, judged, unconditional, widens
from dvc_dat.ledger.copying import COPIED_FROM, LIFETIME, SPEC_ONLY, lifetime_of
from dvc_dat.ledger.env import Env, code_at, platform_record, platform_tag
from dvc_dat.ledger.pin import DIFFERED_AS_ALLOWED, DIFFERED_DETERMINISTIC, PINNED, REPRODUCED, RERUN, RERUNNABLE, tag_of
from dvc_dat.ledger.sandbox import shutdown

JOBS = textwrap.dedent('''
    import random
    from pathlib import Path

    from dvc_dat import Dat, dat
    from dvc_dat.ledger import Ledger, Value, ledger_class


    @ledger_class(preds=("card", "team"))
    class Carded(Value):
        def __init__(self, data: bytes):
            self.data = data

        def encode(self, out) -> None:
            out.write(self.data)

        @classmethod
        def decode(cls, src, store):
            return cls(src.read())


    @dat.fn
    def base(rev, *, n: int) -> dict:
        return {"n": n}


    @dat.fn
    def top(rev, *, b) -> dict:
        return {"n": b.load().obj["n"] + 1}


    @dat.fn(reproducible=True)
    def good(rev, *, n: int) -> dict:
        return {"n": n}


    @dat.fn(reproducible="exact")
    def exact(rev, *, n: int) -> dict:
        return {"n": n}


    @dat.fn(reproducible=True)
    def good_top(rev, *, b) -> dict:
        return {"n": b.load().obj["n"] + 1}


    @dat.fn(reproducible=False)
    def flaky(rev, *, n: int) -> dict:
        return {"n": n}


    @dat.fn(reproducible=("exact", "card"))
    def only_on_a_card(rev, *, n: int) -> dict:
        return {"n": n}


    @dat.fn(reproducible=True)
    def reads_game(rev, *, where: str) -> dict:
        return {"g": Ledger(where).at().load("G1").obj}


    @dat.fn
    def reads_game_plain(rev, *, where: str) -> dict:
        return {"g": Ledger(where).at().load("G1").obj}


    @dat.fn(reproducible=True)
    def loose(rev, *, n: int) -> dict:
        return {"r": random.random(), "n": n}


    @dat.fn(reproducible="exact")
    def liar(rev, *, n: int) -> dict:
        return {"r": random.random(), "n": n}


    @dat.fn(reproducible=[("exact", "card"), True])
    def carded(rev, *, n: int, card: str) -> Carded:
        v = Carded(str(random.random()).encode())
        v.preds["card"] = card
        return v


    @dat.fn(reproducible=True)
    def folder(rev, *, n: int, path: Path) -> Dat:
        (path / "f.txt").write_text(str(n))
        (path / "g.txt").write_text(str(n))
        return Dat(path)


    @dat.fn
    def teamed(rev, *, teams: list) -> Carded:
        v = Carded(b"x")
        v.preds["team"] = teams
        return v
''')

PKG = {"copypkg/__init__.py": '__version__ = "1.0.0"\n', "copypkg/jobs.py": JOBS}
FN = "copypkg.jobs."


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main",
                           *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def declare(name, lifetime):
    """Root's registry row declaring the ledger ``name``'s lifetime, as ``just create ledger`` writes it."""
    with ledgers.root.transaction(by="t") as t:
        t.add(f"ledger/{name}", LIFETIME, lifetime)


def ledger(tmp, name, lifetime=None):
    L = Ledger(tmp / name, create=True)
    if lifetime is not None:
        declare(name, lifetime)
    return L


@pytest.fixture
def w(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DAT_LEDGER", raising=False)
    (tmp_path / ".datconfig.yaml").write_text("root: root\n")
    Ledger(tmp_path / "root", create=True)
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "remote.git")
    repo = tmp_path / "copyrepo"
    for rel, text in PKG.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "one")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "-u", "origin", "main")
    monkeypatch.syspath_prepend(str(repo))
    for m in [m for m in sys.modules if m == "copypkg" or m.startswith("copypkg.")]:
        del sys.modules[m]
    import copypkg.jobs  # noqa: F401
    old = set_env_provider(None)
    set_env_provider(lambda: Env({"copyrepo": code_at(str(repo))}, platform_tag(), record=platform_record()))
    world = SimpleNamespace(tmp=tmp_path, repo=repo, commit=git(repo, "rev-parse", "HEAD"),
                            results=ledger(tmp_path, "results", "permanent"), cold=ledger(tmp_path, "cold", "archival"),
                            do26=ledger(tmp_path, "do26", "transient"), games=ledger(tmp_path, "games", "permanent"))
    with world.games.transaction(by="t") as t:
        Value.Blob({"game": 1}).seal(t, name="G1")
    yield world
    shutdown()
    set_env_provider(old)


def run(L, name, **kw):
    return L.at().run(FN + name, **kw)


def holds(L, v):
    """Does ``L`` hold ``v``'s value, bytes included."""
    subject = v.subject if isinstance(v, Value) else v
    return bool(L.at()._held(subject, "db/value")) and not L.at()._spec_only_at(subject)


def spec_only(L, v):
    return L.at().get(v.subject, SPEC_ONLY) == "true" and not L._store.art.exists(v.hash)


def rows(L, subject):
    return dict(L.at()._record_of(subject))


def chain(w):
    """``do26``: base -> top; ``top`` two values, on a transient ledger."""
    b = run(w.do26, "base", n=1)
    return b, run(w.do26, "top", b=Ref(w.do26.at(), b.subject))


# -- one operator: bytes, rows, origin ------------------------------------------------------------------------

def test_a_copy_has_the_same_hash_subject_and_provenance(w):
    v = run(w.do26, "base", n=1)
    source = w.do26.at().id
    assert w.results.at().copy(v, safe=False) == [v.subject]
    got = Ref(w.results.at(), v.subject).load()
    assert got.hash == v.hash and got.obj == {"n": 1} and got.subject == v.subject
    assert dict(got.dependencies) == dict(v.dependencies)
    r = rows(w.results, v.subject)
    assert r[COPIED_FROM] == f"do26@{source}" and r["db/fn"] == FN + "base" and r["db/keys"] == {"n": 1}
    assert "db/at" not in r and got.at is None and v.at.ledger is w.do26    # a revision of another ledger: left there
    assert r["db/commit"] == w.commit and r["db/provenance"] == "eval:unsandboxed"
    assert w.results.at().get(v.dependencies["code"], "db/modules") is not None
    assert w.results.at()._store.art.exists(v.hash)


def test_a_folder_value_brings_every_file(w):
    d = run(w.do26, "folder", n=3)
    w.results.at().copy(d, safe=False)
    got = Ref(w.results.at(), d.subject).load()
    assert got.hash == d.hash and (got.path / "f.txt").read_text() == "3"


def test_copy_dedupes_and_a_second_copy_adds_nothing(w):
    v = run(w.do26, "base", n=1)
    h = w.results.at().copy(v, safe=False)
    top = w.results.at().id
    assert w.results.at().copy(v, safe=False) == h
    assert w.results.at()._held(v.subject, "db/value")[0].rev == top
    assert len(list(w.results.at().history(v.subject, COPIED_FROM))) == 1


def test_several_values_land_in_one_revision_with_whatever_else_it_writes(w):
    a, b = run(w.do26, "base", n=1), run(w.do26, "base", n=2)
    with w.results.transaction(by="t") as t:
        assert t.copy(a, b, safe=False) == [a.subject, b.subject]
        t.add("note", "says", "promoted")
    top = w.results.at()
    assert top._held(a.subject, "db/value")[0].rev == top._held(b.subject, "db/value")[0].rev == top.id


def test_a_refused_body_writes_nothing_and_no_bytes(w):
    v = run(w.do26, "base", n=1)
    with pytest.raises(RuntimeError):
        with w.results.transaction(by="t") as t:
            t.copy(v, safe=False)
            raise RuntimeError("no")
    assert not holds(w.results, v) and not w.results._store.art.exists(v.hash)


def test_a_ref_reads_at_its_own_revision_and_a_name_travels(w):
    with w.do26.transaction(by="t") as t:
        Value.Blob({"x": 1}).seal(t, name="note/one")
    r = Ref(w.do26.at(), "note/one")
    w.results.at().copy(r, safe=False)
    assert Ref(w.results.at(), "note/one").hash == r.hash


def test_what_copy_takes(w):
    with pytest.raises(TypeError, match="sealed Value or a Ref"):
        w.results.at().copy("note/one")
    with pytest.raises(NotCopied, match="unsaved"):
        w.results.at().copy(Value.Blob({"x": 1}))
    v = run(w.do26, "base", n=1)
    with pytest.raises(NotCopied, match="already"):
        w.do26.at().copy(v, safe=False)
    with pytest.raises(TypeError):
        w.results.at().copy(v, deep="yes")
    with pytest.raises(TypeError):
        w.results.at().copy()


def test_declared_preds_read_here_as_there(w):
    with w.do26.transaction(by="t") as t:
        t.add("db/pred/team", "db/cardinality", "many")
    v = run(w.do26, "teamed", teams=["a", "b"])
    w.results.at().copy(v, safe=False)
    assert w.results.at().all(v.subject, "team") == ["a", "b"]
    assert Ref(w.results.at(), v.subject).load().preds["team"] == ["a", "b"]


def test_a_memo_entry_copied_hits_on_the_destination(w):
    v = run(w.do26, "base", n=1)
    w.results.at().copy(v, safe=False)
    assert w.results.at().run(FN + "base", n=1, seal="get").subject == v.subject


# -- lifetimes -------------------------------------------------------------------------------------------------

def test_a_lifetime_is_a_row_of_three_words(w):
    assert (lifetime_of(w.results), lifetime_of(w.cold), lifetime_of(w.do26)) == ("permanent", "archival", "transient")
    bare = ledger(w.tmp, "bare")
    with pytest.raises(NotCopied, match="no lifetime"):
        lifetime_of(bare)
    declare("bare", "forever")
    with pytest.raises(NotCopied, match="'forever'"):
        lifetime_of(bare)


def test_a_lifetime_is_read_on_root_never_on_the_ledger_itself(w):
    """SVP 251 Q3 (B): the row lives on root, so a row the ledger writes about itself declares nothing."""
    own = ledger(w.tmp, "own26")
    with own.transaction(by="t") as t:
        t.add("ledger/own26", LIFETIME, "permanent")
    with pytest.raises(NotCopied, match=r"no lifetime.*root ledger \(root\)"):
        lifetime_of(own)
    declare("own26", "transient")
    assert lifetime_of(own) == "transient"


def test_a_ledger_gone_from_disk_is_still_judged_by_root(w):
    gone = ledger(w.tmp, "gone26", "archival")
    gone.close()
    (w.tmp / "gone26" / "ledger.db").unlink()
    assert lifetime_of(gone) == "archival"


def test_more_than_one_lifetime_on_root_is_an_error(w):
    with ledgers.root.transaction(by="t") as t:
        t.add(f"db/pred/{LIFETIME}", "db/cardinality", "many")
    declare("results", "transient")
    with pytest.raises(NotCopied, match="more than one lifetime for ledger results"):
        lifetime_of(w.results)
    v = run(w.do26, "base", n=1)
    with pytest.raises(NotCopied, match="more than one lifetime"):
        w.results.at().copy(v)
    assert not holds(w.results, v)


def test_safe_refuses_when_root_does_not_open(w, tmp_path_factory, monkeypatch):
    v = run(w.do26, "base", n=1)
    monkeypatch.chdir(tmp_path_factory.mktemp("noproject"))
    with pytest.raises(NotCopied, match="root ledger, which does not open"):
        w.results.at().copy(v)
    w.results.at().copy(v, safe=False)                                      # a plain copy never looks
    assert holds(w.results, v)


def test_safe_is_the_default_and_refuses_an_undeclared_ledger(w):
    bare = ledger(w.tmp, "bare")
    v = run(w.do26, "base", n=1)
    with pytest.raises(NotCopied, match="no lifetime"):
        bare.at().copy(v)
    bare.at().copy(v, safe=False)                                           # a plain copy never looks
    assert holds(bare, v)


def test_a_plain_copy_leaves_the_inputs(w):
    b, v = chain(w)
    w.results.at().copy(v, safe=False)
    assert holds(w.results, v) and not holds(w.results, b)


def test_deep_places_every_input_whatever_its_ledger(w):
    b, v = chain(w)
    g = run(w.do26, "reads_game_plain", where=str(w.games.path))
    w.results.at().copy(v, g, deep=True, safe=False)
    assert holds(w.results, v) and holds(w.results, b) and holds(w.results, Ref(w.games.at(), "G1").subject)


def test_safe_from_transient_to_permanent_copies_exactly_the_transient_inputs(w):
    b, v = chain(w)
    g = run(w.do26, "reads_game_plain", where=str(w.games.path))
    w.results.at().copy(v, g)
    assert holds(w.results, v) and holds(w.results, b) and holds(w.results, g)
    assert not w.results.at()._held(Ref(w.games.at(), "G1").subject, "db/value"), "the game on a permanent ledger stays"


def test_safe_from_permanent_to_transient_copies_no_input(w):
    b = run(w.results, "base", n=1)
    v = run(w.results, "top", b=Ref(w.results.at(), b.subject))
    w.do26.at().copy(v)
    assert holds(w.do26, v) and not holds(w.do26, b)


def test_safe_ranks_archival_between(w):
    b = run(w.cold, "base", n=1)
    v = run(w.cold, "top", b=Ref(w.cold.at(), b.subject))
    w.do26.at().copy(v)
    assert not holds(w.do26, b), "archival is above transient: referenced"
    w.results.at().copy(v)
    assert holds(w.results, b), "archival is below permanent: copied"


def test_safe_recurses_with_the_same_rule(w):
    b, v = chain(w)
    u = run(w.do26, "top", b=Ref(w.do26.at(), v.subject))
    w.results.at().copy(u)
    assert all(holds(w.results, x) for x in (u, v, b))


def test_an_input_already_on_the_destination_is_left(w):
    b = run(w.results, "base", n=1)
    w.do26.at().copy(b, safe=False)
    v = run(w.do26, "top", b=Ref(w.do26.at(), b.subject))
    w.results.at().copy(v)
    assert holds(w.results, v)


def test_safe_and_deep_refuse_an_input_that_cannot_be_found_and_write_nothing(w, monkeypatch):
    g = run(w.do26, "reads_game_plain", where=str(w.games.path))
    import dvc_dat.ledger.named as named

    monkeypatch.setattr(named, "opened", lambda name: None)
    before = w.results.at().id
    for kw in ({"safe": True}, {"deep": True, "safe": False}):
        with pytest.raises(NotCopied, match="cannot be found"):
            w.results.at().copy(g, **kw)
    assert w.results.at().id == before and not w.results._store.art.exists(g.hash)
    w.results.at().copy(g, safe=False)                                      # a plain copy never looks


def test_a_refusal_caught_in_the_body_leaves_nothing_of_the_copy(w):
    with w.do26.transaction(by="t") as t:
        t.add("db/pred/team", "db/cardinality", "many")
    v = run(w.do26, "teamed", teams=["a"])
    with w.results.transaction(by="t") as t:
        t.add("db/pred/team", "db/cardinality", "one")
    with w.results.transaction(by="t") as t:
        with pytest.raises(NotCopied, match="declared"):
            t.copy(v, safe=False)
        assert not t._ops and not t._copies
    assert not holds(w.results, v)


# -- the rerunnable claim --------------------------------------------------------------------------------------

def test_a_rerunnable_value_copied_with_safe_keeps_its_row_true(w):
    b, v = chain(w)
    w.do26.at().pin(v)
    w.results.at().copy(v)
    top = w.results.at()
    assert top[v.subject, RERUNNABLE] == "true" and holds(w.results, b)
    assert top[f"db/repo/copyrepo/{w.commit[:12]}", PINNED] == tag_of(w.commit)
    assert w.results.at().rerun(v).outcome == REPRODUCED


def test_a_plain_copy_of_a_rerunnable_value_promises_nothing(w):
    v = run(w.do26, "base", n=1)
    w.do26.at().pin(v, rerun=True)
    w.results.at().copy(v, safe=False)
    top = w.results.at()
    assert top.get(v.subject, RERUNNABLE) is None and top.get(v.subject, RERUN) is None
    with pytest.raises(NotPinned, match="not pinned"):
        top.rerun(v)


def test_rerunnable_asserts_the_claim_at_the_destination(w):
    v = run(w.do26, "base", n=1)
    w.results.at().copy(v, rerunnable=True)
    top = w.results.at()
    assert top[v.subject, RERUNNABLE] == "true" and w.do26.at().get(v.subject, RERUNNABLE) is None
    assert git(w.repo, "ls-remote", "--tags", "origin", tag_of(w.commit))


def test_pin_refuses_a_foreign_input_that_cannot_be_found(w, monkeypatch):
    g = run(w.do26, "reads_game_plain", where=str(w.games.path))
    import dvc_dat.ledger.named as named

    monkeypatch.setattr(named, "opened", lambda name: None)
    with pytest.raises(NotPinned, match="cannot be found"):
        w.do26.at().pin(g)


# -- the claim -------------------------------------------------------------------------------------------------

def test_the_claim_grammar():
    assert clauses("exact") == [("exact", ())] and clauses(True) == [(True, ())]
    assert clauses(None) == [(None, ())] and clauses(False) == [(False, ())]
    assert clauses(("exact", "platform/card")) == [("exact", ("platform/card",))]
    assert clauses((True,)) == [(True, ())]
    assert clauses([("exact", "a", "b"), (True, "c"), False]) == [("exact", ("a", "b")), (True, ("c",)), (False, ())]
    for bad in ("close", 1, 0, [], (), ("no", "a"), ("exact", 3), ("exact", ""), [["exact"]], {"exact": 1}):
        with pytest.raises(TypeError):
            clauses(bad)


def test_the_decorator_refuses_what_the_grammar_refuses():
    with pytest.raises(TypeError, match="level"):
        dat.fn(reproducible="close")
    with pytest.raises(TypeError):
        @dat.fn(deterministic=True)
        def gone(rev) -> dict:
            return {}


def test_clauses_read_in_order():
    claim = clauses([("exact", "card"), (True, "rev"), False])
    assert judged(claim, {"card": "a", "rev": "1"}, {"card": "a", "rev": "1"}) == "exact"
    assert judged(claim, {"card": "a", "rev": "1"}, {"card": "b", "rev": "1"}) is True
    assert judged(claim, {"card": "a"}, {"card": "b"}) is False                 # a predicate not carried: no match
    assert judged(clauses(("exact", "card")), {"card": "a"}, {"card": "b"}) is None      # off the list: unknown
    assert unconditional(claim) is False and unconditional(clauses(("exact", "card"))) is None
    assert unconditional(clauses([("exact", "card"), True])) is True
    assert unconditional(clauses([False, True])) is False                       # past the first, none is reached
    assert widens("exact") and widens([("exact", "card"), True]) and not widens(True) and not widens(None)


def test_the_claim_is_a_row_at_seal_outside_the_subject(w):
    v = run(w.do26, "carded", n=1, card="a")
    assert rows(w.do26, v.subject)["db/reproducible"] == [["exact", ["card"]], [True, []]]
    assert claim_of(w.do26.at(), v.subject) == [("exact", ("card",)), (True, ())]
    plain = run(w.do26, "base", n=1)
    assert "db/reproducible" not in rows(w.do26, plain.subject) and claim_text(None) is None
    w.results.at().copy(v, safe=False)
    assert claim_of(w.results.at(), v.subject) == [("exact", ("card",)), (True, ())]


def test_the_row_of_a_draft_saved_later(w):
    v = run(w.do26, "good", n=1, seal=False)
    with w.do26.transaction(by="t") as t:
        v.seal(t)
    assert rows(w.do26, v.subject)["db/reproducible"] == [[True, []]]


def test_exact_widens_the_memo_and_true_does_not(w):
    fn = w.do26.at().ns.load(FN + "exact")
    assert fn.reproducible == "exact" and widens(fn.reproducible)
    good = w.do26.at().ns.load(FN + "good")
    assert good.reproducible is True and not widens(good.reproducible)


def test_a_mounted_claim_is_read_off_its_file(w):
    with w.do26.transaction(by="t") as t:
        t.ns.mount("mnt.cj", root="copypkg", repo="copyrepo")
    run(w.do26, "base", n=1)
    fn = w.do26.at().ns.load("mnt.cj.jobs.carded")
    assert fn.reproducible == [("exact", "card"), True]
    v = w.do26.at().run("mnt.cj.jobs.good", n=1)
    assert rows(w.do26, v.subject)["db/reproducible"] == [[True, []]]


def test_a_sandboxed_value_reruns_from_its_copy_alone(w, monkeypatch):
    with w.do26.transaction(by="t") as t:
        t.ns.mount("mnt.cj", root="copypkg", repo="copyrepo")
    run(w.do26, "base", n=1)                                                # a clean run moves the clock
    v = w.do26.at().run("mnt.cj.jobs.good", n=4)
    w.do26.at().pin(v)
    w.results.at().copy(v)
    assert spec_only(w.results, v) and "cj" in w.results.at().ns.mounts()
    import dvc_dat.ledger.named as named

    monkeypatch.setattr(named, "opened", lambda name: w.results if name == "results" else None)
    assert w.results.at().rerun(v).outcome == REPRODUCED


# -- rerun reads the claim -------------------------------------------------------------------------------------

def test_at_level_true_a_rerun_that_differs_is_differed_as_allowed(w):
    v = run(w.do26, "loose", n=1)
    w.do26.at().pin(v, rerun=True)
    assert w.do26.at()[v.subject, RERUN] == DIFFERED_AS_ALLOWED             # recorded, no error
    assert w.do26.at().rerun(v).reproducible is True


def test_exact_that_differs_is_the_one_error(w):
    v = run(w.do26, "liar", n=1)
    with pytest.raises(Differed, match="exact"):
        w.do26.at().pin(v, rerun=True)


def test_rerun_compares_the_listed_predicates_and_takes_the_first_clause_that_matches(w):
    v = run(w.do26, "carded", n=1, card="a")
    w.do26.at().pin(v)
    out = w.do26.at().rerun(v)
    assert out.outcome == DIFFERED_DETERMINISTIC and out.reproducible == "exact"    # the same card: exact, and it differed


def test_rerun_reads_the_claim_from_the_ledger_not_the_code(w):
    v = run(w.do26, "loose", n=1)
    w.do26.at().pin(v)
    (w.repo / "copypkg" / "jobs.py").write_text(JOBS.replace('@dat.fn(reproducible=True)\n    def loose',
                                                             '@dat.fn(reproducible="exact")\n    def loose'))
    assert w.do26.at().rerun(v).outcome == DIFFERED_AS_ALLOWED


# -- spec-only -------------------------------------------------------------------------------------------------

def test_a_pinned_true_value_keeps_only_its_spec(w):
    v = run(w.do26, "good", n=1)
    w.do26.at().pin(v)
    w.results.at().copy(v)
    assert spec_only(w.results, v) and w.results.at()[v.subject, "db/value"].hash == v.hash
    top = w.results.at()
    assert top[f"db/repo/copyrepo/{w.commit[:12]}", PINNED] == tag_of(w.commit)
    with pytest.raises(SpecOnly, match="do26"):
        Ref(top, v.subject).load()


def test_spec_only_needs_every_part_of_the_rule(w):
    for name, kw in (("good", {"n": 1}), ("base", {"n": 2}), ("flaky", {"n": 3}), ("only_on_a_card", {"n": 4})):
        v = run(w.do26, name, **kw)
        if name != "good":
            w.do26.at().pin(v)                                              # pinned, the claim is short
        w.results.at().copy(v)
        assert holds(w.results, v), f"{name}: an unpinned, unknown, False or only conditional claim keeps the bytes"


def test_exact_and_a_fallback_clause_keep_only_the_spec(w):
    a, b = run(w.do26, "exact", n=1), run(w.do26, "carded", n=2, card="c")
    w.do26.at().pin(a)
    w.do26.at().pin(b)
    w.results.at().copy(a, b)
    assert spec_only(w.results, a) and spec_only(w.results, b)


def test_every_input_must_be_safe_in_turn(w):
    b = run(w.do26, "base", n=1)                                            # transient, no claim: not safe
    v = run(w.do26, "good_top", b=Ref(w.do26.at(), b.subject))
    w.do26.at().pin(v)
    w.results.at().copy(v)
    assert holds(w.results, v) and holds(w.results, b)

    g = run(w.do26, "good", n=9)                                            # transient, claimed and pinned: safe
    w.do26.at().pin(g)
    u = run(w.do26, "good_top", b=Ref(w.do26.at(), g.subject))
    w.do26.at().pin(u)
    w.results.at().copy(u)
    assert spec_only(w.results, u) and spec_only(w.results, g), "both specs: the input is copied by the same rule"


def test_a_foreign_read_on_a_permanent_ledger_is_a_safe_source(w):
    v = run(w.do26, "reads_game", where=str(w.games.path))
    w.do26.at().pin(v)
    w.results.at().copy(v)
    assert spec_only(w.results, v)


def test_a_foreign_read_on_a_transient_ledger_keeps_the_bytes(w):
    side = ledger(w.tmp, "side26", "transient")
    with side.transaction(by="t") as t:
        Value.Blob({"game": 2}).seal(t, name="G1")
    v = run(w.do26, "reads_game", where=str(side.path))
    w.do26.at().pin(v)
    w.results.at().copy(v)
    assert holds(w.results, v) and holds(w.results, Ref(side.at(), "G1").subject)


def test_deep_asks_for_every_byte(w):
    v = run(w.do26, "good", n=1)
    w.do26.at().pin(v)
    w.results.at().copy(v, deep=True)
    assert holds(w.results, v)


def test_safe_false_copies_the_bytes(w):
    v = run(w.do26, "good", n=1)
    w.do26.at().pin(v)
    w.results.at().copy(v, safe=False)
    assert holds(w.results, v)


def test_a_spec_only_entry_is_no_memo_hit_until_a_run_brings_the_bytes(w):
    v = run(w.do26, "good", n=1)
    w.do26.at().pin(v)
    w.results.at().copy(v)
    assert w.results.at().run(FN + "good", n=1, seal="get") is None
    again = w.results.at().run(FN + "good", n=1)
    assert again.hash == v.hash and w.results._store.art.exists(v.hash)
    assert Ref(w.results.at(), v.subject).load().obj == {"n": 1}


def test_a_copy_of_the_bytes_fills_a_spec_only_value(w):
    v = run(w.do26, "good", n=1)
    w.do26.at().pin(v)
    w.results.at().copy(v)
    assert not w.results._store.art.exists(v.hash)
    w.results.at().copy(v, safe=False)
    assert holds(w.results, v)


def test_a_spec_only_value_reruns_at_its_origin_and_alone_when_that_is_gone(w, monkeypatch):
    v = run(w.do26, "good", n=1)
    w.do26.at().pin(v)
    w.results.at().copy(v)
    assert w.results.at().rerun(v).outcome == REPRODUCED
    import dvc_dat.ledger.named as named

    monkeypatch.setattr(named, "opened", lambda name: w.results if name == "results" else None)
    assert w.results.at().rerun(v).outcome == REPRODUCED


def test_a_spec_only_source_copies_as_a_spec(w):
    v = run(w.do26, "good", n=1)
    w.do26.at().pin(v)
    w.cold.at().copy(v)
    w.results.at().copy(Ref(w.cold.at(), v.subject), safe=False)
    assert spec_only(w.results, v)
