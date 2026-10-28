"""Namespace latent bugs (deep scan round 4, 2026-10-27): a name that leaves its mount, a folder at a
dotted at, an unreachable ledger mount, a null in a mounted file, a remount serving the old content."""
import subprocess
import sys
import textwrap

import pytest

import backends
from dvc_dat.ledger import UntracedRead, set_env_provider
from dvc_dat.ledger.sandbox import shutdown

EXTRA = {
    "pyproject.toml": '[project]\nname = "sbx-repo"\nversion = "0.1.0"\n',
    "sbx/__init__.py": "",
    "sbx/stage/__init__.py": "",
    "sbx/stage/specs/base.yaml": "dat:\n  kwargs: {n: 3}\n",
    "sbx/stage/runs.py": textwrap.dedent('''
        def peek(dat, where=""):
            from dvc_dat import Dat
            dat.get_results()["got"] = Dat.manager.ns.load(where)
            dat.save()

        def opened(dat, where=""):
            from pathlib import Path
            dat.get_results()["got"] = Path(where).read_text()
            dat.save()

        def cfg(dat):
            from dvc_dat import Dat
            dat.get_results()["n"] = Dat.manager.ns.load("sbx.stage.specs.base.dat.kwargs.n")
            dat.save()
    '''),
    "sbx/stage/aliased.py": textwrap.dedent('''
        from dvc_dat.ledger import ledger_fn as lfn

        @lfn
        def area(rev, *, side: int) -> dict:
            return {"area": side * side}
    '''),
}


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def sbx(tmp_path, monkeypatch, backend):
    repo = tmp_path / "sbx-repo"
    for rel, text in EXTRA.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "one")
    monkeypatch.syspath_prepend(str(repo))
    for m in [m for m in sys.modules if m == "sbx" or m.startswith("sbx.")]:
        del sys.modules[m]
    import sbx  # noqa: F401
    old = set_env_provider(None)
    L = backends.make(backend, tmp_path / "ledger")
    with L.transaction(by="t", lock=10) as t:
        t.add("db/mount/sbx.stage", "db/root", "sbx/stage")
        t.add("db/mount/sbx.stage", "db/repo", "sbx-repo")
        t.add("db/repo/sbx-repo", "db/commit", git(repo, "rev-parse", "HEAD"))
    yield L, repo
    shutdown()
    set_env_provider(old)


@pytest.fixture
def world(tmp_path):
    from dvc_dat import Dat, DatManager, core

    before = core._default_manager
    Dat.manager = DatManager(dat_folders=[str(tmp_path / "data")])
    yield Dat.manager
    core._default_manager = before
    if before is not None:
        Dat.manager = before


# -- F1: a name segment that is an absolute path escapes the mount ------------------------------------

def test_f1_a_mounted_name_cannot_read_outside_its_mount(sbx, tmp_path):
    """breaks when a segment is an absolute path ("sbx.stage./x/y") because _mounted does
    root.joinpath(*rest) and Path.joinpath('/abs') discards root."""
    L, _repo = sbx
    secret = tmp_path / "outside" / "secret"
    secret.parent.mkdir()
    secret.with_suffix(".yaml").write_text("password: hunter2\n")
    name = "sbx.stage." + str(secret)           # every segment non-empty: passes the dotted-name check
    with pytest.raises((ImportError, KeyError)):
        L.at().ns.load(name)


def test_f1b_a_sandboxed_body_reads_outside_the_mounts_through_ns_load(sbx, world, tmp_path):
    """The same hole inside the worker: Path.read_text of the file is UntracedRead, but
    Dat.manager.ns.load of it returns the contents (the namespace reads under unguarded())."""
    L, _repo = sbx
    secret = tmp_path / "outside" / "secret"
    secret.parent.mkdir()
    secret.with_suffix(".yaml").write_text("password: hunter2\n")
    with pytest.raises(UntracedRead):           # the guard holds for a plain read ...
        L.at().run({"dat": {"do": "sbx.stage.runs.opened"}}, where=str(secret.with_suffix(".yaml")))
    with pytest.raises(Exception):               # ... and must for the namespace too
        v = L.at().run({"dat": {"do": "sbx.stage.runs.peek"}}, where="sbx.stage." + str(secret))
        print("LEAKED:", v.get_results()["got"])




# -- F3: plain Namespace: a folder mounted at a dotted `at` answers to nothing ------------------------

def test_f3_folder_mounted_at_a_dotted_at_is_reachable(tmp_path):
    from dvc_dat import Namespace

    d = tmp_path / "cat"
    d.mkdir()
    (d / "baseline.yaml").write_text("lr: 0.1\n")
    ns = Namespace()
    ns.mount(folder=str(d), at="catalog.models")         # accepted, no error
    assert ns.load("catalog.models.baseline") == {"lr": 0.1}


# -- F4: t.ns.mount takes any non-empty str for `at` --------------------------------------------------

@pytest.mark.parametrize("at", ["pkg.", ".pkg", "a..b"])
def test_f4_t_ns_mount_refuses_an_at_that_no_dotted_name_can_reach(L, at):
    with pytest.raises((TypeError, ValueError)):
        with L.transaction(by="t") as t:
            t.ns.mount(at, root="r", repo="x")





# -- F5: changing a `mounts:` entry in .datconfig.yaml (remount) --------------------------------------

def test_f5_config_remount_replaces_the_root(tmp_path, monkeypatch):
    from dvc_dat.ledger import Ledger

    monkeypatch.delenv("DAT_LEDGER", raising=False)
    monkeypatch.chdir(tmp_path)
    Ledger(create=True)
    cfg = tmp_path / ".datconfig.yaml"
    cfg.write_text("ledger: .dat/ledger\nmounts:\n  pkg.etl: pkg/etl\n")
    Ledger()
    cfg.write_text("ledger: .dat/ledger\nmounts:\n  pkg.etl: pkg/etl2\n")
    L = Ledger()
    assert L.at().ns.mounts()["pkg.etl"]["root"] == "pkg/etl2"
    top = L.at().id
    assert Ledger().at().id == top                          # asserted once, then stable




# -- F7: plain Namespace: a mounted file's null value is 'missing' ------------------------------------

def test_f7_a_null_in_a_mounted_file_loads_as_none(tmp_path):
    from dvc_dat import Namespace

    (tmp_path / "cfg.yaml").write_text("k: null\nz: 0\n")
    ns = Namespace()
    ns.mount(file=str(tmp_path / "cfg.yaml"), at="cfg")
    assert ns.load("cfg.z") == 0
    assert ns.load("cfg.k") is None              # KeyError "'k' is missing from ..." today


# -- F8: plain Namespace: remounting a file at the same name serves the old file ----------------------

def test_f8_remounting_a_file_serves_the_new_file(tmp_path):
    from dvc_dat import Namespace

    (tmp_path / "a.yaml").write_text("x: 1\n")
    (tmp_path / "b.yaml").write_text("x: 2\n")
    ns = Namespace()
    ns.mount(file=str(tmp_path / "a.yaml"), at="cfg")
    assert ns.load("cfg.x") == 1
    ns.mount(file=str(tmp_path / "b.yaml"), at="cfg")
    assert ns.mounts()["cfg"] == str(tmp_path / "b.yaml")
    assert ns.load("cfg.x") == 2                 # 1 today: _base_objects['cfg'] is never dropped


def test_f8b_a_file_mounted_over_a_value_is_what_loads(tmp_path):
    from dvc_dat import Namespace

    (tmp_path / "b.yaml").write_text("x: 2\n")
    ns = Namespace()
    ns.mount(value={"x": 1}, at="cfg")
    ns.mount(file=str(tmp_path / "b.yaml"), at="cfg")
    assert ns.mounts()["cfg"] == str(tmp_path / "b.yaml")
    assert ns.load("cfg.x") == 2                 # 1 today: _registered_values is checked first, never cleared
