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
# > parameters. Part 1 makes one with no ledger, step by step: look
# > up the spec, expand it, instantiate the folder, run it; then
# > `Dat.do`, which runs a dat: all four steps in one call, nothing
# > remembered. Part 2 puts the same project on a ledger:
# > `L.at().run` is a run remembered on the ledger, its spec the memo
# > key, the same spec asked again found, not run. Then a plain dat
# > saved as a value, and dats found by their preds.

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


# %% [markdown]
# # Quick: dats
#
# A dat is a handle for a folder of arbitrary data, derived from and
# specified by a recursive dictionary of parameters: its spec. On a
# ledger it is also a value: sealed, loaded, memoized, found.

# %%
show("q-dats")

# %% [markdown]
# ## Part 1. A dat without a ledger, in its parts
#
# A spec's `dat:` part is what the dat system reads: `do:` names the
# run function, `kwargs:` its arguments, `base:` a spec to inherit,
# `name:` a folder template.
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
Dat.do.mount(folder="mymodule", at="mymodule")   # mymodule/specs/table12.yaml answers to mymodule.specs.table12

# %% [markdown]
# `Dat.do.mount` puts a folder's `.py`, `.yaml` and `.json` files in
# the dat world's namespace: `mymodule/specs/table12.yaml` answers to
# `mymodule.specs.table12`, `build_table` in `mymodule/mult.py` to
# `mymodule.mult.build_table`. A mount may not shadow a module Python
# imports from elsewhere; this folder is `mymodule`'s own source.
#
# ### 1. Look up the spec
#
# `Dat.do.load(name)` is the object a dotted name names: here the
# spec file's dict, as written, its base not merged.

# %%
template_spec = Dat.do.load("mymodule.specs.table12")
print("template:", template_spec)
# → template: {'dat': {'base': 'mymodule.specs.table_base', 'name': 'tables/{YYYY}/table12{unique}', 'do': 'mymodule.mult.build_table', 'kwargs': {'n': 12}}}

# %% [markdown]
# ### 2. Merge its bases, then expand it
#
# The spec was loaded in step 1; two more steps make it complete.
# `Dat.do.merge_bases(spec)` merges the spec over its `dat.base`,
# which it drops: `kwargs` gains `start`, the spec gains `notes`.
# `Dat.manager.expand_spec(spec)` then fills every `{}`: `{YYYY}` is
# the year, `{unique}` empty for a first folder.

# %%
merged_spec = Dat.do.merge_bases(template_spec)
print("merged:", merged_spec)
# → merged: {'dat': {'kwargs': {'start': 1, 'n': 12}, 'name': 'tables/{YYYY}/table12{unique}', 'do': 'mymodule.mult.build_table'}, 'notes': 'shared defaults'}
expanded_spec = Dat.manager.expand_spec(merged_spec)
print("expanded name:", expanded_spec["dat"]["name"])   # expanded name: tables/2026/table12

# %% [markdown]
# ### 3. Instantiate
#
# `Dat.create` does all of that itself (loads the spec, merges its
# bases, expands its `{}`), then makes the folder and writes
# `_spec_.yaml`. It fills `{}` once, with the values the folder
# got, so `{unique}` counts up when the folder is taken. Nothing runs.

# %%
table12_dat = Dat.create(spec="mymodule.specs.table12")   # the Dat object, and its folder on disk
table12_path = Path(table12_dat.get_path())
print("dat:", repr(table12_dat))   # dat: <Dat: tables/2026/table12>
print("files:", sorted(os.listdir(table12_path)))   # files: ['_spec_.yaml']
print("_spec_.yaml:\n" + textwrap.indent((table12_path / "_spec_.yaml").read_text(), "    "))
# _spec_.yaml: kwargs {start: 1, n: 12}; no base:; name: the template; kind: dvc_dat.core.Dat

# %% [markdown]
# The spec keeps `name:` as its template; the folder it filled to is
# the dat's name.
#
# ### 4. Run
#
# `do` is DAT's verb for running a dat: `Dat.do(dat)` calls the run
# function with the dat and the spec's kwargs, in place (1.x's
# `Dat.run()`; `dat.run` is now the run's record, not a verb).
# `save()` in the run function seals the folder, its results in
# `_result_.yaml`; `run/` holds when, where and on which commit.

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
# ### 5. All at once
#
# `Dat.do("mymodule.specs.table12")` is steps 1 to 4 in one call: it
# returns what the run function returned. Nothing is remembered: a
# new folder every call.

# %%
again_dat = Dat.do("mymodule.specs.table12")
print("dat:", repr(again_dat))   # dat: <Dat: tables/2026/table12_2>
print("files:", sorted(os.listdir(again_dat.get_path())))
# files: ['_result_.yaml', '_spec_.yaml', 'log.txt', 'run', 'table.csv']

# %% [markdown]
# ## Part 2. The same dat on a ledger
#
# `Ledger(create=True)` makes the ledger in this folder and adds
# `ledger:` to `.datconfig.yaml`; the reloaded dat world names
# through it. In a ledger project names come from the ledger's
# mounts alone and `Dat.do.mount` is refused, so `mymodule` is
# mounted as two `db/mount` rows; Part 1's mount went with the old
# world.
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
# memo entry. One call does Part 1's four steps and remembers them.

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
print("merged:", Dat.do.merge_bases("mymodule.specs.table12"))   # the base merged, through the ledger's mounts
# → merged: {'dat': {'kwargs': {'start': 1, 'n': 12}, 'name': 'tables/{YYYY}/table12{unique}', 'do': 'mymodule.mult.build_table'}, 'notes': 'shared defaults'}
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
# found by its preds. Part 1's `table12_dat` is sealed here; nothing
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
    L.at().run("mymodule.specs.table12", n=n)   # kwargs update the spec's dat.kwargs, as with Dat.do
print("found:", L.at().values(kind=Dat))
# → found: [<Dat tables/2026/table12>, <Dat table/12>, <Dat tables/2026/table12_2>, <Dat tables/2026/table12_3>]
print("cells:", L.at().select(("n", "cells"), kind=Dat))
# → cells: [('12', '144'), ('12', '144'), ('5', '25'), ('9', '81')]: L.at().run's n=12, table/12 sealed from Part 1, then n=5 and n=9

# %% [markdown]
# Spec kwargs and results are preds, so a query over them is an
# ordinary ledger query.
