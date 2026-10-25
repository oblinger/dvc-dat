"""Sandbox mode: a mounted package in a real tiny git checkout, run in a worker (discovery, no stand-in)."""

import subprocess
import sys
import textwrap

import backends
import pytest

from dvc_dat.ledger import (ConfinedNetwork, ConfinedWrite, LedgerError, NotClean, NotEvaluated, UnmountedImport,
                             UntracedRead, bump, set_env_provider)
from dvc_dat.ledger import sandbox
from dvc_dat.ledger.codec import sha256
from dvc_dat.ledger.sandbox import _ledger_endpoints, shutdown

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
            return {"inner": rev.run("sbx.stage.fns.count", game=game).obj}

        @ledger_fn
        def members(rev, *, s: str) -> list:
            return sorted(rev.all(s, "contains"))

        @ledger_fn
        def folder(rev, *, game: str, path: Path) -> Dat:
            (path / "f.txt").write_text(game)
            return Dat(path)

        @ledger_fn
        def pid(rev, *, game: str) -> dict:
            from sbx.stage import helper
            helper.CALLS = getattr(helper, "CALLS", 0) + 1
            import os
            return {"pid": os.getpid(), "calls": helper.CALLS}

        @ledger_fn
        def die(rev, *, game: str) -> dict:
            import os
            os._exit(3)

        @ledger_fn
        def libs(rev, *, game: str) -> dict:
            import colorsys
            import xlsxwriter
            return {"h": colorsys.rgb_to_hsv(0, 0, 0)[0], "x": bool(xlsxwriter.__version__)}

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
    "sbx/stage/writes.py": textwrap.dedent('''
        import os
        import shutil
        import sqlite3
        import tempfile
        from pathlib import Path
        from dvc_dat.ledger import ledger_fn

        def _dirfd(d, w):
            fd = os.open(d, os.O_RDONLY)
            try:
                os.mkdir("by-fd", dir_fd=fd)
            finally:
                os.close(fd)

        def _src(w):
            (w / "s").write_text("x")
            return w / "s"

        HOWS = {
            "open": lambda d, w: open(d / "a", "w").write("x"),
            "os.open": lambda d, w: os.close(os.open(d / "a", os.O_WRONLY | os.O_CREAT)),
            "o_trunc": lambda d, w: os.close(os.open(d / "seed", os.O_RDONLY | os.O_TRUNC)),
            "write_text": lambda d, w: (d / "a").write_text("x"),
            "mkdir": lambda d, w: os.mkdir(d / "m"),
            "makedirs": lambda d, w: os.makedirs(d / "m1" / "m2"),
            "rename_out": lambda d, w: os.rename(_src(w), d / "r"),
            "replace_out": lambda d, w: os.replace(_src(w), d / "r"),
            "rename_in": lambda d, w: os.rename(d / "seed", w / "stolen"),
            "link_in": lambda d, w: os.link(d / "seed", w / "hard"),
            "symlink": lambda d, w: os.symlink(w, d / "sl"),
            "remove": lambda d, w: os.remove(d / "seed"),
            "rmdir": lambda d, w: os.rmdir(d / "empty"),
            "chmod": lambda d, w: os.chmod(d / "seed", 0o600),
            "utime": lambda d, w: os.utime(d / "seed"),
            "truncate": lambda d, w: os.truncate(d / "seed", 0),
            "copy": lambda d, w: shutil.copy(_src(w), d / "c"),
            "copytree": lambda d, w: shutil.copytree(w, d / "t"),
            "move": lambda d, w: shutil.move(_src(w), d / "mv"),
            "rmtree": lambda d, w: shutil.rmtree(d / "tree"),
            "mkstemp": lambda d, w: os.close(tempfile.mkstemp(dir=d)[0]),
            "mkdtemp": lambda d, w: tempfile.mkdtemp(dir=d),
            "named": lambda d, w: tempfile.NamedTemporaryFile(dir=d).close(),
            "sqlite": lambda d, w: sqlite3.connect(d / "x.db").execute("CREATE TABLE t (x)"),
            "dir_fd": _dirfd,
        }

        def seed(d):
            d.mkdir(parents=True, exist_ok=True)
            (d / "seed").write_text("s")
            (d / "empty").mkdir()
            (d / "tree").mkdir()
            (d / "tree" / "f").write_text("f")

        @ledger_fn
        def write(rev, *, how: str, where: str, path: Path) -> dict:
            if where == "work":                     # every way, inside the dat being produced: all allowed
                for name, act in HOWS.items():
                    seed(path / name)
                    (path / f"{name}-src").mkdir()
                    act(path / name, path / f"{name}-src")
                return {"n": len(HOWS)}
            places = {"scratch": path.parent, "art": Path(rev.ledger._store.art.root),
                      "mount": Path(__file__).parent}
            d = places.get(where) or Path(where)
            (path / "src").mkdir()
            if how == "mkstemp-default":
                os.close(tempfile.mkstemp()[0])
            else:
                HOWS[how](d, path / "src")
            return {}
    '''),
    "sbx/stage/reads.py": textwrap.dedent('''
        import glob
        import os
        import shutil
        import sys
        from pathlib import Path
        import dvc_dat
        import yaml
        from dvc_dat.ledger import ledger_fn

        HOWS = {
            "open": lambda p: Path(p).read_text(),
            "os.open": lambda p: os.close(os.open(p, os.O_RDONLY)),
            "listdir": lambda p: os.listdir(Path(p).parent),
            "scandir": lambda p: list(os.scandir(Path(p).parent)),
            "iterdir": lambda p: list(Path(p).parent.iterdir()),
            "glob": lambda p: glob.glob(str(Path(p).parent / "*")),
            "walk": lambda p: list(os.walk(Path(p).parent)),
            "copy": lambda p: shutil.copy(p, Path.cwd() / "copied"),
        }

        @ledger_fn
        def read(rev, *, how: str, where: str, path: Path) -> dict:
            places = {"stdlib": os.__file__, "site": yaml.__file__, "dvc_dat": dvc_dat.__file__,
                      "prefix": os.path.join(sys.prefix, "pyvenv.cfg"), "repo": Path(__file__).parents[2] / "pyproject.toml",
                      "scratch": path.parent / "nothing-here"}
            out = HOWS[how](places.get(where) or where)
            return {"n": len(out) if isinstance(out, list) else -1}

        @ledger_fn
        def allowed(rev, *, game: str, path: Path) -> dict:
            (path / "mine.txt").write_text(game)
            n = len(Path(__file__).read_text()) > 0 and sorted(os.listdir(Path(__file__).parent)) != []
            art = Path(rev.ledger._store.art.root)
            import colorsys                         # a stdlib import in the body: the import system reads
            import jsonschema_specifications        # its import reads its own schemas (site-packages)
            return {"n": bool(n), "mine": Path("mine.txt").read_text(), "art": art.is_dir() and bool(os.listdir(art)),
                    "registry": len(jsonschema_specifications.REGISTRY) > 0, "h": colorsys.rgb_to_hsv(0, 0, 0)}

        @ledger_fn
        def library_data(rev, *, game: str) -> dict:
            from importlib.resources import files
            return {"n": len(list(files("jsonschema_specifications").joinpath("schemas").iterdir()))}
    '''),
    "sbx/stage/eager.py": textwrap.dedent('''
        from pathlib import Path
        from dvc_dat.ledger import ledger_fn

        HOSTS = Path("/etc/hosts").read_text()     # at load: the module's own load is confined too

        @ledger_fn
        def f(rev, *, game: str) -> dict:
            return {}
    '''),
    "sbx/stage/net.py": textwrap.dedent('''
        import socket
        from dvc_dat.ledger import ledger_fn

        @ledger_fn
        def resolve(rev, *, host: str) -> dict:
            return {"n": len(socket.getaddrinfo(host, 80))}

        @ledger_fn
        def dial(rev, *, port: int) -> dict:
            with socket.socket() as s:
                s.connect(("127.0.0.1", port))
            return {}

        @ledger_fn
        def datagram(rev, *, port: int) -> dict:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.sendto(b"x", ("127.0.0.1", port))
            return {}

        @ledger_fn
        def pair(rev, *, text: str) -> dict:
            a, b = socket.socketpair()
            with a, b:
                a.sendall(text.encode())
                return {"echo": b.recv(64).decode()}
    '''),
}


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def sbx(tmp_path, monkeypatch, backend):
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
    L = backends.make(backend, tmp_path / "ledger")
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
    v = L.at().run("sbx.stage.fns.count", game="G1")
    assert v.sealed and v.obj == {"n": 6} and L.at()[v.subject, "db/provenance"] == "eval:sandbox"
    mods = L.at()[v.dependencies["fn"], "db/modules"]
    assert sorted(mods) == ["sbx/stage/__init__.py", "sbx/stage/fns.py", "sbx/stage/helper.py"]
    assert "code/sbx-repo" not in v.dependencies and v.dependencies["game/G1 n"] == "3"
    top = L.at().id
    assert L.at().run("sbx.stage.fns.count", game="G1").subject == v.subject and L.at().id == top
    (repo / "sbx/stage/helper.py").write_text("def double(x):\n    return x + x\n")
    git(repo, "commit", "-q", "-am", "two")
    with L.transaction(by="t") as t:
        bump(t, "code/sbx-repo")
    assert not v.matches(L.at())                    # the run-time import's file moved
    w = L.at().run("sbx.stage.fns.count", game="G1")
    assert w.same_as(v) and w.subject != v.subject and list(v.diff(w)) == ["fn"]


def test_nested_eval_in_process_and_work_folder(sbx):
    L, _repo = sbx
    v = L.at().run("sbx.stage.fns.nested", game="G1")
    assert v.obj == {"inner": {"n": 6}}
    assert any(k.startswith("eval:sbx.stage.fns.count") for k in v.dependencies)
    d = L.at().run("sbx.stage.fns.folder", game="G1")
    assert (d.path / "f.txt").read_text() == "G1" and d.name == "anonymous/Dat"
    e = L.at().run("sbx.stage.fns.folder", game="G1", path="games/G1")      # a hit, renamed
    assert e.subject == d.subject and e.name == "games/G1" and (e.path / "f.txt").read_text() == "G1"


def test_a_bodys_first_read_can_be_all_in_a_fresh_worker(sbx):
    L, _repo = sbx
    shutdown()                                       # a fresh worker: no ledger module imported lazily yet
    with L.transaction(by="t") as t:
        t.add("db/pred/contains", "db/cardinality", "many")
        t.add("set/A", "contains", "G2")
        t.add("set/A", "contains", "G1")
    v = L.at().run("sbx.stage.fns.members", s="set/A")
    assert v.obj == ["G1", "G2"] and any(k.startswith("all") or "contains" in k for k in v.dependencies)


def test_refusals(sbx):
    L, repo = sbx
    with pytest.raises(UnmountedImport, match="sbx.other from sbx.stage.fns"):
        L.at().run("sbx.stage.fns.borrow", game="G1")
    with pytest.raises(UntracedRead):
        L.at().run("sbx.stage.fns.snoop", game="G1")
    with pytest.raises(ConfinedWrite, match="writes only in its path folder") as e:
        L.at().run("sbx.stage.fns.scribble", game="G1")
    assert not isinstance(e.value, UntracedRead)
    old = L.at(1)
    (repo / "sbx/other.py").write_text("X = 2\n")
    git(repo, "commit", "-q", "-am", "elsewhere")
    with pytest.raises(NotClean, match="binds code/sbx-repo to"):
        old.run("sbx.stage.fns.count", game="G1", clean=True)
    assert old.run("sbx.stage.fns.count", game="G1").obj == {"n": 6}   # no gate: it runs at HEAD (Q39)


def test_salt_item(sbx):
    L, _repo = sbx
    with L.transaction(by="t") as t:
        t.add("db/mount/sbx.stage", "db/salt", "v2")
    v = L.at().run("sbx.stage.fns.count", game="G1")
    assert v.dependencies["salt"] == "v2" and v.matches(L.at())
    with L.transaction(by="t") as t:
        t.add("db/mount/sbx.stage", "db/salt", "v3")
    assert not v.matches(L.at())


def test_a_mount_root_without_init_imports_namespace_style(sbx):
    L, _repo = sbx
    f = L.at().load_fn("flatpkg.calc.area")
    assert f.mode == "sandbox" and f.mount == "flatpkg"
    v = L.at().run("flatpkg.calc.area", side=3)
    assert v.obj == {"area": 9}
    assert sorted(L.at()[v.dependencies["fn"], "db/modules"]) == ["flat/calc.py", "flat/util.py"]
    assert L.at().run("sbx.stage.fns.count", game="G1").obj == {"n": 6}      # the package case


def test_a_draft_keeps_preds_and_runs_on_a_dirty_tree(sbx):
    L, repo = sbx
    v = L.at().run("sbx.stage.kinds.tagged", game="G1", seal=False)
    assert not v.sealed and v.preds == {"game": "G1"} and v.dependencies["fn"].startswith("db/fn/")
    (repo / "sbx/other.py").write_text("X = 3\n")              # dirty
    assert L.at().run("sbx.stage.fns.count", game="G1", seal=False).obj == {"n": 6}
    assert L.at().run("sbx.stage.fns.count", game="G1").obj == {"n": 6}      # a miss runs dirty (Q39)
    with pytest.raises(NotClean, match="uncommitted changes"):
        L.at().run("sbx.stage.fns.count", game="G1", clean=True)


def test_a_dirty_edit_to_a_loaded_module_is_a_new_value_and_reverting_hits(sbx):
    L, repo = sbx
    v = L.at().run("sbx.stage.fns.count", game="G1")
    top = L.at().id
    (repo / "sbx/stage/helper.py").write_text("def double(x):\n    return 3 * x\n")     # uncommitted
    w = L.at().run("sbx.stage.fns.count", game="G1")
    assert w.obj == {"n": 9} and w.subject != v.subject and L.at().id == top + 1
    (repo / "sbx/stage/helper.py").write_text("def double(x):\n    return 2 * x\n")
    assert L.at().run("sbx.stage.fns.count", game="G1").subject == v.subject and L.at().id == top + 1
    (repo / "sbx/other.py").write_text("X = 4\n")              # a module the run never loaded
    assert L.at().run("sbx.stage.fns.count", game="G1").subject == v.subject


def test_a_committed_edit_recomputes_with_no_bump(sbx):
    L, repo = sbx
    v = L.at().run("sbx.stage.fns.count", game="G1")
    (repo / "sbx/stage/helper.py").write_text("def double(x):\n    return 4 * x\n")
    git(repo, "commit", "-q", "-am", "four")                   # the rev still names the old commit
    w = L.at().run("sbx.stage.fns.count", game="G1")
    assert w.obj == {"n": 12} and w.subject != v.subject and not v.matches(L.at())


def test_each_call_is_a_fresh_process(sbx):
    L, _repo = sbx
    a = L.at().run("sbx.stage.fns.pid", game="G1", seal=False).obj
    b = L.at().run("sbx.stage.fns.pid", game="G1", seal=False).obj
    assert a["calls"] == b["calls"] == 1 and a["pid"] != b["pid"]
    assert sandbox._server().alive()
    with pytest.raises(RuntimeError, match=r"ended \(exit code 3\) before it replied"):
        L.at().run("sbx.stage.fns.die", game="G1")
    assert L.at().run("sbx.stage.fns.pid", game="G1", seal=False).obj["calls"] == 1   # the server lives on


def test_third_party_modules_are_in_the_fn_item(sbx, monkeypatch):
    import colorsys
    import importlib.metadata as md

    pytest.importorskip("xlsxwriter")
    L, _repo = sbx
    v = L.at().run("sbx.stage.fns.libs", game="G1")
    mods = L.at()[v.dependencies["fn"], "db/modules"]
    assert mods["py:colorsys.py"] == sha256(open(colorsys.__file__, "rb").read())
    assert mods["dist:xlsxwriter"].startswith(md.version("xlsxwriter") + ":")
    assert not any(k.startswith(("dist:dvc-dat", "py:dvc_dat", "dist:pyyaml")) for k in mods)
    assert v.matches(L.at())
    real = sandbox.third_party_now
    monkeypatch.setattr(sandbox, "third_party_now", lambda k: "9.9:x" if k == "dist:xlsxwriter" else real(k))
    assert not v.matches(L.at())                    # a new install of a loaded distribution: a new value


def test_load_fn_refuses_an_unmounted_import_at_load(sbx):
    L, _repo = sbx
    with pytest.raises(UnmountedImport, match="sbx.other from sbx.stage.fns; mount it or move it"):
        L.at().load_fn("sbx.stage.fns.borrow")
    assert L.at().load_fn("sbx.stage.fns.snoop").mode == "sandbox"   # same module, no such import


def test_network_refused(sbx):
    import socket

    L, _repo = sbx
    assert issubclass(ConfinedNetwork, PermissionError) and issubclass(ConfinedNetwork, LedgerError)
    with pytest.raises(ConfinedNetwork, match="example.com: a sandboxed function does not use the network"):
        L.at().run("sbx.stage.net.resolve", host="example.com")
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        srv.setblocking(False)
        port = srv.getsockname()[1]
        with pytest.raises(ConfinedNetwork, match=f"127.0.0.1:{port}"):
            L.at().run("sbx.stage.net.dial", port=port)
        with pytest.raises(BlockingIOError):
            srv.accept()                            # refused before the connect was made
    with pytest.raises(ConfinedNetwork):
        L.at().run("sbx.stage.net.datagram", port=9)
    assert L.at().run("sbx.stage.net.pair", text="hi").obj == {"echo": "hi"}   # a local socket is not the network


def test_the_ledgers_own_endpoint_is_allowed():
    hosts, addrs = _ledger_endpoints("postgresql://u:pw@127.0.0.1:5433/db?art=/tmp/a")
    assert hosts == {"127.0.0.1"} and addrs == {("127.0.0.1", 5433)}
    hosts, addrs = _ledger_endpoints("postgresql://u@[::1],127.0.0.1:6000/db")
    assert hosts == {"::1", "127.0.0.1"} and ("127.0.0.1", 6000) in addrs and ("::1", 5432) in addrs
    assert _ledger_endpoints("/some/ledger/folder") == (set(), set())


WRITE_HOWS = ["open", "os.open", "o_trunc", "write_text", "mkdir", "makedirs", "rename_out", "replace_out",
              "rename_in", "link_in", "symlink", "remove", "rmdir", "chmod", "utime", "truncate", "copy",
              "copytree", "move", "rmtree", "mkstemp", "mkdtemp", "named", "sqlite"]


def test_writes_confined_to_the_dat_being_produced(sbx, tmp_path):
    L, repo = sbx
    assert L.at().run("sbx.stage.writes.write", how="all", where="work").obj == {"n": len(WRITE_HOWS) + 1}
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "seed").write_text("s")
    (outside / "empty").mkdir()
    (outside / "tree").mkdir()
    (outside / "tree" / "f").write_text("f")
    before = sorted(p.relative_to(outside).as_posix() for p in outside.rglob("*"))
    for how in WRITE_HOWS:
        with pytest.raises(ConfinedWrite, match="a sandboxed function writes only in its path folder"):
            L.at().run("sbx.stage.writes.write", how=how, where=str(outside))
    assert sorted(p.relative_to(outside).as_posix() for p in outside.rglob("*")) == before
    assert (outside / "seed").read_text() == "s"
    for where in ("scratch", "art"):
        for how in ("open", "mkdir", "mkstemp"):
            with pytest.raises(ConfinedWrite):
                L.at().run("sbx.stage.writes.write", how=how, where=where)
    with pytest.raises(ConfinedWrite):
        L.at().run("sbx.stage.writes.write", how="mkstemp-default", where="")
    with pytest.raises(ConfinedWrite):                  # a path relative to a descriptor on a mount
        L.at().run("sbx.stage.writes.write", how="dir_fd", where="mount")
    assert not (repo / "sbx/stage/by-fd").exists()


READ_HOWS = ["open", "os.open", "listdir", "scandir", "iterdir", "copy"]
SWALLOWED = ["glob", "walk"]            # they catch the OSError themselves: the folder reads as empty


def test_reads_confined_to_the_mounts_the_dats_and_the_work_folder(sbx, tmp_path):
    pytest.importorskip("jsonschema_specifications")
    L, _repo = sbx
    L.at().run("sbx.stage.fns.folder", game="G1")           # something in the art store
    v = L.at().run("sbx.stage.reads.allowed", game="G1")
    assert v.obj == {"n": True, "mine": "G1", "art": True, "registry": True, "h": (0.0, 0.0, 0.0)}
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "f.txt").write_text("x")
    for where in ("stdlib", "site", "dvc_dat", "prefix", "repo", "scratch", str(outside / "f.txt")):
        for how in READ_HOWS:
            with pytest.raises(UntracedRead, match="outside the mounts, the dats and the path folder"):
                L.at().run("sbx.stage.reads.read", how=how, where=where)
        for how in SWALLOWED:
            assert L.at().run("sbx.stage.reads.read", how=how, where=where).obj == {"n": 0}
    with pytest.raises(UntracedRead):                       # a library's data, read after its import
        L.at().run("sbx.stage.reads.library_data", game="G1")
    with pytest.raises(UntracedRead, match="/etc/hosts"):    # a mounted module's own load
        L.at().run("sbx.stage.eager.f", game="G1")


def test_a_sandboxed_draft_saved_later_is_the_memo_entry(sbx):
    L, _repo = sbx
    d = L.at().run("sbx.stage.fns.count", game="G1", seal=False)
    assert d.subject is None and "_run" in d.__dict__
    d.seal(L)
    assert L.at()[d.subject, "db/provenance"] == "eval:sandbox"
    assert L.at().run("sbx.stage.fns.count", game="G1", seal="get").subject == d.subject


def test_a_sandboxed_run_saves_into_a_transaction(sbx):
    L, _repo = sbx
    with L.transaction(by="t") as t:
        v = L.at().run("sbx.stage.fns.count", game="G1", seal=t)
        t[v.subject, "status"] = "ok"
    assert L.at()[v.subject, "status"] == "ok" and L.at()[v.subject, "db/fn"] == "sbx.stage.fns.count"
    assert L.at().run("sbx.stage.fns.count", game="G1").subject == v.subject
