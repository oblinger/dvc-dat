"""Discovery (A56): the dvc-dat checkout itself is never a repo of the process, a nested demo checkout is."""

import subprocess
import sys

from dvc_dat.ledger2.env import discover


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
