"""Leg 3: contracts, one block per Interface method of the SVP447 Ledger Module page,
including every exception the spec names that is reachable without the sandbox."""

import dataclasses
import threading
import time

import pandas as pd
import pytest

from dvc_dat.ledger2 import (Dat, Exists, Fn, Ledger, LedgerError, LockTimeout, Multiple, NotEvaluated, Pickled,
                             Ref, Rev, Table, Unindexed, UnmountedImport, UntracedRead, Value, attr, bump)


class Note(Value):
    """A minimal user kind."""

    def __init__(self, text):
        self.text = text

    def encode(self):
        return self.text.encode()

    @classmethod
    def decode(cls, data, store):
        return cls(data.decode())


def put(L, *rows, by="t"):
    with L.transaction(by=by) as t:
        for r in rows:
            t.add(*r)
    return t.rev


# ---------------------------------------------------------------- Ledger


class TestLedgerOpen:
    def test_profile_path(self, tmp_path):
        L = Ledger.open(str(tmp_path / "a.db"))
        assert L.at().id == 0

    def test_dat_ledger_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DAT_LEDGER", str(tmp_path / "env.db"))
        L = Ledger.open()
        put(L, ("s", "p", "o"))
        assert Ledger.open().at()["s", "p"] == "o"

    def test_datconfig(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DAT_LEDGER", raising=False)
        (tmp_path / ".datconfig.yaml").write_text("ledger: led/x.db\n")
        (tmp_path / "sub").mkdir()
        monkeypatch.chdir(tmp_path / "sub")
        L = Ledger.open()
        assert L.path == tmp_path / "led" / "x.db"

    def test_none_configured(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DAT_LEDGER", raising=False)
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FileNotFoundError):
            Ledger.open()


class TestLedgerAt:
    def test_forms(self, L):
        put(L, ("s", "p", "1"))
        with L.transaction(by="t") as t:
            bump(t, "ledger", "minor", confirm=lambda a, b: True)
        put(L, ("s", "p", "2"))
        assert L.at().id == 3
        assert L.at(1)["s", "p"] == "1"
        assert L.at("1")["s", "p"] == "1"            # a digit-only string is an id (review lean)
        assert L.at("0.1.0").id == 2                 # a ledger version
        assert L.at(0).all() == []

    def test_missing_revision(self, L):
        put(L, ("s", "p", "1"))
        with pytest.raises(KeyError):
            L.at(5)
        with pytest.raises(KeyError):
            L.at(-1)
        with pytest.raises(KeyError):
            L.at("9.9.9")
        with pytest.raises(TypeError):
            L.at("prod")


class TestLedgerTransaction:
    def test_with_only(self, L):
        t = L.transaction(by="t")
        with pytest.raises(RuntimeError):
            t.add("s", "p", "o")
        with pytest.raises(RuntimeError):
            t.base
        assert L.at().id == 0

    def test_by_required(self, L):
        with pytest.raises(TypeError):
            L.transaction()
        with pytest.raises(TypeError):
            L.transaction(by="")

    def test_time_stamps_and_takes_no_value(self, L):
        with L.transaction(by="t", time=True) as t:
            pass
        assert t.rev[t.rev.tx, "time"].endswith("+00:00")
        with pytest.raises(TypeError):
            L.transaction(by="t", time="2026-01-01")
        with L.transaction(by="t") as t2:
            pass
        assert t2.rev.get(t2.rev.tx, "time") is None

    def test_keywords_and_t_tx_land_on_one_subject(self, L):
        with L.transaction(by="human:dan", why="T531", ticket="T9") as t:
            t.add(t.tx, "checked", "G1,G4,G5")
            t.add("x", "made_in", t.tx)
        r = t.rev
        assert dict(r.all(r.tx)) == {"by": "human:dan", "why": "T531", "ticket": "T9", "checked": "G1,G4,G5"}
        assert r["x", "made_in"] == r.tx
        assert not any(s.startswith("ledger/tx/pending") for s, _p, _o in r.all())

    def test_exception_writes_nothing(self, L):
        with pytest.raises(ZeroDivisionError):
            with L.transaction(by="t") as t:
                t.add("s", "p", "o")
                1 / 0
        assert L.at().id == 0
        with pytest.raises(RuntimeError):
            t.rev

    def test_one_revision_per_with(self, L):
        with L.transaction(by="t") as t:
            for i in range(5):
                t.add("s", f"p{i}", "o")
        assert t.rev.id == 1 and L.at().id == 1


class TestLock:
    def test_base_stays_top_and_writes_land(self, L):
        put(L, ("code/sv-pipe", "version", "0.2.2"), ("model/shot", "version", "1.0.0"))
        with L.transaction(by="agent:svp", lock=5) as t:
            v = t.base["code/sv-pipe", "version"]
            m = t.base["model/shot", "version"]
            assert t.base.id == L.at().id
            t.add("rel/pipe", "pair", f"{v}+{m}")
        assert L.at()["rel/pipe", "pair"] == "0.2.2+1.0.0"

    def test_body_past_limit_writes_nothing(self, L):
        with pytest.raises(LockTimeout):
            with L.transaction(by="t", lock=0.2) as t:
                t.add("s", "p", "o")
                time.sleep(2)
        assert L.at().id == 0

    def test_lock_not_had_within_limit(self, L):
        started, done = threading.Event(), threading.Event()

        def holder():
            with L.transaction(by="holder", lock=10) as t:
                t.add("s", "p", "held")
                started.set()
                done.wait(5)
        th = threading.Thread(target=holder)
        th.start()
        try:
            assert started.wait(5)
            with pytest.raises(LockTimeout):
                with L.transaction(by="late", lock=0.3):
                    pass
        finally:
            done.set()
            th.join(10)
        assert L.at()["s", "p"] == "held" and L.at().id == 1

    def test_writer_without_lock_waits_and_follows(self, L):
        started, done = threading.Event(), threading.Event()

        def holder():
            with L.transaction(by="holder", lock=10) as t:
                t.add("s", "p", "first")
                started.set()
                done.wait(5)
        th = threading.Thread(target=holder)
        th.start()
        assert started.wait(5)
        threading.Timer(0.3, done.set).start()
        with L.transaction(by="free") as t2:
            t2.add("s", "p", "second")
        th.join(10)
        assert t2.rev.id == 2 and L.at()["s", "p"] == "second"


# ---------------------------------------------------------------- Rev


class TestRevFields:
    def test_id_tx_ledger(self, L):
        r = put(L, ("s", "p", "o"), by="human:dan")
        assert r.id == 1 and r.tx == "ledger/tx/1" and r.ledger is L
        assert r[r.tx, "by"] == "human:dan"
        assert r.ledger.at(r.id) == r and L.at(0) < r


class TestRevGetitem:
    def test_three_forms(self, L):
        put(L, ("code/sv-pipe", "version", "0.2.1"))
        r2 = put(L, ("code/sv-pipe", "version", "0.2.2"))
        rev = L.at()
        assert rev["code/sv-pipe"] == ("version", "0.2.2")
        assert rev["code/sv-pipe", "version"] == "0.2.2"
        assert rev["code/sv-pipe", "version", "0.2.2"] == r2
        assert rev["code/sv-pipe", "version", "0.2.1"].id == 1   # a superseded value: the Rev that set it

    def test_none_and_several(self, L):
        put(L, ("ledger/pred/tag", "cardinality", "many"), ("s", "tag", "a"), ("s", "tag", "b"))
        rev = L.at()
        with pytest.raises(KeyError):
            rev["nobody", "p"]
        with pytest.raises(Multiple):
            rev["s", "tag"]
        with pytest.raises(Multiple):
            rev["s"]
        with pytest.raises(KeyError):
            rev["s", "tag", "zz"]
        assert not isinstance(Multiple("x"), KeyError)


class TestRevGet:
    def test_default_and_multiple(self, L):
        put(L, ("ledger/pred/tag", "cardinality", "many"), ("s", "tag", "a"), ("s", "tag", "b"), ("s", "v", "1"))
        rev = L.at()
        assert rev.get("s", "v") == "1"
        assert rev.get("s", "nope") is None and rev.get("s", "nope", default="d") == "d"
        with pytest.raises(Multiple):
            rev.get("s", "tag")

    def test_since(self, L):
        a = put(L, ("s", "v", "1"))
        put(L, ("t", "v", "2"))
        rev = L.at()
        assert rev.get("s", "v", since=a) is None
        assert rev.get("t", "v", since=a) == "2"


class TestRevAll:
    def test_forms(self, L):
        put(L, ("code/sv-pipe", "version", "0.2.2"), ("code/sv-pipe", "commit", "b48dca7c"))
        put(L, ("ledger/pred/kwargs.bins", "index", "true"))
        rev = L.at()
        assert ("code/sv-pipe", "version", "0.2.2") in rev.all()
        assert rev.all("code/sv-pipe") == [("version", "0.2.2"), ("commit", "b48dca7c")]
        assert rev.all("code/sv-pipe", "version") == ["0.2.2"]
        assert rev.all("ledger/pred/kwargs.bins", "index", "true") == [L.at(2)]
        assert rev.all(since=L.at(1)) == [("ledger/tx/2", "by", "t"), ("ledger/pred/kwargs.bins", "index", "true")]

    def test_value_rows_are_unloaded_refs(self, L):
        with L.transaction(by="t") as t:
            t.add("model/shot", "value", Pickled({"w": 1}))
        refs = L.at().all("model/shot", "value")
        assert len(refs) == 1 and isinstance(refs[0], Ref) and refs[0].load().obj == {"w": 1}

    def test_json_document(self, L):
        put(L, ("s", "metrics", {"g5": 0.93, "g1": [1, 2]}))
        assert L.at()["s", "metrics"] == {"g5": 0.93, "g1": [1, 2]}


class TestRevContains:
    def test_held_only(self, L):
        put(L, ("s", "p", "1"))
        put(L, ("s", "p", "2"))
        rev = L.at()
        assert ("s", "p", "2") in rev and ("s", "p", "1") not in rev
        assert ("s", "p", "1") in L.at(1)


class TestRevRefs:
    @pytest.fixture
    def three(self, L):
        put(L, ("run/0-2-2/G1", "kind", "Run"), ("run/0-2-2/G5", "kind", "Run"), ("run/0-2-3/G5", "kind", "Run"),
            ("ledger/pred/kwargs.game", "index", "true"))
        return L

    def test_prefix_glob_and_exact(self, three):
        rev = three.at()
        assert [r.subject for r in rev.refs(s="run/0-2-2/*")] == ["run/0-2-2/G1", "run/0-2-2/G5"]
        assert [r.subject for r in rev.refs(s="run/0-2-3/G5")] == ["run/0-2-3/G5"]
        with pytest.raises(ValueError):
            rev.refs(s="*/G5")

    def test_where_any_value_and_declared_indexes(self, three):
        rev = three.at()
        assert len(rev.refs(where={"kind": None})) == 3
        assert [r.subject for r in rev.refs(s="ledger/pred/*", where={"index": "true"})] == \
            ["ledger/pred/kwargs.game"]

    def test_one(self, three):
        rev = three.at()
        assert rev.refs(s="run/0-2-3/G5", one=True).subject == "run/0-2-3/G5"
        with pytest.raises(Multiple):
            rev.refs(s="run/*", one=True)
        with pytest.raises(KeyError):
            rev.refs(s="nothing/*", one=True)

    def test_unindexed(self, three):
        rev = three.at()
        with pytest.raises(Unindexed):
            rev.refs(where={"result.metrics.g5": "0.93"})
        with pytest.raises(Unindexed):
            rev.refs(gamez="G5")                     # a typo in a kwargs key is loud
        assert rev.refs(game="G5") == []             # declared, no rows yet
        assert rev.refs(where={"color": "red"}) == []  # a plain predicate with no rows

    def test_since(self, three):
        a = three.at()
        put(three, ("run/0-2-2/G1", "version", "0.2.2"))
        assert [r.subject for r in three.at().refs(where={"version": None}, since=a)] == ["run/0-2-2/G1"]
        assert three.at().refs(where={"kind": None}, since=a) == []

    def test_pinned_at_the_query_rev(self, three):
        rev = three.at()
        r = rev.refs(s="run/0-2-2/G1", one=True)
        put(three, ("run/0-2-2/G1", "kind", "Other"))
        assert r.rev == rev and r.rev["run/0-2-2/G1", "kind"] == "Run"


class TestRevSelect:
    def test_tuples_in_key_order(self, coded):
        rev = coded.at()
        rev.eval("l2fns.scaled", x=2)
        rev = coded.at()
        rev.eval("l2fns.scaled", x=5, by=2)
        got = coded.at().select(("x", "by"), fn="l2fns.scaled")
        assert sorted(got) == [("2", "3"), ("5", "2")]
        one = coded.at().select(("by",), fn="l2fns.scaled", x=5, one=True)
        assert one == ("2",)

    def test_bare_key_reads_the_predicate_when_no_kwargs_row(self, L):
        put(L, ("code/sv-pipe", "version", "0.2.3"), ("model/x", "version", "2.1.0"))
        assert L.at().select(("version",), where={"version": None}) == [("0.2.3",), ("2.1.0",)]

    def test_keys_required_as_tuple(self, L):
        with pytest.raises(TypeError):
            L.at().select("version")


class TestRevLoad:
    def test_value_and_pointer(self, L):
        v = Note("hello")
        with L.transaction(by="t") as t:
            subj = t.seal(v)
            t.add("notes/hello", "value", v)
        again = L.at().load("notes/hello")
        assert again.text == "hello" and again.subject == subj and again.sealed
        with pytest.raises(KeyError):
            L.at().load("nothing")


class TestRevLoadFn:
    def test_fields(self, L, envbox):
        f = L.at().load_fn("l2fns.scaled")
        assert isinstance(f, Fn) and f.name == "l2fns.scaled" and f.mode == "base" and f.mount is None
        assert f.module.name == "l2fns.py" and f.sha.startswith("sha256:")
        assert list(f.signature.parameters) == ["x", "by"]
        assert f.env == envbox.env and f.subject.startswith("ledger/fn/l2fns.scaled/")

    def test_unresolvable(self, L):
        with pytest.raises(ImportError):
            L.at().load_fn("l2fns.nope")
        with pytest.raises(TypeError):
            L.at().load_fn("nodots")

    def test_mounted_prefix_is_sandbox_and_not_built(self, L):
        put(L, ("ledger/mount/l2fns", "root", "tests/ledger2"))
        with pytest.raises(NotImplementedError):
            L.at().load_fn("l2fns.scaled")

    @pytest.mark.skip(reason="UnmountedImport needs the sandbox's MountFinder (out of scope for the spike)")
    def test_unmounted_import(self):
        raise UnmountedImport("unreachable in base mode")


class TestRevEval:
    def test_string_only(self, coded):
        import l2fns
        with pytest.raises(TypeError):
            coded.at().eval(l2fns.double, x=1)

    def test_memo_values(self, coded):
        with pytest.raises(ValueError):
            coded.at().eval("l2fns.double", x=1, memo="got")
        with pytest.raises(ValueError):
            coded.at().eval("l2fns.double", x=1, memo=1.5)

    def test_keys(self, coded):
        with pytest.raises(TypeError):
            coded.at().eval("l2fns.double", y=1)
        with pytest.raises(TypeError):
            coded.at().eval("l2fns.double", x=[1])


# ---------------------------------------------------------------- Transaction


class TestTransactionFields:
    def test_tx_base_rev(self, L):
        put(L, ("s", "p", "o"))
        with L.transaction(by="t") as t:
            assert t.tx.startswith("ledger/tx/") and t.tx != "ledger/tx/2"
            assert t.base.id == 1
            with pytest.raises(RuntimeError):
                t.rev
        assert t.rev.id == 2

    def test_base_without_lock_is_a_snapshot(self, L):
        put(L, ("s", "p", "1"))
        with L.transaction(by="a") as t:
            put(L, ("s", "p", "2"))
            assert t.base["s", "p"] == "1"
            t.add("s", "q", "x")
        assert t.rev.id == 3


class TestTransactionAdd:
    def test_objects(self, L):
        with L.transaction(by="t") as t:
            t.add("s", "str", "0.2.2")
            t.add("s", "doc", {"a": [1, 2]})
            t.add("s", "value", Note("n"))
            t.add("s", "obj", {1, 2})                 # pickleable, not JSON: wrapped in Pickled
        rev = t.rev
        assert rev["s", "str"] == "0.2.2" and rev["s", "doc"] == {"a": [1, 2]}
        assert rev["s", "value"].load().text == "n"
        assert rev["s", "obj"].load().obj == {1, 2}
        assert rev["s", "obj"].type is Pickled

    def test_value_predicate_is_always_an_artifact(self, L):
        with L.transaction(by="t") as t:
            t.add("model/shot", "value", {"weights": [1, 2]})
            t.add("model/name", "value", "a string")
        rev = L.at()
        assert isinstance(rev["model/shot", "value"], Ref)
        assert rev.load("model/shot").obj == {"weights": [1, 2]} and rev.load("model/name").obj == "a string"

    def test_scalars_refused(self, L):
        with L.transaction(by="t") as t:
            for bad in (16, 0.5, True, None):
                with pytest.raises(ValueError):
                    t.add("s", "p", bad)
        assert t.rev.all("s") == []

    def test_add_never_retracts(self, L):
        put(L, ("s", "p", "1"))
        put(L, ("s", "p", "2"))
        assert [r[5] for r in L._store.rows(2)] == [True] * 4

    def test_ref_object(self, L):
        put(L, ("game/G7", "court", "hs"))
        with L.transaction(by="t") as t:
            t.add("gameset", "member", Ref(L.at(), "game/G7"))
        r = L.at()["gameset", "member"]
        assert isinstance(r, Ref) and r.subject == "game/G7" and r.hash is None


class TestTransactionRemove:
    def test_many_and_one(self, L):
        put(L, ("ledger/pred/tag", "cardinality", "many"), ("s", "tag", "a"), ("s", "tag", "b"), ("s", "v", "1"))
        with L.transaction(by="t") as t:
            t.remove("s", "tag", "a")
            t.remove("s", "v", "1")
        rev = L.at()
        assert rev.all("s", "tag") == ["b"]
        assert rev.get("s", "v") is None
        assert L.at(1)["s", "v"] == "1"

    def test_remove_of_another_value_is_a_noop_on_one(self, L):
        put(L, ("s", "v", "1"))
        with L.transaction(by="t") as t:
            t.remove("s", "v", "2")
        assert L.at()["s", "v"] == "1"


class TestTransactionSeal:
    def test_rows_and_fields(self, L, envbox):
        put(L, ("code/testrepo", "version", "1.0.0"), ("code/testrepo", "commit", "abc1234"))
        with L.transaction(by="t") as t:
            t.add("run/G5", "value", Note("run"))
        run = L.at().load("run/G5")
        v = Note("shots")
        with L.transaction(by="human:dan") as t:
            subj = t.seal(v, deps=[run])
            assert not v.sealed
        assert subj.startswith("Note/") and v.sealed and v.subject == subj
        rows = dict(L.at().all(subj))
        assert rows["kind"] == "Note" and rows["provenance"] == "seal"
        assert rows["value"].hash == v.hash
        assert rows["trace.dat:run/G5"] == run.hash
        assert rows["trace.code/testrepo"] == "1.0.0+abc1234"
        assert rows["trace.uv.lock"] == envbox.env.lock and rows["trace.platform"] == envbox.env.platform
        assert dict(v.trace) == {k[len("trace."):]: x for k, x in rows.items() if k.startswith("trace.")}
        assert v.matches(L.at())

    def test_idempotent(self, L):
        with L.transaction(by="t") as t:
            a = t.seal(Note("x"))
        n = len(L.at().all())
        with L.transaction(by="t") as t:
            b = t.seal(Note("x"))
        assert a == b and len(L.at().all()) == n + 1          # only the second tx's `by` row
        with L.transaction(by="t") as t:
            c = t.seal(Note("y"))
        assert c != a

    def test_exists_on_seal_predicate_and_annotation_allowed(self, L):
        with L.transaction(by="t") as t:
            subj = t.seal(Note("x"))
            t.add(subj, "note", "same tx annotation")
        with L.transaction(by="t") as t:
            t.add(subj, "verdict", "good")
        assert L.at()[subj, "verdict"] == "good"
        for p in ("value", "kind", "provenance", "trace.platform", "kwargs.k", "result.r", "fn"):
            with pytest.raises(Exists):
                with L.transaction(by="t") as t:
                    t.add(subj, p, "rewritten")
        with pytest.raises(Exists):
            with L.transaction(by="t") as t:
                t.remove(subj, "kind", "Note")
        assert L.at()[subj, "kind"] == "Note"

    def test_dep_checks(self, L):
        with L.transaction(by="t") as t:
            t.add("run/G5", "value", Note("run"))
        run = L.at().load("run/G5")
        with L.transaction(by="t") as t:
            t.add("run/G5", "value", Note("changed"))
        with pytest.raises(ValueError):
            with L.transaction(by="t") as t:
                t.seal(Note("x"), deps=[Note("loose")])
        with L.transaction(by="t") as t:      # read at another revision: subject@rev, still checked there
            subj = t.seal(Note("x"), deps=[run])
        assert f"trace.dat:run/G5@{run.rev.id}" in dict(L.at().all(subj))

    def test_fresh_eval_value_as_a_dep(self, coded):
        # A miss hands back a value whose rev is the evaluating revision, which predates the
        # seal; the dep check must still find the (immutable) memo subject.
        m = coded.at().eval("l2fns.double", x=2)
        assert m.rev.id < coded.at().id
        with coded.transaction(by="t") as t:
            subj = t.seal(Note("report"), deps=[m])
        assert coded.at()[subj, f"trace.dat:{m.subject}"] == m.hash
        with coded.transaction(by="t") as t:   # eval inside the block: sealed after t.base
            m3 = coded.at().eval("l2fns.double", x=3)
            t.seal(Note("report 3"), deps=[m3])
        with pytest.raises(ValueError):
            with coded.transaction(by="t") as t:
                fake = Note("forged")
                fake._provenance(subject=m.subject, rev=m.rev, trace={}, sealed=True)
                t.seal(Note("x"), deps=[fake])

    def test_several_seals_and_a_pointer(self, L):
        a, b = Note("a"), Note("b")
        with L.transaction(by="t") as t:
            sa = t.seal(a)
            sb = t.seal(b, deps=[a])
            t.add("ptr", "value", b)
        assert L.at()["ptr", "value"].subject == sb
        assert dict(b.trace)[f"dat:{sa}"] == a.hash

    def test_failed_transaction_leaves_value_unsealed(self, L):
        v = Note("x")
        with pytest.raises(RuntimeError):
            with L.transaction(by="t") as t:
                t.seal(v)
                raise RuntimeError
        assert not v.sealed and v.subject is None and L.at().id == 0

    def test_index_rows_for_declared_paths(self, L):
        @dataclasses.dataclass
        class R:
            metrics: dict
        put(L, ("ledger/pred/result.metrics.g5", "index", "true"), ("ledger/pred/result.nothing", "index", "true"))
        with L.transaction(by="t") as t:
            subj = t.seal(Pickled({"metrics": {"g5": 0.93}}))
        assert L.at()[subj, "result.metrics.g5"] == "0.93"
        assert L.at().get(subj, "result.nothing") is None
        assert [r.subject for r in L.at().refs(where={"result.metrics.g5": 0.93})] == [subj]

    def test_fn_dep_pins_the_code(self, coded):
        f = coded.at().load_fn("l2fns.double")
        with coded.transaction(by="t") as t:
            subj = t.seal(Note("hand"), deps=[f])
        rev = coded.at()
        assert rev[subj, "trace.fn"] == f.subject
        assert rev[f.subject, "name"] == "l2fns.double" and rev[f.subject, "mode"] == "base"


# ---------------------------------------------------------------- Ref


class TestRef:
    def test_fields_and_load(self, L):
        with L.transaction(by="t") as t:
            t.add("model/shot", "value", Note("v1"))
        rev = L.at()
        r = Ref(rev, "model/shot")
        assert r.rev == rev and r.subject == "model/shot" and r.hash.startswith("sha256:") and r.type is Note
        assert r.load().text == "v1" and r.load() is r.load()
        assert dict(r.rev.all(r.subject))["value"] == r
        assert Ref(rev, "no/value").type is None and Ref(rev, "no/value").hash is None

    def test_pinned_and_frozen(self, L):
        with L.transaction(by="t") as t:
            t.add("model/shot", "value", Note("v1"))
        r = Ref(L.at(), "model/shot")
        with L.transaction(by="t") as t:
            t.add("model/shot", "value", Note("v2"))
        assert r.load().text == "v1" and Ref(L.at(), "model/shot").load().text == "v2"
        with pytest.raises(AttributeError):
            r.subject = "x"

    def test_equal_by_bytes(self, L):
        with L.transaction(by="t") as t:
            t.add("a", "value", Note("same"))
            t.add("b", "value", Note("same"))
        rev = L.at()
        assert Ref(rev, "a") == Ref(rev, "b") and hash(Ref(rev, "a")) == hash(Ref(rev, "b"))

    def test_unimportable_class_is_loud(self, L):
        with L.transaction(by="t") as t:
            t.add("x", "value", Note("n"))
        from dvc_dat.ledger2.codec import ref_text
        h = L.at()["x", "value"].hash
        with L._store.writer(5, locked=False) as w:   # a row naming a class that no longer imports
            w.insert(w.next_rev(), [("y", "value", ref_text("gone.module.Klass", h, None), True)])
        with pytest.raises(ImportError):
            Ref(L.at(), "y").load()


# ---------------------------------------------------------------- Value


class TestValue:
    def test_hash_same_as_diff(self):
        a, b = Note("x"), Note("x")
        assert a.hash == b.hash and a.same_as(b) and not a.same_as(None) and not a.same_as(Note("y"))
        a._provenance(subject=None, rev=None, trace={"k": "1", "j": "2"}, sealed=False)
        b._provenance(subject=None, rev=None, trace={"k": "1", "j": "3", "m": "4"}, sealed=False)
        assert a.diff(b) == {"j": ("2", "3"), "m": (None, "4")}

    def test_defaults(self):
        v = Note("x")
        assert v.subject is None and v.rev is None and dict(v.trace) == {} and v.sealed is False

    def test_base_class_is_abstract(self):
        with pytest.raises(NotImplementedError):
            Value().encode()

    def test_pickled_table_dat_round_trip(self, L, tmp_path):
        folder = tmp_path / "d"
        (folder / "sub").mkdir(parents=True)
        (folder / "a.txt").write_text("A")
        (folder / "sub" / "b.bin").write_bytes(b"\x00\x01")
        df = pd.DataFrame({"g": ["G1", "G5"], "n": [1, 2]})
        with L.transaction(by="t") as t:
            t.add("p", "value", Pickled({"k": (1, 2)}))
            t.add("tab", "value", Table(df))
            t.add("dat", "value", Dat(folder))
        rev = L.at()
        assert rev.load("p").obj == {"k": (1, 2)}
        assert rev.load("tab").table.equals(df)
        d = rev.load("dat")
        assert (d.path / "a.txt").read_text() == "A" and (d.path / "sub" / "b.bin").read_bytes() == b"\x00\x01"
        assert d.same_as(Dat(folder))


# ---------------------------------------------------------------- Fn


class TestFn:
    def test_call_is_eval(self, coded):
        rev = coded.at()
        f = rev.load_fn("l2fns.double")
        a = f(x=3)
        b = coded.at().eval("l2fns.double", x=3)
        assert a.obj == {"x": 3, "out": 6} and a.subject == b.subject

    def test_pinned_to_its_rev(self, coded):
        put(coded, ("model/shot", "version", "1.0.0"))
        f = coded.at().load_fn("l2fns.uses_model")
        put(coded, ("model/shot", "version", "2.0.0"))
        assert f(game="G5").obj == "G5@1.0.0"
        assert coded.at().eval("l2fns.uses_model", game="G5").obj == "G5@2.0.0"


# ---------------------------------------------------------------- module


class TestBump:
    def test_patch_from_nothing(self, L):
        with L.transaction(by="t") as t:
            assert bump(t, "code/sv-pipe") == "0.0.1"
        assert L.at()["code/sv-pipe", "version"] == "0.0.1"

    def test_minor_major_need_confirm(self, L):
        put(L, ("ledger", "version", "3.1.4"))
        with L.transaction(by="t") as t:
            with pytest.raises(ValueError):
                bump(t, "ledger", "minor")
            with pytest.raises(ValueError):
                bump(t, "ledger", "minor", confirm=lambda a, b: False)
            asked = []
            assert bump(t, "ledger", "minor", confirm=lambda a, b: asked.append((a, b)) or True) == "3.2.0"
        assert asked == [("3.1.4", "3.2.0")]
        with L.transaction(by="t") as t:
            assert bump(t, "ledger", "major", confirm=lambda a, b: True) == "4.0.0"

    def test_bad_inputs(self, L):
        put(L, ("s", "version", "v2"))
        with L.transaction(by="t") as t:
            with pytest.raises(ValueError):
                bump(t, "s")
            with pytest.raises(ValueError):
                bump(t, "x", "micro")


class TestAttr:
    def test_walks(self):
        @dataclasses.dataclass
        class Rec:
            result: dict
        r = Rec({"metrics": {"g5": 0.93}, "list": [10, 20]})
        assert attr(r, "result.metrics.g5") == 0.93
        assert attr({"a": {"b": "c"}}, "a.b") == "c"
        assert attr(r, "result.list.1") == 20
        with pytest.raises(KeyError):
            attr(r, "result.metrics.g6")
        with pytest.raises(KeyError):
            attr(r, "nothing.at.all")


class TestExceptions:
    def test_hierarchy(self):
        for e in (Multiple, NotEvaluated, UnmountedImport, UntracedRead, LockTimeout, Unindexed, Exists):
            assert issubclass(e, LedgerError)
        assert issubclass(LockTimeout, TimeoutError) and issubclass(UnmountedImport, ImportError)

    @pytest.mark.skip(reason="UntracedRead needs the sandbox's audit hook (out of scope for the spike)")
    def test_untraced_read(self):
        raise UntracedRead("unreachable in base mode")


def test_rev_is_hashable_and_ordered(L):
    put(L, ("s", "p", "o"))
    assert {L.at(1), L.at(1)} == {L.at(1)} and isinstance(L.at(1), Rev)
