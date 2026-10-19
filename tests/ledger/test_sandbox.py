"""Sandbox mode: a mounted package in a real tiny git checkout, run in a worker (discovery, no stand-in)."""

import subprocess
import sys
import textwrap

import pytest

from dvc_dat.ledger import (ConfinedWrite, Ledger, NotEvaluated, UnmountedImport, UntracedRead, bump,
                             set_env_provider)
from dvc_dat.ledger.sandbox import shutdown

PKG = {
    "pyproject.toml": '[project]\nname = "sbx-repo"\nversion = "0.1.0"\n',
    "sbx/__init__.py": "",
    "sbx/other.py": "X = 1\n",
    "sbx/stage/__init__.py": "",
    "flat/calc.py": textwrap.dedent('''
        from dvc_dat.ledger import ledger_fn
        from flatpkg import util

        @ledger_fn
        def area(rev, *, side: int) -> dict:
            return {"area": util.square(side)}
    '''),
    "flat/util.py": "def square(x):\n    return x * x\n",
    "sbx/stage/kinds.py": textwrap.dedent('''
        from dvc_dat.ledger import Value, ledger_class, ledger_fn

        @ledger_class(preds=("game",))
        class Tagged(Value):
            def __init__(self, data: bytes):
                self.data = data
            def encode(self) -> bytes:
                return self.data
            @classmethod
            def decode(cls, data, store):
                return cls(data)

        @ledger_fn
        def tagged(rev, *, game: str) -> Tagged:
            v = Tagged(game.encode())
            v.preds["game"] = game
            return v
    '''),
    "sbx/stage/helper.py": "def double(x):\n    return 2 * x\n",
    "sbx/stage/fns.py": textwrap.dedent('''
        import importlib
        from pathlib import Path
        from dvc_dat.ledger import Dat, ledger_fn

        @ledger_fn
        def count(rev, *, game: str) -> dict:
            n = int(rev[f"game/{game}", "n"])
            return {"n": importlib.import_module("sbx.stage.helper").double(n)}

        @ledger_fn
        def nested(rev, *, game: str) -> dict:
            return {"inner": rev.eval("sbx.stage.fns.count", game=game).obj}

        @ledger_fn
        def folder(rev, *, game: str, work: Path) -> Dat:
            (work / "f.txt").write_text(game)
            return Dat(work)

        @ledger_fn
        def borrow(rev, *, game: str) -> dict:
            from sbx import other
            return {"x": other.X}

        @ledger_fn
        def snoop(rev, *, game: str) -> dict:
            return {"n": len(Path("/etc/hosts").read_text())}

        @ledger_fn
        def scribble(rev, *, game: str) -> dict:
            Path("/tmp/ledger-sandbox-scribble.txt").write_text("x")
            return {}
    '''),
}


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def sbx(tmp_path, monkeypatch):
    repo = tmp_path / "sbx-repo"
    for rel, text in PKG.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "one")
    monkeypatch.syspath_prepend(str(repo))
    for m in [m for m in sys.modules if m == "sbx" or m.startswith("sbx.")]:
        del sys.modules[m]
    import sbx  # noqa: F401  (discovery sees the checkout)
    old = set_env_provider(None)
    L = Ledger(tmp_path / "ledger", create=True)
    with L.transaction(by="t") as t:
        t.add("db/mount/sbx.stage", "db/root", "sbx/stage")
        t.add("db/mount/sbx.stage", "db/repo", "sbx-repo")
        t.add("db/mount/flatpkg", "db/root", "flat")          # a plain folder, no __init__.py
        t.add("db/mount/flatpkg", "db/repo", "sbx-repo")
        t["game/G1"] = {"n": "3"}
        bump(t, "code/sbx-repo")
    yield L, repo
    shutdown()
    set_env_provider(old)


def test_sandboxed_eval_seals_records_loaded_modules_and_hits(sbx):
    L, repo = sbx
    f = L.at().load_fn("sbx.stage.fns.count")
    assert f.mode == "sandbox" and f.mount == "sbx.stage" and f.module == repo / "sbx/stage/fns.py"
    v = L.at().eval("sbx.stage.fns.count", game="G1")
    assert v.sealed and v.obj == {"n": 6} and L.at()[v.subject, "db/provenance"] == "eval:sandbox"
    mods = L.at()[v.trace["fn"], "db/modules"]
    assert sorted(mods) == ["sbx/stage/__init__.py", "sbx/stage/fns.py", "sbx/stage/helper.py"]
    assert "code/sbx-repo" not in v.trace and v.trace["game/G1 n"] == "3"
    top = L.at().id
    assert L.at().eval("sbx.stage.fns.count", game="G1").subject == v.subject and L.at().id == top
    (repo / "sbx/stage/helper.py").write_text("def double(x):\n    return x + x\n")
    git(repo, "commit", "-q", "-am", "two")
    with L.transaction(by="t") as t:
        bump(t, "code/sbx-repo")
    assert not v.matches(L.at())                    # the run-time import's file moved
    w = L.at().eval("sbx.stage.fns.count", game="G1")
    assert w.same_as(v) and w.subject != v.subject and list(v.diff(w)) == ["fn"]


def test_nested_eval_in_process_and_work_folder(sbx):
    L, _repo = sbx
    v = L.at().eval("sbx.stage.fns.nested", game="G1")
    assert v.obj == {"inner": {"n": 6}}
    assert any(k.startswith("eval:sbx.stage.fns.count") for k in v.trace)
    d = L.at().eval("sbx.stage.fns.folder", game="G1")
    assert (d.path / "f.txt").read_text() == "G1"


def test_refusals(sbx):
    L, repo = sbx
    with pytest.raises(UnmountedImport, match="sbx.other from sbx.stage.fns"):
        L.at().eval("sbx.stage.fns.borrow", game="G1")
    with pytest.raises(UntracedRead):
        L.at().eval("sbx.stage.fns.snoop", game="G1")
    with pytest.raises(ConfinedWrite, match="writes only in its work folder") as e:
        L.at().eval("sbx.stage.fns.scribble", game="G1")
    assert not isinstance(e.value, UntracedRead)
    old = L.at(1)
    (repo / "sbx/other.py").write_text("X = 2\n")
    git(repo, "commit", "-q", "-am", "elsewhere")
    with pytest.raises(NotEvaluated):
        old.eval("sbx.stage.fns.count", game="G1")


def test_salt_item(sbx):
    L, _repo = sbx
    with L.transaction(by="t") as t:
        t.add("db/mount/sbx.stage", "db/salt", "v2")
    v = L.at().eval("sbx.stage.fns.count", game="G1")
    assert v.trace["salt"] == "v2" and v.matches(L.at())
    with L.transaction(by="t") as t:
        t.add("db/mount/sbx.stage", "db/salt", "v3")
    assert not v.matches(L.at())


def test_a_mount_root_without_init_imports_namespace_style(sbx):
    L, _repo = sbx
    f = L.at().load_fn("flatpkg.calc.area")
    assert f.mode == "sandbox" and f.mount == "flatpkg"
    v = L.at().eval("flatpkg.calc.area", side=3)
    assert v.obj == {"area": 9}
    assert sorted(L.at()[v.trace["fn"], "db/modules"]) == ["flat/calc.py", "flat/util.py"]
    assert L.at().eval("sbx.stage.fns.count", game="G1").obj == {"n": 6}      # the package case


def test_memo_false_keeps_preds_and_runs_on_a_dirty_tree(sbx):
    L, repo = sbx
    v = L.at().eval("sbx.stage.kinds.tagged", game="G1", memo=False)
    assert not v.sealed and v.preds == {"game": "G1"} and v.trace["fn"].startswith("db/fn/")
    (repo / "sbx/other.py").write_text("X = 3\n")              # dirty
    assert L.at().eval("sbx.stage.fns.count", game="G1", memo=False).obj == {"n": 6}
    with pytest.raises(NotEvaluated):
        L.at().eval("sbx.stage.fns.count", game="G1")


def test_load_fn_refuses_an_unmounted_import_at_load(sbx):
    L, _repo = sbx
    with pytest.raises(UnmountedImport, match="sbx.other from sbx.stage.fns; mount it or move it"):
        L.at().load_fn("sbx.stage.fns.borrow")
    assert L.at().load_fn("sbx.stage.fns.snoop").mode == "sandbox"   # same module, no such import
