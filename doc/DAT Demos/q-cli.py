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
from importlib.resources import files
from pathlib import Path

from dvc_dat.ledger import Ledger

demos_path = Path(globals().get("demos_path", Path.cwd()))   # survives the chdir
os.chdir(demos_path)
scratch_path = demos_path / "scratch/q-cli"       # the project; its folder (and pyproject) name it q-cli
shutil.rmtree(scratch_path, ignore_errors=True)   # a re-run starts clean
for module_name in [m for m in sys.modules if m.split(".")[0] in ("mymodule", "q_cli_main")]:
    del sys.modules[module_name]
sys.path[:] = [p for p in sys.path if p != str(scratch_path)]

scratch_path.mkdir(parents=True)
os.chdir(scratch_path)
os.environ["PATH"] = f"{Path(sys.executable).parent}:{os.environ['PATH']}"   # `just run` execs this venv's python3
os.environ["PYTHONPATH"] = str(scratch_path)      # the verbs import mymodule
sys.path.insert(0, str(scratch_path))

# the same mymodule as q-dats; table_dat.table also carries @command
module_path = Path("mymodule")
(module_path / "specs").mkdir(parents=True)
(module_path / "__init__.py").write_text('__version__ = "0.1.0"\n')   # the version `just bump mymodule` edits
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
  base: specs.table_base
  name: tables/{YYYY}/table12{unique}
  do: mymodule.mult.build_table
  kwargs: {n: 12}
''')
(module_path / "table_dat.py").write_text('''\
from pathlib import Path

import yaml

from dvc_dat.just import command
from dvc_dat.ledger import Dat, ledger_class, ledger_fn

from mymodule.mult import write_table


@ledger_class(preds=("n", "start", "cells"))
class TableDat(Dat):
    """A dat that is a value: the folder `_spec_.yaml`, `_result_.yaml`, `table.csv`."""

    @classmethod
    def kind_ok(cls, kind):
        """`do` made it, so its `_spec_` says `dvc_dat.core.Dat`."""
        return kind == "dvc_dat.core.Dat" or super().kind_ok(kind)


def path_to_table_dat(path) -> TableDat:
    """The dat already in `path`, as a value; nothing runs. Its kwargs and result are its preds."""
    spec = yaml.safe_load(Path(path, "_spec_.yaml").read_text())
    result = yaml.safe_load(Path(path, "_result_.yaml").read_text())
    table_dat = TableDat(Path(path))
    table_dat.preds.update(spec["dat"]["kwargs"])
    table_dat.preds["cells"] = result["cells"]
    return table_dat


@command(args="spec=…", help="the table dat a spec names")
@ledger_fn
def table(rev, *, spec: dict, path: Path) -> TableDat:
    """The table constructor: the run itself. `spec` is the question, `path` the folder it fills."""
    cells = write_table(path, **spec["dat"]["kwargs"])
    (path / "_spec_.yaml").write_text(yaml.safe_dump(spec))
    (path / "_result_.yaml").write_text(yaml.safe_dump({"cells": cells}))
    return path_to_table_dat(path)
''')

Path("q_cli_main.py").write_text('''\
"""The project's main: `just run` execs it (`run:` in .datconfig.yaml)."""
import sys

from dvc_dat import Dat

Dat.do.mount(folder="mymodule/specs", at="specs")
Dat.do.mount(module="mymodule.table_dat", at="table")

if __name__ == "__main__":
    sys.exit(Dat.cli_main())
''')
L = Ledger(create=True)                           # .datconfig.yaml + .dat/ledger
with open(".datconfig.yaml", "a") as config_file:
    config_file.write("run: python3 -m q_cli_main\n")
Path("justfile").write_text(
    f"import '{files('dvc_dat') / 'dvc_dat.just'}'  # run\n"
    "import '../../justfile'  # the demo's ledger verbs\n"
    "import? '.dat/targets.just'  # the declared commands\n")
Path("pyproject.toml").write_text('[project]\nname = "q-cli"\nversion = "0.1.0"\n')
Path(".gitignore").write_text(".dat/\ndata/\n__pycache__/\n")
for args in (["init", "-q"], ["config", "user.name", "demo"], ["config", "user.email", "demo@example.com"],
             ["add", "."], ["commit", "-q", "-m", "q-cli"]):
    subprocess.run(["git", *args], check=True)

import mymodule.table_dat                         # discovery finds the checkout, the repo q-cli
with L.transaction(by="human:dan", why="mount mymodule") as t:   # sandboxed: code = the module bytes a run loads
    t.add("db/mount/mymodule", "db/root", "mymodule")
    t.add("db/mount/mymodule", "db/repo", "q-cli")
    t.add("db", "version", "3.1.4")
just_done = subprocess.run(["just", "mounts"], check=True, capture_output=True)   # writes .dat/targets.just, the declared commands

# %% [markdown]
# # Quick: the CLI
#
# A project's `justfile` imports dvc-dat's `run` and a set of ledger
# verbs. Each verb is syntactic sugar for one API call, shown beside
# every command below as `# same as:`, so a shell line and a Python
# line are the same question. `just --list` is the menu; `[run]` holds
# the commands the project's code declares.

# %%
# !just --list --color never
# → Available recipes:
# →     bump name part="patch" # bump a version: <module> edits its __version__ in the source; db is the ledger's release (a/b: a ledger clock); minor and major ask for yes
# →     history subject        # every row a subject has held, with each revision's db/by
# →     index pred             # declare a pred indexed
# →     mounts *args           # mounts [PREFIX]: the mounted names, with what each loads to
# →     run *args              # run TARGET [ARG ...] [KEY=VALUE ...]: a mounted name, a dotted function, a spec
# →     set subject *args      # rows on a subject: k=v a fact, k:=v JSON, alias=TARGET the name's value (a hash prefix is expanded)
# →     value *args            # exactly one value matching the preds
# →     values *args           # the values matching k=v / k:=v preds (kind=<short class name> narrows)
# →     why name *args         # a value's dependencies, whether they hold at the head, and what moved since the alias's last target
# →
# →     [run]
# →     table *args            # spec=…  the table dat a spec names

# %% [markdown]
# ## Running
#
# The project is q-dats's `mymodule`. Its main, which `run` execs,
# mounted it:
#
# ```python
# Dat.do.mount(folder="mymodule/specs", at="specs")       # the project's main, which run execs
# Dat.do.mount(module="mymodule.table_dat", at="table")   # table_dat's @command functions become verbs
# # the run function: table in mymodule/table_dat.py, the table dat a spec names
# ```
#
# `just run` runs a ledger function and seals its result as a value;
# `alias=` names it. A spec's name (`specs.table12`) is not a ledger
# key yet, so the spec itself is the key, written as YAML.

# %%
# !just run mymodule.table_dat.table spec="{dat: {do: mymodule.mult.build_table, kwargs: {n: 12, start: 1}}}" alias=table/12
# same as: L.at().run("mymodule.table_dat.table", spec={"dat": {"do": "mymodule.mult.build_table", "kwargs": {"n": 12, "start": 1}}}, path="table/12")
# → ran  table/12  n=12 start=1 cells=144

# %% [markdown]
# Asked again with the same spec and code, it finds the value
# instead of re-running.

# %%
# !just run mymodule.table_dat.table spec="{dat: {do: mymodule.mult.build_table, kwargs: {n: 12, start: 1}}}" alias=table/12
# same as: the same L.at().run(...), a memo hit
# → hit  table/12  n=12 start=1 cells=144

# %% [markdown]
# A function marked `@command` is its own verb: `just table` is
# `just run table.table`, the mounted name of the same function.

# %%
# !just table spec="{dat: {do: mymodule.mult.build_table, kwargs: {n: 12, start: 1}}}"
# same as: just run table.table spec=…, i.e. L.at().run("mymodule.table_dat.table", spec=…)
# → hit  table/12  n=12 start=1 cells=144

# %% [markdown]
# ## Finding computed values
#
# `just values` lists every value whose predicates match; `kind=`
# narrows to one class. A value prints by its name if it has one.

# %%
# !just values kind=TableDat
# same as: L.at().values(kind="mymodule.table_dat.TableDat")
# → table/12   n=12 start=1 cells=144

# %% [markdown]
# `just value` is the one value that matches.

# %%
# !just value n=12
# same as: L.at().value(n="12")
# → table/12   n=12 start=1 cells=144

# %% [markdown]
# `just history` is every row a subject has held, with who wrote it:
# `table/12` got its alias from the run.

# %%
# !just history table/12
# same as: [r for r in L.at().rows() if r.subject == "table/12"]
# → rev  by         predicate  object
# →   3  name       db/alias   #<8 hex>

# %% [markdown]
# `just why` is what a value was computed from, and whether that all
# still holds.

# %%
# !just why table/12
# same as: v = L.at().load("table/12"); v.matches(L.at()), v.dependencies
# → table/12: #<8 hex>, matches the head
# → dependencies: code <8 hex>, fn mymodule.table_dat.table, platform <platform>

# %% [markdown]
# ## Updating
#
# A write adds a row; nothing changes in place. `set` adds one fact
# to a subject; a name is one more row on its subject (`db/alias`), so
# `set table/prod alias=<hash prefix>` points it at a value and prints
# what it pointed at before. `index` makes a predicate fast to list by.

# %%
table12_prefix = L.at().load("table/12").subject[:8]   # the value's hash, short
# !just set table/12 checked=yes
# same as: with L.transaction(by="human:$USER") as t: t["table/12", "checked"] = "yes"
# !just set table/prod alias={table12_prefix}
# same as: with L.transaction(by=…) as t: t.add("table/prod", "db/alias", subject)
# !just index n
# same as: with L.transaction(by=…) as t: t.add("db/pred/n", "db/index", "true")
# → table/12 checked=yes
# → table/prod: (none) -> #<8 hex>
# → n: indexed; 1 subjects hold it

# %% [markdown]
# ## Releasing
#
# A code version lives in its source: `just bump mymodule` edits the
# `__version__` line in `mymodule/__init__.py` and does nothing else,
# not even commit.

# %%
# !just bump mymodule
# same as: bump_source("mymodule", "patch")
# → mymodule: 0.1.0 -> 0.1.1 in mymodule/__init__.py
# → commit it: git commit -am "mymodule 0.1.1"

# %% [markdown]
# The ledger's `db/repo/q-cli/mymodule` clock is the version of `mymodule` runs were exposed to.
# The first run (rev 2) put `0.1.0` there; after the commit, the next run from the clean checkout moves it to `0.1.1`, and `db/repo/q-cli` to that run's commit.

# %%
# !git commit -qam "mymodule 0.1.1"
# !just run mymodule.table_dat.table spec="{dat: {do: mymodule.mult.build_table, kwargs: {n: 12, start: 1}}}"
# !just history db/repo/q-cli/mymodule
# same as: [r for r in L.at().rows() if r.subject == "db/repo/q-cli/mymodule"]
# !just history db/repo/q-cli
# → ran  anonymous/Dat  n=12 start=1 cells=144
# → rev  by         predicate  object
# →   2  eval:mymodule.table_dat.table version    0.1.0
# →   7  eval:mymodule.table_dat.table version    0.1.1
# → rev  by         predicate  object
# →   2  eval:mymodule.table_dat.table commit     <40 hex>
# →   7  eval:mymodule.table_dat.table commit     <40 hex>

# %% [markdown]
# A bump of `db`, the ledger's own clock, is a release: a row on the
# ledger, behind a typed `yes` for minor and major.

# %%
# !echo yes | just bump db minor
# same as: with L.transaction(by=…, lock=10, why="release") as t: bump(t, "db", "minor", confirm=…)
# → db: 3.1.4 -> 3.2.0? yes
# → db: 3.1.4 -> 3.2.0, a release

# %% [markdown]
# ## Other commands
#
# `just mounts` lists the mounted names and what each loads to:

# %%
# !just mounts
# same as: dvc_dat.dat_tools.cmd_list(""), in the namespace q_cli_main mounted
# → Base names matching: '*'
# →   dt                        -->  <module>
# →   specs/table12             -->  {'dat': {'base': 'specs.table_base', 'name': 'tables/{YYYY}/table12{unique}', 'do': 'mymodule.mult.build_table', 'kwargs': {'n': 12}}}
# →   specs/table_base          -->  {'dat': {'kwargs': {'start': 1}}, 'notes': 'shared defaults'}
# →   table                     -->  <module>

# %% [markdown]
# The rest, not run here:
#
# | Command | What it does |
# | --- | --- |
# | `x TARGET k=v` | `bin/x`, the same as `just run TARGET k=v` |
# | `dat TARGET k=v` | the `dat` console script: `Dat.do(TARGET, …)` from a shell, no ledger; `dat --list`, `dat --info` ([DAT CLI](../DAT%20Design/DAT%20API/DAT%20CLI.md)) |
# | `just sealed` | in the dvc-dat repo: values sealed with `v.seal()` and never saved; `just sealed purge older=14d` drops the old ones |
# | `just test` | in the dvc-dat repo: the test suite |
# | `just demo` | in the dvc-dat repo: sync and execute the `demo-*` notebooks |
# | `just docs` | in the dvc-dat repo: the documentation site, `doc/` to `site/` |
