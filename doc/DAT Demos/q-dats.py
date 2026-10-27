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
# > A dat is a folder made from a spec, a recursive dict of
# > parameters. Dat creation is three steps: look up the spec,
# > expand it (merge its base, fill its `{}`), instantiate the Dat
# > and its folder; each run by hand, the last producing the dat.
# > Then `Dat.create`, the shorthand doing all three in one call. Then
# > `Dat.manager.run`, the one way to run a dat, and `dat.run`, the
# > record it leaves. Then a ledger: `L.at().run` is a run remembered, its
# > spec the memo key, the same spec asked again found, not run; a
# > dat sealed as a value; dats found by their preds.

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
Path(".datconfig.yaml").write_text("dat_folders: data\n")   # a plain dat project: its dats live in data/
Dat.manager = None                   # the dat world reloads from this folder


def show(name):
    """The figure `<name>.svg` beside this notebook."""
    display(SVG(filename=str(demos_path / f"{name}.svg")))


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
    """The run function: `Dat.manager.run` calls it with the new dat and the spec's kwargs."""
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
Dat.do.mount(folder="mymodule", at="mymodule")   # mymodule's files join the dat world's namespace:
# mymodule/specs/table12.yaml answers to mymodule.specs.table12, build_table in mult.py to mymodule.mult.build_table



# %% [markdown]
# # Quick: dats
#
# A dat is a handle for a folder of arbitrary data, derived from and
# specified by a recursive dictionary of parameters: its spec. On a
# ledger it is also a value: sealed, loaded, memoized, found.

# %%
show("q-dats")

# %% [markdown]
# A spec's `dat:` part is what the dat system reads: `do:` names the
# run function, `kwargs:` its arguments, `base:` a spec to inherit,
# `name:` a folder template; Setup's `table12` inherits `table_base`.

# %% [markdown]
# ## Dat creation
#
# A dat is created in three steps:
#
# 1. **Look up** its spec by name: `Dat.do.load(name)` is the object
#    a dotted name names, here the spec file's dict as written.
# 2. **Expand** it: `Dat.manager.expand_spec(spec)` merges the spec
#    over its `dat.base`, which it drops, then fills every template
#    variable `{}`; `{YYYY}` is the year, `{unique}` empty.
# 3. **Instantiate** it: `Dat.create(spec=expanded_spec)` is the Dat
#    object, its folder made and `_spec_.yaml` written. Nothing runs.

# %%
spec = Dat.do.load("mymodule.specs.table12")    # 1. the spec as written
expanded_spec = Dat.manager.expand_spec(spec)   # 2. dat.base merged in, every {…} filled
table12_dat = Dat.create(spec=expanded_spec)    # 3. the Dat and its folder

# %%
# print results
table12_path = Path(table12_dat.get_path())
print("SPEC:    ", spec)
print("EXPANDED:", expanded_spec)   # base: gone, kwargs gains start, notes appears, name: filled
print("DAT:     ", repr(table12_dat))
print("FILES:   ", sorted(os.listdir(table12_path)))
print("_SPEC_.YAML:\n" + textwrap.indent((table12_path / "_spec_.yaml").read_text(), "    "))
# _spec_.yaml: the expanded spec, plus kind: dvc_dat.core.Dat

# %% [markdown]
# ## `Dat.create`, the three steps in one call
#
# `Dat.create(spec=name)` is the shorthand: it looks the spec up,
# expands it (base merged, `{}` filled) and instantiates the dat.
# Nothing runs.

# %%
shorthand_dat = Dat.create(spec="mymodule.specs.table12")   # steps 1-3

# %%
# print results
shorthand_path = Path(shorthand_dat.get_path())
print("DAT:", repr(shorthand_dat))
print("MANUAL _SPEC_.YAML:\n" + textwrap.indent((table12_path / "_spec_.yaml").read_text(), "    "))
print("SHORTHAND _SPEC_.YAML:\n" + textwrap.indent((shorthand_path / "_spec_.yaml").read_text(), "    "))
# the same kwargs, do, kind and notes; name: tables/2026/table12 by hand, tables/{YYYY}/table12{unique} in the shorthand

# %% [markdown]
# One difference, in `name:`. The shorthand expands `{}` after it
# places the folder, with the placement's own `{YYYY}` and `{unique}`:
# `table12` is taken, so `{unique}` counts up to `_2`, and
# `_spec_.yaml` keeps `name:` as the template. By hand,
# `expand_spec` sees no folder, so `{unique}` is always empty and
# `name:` is filled once; were `tables/2026/table12` taken, step 3
# would raise `FileExistsError` instead of counting up.

# %% [markdown]
# ## Running a dat
#
# `Dat.manager.run(dat)` is the one way to run a dat: it calls the
# spec's run function with the dat and the spec's kwargs, in place,
# and records the run in `dat.run`. `save()` in the run function
# seals the folder, its results in `_result_.yaml`.
# The cell runs once: a sealed dat refuses a second run, which
# `RuntimeError: ... is sealed` reports.

# %%
Dat.manager.run(table12_dat)   # calls build_table in mult.py with this dat and n=12, start=1

# %%
# print results
print("FILES:", sorted(os.listdir(table12_path)))
print("CELLS:", table12_dat.get_results()["cells"])
print("TABLE.CSV:\n" + textwrap.indent("\n".join((table12_path / "table.csv").read_text().splitlines()[:3]), "    "))
print("_RESULT_.YAML:\n" + textwrap.indent((table12_path / "_result_.yaml").read_text(), "    "))

# %% [markdown]
# `dat.run` is the run's record, a sub-dat in the dat's `run/`
# folder: when and where it ran, on which commit, how long it took
# and the hash it sealed. It is outside the dat's own hash.

# %%
run_results = table12_dat.run.get_results()["dat"]
print("run:", repr(table12_dat.run))   # run: <Dat: tables/2026/table12/run>
print("run_at:", run_results["run_at"])   # run_at: when the run started
print("run_time:", run_results["run_time"])   # run_time: how long build_table took
print("code:", run_results["code"])   # code: the branch, commit and dirty flag of the checkout holding mult.py

# %% [markdown]
# Given a name, `Dat.manager.run` creates the dat from the spec
# first: it returns what the run function returned, a new folder
# every call.

# %%
again_dat = Dat.manager.run("mymodule.specs.table12")   # same as: Dat.manager.run(Dat.create(spec="mymodule.specs.table12"))
print("dat:", repr(again_dat))   # dat: <Dat: tables/2026/table12_3>
print("files:", sorted(os.listdir(again_dat.get_path())))
# files: ['_result_.yaml', '_spec_.yaml', 'log.txt', 'run', 'table.csv']

# %% [markdown]
# ## On a ledger: memo, seal, find
#
# A ledger remembers: a run is a memo entry, found again rather than
# rerun; a dat is a value, sealed under a name and loaded back; dats
# are found by their preds.
#
# `Ledger(create=True)` makes the ledger in this folder and adds
# `ledger:` to `.datconfig.yaml`; the reloaded dat world names
# through it. In a ledger project names come from the ledger's
# mounts alone and `Dat.do.mount` is refused, so `mymodule` is
# mounted as two `db/mount` rows; the earlier mount went with the
# old world.
#
# #### Setup

# %%
L = Ledger(create=True)              # .dat/ledger, and ledger: in .datconfig.yaml
Dat.manager = None                   # the dat world reloads, its namespace the ledger's
print(".datconfig.yaml:", Path(".datconfig.yaml").read_text().splitlines())
# → .datconfig.yaml: ['dat_folders: data', 'ledger: .dat/ledger']
import mymodule                      # discovery finds the checkout, the repo q-dats
with L.transaction(by="human:dan", why="mount mymodule") as t:
    t.add("db/mount/mymodule", "db/root", "mymodule")   # the folder the prefix names
    t.add("db/mount/mymodule", "db/repo", "q-dats")     # in this repo's checkout
try:
    Dat.do.mount(folder="mymodule", at="mymodule")
except TypeError as e:
    print("refused:", str(e).split(" (")[0])
# → refused: a ledger project names things through its db/mount rows

# %% [markdown]
# `L.at().run(name)` is a run remembered on the ledger: the result
# found if this code computed it before, else run and sealed as the
# memo entry. One call creates the dat in the three steps, runs it,
# and remembers it.

# %%
table12_value = L.at().run("mymodule.specs.table12")
print("ran:", repr(table12_value))   # ran: <Dat tables/2026/table12>: the spec's template, filled in the ledger's data folder

# %% [markdown]
# ### What run did, piece by piece
#
# `L.at().resolve(name)` is what a dotted name denotes on the ledger,
# read off the mounted file, never imported: the spec's dict, as
# `Dat.do.load` gave it. Its bases merged and `{}` expanded, with
# `dat.name` removed and `dat.kind` set, it is the memo key, stored
# as the value's `db/keys`.

# %%
print("spec:", L.at().resolve("mymodule.specs.table12"))
# → spec: {'dat': {'base': 'mymodule.specs.table_base', 'name': 'tables/{YYYY}/table12{unique}', 'do': 'mymodule.mult.build_table', 'kwargs': {'n': 12}}}
print("expanded:", Dat.manager.expand_spec(Dat.do.load("mymodule.specs.table12")))   # base merged and {} filled, through the ledger's mounts
# → expanded: {'dat': {'kwargs': {'start': 1, 'n': 12}, 'name': 'tables/2026/table12', 'do': 'mymodule.mult.build_table'}, 'notes': 'shared defaults'}
print("db/keys:", L.at()[table12_value.subject, "db/keys"])   # the memo key
# → db/keys: {'dat': {'do': 'mymodule.mult.build_table', 'kind': 'dvc_dat.core.Dat', 'kwargs': {'n': 12, 'start': 1}}, 'notes': 'shared defaults'}

# %% [markdown]
# The run function resolves to an `Fn`, a ledger function: kind
# `dat` (undecorated, run through a spec), sandboxed because it is
# mounted. It ran in a sandboxed worker, its code the mounted files
# it loaded; `db/fn` names it, and the first clean run wrote the
# package's version clock at `db/repo/q-dats/mymodule`.

# %%
run_fn = L.at().resolve("mymodule.mult.build_table")
print("fn:", repr(run_fn), " kind:", run_fn.kind, " sandboxed:", run_fn.code.sandboxed)
# → fn: <Fn mymodule.mult.build_table@0.1.0>  kind: dat  sandboxed: True
print("db/fn:", L.at()[table12_value.subject, "db/fn"])   # db/fn: mymodule.mult.build_table
print("db/repo/q-dats/mymodule:", L.at()["db/repo/q-dats/mymodule", "version"])   # db/repo/q-dats/mymodule: 0.1.0

# %% [markdown]
# The same spec asked again is a memo hit: nothing runs, nothing is
# written.

# %%
top_id = L.at().id
again_value = L.at().run("mymodule.specs.table12")
print("hit:", again_value.subject == table12_value.subject,
      " nothing written:", L.at().id == top_id)   # hit: True  nothing written: True

# %% [markdown]
# ### Saving a plain dat as a value
#
# On a ledger a dat is a value: sealed under a name, loaded back,
# found by its preds. The hand-made `table12_dat` is sealed here; nothing
# runs. Its preds are its spec's `kwargs` and its result's entries,
# read from the folder.

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

# %% [markdown]
# Sealing sent the files to the art store by their hashes; the
# manifest naming them is the value's bytes. `load` rebuilds the
# folder from the store, a view in the ledger's data folder; it does
# not run anything.

# %% [markdown]
# ### Finding dats

# %%
for n in (5, 9):
    L.at().run("mymodule.specs.table12", n=n)   # kwargs update the spec's dat.kwargs, as with Dat.manager.run
print("found:", L.at().values(kind=Dat))
# → found: [<Dat tables/2026/table12>, <Dat table/12>, <Dat tables/2026/table12_2>, <Dat tables/2026/table12_3>]
print("cells:", L.at().select(("n", "cells"), kind=Dat))
# → cells: [('12', '144'), ('12', '144'), ('5', '25'), ('9', '81')]: L.at().run's n=12, table/12 sealed from table12_dat, then n=5 and n=9

# %% [markdown]
# Spec kwargs and results are preds, so a query over them is an
# ordinary ledger query.
