"""DAT 1043, 1044: a code version lives in its source. ``bump_source`` edits ``__version__``; ``bump`` refuses
``db/repo/`` subjects; a declared version counts only from a clean checkout; a clean seal moves the
``db/repo/<repo>/<package>`` clock to the version the run was exposed to, one per package, and
``db/repo/<repo>`` to the commit of the latest clean run."""

import re
import warnings

import pytest

from dvc_dat.ledger import Checkout, Env, NotClean, Value, bump, bump_source
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
    assert b.package == "bumpme"
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


def test_bump_refuses_clock_subjects_and_writes_nothing(L):
    top = L.at().id
    with pytest.raises(TypeError, match=r"db/repo/x/y: a code version lives in its source; just bump <module> "
                                        r".*records it in db/repo/<repo>/<package> \(the commit in db/repo/<repo>\)"):
        with L.transaction(by="t", lock=10) as t:
            bump(t, "db/repo/x/y")
    assert L.at().id == top and L.at().get("db/repo/x/y", "version") is None


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
    f = L.at().resolve("plane.measure.length")
    assert re.fullmatch(r"[0-9a-f]{8}\+dirty", f.code.version)
    assert git(repo, "rev-parse", "HEAD").startswith(f.code.version[:8])
    git(repo, "commit", "-q", "-am", "edit")
    assert L.at().resolve("plane.measure.length").code.version == "2.7.1"


def test_a_clean_seal_moves_the_clock_once(mounted):
    L, repo = mounted
    head = git(repo, "rev-parse", "HEAD")
    L.at().run("plane.measure.length", a=(0, 0), b=(3, 4))
    assert L.at()["db/repo/code-repo/plane"] == {"version": "2.7.1"}
    assert L.at()["db/repo/code-repo"] == {"commit": head}
    n = len(L.at().rows("db/repo/code-repo/plane", "version"))
    L.at().run("plane.measure.length", a=(0, 0), b=(6, 8))      # the same version: nothing written
    assert len(L.at().rows("db/repo/code-repo/plane", "version")) == n
    assert len(L.at().rows("db/repo/code-repo", "commit")) == 1
    (repo / "plane/__init__.py").write_text('__version__ = "2.7.2"\n')
    git(repo, "commit", "-q", "-am", "bump")
    L.at().run("plane.measure.length", a=(0, 0), b=(3, 4))
    assert L.at()["db/repo/code-repo/plane", "version"] == "2.7.2"
    assert L.at()["db/repo/code-repo", "commit"] == git(repo, "rev-parse", "HEAD")
    assert not [r for r in L.at().rows() if r.subject.startswith("code/")]


def test_two_packages_in_one_checkout_each_keep_a_clock(mounted):
    L, repo = mounted
    (repo / "bare/__init__.py").write_text('__version__ = "0.4.0"\n')
    git(repo, "commit", "-q", "-am", "bare versioned")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        L.at().run("plane.measure.length", a=(0, 0), b=(3, 4))
        L.at().run("bare.calc.length", a=(0, 0), b=(3, 4))
    assert L.at()["db/repo/code-repo/plane", "version"] == "2.7.1"
    assert L.at()["db/repo/code-repo/bare", "version"] == "0.4.0"


def test_the_commit_row_follows_the_latest_clean_run(mounted):
    L, repo = mounted
    (repo / "bare/__init__.py").write_text('__version__ = "0.4.0"\n')
    git(repo, "commit", "-q", "-am", "bare versioned")
    L.at().run("plane.measure.length", a=(0, 0), b=(3, 4))
    first = git(repo, "rev-parse", "HEAD")
    assert L.at()["db/repo/code-repo", "commit"] == first
    (repo / "bare/__init__.py").write_text('__version__ = "0.4.1"\n')
    git(repo, "commit", "-q", "-am", "bare bump")
    L.at().run("bare.calc.length", a=(0, 0), b=(3, 4))
    second = git(repo, "rev-parse", "HEAD")
    assert second != first and L.at()["db/repo/code-repo", "commit"] == second
    assert L.at()["db/repo/code-repo/plane", "version"] == "2.7.1"   # plane's clock stays
    L.at().run("plane.measure.length", a=(0, 0), b=(6, 8))           # plane at 2.7.1, the new commit
    assert L.at()["db/repo/code-repo", "commit"] == second
    assert len(L.at().rows("db/repo/code-repo", "commit")) == 2


def test_a_dirty_run_leaves_the_clock(mounted):
    L, repo = mounted
    (repo / "plane/__init__.py").write_text('__version__ = "2.7.2"\n')     # uncommitted
    v = L.at().run("plane.measure.length", a=(0, 0), b=(3, 4))
    assert v.sealed and L.at().get("db/repo/code-repo/plane", "version") is None
    assert L.at().get("db/repo/code-repo", "commit") is None


def test_a_lower_version_on_one_package_warns_and_keeps_its_row(mounted):
    L, repo = mounted
    (repo / "bare/__init__.py").write_text('__version__ = "0.4.0"\n')
    git(repo, "commit", "-q", "-am", "bare versioned")
    with L.transaction(by="t") as t:
        t.add("db/repo/code-repo/plane", "version", "9.0.0")
    msg = "db/repo/code-repo/plane: the run's code is 2.7.1, below the ledger's 9.0.0; the clock keeps 9.0.0"
    with pytest.warns(UserWarning, match=re.escape(msg)):       # sealed in the worker, warned here
        L.at().run("plane.measure.length", a=(0, 0), b=(3, 4))
    assert L.at()["db/repo/code-repo/plane", "version"] == "9.0.0"
    assert L.at()["db/repo/code-repo", "commit"] == git(repo, "rev-parse", "HEAD")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        L.at().run("bare.calc.length", a=(0, 0), b=(3, 4))
    assert L.at()["db/repo/code-repo/bare", "version"] == "0.4.0"
    f = L.at().resolve("plane.measure.length")
    with pytest.warns(UserWarning, match=re.escape(msg)):
        with L.transaction(by="t") as t:                       # a hand seal, in this process
            Value.Blob({"x": 3}).seal(t, deps=[f])


def test_the_workers_warning_reaches_the_caller(mounted, capfd):
    L, _repo = mounted
    with L.transaction(by="t") as t:
        t.add("db/repo/code-repo/plane", "version", "9.0.0")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        L.at().run("plane.measure.length", a=(0, 0), b=(3, 4))
    assert [str(w.message) for w in caught if "db/repo/code-repo/plane" in str(w.message)] == \
        ["db/repo/code-repo/plane: the run's code is 2.7.1, below the ledger's 9.0.0; the clock keeps 9.0.0"]
    assert "db/repo/code-repo/plane" not in capfd.readouterr().err     # not the worker's stderr


def test_clean_reads_the_repos_commit_row(mounted):
    L, repo = mounted
    with pytest.raises(NotClean, match="names no db/repo/code-repo commit"):
        L.at().run("plane.measure.length", a=(0, 0), b=(3, 4), clean=True)
    L.at().run("plane.measure.length", a=(0, 0), b=(3, 4))
    assert L.at().run("plane.measure.length", a=(0, 0), b=(3, 4), clean=True).obj == 2.5
    with L.transaction(by="t") as t:
        t.add("db/repo/code-repo", "commit", "0" * 40)
    with pytest.raises(NotClean, match="binds db/repo/code-repo to 00000000"):
        L.at().run("plane.measure.length", a=(0, 0), b=(3, 4), clean=True)


def test_codes_package_is_the_root_whose_version_it_read(mounted, installed):
    L, repo = mounted
    assert L.at().resolve("plane.measure.length").code.package == "plane"
    assert L.at().resolve("bare.calc.length").code.package is None        # named by its commit
    (repo / "plane/__init__.py").write_text('__version__ = "2.7.2"\n')     # dirty
    assert L.at().resolve("plane.measure.length").code.package is None
    assert L.at().resolve("geom1037.dist.distance").code.package == "geom1037"


def test_a_hand_seal_with_no_code_writes_no_clock(mounted):
    L, _repo = mounted
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with L.transaction(by="t") as t:
            Value.Blob({"x": 1}).seal(t)
    assert not [r for r in L.at().rows() if r.subject.startswith("db/repo/")]


def test_a_hand_seal_with_an_fn_dep_moves_the_clock(mounted):
    L, repo = mounted
    f = L.at().resolve("plane.measure.length")
    with L.transaction(by="t") as t:
        Value.Blob({"x": 2}).seal(t, deps=[f])
    assert L.at()["db/repo/code-repo/plane", "version"] == "2.7.1"
    assert L.at()["db/repo/code-repo", "commit"] == git(repo, "rev-parse", "HEAD")


def test_bump_source_takes_the_innermost_version(pkg):
    (pkg / "bumpme/inner").mkdir()
    (pkg / "bumpme/inner/__init__.py").write_text('__version__ = "4.0.0"\n')    # a mount root's own
    (pkg / "bumpme/inner/leaf.py").write_text("Y = 2\n")
    b = bump_source("bumpme.inner.leaf")
    assert (b.old, b.new, b.path, b.package) == ("4.0.0", "4.0.1", pkg / "bumpme/inner/__init__.py", "bumpme.inner")
    assert '__version__ = "0.1.0"' in (pkg / "bumpme/__init__.py").read_text()
