# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.6
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# > **Plan** (what this sheet teaches; delete once the sections
# > carry it on their own)
# >
# > A dat is a folder made from a spec. The sheet makes one in three
# > steps (instantiate, run, save), then all three at once,
# > remembered on the ledger by `L.at().run`, then finds dats by their
# > preds. In a ledger project names come from the ledger's mounts
# > alone: `L.at().resolve(name)` says what a dotted name denotes, and
# > `Dat.create`, `Dat.do` and `L.at().run` all name through it.

# %% [markdown]
# #### Setup

# %%
import os, shutil, subprocess, sys, textwrap
from pathlib import Path

from IPython.display import SVG, display

from dvc_dat import Dat
from dvc_dat.ledger import Ledger

demos_path = Path(globals().get("demos_path", Path.cwd()))   # survives the chdir
os.chdir(demos_path)
scratch_path = demos_path / "scratch/q-dats"
shutil.rmtree(scratch_path, ignore_errors=True)   # a re-run starts clean
for module_name in [m for m in sys.modules if m.split(".")[0] == "mymodule"]:
    del sys.modules[module_name]
sys.path[:] = [p for p in sys.path if p != str(scratch_path)]

scratch_path.mkdir(parents=True)
os.chdir(scratch_path)
git_cmd = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com"]
Path(".gitignore").write_text(".dat/\ndata/\n")
Path("pyproject.toml").write_text('[project]\nname = "q-dats"\nversion = "0.1.0"\n')
for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "q-dats"]):
    subprocess.run(git_cmd + args, check=True)
sys.path.insert(0, str(scratch_path))
L = Ledger(create=True)              # .datconfig.yaml + .dat/ledger
Dat.manager = None                   # the dat world reloads from this folder


def show(name):
    """The figure `<name>.svg` beside this notebook."""
    display(SVG(filename=str(demos_path / f"{name}.svg")))


# %% [markdown]
# # Quick: dats
#
# A dat is a handle for a folder of arbitrary data, derived from and
# specified by a recursive dictionary of parameters: its spec. On a
# ledger it is also a value: sealed, loaded, memoized, found.

# %%
show("q-dats")

# %% [markdown]
# ## A Dat is a folder with a spec
#
# A spec is a recursive dict of parameters; its `dat:` part is what
# the dat system reads. `do:` names the run function, `kwargs:` its
# arguments, `base:` a spec to inherit, `name:` a folder template.
#
# #### Setup

# %%
# the files: a run function in mult.py, two template specs in specs/
module_path = Path("mymodule")
(module_path / "specs").mkdir(parents=True)
(module_path / "__init__.py").write_text('__version__ = "0.1.0"\n')   # the code's version, in its source
(module_path / "mult.py").write_text('''\
import csv
from pathlib import Path


def write_table(folder, n=10, start=1):
    """`table.csv`, the n x n multiplication table from `start`; its cell count."""
    numbers = range(start, start + n)
    with open(Path(folder, "table.csv"), "w", newline="") as f:
        csv.writer(f).writerows([[a * b for b in numbers] for a in numbers])
    return n * n


def build_table(dat, n=10, start=1):
    """The run function: `do` calls it with the new dat and the spec's kwargs."""
    cells = write_table(dat.get_path(), n, start)
    Path(dat.get_path(), "log.txt").write_text(f"{n} x {n} from {start}\\n")
    dat.get_results()["cells"] = cells
    dat.save()
    return dat
''')
(module_path / "specs/table_base.yaml").write_text('''\
dat:
  kwargs: {start: 1}
notes: shared defaults
''')
(module_path / "specs/table12.yaml").write_text('''\
dat:
  base: mymodule.specs.table_base
  name: tables/{YYYY}/table12{unique}
  do: mymodule.mult.build_table
  kwargs: {n: 12}
''')
subprocess.run(git_cmd + ["add", "mymodule"], check=True)
subprocess.run(git_cmd + ["commit", "-q", "-m", "mymodule"], check=True)
import mymodule                      # discovery finds the checkout, the repo q-dats
with L.transaction(by="human:dan", why="mount mymodule") as t:
    t.add("db/mount/mymodule", "db/root", "mymodule")   # the folder the prefix names
    t.add("db/mount/mymodule", "db/repo", "q-dats")     # in this repo's checkout

# %% [markdown]
# Mounting `mymodule` is two rows on the ledger, and it is the
# project's one namespace: `mymodule/specs/table12.yaml` answers to
# `mymodule.specs.table12`, and `build_table` in `mymodule/mult.py`
# to `mymodule.mult.build_table`. `L.at().resolve(name)` is what a
# dotted name denotes on the ledger: a spec file's dict, a function's
# `Fn`, read off the file and never imported.

# %%
print("spec:", L.at().resolve("mymodule.specs.table12"))
# → spec: {'dat': {'base': 'mymodule.specs.table_base', 'name': …, 'do': 'mymodule.mult.build_table', 'kwargs': {'n': 12}}}
run_fn = L.at().resolve("mymodule.mult.build_table")
print("fn:", repr(run_fn), " kind:", run_fn.kind)   # fn: <Fn mymodule.mult.build_table@0.1.0>  kind: dat

# %% [markdown]
# `build_table` carries no decorator, so its kind is `dat`: a dat's
# run function, run through a spec. Making a dat from a spec is three
# steps: instantiate, run, save.
#
# ## 1. Instantiate
#
# `Dat.create` merges the base under the spec, fills the name template
# once, makes the folder and writes `_spec_.yaml`. Nothing runs.

# %%
table12_dat = Dat.create(spec="mymodule.specs.table12")   # the Dat object, and its folder on disk
table12_path = Path(table12_dat.get_path())
print("dat:", repr(table12_dat))   # dat: <Dat: tables/2026/table12>
print("files:", sorted(os.listdir(table12_path)))   # files: ['_spec_.yaml']
print("_spec_.yaml:\n" + textwrap.indent((table12_path / "_spec_.yaml").read_text(), "    "))
# _spec_.yaml: kwargs {start: 1, n: 12}; no base:; name: the template

# %% [markdown]
# The spec keeps `name:` as its template; the folder it filled to is
# the dat's name, and `{unique}` counts up when the folder is taken.
#
# ## 2. Run
#
# `Dat.do(dat)` calls the run function with the dat and the spec's kwargs,
# in place. The folder gains whatever the run wrote, `_result_.yaml`
# (what the run stored) and `run/` (when, where, on which commit).

# %%
Dat.do(table12_dat)   # executes build_table in mult.py for this dat

print("files:", sorted(os.listdir(table12_path)))
# files: ['_result_.yaml', '_spec_.yaml', 'log.txt', 'run', 'table.csv']
print("cells:", table12_dat.get_results()["cells"])   # cells: 144
print("table.csv:\n" + textwrap.indent("\n".join((table12_path / "table.csv").read_text().splitlines()[:3]), "    "))
# table.csv: rows 1..12, 2..24, 3..36
print("_result_.yaml:\n" + textwrap.indent((table12_path / "_result_.yaml").read_text(), "    "))
# _result_.yaml: cells, and under dat: what the seal recorded

# %% [markdown]
# ## 3. Save it as a value
#
# On a ledger a dat is a value: sealed under a name, loaded back,
# found by its preds. Nothing runs here. Its preds are its spec's
# `kwargs` and its result's entries, read from the folder.

# %%
with L.transaction(by="human:dan") as t:
    table12_dat.seal(t, name="table/12")   # the folder's files go to the art store; the row names the kind, dvc_dat.core.Dat
print("dat:", repr(table12_dat), " sealed:", table12_dat.sealed)   # dat: <Dat table/12>  sealed: <the seal's moment>

loaded_dat = L.at().load("table/12")       # the folder rebuilt from the store; nothing runs
print("files:", sorted(os.listdir(loaded_dat.get_path())))
# files: ['_result_.yaml', '_spec_.yaml', 'log.txt', 'run', 'table.csv']
print("cells:", loaded_dat.get_results()["cells"])   # cells: 144
print("preds:", dict(sorted(loaded_dat.preds.items())))
# preds: {'cells': '144', 'n': '12', 'start': '1'}
print("found:", L.at().values(kind=Dat), L.at().value(n=12))   # found: [<Dat table/12>] table/12

# %% [markdown]
# Sealing sent the files to the art store by their hashes; the
# manifest naming them is the value's bytes. `load` rebuilds the
# folder from the store, a view in the ledger's data folder; it does
# not run anything.

# %% [markdown]
# ## Execution in practice: all done in one step
#
# `Dat.do("mymodule.specs.table12")` is steps 1 and 2: it instantiates
# the spec, runs the dat, and returns what the run function returned.
# It is a plain dat: nothing remembered, a new folder every time.

# %%
again_dat = Dat.do("mymodule.specs.table12")
print("dat:", repr(again_dat))   # dat: <Dat: tables/2026/table12_2>
print("files:", sorted(os.listdir(again_dat.get_path())))
# files: ['_result_.yaml', '_spec_.yaml', 'log.txt', 'run', 'table.csv']

# %% [markdown]
# All three steps at once, remembered, is `L.at().run`: a run on the
# ledger, the same call a ledger function gets. The spec is the memo
# key and the run function's code is part of the result's record:
# mounted, it runs in a sandboxed worker and its code is the files it
# loaded. The same spec asked again is found, not run.

# %%
table12_value = L.at().run("mymodule.specs.table12")
print("ran:", repr(table12_value))   # ran: <Dat tables/2026/table12>: named by the spec's template

top_id = L.at().id
again_value = L.at().run("mymodule.specs.table12")
print("hit:", again_value.subject == table12_value.subject,
      " nothing written:", L.at().id == top_id)   # hit: True  nothing written: True
print("db/fn:", L.at()[table12_value.subject, "db/fn"])   # db/fn: mymodule.mult.build_table
print("db/repo/q-dats/mymodule:", L.at()["db/repo/q-dats/mymodule", "version"])   # db/repo/q-dats/mymodule: 0.1.0: the first clean run wrote the clock
print("db/keys:", L.at()[table12_value.subject, "db/keys"])   # the memo key
# → db/keys: {'dat': {'do': 'mymodule.mult.build_table', 'kind': 'dvc_dat.core.Dat', 'kwargs': {'n': 12, 'start': 1}}, 'notes': 'shared defaults'}

# %% [markdown]
# The memo key is the spec with its base merged in, every `{}`
# expanded and `name:` left out; the second call is a memo hit,
# nothing runs and nothing is written.

# %% [markdown]
# ## Finding dats

# %%
for n in (5, 9):
    L.at().run("mymodule.specs.table12", n=n)   # kwargs update the spec's dat.kwargs, as with Dat.do
print("cells:", L.at().select(("n", "cells"), kind=Dat))
# cells: [('12', '144'), ('12', '144'), ('5', '25'), ('9', '81')]: table/12 sealed from step 2's folder, then by L.at().run

# %% [markdown]
# Spec kwargs and results are preds, so a query over them is an
# ordinary ledger query.
