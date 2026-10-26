"""Discovery (A56): the dvc-dat checkout itself is never a repo of the process, a nested demo checkout is."""

import subprocess
import sys

from dvc_dat.ledger.env import discover


def git(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True,
                   capture_output=True)


def test_a_module_inside_the_dvc_dat_checkout_is_not_a_repo(tmp_path, monkeypatch):
    own = tmp_path / "dvc-dat-copy"
    (own / "doc" / "demos" / "insidepkg").mkdir(parents=True)
    (own / "pyproject.toml").write_text('[project]\nname = "dvc_dat"\n')
    (own / "doc" / "demos" / "insidepkg" / "__init__.py").write_text("")
    nested = own / "doc" / "demos" / "scratch" / "demo"
    (nested / "nestedpkg").mkdir(parents=True)
    (nested / "pyproject.toml").write_text('[project]\nname = "demo-game"\n')
    (nested / "nestedpkg" / "__init__.py").write_text("")
    for repo in (nested, own):
        git(repo, "init", "-q")
        git(repo, "add", ".")
        git(repo, "commit", "-q", "-m", "x")
    monkeypatch.syspath_prepend(str(own / "doc" / "demos"))
    monkeypatch.syspath_prepend(str(nested))
    import insidepkg  # noqa: F401
    import nestedpkg  # noqa: F401
    try:
        code = discover().code
        assert "dvc-dat" not in code and "dvc_dat" not in code
        assert "demo-game" in code and code["demo-game"].path.name == "demo"
    finally:
        del sys.modules["insidepkg"], sys.modules["nestedpkg"]


def test_a_dat_noncode_path_leaves_the_checkout_clean(tmp_path, monkeypatch):
    """T560: `.gitattributes` `doc/** dat-noncode` keeps a doc edit out of both dirty bits; a code edit is dirty."""
    from dvc_dat.core import _code_of
    from dvc_dat.ledger.env import code_at

    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "doc" / "sub").mkdir(parents=True)
    (repo / ".gitattributes").write_text("doc/** dat-noncode\n")
    (repo / "pkg" / "noncodemod.py").write_text("def f():\n    return 1\n")
    (repo / "doc" / "sub" / "page.md").write_text("# page\n")
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "x")
    monkeypatch.syspath_prepend(str(repo / "pkg"))
    import noncodemod
    try:
        def dirty():
            a, b = _code_of(noncodemod.f)["dirty"], code_at(str(repo)).dirty
            assert a == b
            return a

        assert dirty() is False
        (repo / "doc" / "sub" / "page.md").write_text("# page, rewritten\n")
        assert dirty() is False                      # a doc edit is not a code edit
        (repo / "pkg" / "noncodemod.py").write_text("def f():\n    return 2\n")
        assert dirty() is True                       # a code edit is
        git(repo, "checkout", "-q", "--", "pkg")
        assert dirty() is False
        (repo / ".gitattributes").write_text("")     # the attribute is the rule: without it doc/ is code
        git(repo, "commit", "-qm", "drop attr", "--", ".gitattributes")
        assert dirty() is True
    finally:
        del sys.modules["noncodemod"]


def _twin(run, modname):
    """A checkout ``<run>/twin`` holding ``modname``: named by its folder (no pyproject), as two scratch
    runs of one demo are, so a deleted one still carries the name."""
    folder = run / "twin"
    folder.mkdir(parents=True)
    (folder / f"{modname}.py").write_text("")
    git(folder, "init", "-q")
    git(folder, "add", ".")
    git(folder, "commit", "-q", "-m", "x")
    return folder


def test_a_deleted_checkout_is_not_discovered_when_a_live_one_shares_its_name(tmp_path, monkeypatch):
    """DAT 1023: a re-run's previous scratch checkout, deleted, still has modules in ``sys.modules``;
    discovery reports the live checkout of that name, never the deleted one (whichever sorts last)."""
    import shutil

    old = _twin(tmp_path / "run-b", "twin_old_1023")       # sorts after the live one
    live = _twin(tmp_path / "run-a", "twin_new_1023")
    monkeypatch.syspath_prepend(str(old))
    import twin_old_1023  # noqa: F401
    try:
        assert discover().code["twin"].path == old              # the first run, while its checkout exists
        monkeypatch.syspath_prepend(str(live))
        import twin_new_1023  # noqa: F401
        shutil.rmtree(old)                                      # the re-run deletes the previous scratch
        co = discover().code["twin"]
        assert co.path == live and co.commit is not None
    finally:
        sys.modules.pop("twin_old_1023", None)
        sys.modules.pop("twin_new_1023", None)


def test_two_live_checkouts_sharing_a_name_resolve_to_the_latest_imported(tmp_path, monkeypatch):
    """DAT 1023: of two existing same-named checkouts, the one the most recently imported module was
    loaded from wins, not the one whose path sorts last."""
    first = _twin(tmp_path / "run-b", "twin_first_1023")
    second = _twin(tmp_path / "run-a", "twin_second_1023")
    monkeypatch.syspath_prepend(str(first))
    monkeypatch.syspath_prepend(str(second))
    import twin_first_1023  # noqa: F401
    import twin_second_1023  # noqa: F401
    try:
        assert discover().code["twin"].path == second
    finally:
        sys.modules.pop("twin_first_1023", None)
        sys.modules.pop("twin_second_1023", None)
