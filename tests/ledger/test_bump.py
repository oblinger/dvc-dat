"""DAT 1043: a code version lives in its source. ``bump_source`` edits ``__version__``; ``bump`` refuses
``code/<repo>``; a declared version counts only from a clean checkout; a clean seal moves the
``code/<repo>`` clock to the version the run was exposed to."""

import re
import warnings

import pytest

from dvc_dat.ledger import Checkout, Env, Value, bump, bump_source
from dvc_dat.ledger.code import installed_version
from test_code import forget, git, installed, mounted  # noqa: F401  (fixtures)


@pytest.fixture
def pkg(tmp_path, monkeypatch):
    """``bumpme`` (a package) and ``onefile`` (a single-file module) on ``sys.path``, in a git checkout."""
    root = tmp_path / "bump-repo"
    (root / "bumpme").mkdir(parents=True)
    (root / "bumpme/__init__.py").write_text('"""A package."""\n__version__ = "0.1.0"\nOTHER = "1.2.3"\n')
    (root / "bumpme/sub.py").write_text("X = 1\n")
    (root / "onefile.py").write_text("__version__ = '2.0.9'\n")
    git(root, "init", "-q")
    monkeypatch.syspath_prepend(str(root))
    forget("bumpme", "onefile")
    yield root
    forget("bumpme", "onefile")


def test_bump_source_patch_rewrites_one_line(pkg):
    b = bump_source("bumpme.sub")
    assert (b.module, b.old, b.new, b.path) == ("bumpme.sub", "0.1.0", "0.1.1", pkg / "bumpme/__init__.py")
    assert b.repo == "bump-repo"
    assert (pkg / "bumpme/__init__.py").read_text() == '"""A package."""\n__version__ = "0.1.1"\nOTHER = "1.2.3"\n'


def test_bump_source_minor_needs_confirm(pkg):
    with pytest.raises(ValueError, match="needs confirm="):
        bump_source("bumpme", "minor")
    with pytest.raises(ValueError, match="refused by confirm"):
        bump_source("bumpme", "major", confirm=lambda old, new: False)
    assert '__version__ = "0.1.0"' in (pkg / "bumpme/__init__.py").read_text()
    seen = []
    b = bump_source("bumpme", "minor", confirm=lambda old, new: seen.append((old, new)) or True)
    assert b.new == "0.2.0" and seen == [("0.1.0", "0.2.0")]


def test_bump_source_single_file_module(pkg):
    assert bump_source("onefile", "major", confirm=lambda o, n: True).new == "3.0.0"
    assert (pkg / "onefile.py").read_text() == "__version__ = '3.0.0'\n"


def test_bump_source_refusals(pkg):
    (pkg / "bumpme/__init__.py").write_text("X = 1\n")
    with pytest.raises(ValueError, match='no __version__ = "X.Y.Z" line to bump; add one'):
        bump_source("bumpme")
    (pkg / "bumpme/__init__.py").write_text('__version__ = "0.1"\n')
    with pytest.raises(ValueError, match="not MAJOR.MINOR.PATCH"):
        bump_source("bumpme")
    assert (pkg / "bumpme/__init__.py").read_text() == '__version__ = "0.1"\n'
    with pytest.raises(ModuleNotFoundError, match="no_such_mod_1043"):
        bump_source("no_such_mod_1043")


def test_bump_refuses_code_subjects_and_writes_nothing(L):
    top = L.at().id
    with pytest.raises(TypeError, match=r"code/x: a code version lives in its source; just bump <module> "):
        with L.transaction(by="t", lock=10) as t:
            bump(t, "code/x")
    assert L.at().id == top and L.at().get("code/x", "version") is None


def test_installed_version_is_the_attr_only_from_a_clean_checkout(installed):
    import geom1037  # noqa: F401

    def env(dirty):
        return Env({"r": Checkout(None, "abcdef0123456789", dirty, installed)}, "p")
    assert installed_version("geom1037", env(False), "r", "f" * 16) == "5.3.9"
    assert installed_version("geom1037", env(True), "r", "f" * 16) == "abcdef01+dirty"
    assert installed_version("geom1037", env(True), None, "f" * 16) == "5.3.9"      # no checkout: a wheel


def test_mounted_version_under_a_dirty_checkout(mounted):
    L, repo = mounted
    (repo / "code_anchor.py").write_text("# edited\n")        # tracked, not loaded by plane
    f = L.at().load_fn("plane.measure.length")
    assert re.fullmatch(r"[0-9a-f]{8}\+dirty", f.code.version)
    assert git(repo, "rev-parse", "HEAD").startswith(f.code.version[:8])
    git(repo, "commit", "-q", "-am", "edit")
    assert L.at().load_fn("plane.measure.length").code.version == "2.7.1"


def test_a_clean_seal_moves_the_clock_once(mounted):
    L, repo = mounted
    head = git(repo, "rev-parse", "HEAD")
    L.at().run("plane.measure.length", a=(0, 0), b=(3, 4))
    assert L.at()["code/code-repo"] == {"version": "2.7.1", "commit": head}
    n = len(L.at().rows("code/code-repo", "version"))
    L.at().run("plane.measure.length", a=(0, 0), b=(6, 8))      # the same version: nothing written
    assert len(L.at().rows("code/code-repo", "version")) == n
    (repo / "plane/__init__.py").write_text('__version__ = "2.7.2"\n')
    git(repo, "commit", "-q", "-am", "bump")
    L.at().run("plane.measure.length", a=(0, 0), b=(3, 4))
    assert L.at()["code/code-repo"] == {"version": "2.7.2", "commit": git(repo, "rev-parse", "HEAD")}


def test_a_dirty_run_leaves_the_clock(mounted):
    L, repo = mounted
    (repo / "plane/__init__.py").write_text('__version__ = "2.7.2"\n')     # uncommitted
    v = L.at().run("plane.measure.length", a=(0, 0), b=(3, 4))
    assert v.sealed and L.at().get("code/code-repo", "version") is None


def test_a_lower_version_warns_and_keeps_the_row(mounted, capfd):
    L, _repo = mounted
    with L.transaction(by="t") as t:
        t.add("code/code-repo", "version", "9.0.0")
    L.at().run("plane.measure.length", a=(0, 0), b=(3, 4))      # sealed in the worker: its stderr
    assert "code/code-repo: the run's code is 2.7.1, below the ledger's 9.0.0; the clock keeps 9.0.0" \
        in capfd.readouterr().err
    assert L.at()["code/code-repo", "version"] == "9.0.0"
    f = L.at().load_fn("plane.measure.length")
    with pytest.warns(UserWarning, match=r"code/code-repo: the run's code is 2.7.1, below the ledger's 9.0.0"):
        with L.transaction(by="t") as t:                       # a hand seal, in this process
            Value.Blob({"x": 3}).seal(t, deps=[f])


def test_a_hand_seal_with_no_code_writes_no_clock(mounted):
    L, _repo = mounted
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with L.transaction(by="t") as t:
            Value.Blob({"x": 1}).seal(t)
    assert not [r for r in L.at().rows() if r.subject.startswith("code/")]


def test_a_hand_seal_with_an_fn_dep_moves_the_clock(mounted):
    L, _repo = mounted
    f = L.at().load_fn("plane.measure.length")
    with L.transaction(by="t") as t:
        Value.Blob({"x": 2}).seal(t, deps=[f])
    assert L.at()["code/code-repo", "version"] == "2.7.1"
