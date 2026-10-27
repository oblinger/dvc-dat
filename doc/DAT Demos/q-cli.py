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
# > A ledger project is worked from a shell with `just <verb>`; each
# > verb is one API call, shown beside it as `# same as:`. Running
# > (`just run`, a declared command), finding (`values`, `value`,
# > `history`, `why`), updating (`set`, `index`), releasing (`bump`),
# > and the namespace (`mounts`). Names are the ledger's mounts.

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

# the same mymodule as q-dats; specs/table12.yaml also carries command: true
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
    """The run function: a run calls it with the new dat and the spec's kwargs."""
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
command: true
''')
Path("q_cli_main.py").write_text('''\
"""The project's main: `just run` execs it (`run:` in .datconfig.yaml)."""
import sys

from dvc_dat import Dat

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

import mymodule.mult                              # discovery finds the checkout, the repo q-cli
with L.transaction(by="human:dan", why="mount mymodule") as t:   # mymodule's code is the mount's: its files, hashed
    t.ns.mount("mymodule", root="mymodule", repo="q-cli")   # the two db/mount/mymodule rows
    t.add("db", "version", "3.1.4")
just_done = subprocess.run(["just", "mounts"], check=True, capture_output=True)   # writes .dat/targets.just, the declared commands

# %% [markdown]
# # Quick: the CLI
#
# A project's `justfile` imports dvc-dat's `run` and a set of ledger
# verbs. Each verb is syntactic sugar for one API call, shown beside
# every command below as `# same as:`, so a shell line and a Python
# line are the same call. `just --list` is the menu; `[run]` holds
# the commands the project's code declares.

# %%
# !just --list --color never
# → Available recipes:
# →     bump name part="patch" # bump a version: <module> edits its __version__ in the source; db is the ledger's release (a/b: a ledger clock); minor and major ask for yes
# →     history subject        # every row a subject has held, with each revision's db/by
# →     index pred             # declare a pred indexed
# →     mounts *args           # mounts [PREFIX]: the mounted names, with what each loads to
# →     run *args              # run TARGET [ARG ...] [KEY=VALUE ...]: a mounted name, a dotted function, a spec
# →     set subject *args      # rows on a subject: k=v a fact, alias=TARGET the name's value (a hash prefix is expanded)
# →     value *args            # exactly one value matching the preds
# →     values *args           # the values matching k=v preds (kind=<short class name> narrows)
# →     why name *args         # a value's dependencies, whether they hold at the head, and what moved since the alias's last target
# →
# →     [run]
# →     table12 *args

# %% [markdown]
# ## Running
#
# The project is q-dats's `mymodule`, mounted on the ledger in Setup:
#
# ```python
# t.ns.mount("mymodule", root="mymodule", repo="q-cli")
# ```
#
# Those rows are the project's names: `mymodule/specs/table12.yaml`
# is `mymodule.specs.table12`. `just run` of a spec makes the dat,
# runs it and seals it as a value; `alias=` names it. The spec is the
# memo key. `mymodule` is mounted, so its run function runs in a
# sandboxed worker, and its code is the files that run loaded.

# %%
# !just run mymodule.specs.table12 alias=table/12
# same as: L.at().run("mymodule.specs.table12", path="table/12")
# → ran  table/12  start=1 n=12 cells=144

# %% [markdown]
# Asked again with the same spec and code, it finds the value
# instead of re-running.

# %%
# !just run mymodule.specs.table12 alias=table/12
# same as: L.at().run("mymodule.specs.table12", path="table/12"), a memo hit
# → hit  table/12  start=1 n=12 cells=144

# %% [markdown]
# A mounted spec with `command: true` is its own verb: `just table12`
# is `just run mymodule.specs.table12`.

# %%
# !just table12
# same as: L.at().run("mymodule.specs.table12")
# → hit  table/12  start=1 n=12 cells=144

# %% [markdown]
# ## Finding computed values
#
# `just values` lists every value whose predicates match; `kind=`
# narrows to one class. A value prints by its name if it has one.

# %%
# !just values kind=Dat
# same as: L.at().values(kind=Dat)
# → table/12   start=1 n=12 cells=144

# %% [markdown]
# `just value` is the one value that matches.

# %%
# !just value n=12
# same as: L.at().value(n="12")
# → table/12   start=1 n=12 cells=144

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
# still holds. A sandboxed run names no commit: `code` is the bytes of
# the files it loaded, so a commit that leaves them alone leaves the
# value current.

# %%
# !just why table/12
# same as: v = L.at().load("table/12"); v.matches(L.at()), v.dependencies
# → table/12: #<8 hex>, matches the head
# → dependencies: code <8 hex>, fn mymodule.mult.build_table, platform <platform>

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
# !just run mymodule.specs.table12
# !just history db/repo/q-cli/mymodule
# same as: [r for r in L.at().rows() if r.subject == "db/repo/q-cli/mymodule"]
# !just history db/repo/q-cli
# → ran  tables/2026/table12  start=1 n=12 cells=144
# → rev  by         predicate  object
# →   2  eval:mymodule.mult.build_table version    0.1.0
# →   7  eval:mymodule.mult.build_table version    0.1.1
# → rev  by         predicate  object
# →   2  eval:mymodule.mult.build_table commit     <40 hex>
# →   7  eval:mymodule.mult.build_table commit     <40 hex>

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
# `just mounts` lists the names the project mounts, the ledger's
# `db/mount` prefixes beside dvc-dat's own `dt`:

# %%
# !just mounts
# same as: dvc_dat.dat_tools.cmd_list(""), in Dat.manager.ns
# → Base names matching: '*'
# →   dt                        -->  <module>
# →   mymodule                  -->  <module>

# %% [markdown]
# The rest, not run here:
#
# | Command | What it does |
# | --- | --- |
# | `x TARGET k=v` | `bin/x`, the same as `just run TARGET k=v` |
# | `dat TARGET k=v` | the `dat` console script: `Dat.manager.run(TARGET, …)` from a shell, no ledger; `dat --list`, `dat --info` ([DAT CLI](../DAT%20Design/DAT%20API/DAT%20CLI.md)) |
# | `just sealed` | in the dvc-dat repo: values sealed with `v.seal()` and never saved; `just sealed purge older=14d` drops the old ones |
# | `just test` | in the dvc-dat repo: the test suite |
# | `just demo` | in the dvc-dat repo: sync and execute the `demo-*` notebooks |
# | `just docs` | in the dvc-dat repo: the documentation site, `doc/` to `site/` |
