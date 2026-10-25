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
# #### Setup

# %%
import os, shutil, subprocess, sys
from pathlib import Path

from IPython.display import SVG, display

from dvc_dat import Dat
from dvc_dat.ledger import Ledger, bump

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
# ## A dat is a folder with a spec
#
# A spec is a recursive dict of parameters; its `dat:` part is what
# the dat system reads. `do:` names the run function, `kwargs:` its
# arguments, `base:` a spec to inherit, `name:` a folder template.

# %%
module_path = Path("mymodule")
(module_path / "specs").mkdir(parents=True)
(module_path / "mult.py").write_text('''\
import csv
from pathlib import Path


def write_table(folder, n=10, start=1):
    """`table.csv`, the n x n multiplication table from `start`; its cell count."""
    numbers = range(start, start + n)
    with open(Path(folder, "table.csv"), "w", newline="") as f:
        csv.writer(f).writerows([[a * b for b in numbers] for a in numbers])
    return n * n


def table(dat, n=10, start=1):
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
  base: specs.table_base
  name: tables/{YYYY}/table12{unique}
  do: mymodule.mult.table
  kwargs: {n: 12}
''');

# %% [markdown]
# `do` instantiates a spec: it merges the base under it, fills the
# name template once, makes the folder, and calls the run function
# with the dat and its kwargs. Mounting `specs/` makes
# `specs/table12.yaml` answer to `specs.table12`.

# %%
do = Dat.do
do.mount(folder="mymodule/specs", at="specs")
table12_dat = do("specs.table12")
table12_path = Path(table12_dat.get_path())
print("dat:", repr(table12_dat))   # dat: <Dat: tables/2026/table12>
print("files:", sorted(os.listdir(table12_path)))
# files: ['_result_.yaml', '_spec_.yaml', 'log.txt', 'run', 'table.csv']
print("_spec_.yaml:\n" + (table12_path / "_spec_.yaml").read_text())
# _spec_.yaml: kwargs {start: 1, n: 12}; no base:; name: the template
print("cells:", table12_dat.get_results()["cells"])   # cells: 144
print("table.csv:\n" + "\n".join((table12_path / "table.csv").read_text().splitlines()[:3]))
# table.csv: rows 1..12, 2..24, 3..36

again_dat = do("specs.table12")
print("dat:", repr(again_dat))   # dat: <Dat: tables/2026/table12_2>

# %% [markdown]
# The folder holds whatever the run wrote, beside `_spec_.yaml` (the
# spec, base merged in, stored whole) and `_result_.yaml` (what the
# run stored); `run/` records when, where and on which commit it ran.
# The spec keeps `name:` as its template; the folder it filled to is
# the dat's name, and `{unique}` counts up on a second run.

# %% [markdown]
# ## A dat is also a value
#
# On a ledger a dat is a value: sealed under a name, loaded back,
# found by its preds. `TableDat` is a ledger value class over a dat
# folder; `as_value` reads its preds from the spec's kwargs and the
# result.

# %%
(module_path / "table_dat.py").write_text('''\
from pathlib import Path

import yaml

from dvc_dat.ledger import Dat, ledger_class, ledger_fn

from mymodule.mult import write_table


@ledger_class(preds=("n", "start", "cells"))
class TableDat(Dat):
    """A table dat: `_spec_.yaml`, `_result_.yaml`, `table.csv`."""

    @classmethod
    def kind_ok(cls, kind):
        """`do` made it, so its `_spec_` says `dvc_dat.core.Dat`."""
        return kind == "dvc_dat.core.Dat" or super().kind_ok(kind)


def as_value(folder) -> TableDat:
    """The dat in `folder` as a value; its kwargs and result are its preds."""
    spec = yaml.safe_load(Path(folder, "_spec_.yaml").read_text())
    result = yaml.safe_load(Path(folder, "_result_.yaml").read_text())
    value = TableDat(Path(folder))
    value.preds.update(spec["dat"]["kwargs"])
    value.preds["cells"] = result["cells"]
    return value


@ledger_fn
def table(rev, *, spec: dict, path: Path) -> TableDat:
    """The table constructor: `spec` the question, `path` the folder."""
    cells = write_table(path, **spec["dat"]["kwargs"])
    (path / "_spec_.yaml").write_text(yaml.safe_dump(spec))
    (path / "_result_.yaml").write_text(yaml.safe_dump({"cells": cells}))
    return as_value(path)
''')
from mymodule.table_dat import TableDat, as_value

hand_dat = as_value(table12_path)
with L.transaction(by="human:dan") as t:
    hand_dat.seal(t, name="tables/table12")
print("dat:", repr(hand_dat), " sealed:", hand_dat.sealed)   # dat: <TableDat tables/table12>  sealed: <the seal's moment>

loaded_dat = L.at().load("tables/table12")
print("files:", sorted(p.name for p in loaded_dat.path.iterdir()))
# files: ['_result_.yaml', '_spec_.yaml', 'log.txt', 'run', 'table.csv']
print("preds:", dict(sorted(loaded_dat.preds.items())))
# preds: {'cells': '144', 'n': '12', 'start': '1'}

# %% [markdown]
# Sealing sent the files to the art store by their hashes; the
# manifest naming them is the value's bytes. `load` rebuilds the
# folder from the store.

# %% [markdown]
# ## The dat constructor is a ledger function
#
# `table(rev, *, spec, path)` builds a table dat under `@ledger_fn`:
# the spec is the question, and the answer is remembered. A ledger
# function runs committed, mounted code, in a sandbox.

# %%
subprocess.run(git_cmd + ["add", "mymodule"], check=True)
subprocess.run(git_cmd + ["commit", "-q", "-m", "mymodule"], check=True)
with L.transaction(by="human:dan", why="mount mymodule") as t:
    t.add("db/mount/mymodule", "db/root", "mymodule")
    t.add("db/mount/mymodule", "db/repo", "q-dats")
    bump(t, "code/q-dats", "minor", confirm=lambda old, new: True)

table12_spec_record = do.resolve("specs.table12")
spec_dat = L.at().run("mymodule.table_dat.table", spec=table12_spec_record)
print("dat:", repr(spec_dat))   # dat: <TableDat anonymous/Dat>: no name given

top_id = L.at().id
again_spec_dat = L.at().run("mymodule.table_dat.table", spec=table12_spec_record)
print("same subject:", again_spec_dat.subject == spec_dat.subject,
      " nothing written:", L.at().id == top_id)   # same subject: True  nothing written: True: a hit

# %% [markdown]
# The same spec is the same question: the second run is a memo hit,
# nothing runs and nothing is written.

# %% [markdown]
# ## Finding dats

# %%
for n in (5, 9):
    L.at().run("mymodule.table_dat.table",
               spec={"dat": {"do": "mymodule.mult.table", "kwargs": {"n": n, "start": 1}}})
print("cells:", L.at().select(("n", "cells"), kind=TableDat))
# cells: [('12', '144'), ('12', '144'), ('5', '25'), ('9', '81')]: table12 by hand, then by the constructor

# %% [markdown]
# Spec kwargs and results are preds, so a query over them is an
# ordinary ledger query.
