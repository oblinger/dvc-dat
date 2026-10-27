# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.6
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # dvc-dat walkthrough
#
# One small project, built in a temp folder, run top to bottom against dvc-dat 2.12:
# a mounted folder of YAML templates, a `dat.base` chain, `do()` and a keyword
# fork, loading a dat, the `merge_dicts` recipe, and the command-line main.
# Nothing is written outside the temp folder. The reference is in
# [`doc/`](../index.md).

# %% [markdown]
# ## The project
#
# A `.datconfig.yaml`, a `catalog/` of templates, and a package whose `main.py`
# makes the mounts. `experiment.yaml` inherits from `base.yaml`.

# %%
import os, subprocess, sys, tempfile, textwrap
from pathlib import Path

# resolve(): on macOS the temp folder sits behind the /var -> /private/var symlink
PROJECT = Path(tempfile.mkdtemp(prefix="dat-walkthrough-")).resolve()

FILES = {
    ".datconfig.yaml": """
        dat_folders: data
        run: python -m mypkg.main
    """,
    "catalog/base.yaml": """
        dat:
          do: mypkg.train.train
          name: "runs/{YYYY}-{MM}-{DD}/exp{unique}"
          kwargs: {epochs: 10, lr: 0.1}
        model: {layers: 2, width: 64}
    """,
    "catalog/experiment.yaml": """
        dat:
          base: catalog.base
          kwargs: {lr: 0.01}
        model: {width: 128}
    """,
    "mypkg/__init__.py": "",
    "mypkg/train.py": """
        def train(dat, epochs, lr):
            dat.get_results()["loss"] = round(1 / (1 + epochs * lr), 4)
            dat.save()      # seals the dat when the run ends
            return dat
    """,
    "mypkg/main.py": """
        import os
        import sys
        from pathlib import Path
        from dvc_dat import Dat

        ROOT = Path(__file__).parent.parent
        Dat.do.mount(folder=str(ROOT / "catalog"), at="catalog")

        if __name__ == "__main__":
            if os.environ.get("DAT_CLI_CONFIG"):   # launched by `just run`
                sys.exit(Dat.cli_main())
    """,
}
for name, text in FILES.items():
    path = PROJECT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip())
print(*sorted(FILES), sep="\n")

# %% [markdown]
# ## Mount the catalog
#
# `DatManager.load_dat_config(PROJECT, do=do)` reads that config and becomes
# the default world, `Dat.manager` (a program run from inside the project needs
# no call: the first `do` finds the nearest `.datconfig.yaml`). It also puts the
# project first on `sys.path`, so importing `mypkg.main` makes its mounts,
# exactly as a notebook would import any program's main.

# %%
from dvc_dat import Dat, DatManager

do, merge_dicts = Dat.do, Dat.merge_dicts

Dat.manager = DatManager.load_dat_config(PROJECT, do=do)
import mypkg.main  # noqa: E402,F401 -- the mounts

do.load("catalog.experiment")      # the template as written

# %% [markdown]
# ## Run a template, then fork it
#
# `do(template)` creates a dat from the template and runs it as
# `fn(dat, *dat.args, **dat.kwargs)`. Keyword arguments fork: they are written
# into the new dat's `dat.kwargs`, so the spec on disk is the record of the run. A run saves nothing by itself:
# `train` ends with `dat.save()`, which seals the dat when the run returns.

# %%
d1 = do("catalog.experiment")
d2 = do("catalog.experiment", epochs=50)
for d in (d1, d2):
    print(d.get_path_name(), d.get_spec()["dat"]["kwargs"], d.get_results()["loss"])

# %% [markdown]
# ## Load a dat
#
# A slash path names a dat folder under `dat_folders`. `_spec_.yaml` is the
# expanded recipe, with `dat.base` merged in when the dat was created: nested
# mappings merge key by key, the child wins, and `dat.base` is gone.
# `_result_.yaml` holds what the run produced and the seal: when it ran, what it
# loaded, and the folder's hash.

# %%
d = Dat.load(d2.get_path_name())
print((Path(d.get_path()) / "_spec_.yaml").read_text())
print((Path(d.get_path()) / "_result_.yaml").read_text())

# %% [markdown]
# ## A variation: `merge_dicts`
#
# A created dat's spec never changes. A variation is a new dat made from an edited
# copy. The copy's `dat.name` is the folder the original landed in, so ask for
# `increment` (or pass `path=`) to land beside it. `do(dat)` runs a dat as it is.

# %%
spec = merge_dicts(d.get_spec(), {"dat": {"target_exists": "increment"},
                                  "model": {"width": 256}})
d3 = do(Dat.create(spec=spec))
print(d3.get_path_name(), d3.get_spec()["model"], d3.get_results()["loss"])


# %% [markdown]
# ## The command line
#
# `x TARGET` is `just run TARGET`: the `run` recipe of `dvc_dat.just` finds
# `.datconfig.yaml`, sets `DAT_CLI_CONFIG` and execs `run:`, here
# `python -m mypkg.main`, which makes its mounts and hands the command line
# to `Dat.cli_main()`. The cell does the same by hand, so it needs no `just`
# on `PATH`. Every `KEY=VALUE` value is JSON, else the text as typed.

# %%
def x(*args):
    env = dict(os.environ, DAT_CLI_CONFIG=str(PROJECT / ".datconfig.yaml"))
    done = subprocess.run([sys.executable, "-m", "mypkg.main", *args],
                          cwd=PROJECT, env=env, capture_output=True, text=True)
    print(f"$ x {' '.join(args)}\n{done.stdout}{done.stderr}")

x("catalog.experiment", "epochs=5", "--dry-run")
x("catalog.experiment", "epochs=5")
x("--list", "catalog")

# %% [markdown]
# ## Clean up

# %%
import shutil
shutil.rmtree(PROJECT)
