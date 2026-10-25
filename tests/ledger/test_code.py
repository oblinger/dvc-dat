"""``fn.code`` (DAT 1037): the code a function is loaded from, at a version, as a ``Code`` value.

Installed code reads its version from its environment; mounted code from the mounted root's
``__version__``, read after import, else from git. ``Fn.mode`` is gone."""

import re
import subprocess
import sys
import textwrap

import pytest

import backends
from dvc_dat.ledger import Code, set_env_provider
from dvc_dat.ledger.sandbox import shutdown

FN = textwrap.dedent('''
    import math
    from dvc_dat.ledger import ledger_fn

    @ledger_fn
    def length(rev, a, b) -> float:
        return math.dist(a, b) * 0.5
''')

REPO = {
    "pyproject.toml": '[project]\nname = "code-repo"\nversion = "0.1.0"\n',
    "code_anchor.py": "",                   # imported so discovery sees the checkout
    "plane/__init__.py": '__version__ = "2.7.1"\n',
    "plane/measure.py": FN,
    "bare/__init__.py": "",
    "bare/calc.py": FN,
}


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


def forget(*tops):
    for m in [m for m in sys.modules if m.split(".")[0] in tops]:
        del sys.modules[m]


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """A package outside any checkout, on ``sys.path``, declaring ``__version__``."""
    root = tmp_path / "site"
    (root / "geom1037").mkdir(parents=True)
    (root / "geom1037/__init__.py").write_text('__version__ = "5.3.9"\n')
    (root / "geom1037/dist.py").write_text(FN.replace("length", "distance"))
    monkeypatch.syspath_prepend(str(root))
    forget("geom1037")
    yield root
    forget("geom1037")


@pytest.fixture
def mounted(tmp_path, monkeypatch):
    repo = tmp_path / "code-repo"
    for rel, text in REPO.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "one")
    monkeypatch.syspath_prepend(str(repo))
    forget("code_anchor", "plane", "bare")
    import code_anchor  # noqa: F401  (discovery sees the checkout)
    old = set_env_provider(None)
    L = backends.make("sqlite", tmp_path / "ledger")
    with L.transaction(by="t") as t:
        for prefix in ("plane", "bare"):
            t.add(f"db/mount/{prefix}", "db/root", prefix)
            t.add(f"db/mount/{prefix}", "db/repo", "code-repo")
    yield L, repo
    shutdown()
    set_env_provider(old)
    forget("code_anchor", "plane", "bare")


def test_installed_code_takes_its_packages_version(L, installed):
    f = L.at().load_fn("geom1037.dist.distance")
    assert isinstance(f.code, Code)
    assert f.code.sandboxed is False and f.code.version == "5.3.9" and f.code.mounts == {}
    assert "geom1037/dist.py" in f.code.modules
    assert f.code.commit is None and f.code.lock is None        # outside any checkout
    assert str(f) == "geom1037.dist.distance@5.3.9" and repr(f) == "<Fn geom1037.dist.distance@5.3.9>"
    assert str(f.code) == "geom1037@5.3.9" and repr(f.code) == "<Code geom1037@5.3.9>"
    assert f(a=(3, 4), b=(0, 0), seal=False).obj == 2.5     # outside a checkout: a draft only


def test_installed_code_without_a_version_falls_back_to_the_fn_sha(L, installed):
    (installed / "geom1037/__init__.py").write_text("")
    forget("geom1037")
    f = L.at().load_fn("geom1037.dist.distance")
    assert f.code.version == "#" + f.sha[:8]


def test_mounted_code_takes_the_roots_version(mounted):
    L, repo = mounted
    f = L.at().load_fn("plane.measure.length")
    assert f.code.sandboxed is True and f.code.version == "2.7.1"
    assert f.code.modules == ["plane/__init__.py", "plane/measure.py"]
    assert f.code.mounts == {"plane": {"repo": "code-repo", "root": "plane"},
                             "bare": {"repo": "code-repo", "root": "bare"}}
    assert f.code.commit == git(repo, "rev-parse", "HEAD") and f.code.lock is None   # no uv.lock committed
    assert str(f) == "plane.measure.length@2.7.1" and repr(f.code) == "<Code plane@2.7.1>"
    assert "plane" not in sys.modules            # the version was read in the worker, not here
    assert f(a=(0, 0), b=(3, 4)).obj == 2.5


def test_mounted_code_records_the_lock(mounted):
    L, repo = mounted
    (repo / "uv.lock").write_text("version = 1\n")
    git(repo, "add", "uv.lock")
    git(repo, "commit", "-q", "-m", "lock")
    f = L.at().load_fn("plane.measure.length")
    assert f.code.lock == git(repo, "rev-parse", "HEAD:uv.lock")


def test_a_mounted_root_without_a_version_is_named_by_its_commit(mounted):
    L, repo = mounted
    f = L.at().load_fn("bare.calc.length")
    assert re.fullmatch(r"[0-9a-f]{8}", f.code.version)
    assert git(repo, "rev-parse", "HEAD").startswith(f.code.version)
    assert str(f.code) == f"bare@{f.code.version}"


def test_a_dirty_loaded_file_says_dirty(mounted):
    L, repo = mounted
    calc = repo / "bare/calc.py"
    calc.write_text(calc.read_text() + "\n# edited\n")
    f = L.at().load_fn("bare.calc.length")
    assert re.fullmatch(r"[0-9a-f]{8}\+dirty", f.code.version)


def test_a_version_bump_is_a_new_version(mounted):
    L, repo = mounted
    (repo / "plane/__init__.py").write_text('__version__ = "2.7.2"\n')
    git(repo, "commit", "-q", "-am", "bump")
    assert str(L.at().load_fn("plane.measure.length")) == "plane.measure.length@2.7.2"


def test_fn_has_no_mode(L, installed):
    f = L.at().load_fn("geom1037.dist.distance")
    assert not hasattr(f, "mode")


def test_codes_properties_are_read_only(L, installed):
    code = L.at().load_fn("geom1037.dist.distance").code
    for prop in ("modules", "mounts", "commit", "lock", "sandboxed", "version", "name"):
        with pytest.raises(AttributeError):
            setattr(code, prop, None)
    code.modules.append("x.py")                 # a copy: the content does not change
    assert "x.py" not in code.modules
