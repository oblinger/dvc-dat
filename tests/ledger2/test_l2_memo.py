"""Leg 4: the memo. Hit, miss on a trace change, stale entries kept under their own subject,
``memo=False`` and ``memo="get"``, ``diff`` naming exactly what moved, ``NotEvaluated``."""

import importlib
import sys

import pytest

import l2fns
from dvc_dat.ledger2 import NotEvaluated, Pickled, Ref
from dvc_dat.ledger2.fn import Code, Env


def put(L, *rows):
    with L.transaction(by="t") as t:
        for r in rows:
            t.add(*r)
    return t.rev


def calls(name):
    return l2fns.CALLS[name]


class TestHit:
    def test_second_eval_is_a_hit(self, coded):
        n = calls("double")
        a = coded.at().eval("l2fns.double", x=4)
        b = coded.at().eval("l2fns.double", x=4)
        assert calls("double") == n + 1
        assert a.sealed and b.sealed and a.subject == b.subject and a.same_as(b)
        assert b.obj == {"x": 4, "out": 8} and b.rev == coded.at()

    def test_defaults_are_part_of_the_keys(self, coded):
        n = calls("scaled")
        a = coded.at().eval("l2fns.scaled", x=2)
        b = coded.at().eval("l2fns.scaled", x=2, by=3)
        assert calls("scaled") == n + 1 and a.subject == b.subject

    def test_number_and_text_are_one_key(self, coded):
        a = coded.at().eval("l2fns.scaled", x=2)
        assert coded.at().eval("l2fns.scaled", x=2, memo="get").subject == a.subject
        assert coded.at()[a.subject, "kwargs.x"] == "2"

    def test_entry_rows(self, coded, envbox):
        v = coded.at().eval("l2fns.double", x=1)
        rows = dict(coded.at().all(v.subject))
        assert v.subject.startswith("Pickled/")
        assert rows["fn"] == "l2fns.double" and rows["provenance"] == "eval" and rows["kind"] == "Pickled"
        assert rows["kwargs.x"] == "1" and rows["trace.fn"].startswith("ledger/fn/l2fns.double/")
        assert rows["trace.code/testrepo"] == "1.0.0+abc1234"
        assert dict(v.trace) == {"fn": rows["trace.fn"], "code/testrepo": "1.0.0+abc1234",
                                 "uv.lock": envbox.env.lock, "platform": envbox.env.platform}
        f = rows["trace.fn"]
        assert coded.at()[f, "name"] == "l2fns.double" and coded.at()[f, "mode"] == "base"
        assert coded.at()[v.subject, "value"].hash == v.hash

    def test_refs_find_by_dotted_name(self, coded):
        coded.at().eval("l2fns.double", x=1)
        coded.at().eval("l2fns.double", x=2)
        refs = coded.at().refs(fn="l2fns.double")
        assert len(refs) == 2 and all(isinstance(r, Ref) for r in refs)
        assert coded.at().refs(fn="l2fns.double", x=2, one=True).load().obj["out"] == 4

    def test_value_return_is_kept_not_wrapped(self, coded):
        v = coded.at().eval("l2fns.returns_value", x=1)
        assert isinstance(v, Pickled) and v.obj == [1]

    def test_no_keys(self, coded):
        n = calls("no_keys")
        assert coded.at().eval("l2fns.no_keys").obj == "constant"
        coded.at().eval("l2fns.no_keys")
        assert calls("no_keys") == n + 1


class TestMiss:
    def test_read_binding_moves(self, coded):
        put(coded, ("model/shot", "version", "1.0.0"))
        a = coded.at().eval("l2fns.uses_model", game="G5")
        assert a.trace["model/shot"] == "1.0.0"
        put(coded, ("model/shot", "version", "1.1.0"))
        n = calls("uses_model")
        b = coded.at().eval("l2fns.uses_model", game="G5")
        assert calls("uses_model") == n + 1 and b.obj == "G5@1.1.0"
        assert a.diff(b) == {"model/shot": ("1.0.0", "1.1.0")}
        assert not a.matches(coded.at()) and b.matches(coded.at())

    def test_stale_entry_kept_under_its_own_subject(self, coded):
        put(coded, ("model/shot", "version", "1.0.0"))
        a = coded.at().eval("l2fns.uses_model", game="G5")
        put(coded, ("model/shot", "version", "1.1.0"))
        b = coded.at().eval("l2fns.uses_model", game="G5")
        assert a.subject != b.subject
        found = {r.subject for r in coded.at().refs(fn="l2fns.uses_model", game="G5")}
        assert found == {a.subject, b.subject}
        assert coded.at().load(a.subject).obj == "G5@1.0.0"
        assert coded.at().eval("l2fns.uses_model", game="G5").subject == b.subject

    def test_old_rev_still_hits_the_old_entry(self, coded):
        put(coded, ("model/shot", "version", "1.0.0"))
        old = coded.at()
        a = old.eval("l2fns.uses_model", game="G5")
        put(coded, ("model/shot", "version", "1.1.0"))
        coded.at().eval("l2fns.uses_model", game="G5")
        n = calls("uses_model")
        assert coded.at(old.id).eval("l2fns.uses_model", game="G5").subject == a.subject
        assert calls("uses_model") == n

    def test_dat_load_moves(self, coded):
        with coded.transaction(by="t") as t:
            t.add("data/norm", "value", Pickled("norm-6"))
        a = coded.at().eval("l2fns.uses_norm", game="G1")
        assert a.trace["dat:data/norm"] == Ref(coded.at(), "data/norm").hash
        with coded.transaction(by="t") as t:
            t.add("data/norm", "value", Pickled("norm-7"))
        b = coded.at().eval("l2fns.uses_norm", game="G1")
        assert b.obj["norm"] == "norm-7" and list(a.diff(b)) == ["dat:data/norm"]

    def test_nested_eval_item(self, coded):
        put(coded, ("model/shot", "version", "1.0.0"))
        a = coded.at().eval("l2fns.chain", game="G5")
        inner = coded.at().eval("l2fns.uses_model", game="G5", memo="get")
        key = 'eval:l2fns.uses_model{"game":"G5"}'
        assert a.trace[key] == inner.hash and a.obj == "G5@1.0.0!"
        n, m = calls("chain"), calls("uses_model")
        coded.at().eval("l2fns.chain", game="G5")
        assert (calls("chain"), calls("uses_model")) == (n, m)
        put(coded, ("model/shot", "version", "2.0.0"))
        b = coded.at().eval("l2fns.chain", game="G5")
        assert (calls("chain"), calls("uses_model")) == (n + 1, m + 1) and b.obj == "G5@2.0.0!"

    def test_query_read_item(self, coded):
        a = coded.at().eval("l2fns.lists_versions")
        assert a.obj == ["code/testrepo"]
        put(coded, ("model/new", "version", "0.0.1"))
        b = coded.at().eval("l2fns.lists_versions")
        assert b.obj == ["code/testrepo", "model/new"] and len(a.diff(b)) == 1

    def test_platform_and_lock_move(self, coded, envbox):
        a = coded.at().eval("l2fns.double", x=9)
        envbox.set(platform="other-card")
        b = coded.at().eval("l2fns.double", x=9)
        assert a.diff(b) == {"platform": ("test-platform", "other-card")}
        envbox.set(lock="sha256:lock-2")
        c = coded.at().eval("l2fns.double", x=9)
        assert list(b.diff(c)) == ["uv.lock"]

    def test_code_change_moves_the_fn_subject(self, coded, tmp_path, monkeypatch):
        pkg = tmp_path / "l2edit.py"
        pkg.write_text("def f(rev, *, x):\n    return x + 1\n")
        monkeypatch.syspath_prepend(str(tmp_path))
        sys.modules.pop("l2edit", None)
        a = coded.at().eval("l2edit.f", x=1)
        pkg.write_text("def f(rev, *, x):\n    return x + 20\n")  # a new size: the .pyc is stale
        importlib.reload(sys.modules["l2edit"])
        b = coded.at().eval("l2edit.f", x=1)
        assert (a.obj, b.obj) == (2, 21) and list(a.diff(b)) == ["fn"]
        assert len(coded.at().refs(fn="l2edit.f")) == 2
        sys.modules.pop("l2edit", None)

    def test_bump_of_an_unread_subject_is_a_hit(self, coded):
        put(coded, ("model/shot", "version", "1.0.0"))
        a = coded.at().eval("l2fns.uses_model", game="G1")
        with coded.transaction(by="t") as t:
            t.add("data/norm", "version", "8.0.0")
        n = calls("uses_model")
        assert coded.at().eval("l2fns.uses_model", game="G1").subject == a.subject
        assert calls("uses_model") == n


class TestMemoFlags:
    def test_memo_false_runs_and_seals_nothing(self, coded):
        a = coded.at().eval("l2fns.double", x=5)
        top = coded.at().id
        n = calls("double")
        c = coded.at().eval("l2fns.double", x=5, memo=False)
        assert calls("double") == n + 1 and coded.at().id == top
        assert not c.sealed and c.subject is None and c.same_as(a) and dict(c.trace) == dict(a.trace)

    def test_memo_get(self, coded):
        n = calls("double")
        assert coded.at().eval("l2fns.double", x=6, memo="get") is None
        assert calls("double") == n and coded.at().refs(fn="l2fns.double") == []
        a = coded.at().eval("l2fns.double", x=6)
        assert coded.at().eval("l2fns.double", x=6, memo="get").subject == a.subject

    def test_failure_seals_nothing(self, coded):
        top = coded.at().id
        with pytest.raises(RuntimeError):
            coded.at().eval("l2fns.boom", x=1)
        assert coded.at().id == top


class TestNotEvaluated:
    def test_commit_disagrees(self, coded, envbox):
        envbox.code(commit="fff9999")
        with pytest.raises(NotEvaluated):
            coded.at().eval("l2fns.double", x=1)
        with pytest.raises(NotEvaluated):
            coded.at().eval("l2fns.double", x=1, memo=False)
        assert coded.at().eval("l2fns.double", x=1, memo="get") is None

    def test_dirty_tree(self, coded, envbox):
        envbox.code(dirty=True)
        with pytest.raises(NotEvaluated):
            coded.at().eval("l2fns.double", x=1)

    def test_no_binding(self, L):
        with pytest.raises(NotEvaluated):
            L.at().eval("l2fns.double", x=1)

    def test_outside_any_checkout(self, coded, envbox):
        envbox.env = Env({}, "<none>", "p")
        with pytest.raises(NotEvaluated):
            coded.at().eval("l2fns.double", x=1)

    def test_hit_at_a_rev_this_env_cannot_run(self, coded, envbox):
        a = coded.at().eval("l2fns.double", x=2)
        old = coded.at()
        with coded.transaction(by="t") as t:
            t.add("code/testrepo", "version", "1.1.0")
            t.add("code/testrepo", "commit", "bbb2222")
        envbox.env = Env({"testrepo": Code("1.1.0", "bbb2222")}, envbox.env.lock, envbox.env.platform)
        assert old.eval("l2fns.double", x=2).subject == a.subject        # a hit: reading is always allowed
        with pytest.raises(NotEvaluated):
            old.eval("l2fns.double", x=3)                               # a miss: 1.0.0 cannot run here
        assert coded.at().eval("l2fns.double", x=3).obj["out"] == 6
