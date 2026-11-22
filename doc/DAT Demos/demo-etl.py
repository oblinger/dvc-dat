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
# <!-- contents: written by add_contents.py -->
# **ETL pipelines: computing, recomputing only what moved**
#
# Contents:
#
# - [Setup](#setup)
# - [Setup: the city data](#setup-the-city-data)
# - [A pipeline of stages](#a-pipeline-of-stages)
# - [Summer, and one more city](#summer-and-one-more-city)
# - [Two reports merged](#two-reports-merged)
# - [Changing a city's data](#changing-a-citys-data)
# - [Changing one stage's code](#changing-one-stages-code)
# - [Reading a result's dependencies back](#reading-a-results-dependencies-back)

# %% [markdown]
# #### Setup

# %%
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from importlib.resources import files
from pathlib import Path

from IPython.display import SVG, Code, display

from dvc_dat.ledger import Ledger

for module_name in [m for m in sys.modules if m == "comfort" or m.startswith("comfort.")]:
    del sys.modules[module_name]                  # a re-run: forget the last run's code repo
sys.path[:] = [p for p in sys.path if not p.endswith("/comfort-repo")]
scratch_path = Path(tempfile.mkdtemp(prefix="demo-etl-"))
repo_path = scratch_path / "comfort-repo"      # the code's repo, a copy of comfort-repo/ beside this notebook
shutil.copytree("comfort-repo", repo_path, ignore=shutil.ignore_patterns("__pycache__"))


def show(name: str) -> None:
    """A module of the code's repo (`comfort/stages.py`) shown as code, or the figure `<name>.svg` beside this notebook."""
    if name.endswith(".py"):
        print(f"comfort-repo/{name}")
        display(Code(filename=str(repo_path / name), language="python"))
    else:
        display(SVG(filename=f"{name}.svg"))


def git(*args: str) -> str:
    """Run git in the code's repo; return its stdout."""
    cmd = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com",
           "-c", "init.defaultBranch=main", *args]
    done = subprocess.run(cmd, cwd=repo_path, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def commit(message: str, *rels: str) -> None:
    """Commit files of the code's repo; re-running with the same files commits nothing."""
    git("add", *rels)
    if git("status", "--porcelain", "--", *rels):
        git("commit", "-q", "-m", message)


git("init", "-q")
commit("comfort: the stages", "comfort")
(repo_path / ".datconfig.yaml").write_text(     # for `just`: the ledger, and a main importing comfort
    "root: ../ledger\ndefault: root\nnamespace: ledger\n"
    'run: python3 -c "import sys, comfort; from dvc_dat import Dat; sys.exit(Dat.cli_main())"\n')
(repo_path / "justfile").write_text(
    f"import '{files('dvc_dat') / 'dvc_dat.just'}'  # run, the ledger verbs\n")
os.environ["PATH"] = f"{Path(sys.executable).parent}:{os.environ['PATH']}"   # `just run` execs this venv's python3
sys.path.insert(0, str(repo_path))
L = Ledger(scratch_path / "ledger", create=True)

STAGES = ("mnt.comfort.stages.daily_comfort", "mnt.comfort.stages.city_comfort", "mnt.comfort.report.comfort_report")


def entry_counts() -> dict:
    """How many results each stage has sealed on the ledger so far."""
    rev = L.at()
    return {name.rsplit(".", 1)[1]: len(rev.refs(fn=name)) for name in STAGES}


def ran_since(counts_before: dict) -> dict:
    """How many times each stage ran (missed and sealed) since `counts_before`."""
    counts_now = entry_counts()
    return {stage: counts_now[stage] - counts_before[stage] for stage in counts_now}


# %% [markdown]
# # ETL pipelines: computing, recomputing only what moved
#
# An ETL pipeline is a series of stages, each computing a value from the values of the stage below it, over a set of inputs.
# Every stage here is a ledger function, so every result is a value sealed with its dependencies, the exact inputs and code it was computed from.
# Asked for a result, the ledger hands back a sealed one whose dependencies still hold and runs the stage only when one of its dependencies has moved.
# So a change anywhere in the pipeline recomputes that stage and what is downstream of it, and nothing else.

# %% [markdown]
# ## Setup: the city data
#
# The task: five cities each report a year of weather, a date, a temperature and a humidity per day; a city set names the representative cities a report covers.
# The pipeline adds a comfort score to each city's days, bins a city's days by comfort level over a date range, and reports the city set's comfortable days and its two most comfortable cities over that range.
# Every input is a ledger write, so every change to one is something the pipeline can see.
# Each city's weather is a value found by the alias `weather/<city>`; the city set, a few representative cities, is held as `contains` rows on its own subject.

# %%
show("demo-etl-data")

# %% [markdown]
# ### The value kinds
#
# Two kinds of value: a city's days, one row per day, `[date, °F, humidity %]` as reported and with a comfort column once scored, and a comfort count, the count of days at each of ten comfort levels.
# The code lives in `comfort-repo/` beside this notebook, plain Python files; setup copies it into a scratch git repo, since a stage's code is identified by the files its repo holds, and `show` prints a module.

# %%
show("comfort/values.py")

# %%
from comfort.values import Days


# %% [markdown]
# ### Five cities' weather
#
# Each city's temperature follows the seasons around its own yearly mean, so summer and winter differ.

# %%
MEAN_F = {"Austin": 69, "Boston": 52, "Chicago": 50, "Denver": 51, "Miami": 77}


def seal_weather(city: str, seed: int) -> None:
    """Seal a year of a city's weather drawn from `seed`, and point `weather/<city>` at it."""
    rng = random.Random(seed)
    days = []
    for n in range(365):
        season = -math.cos(2 * math.pi * (n - 15) / 365)    # -1 mid-January, +1 mid-July
        temp = round(MEAN_F[city] + 20 * season + rng.uniform(-8, 8))
        days.append([(date(2026, 1, 1) + timedelta(n)).isoformat(), temp, rng.randrange(20, 90)])
    weather_value = Days(days)
    weather_value.preds["city"] = city
    with L.transaction(by="human:dan", why=f"{city}'s data") as t:
        weather_value.seal(t, name=f"weather/{city}")


for city, seed in [("Austin", 1), ("Boston", 2), ("Chicago", 3), ("Denver", 4), ("Miami", 5)]:
    seal_weather(city, seed)
print(L.at().load("weather/Austin").days[:3])
# → [['2026-01-01', 44, 28], ['2026-01-02', 46, 83], ['2026-01-03', 54, 80]]

# %% [markdown]
# ### The city set
#
# A city set is rows: `cityset/representative contains Austin`, one per city; `contains` is declared many-valued, so the rows add up to a set.
# `all` answers in revision order, the order the rows were added.

# %%
with L.transaction(by="human:dan", why="the city set") as t:
    t.add("db/pred/contains", "db/cardinality", "many")
    for city in ("Boston", "Austin", "Chicago"):
        t.add("cityset/representative", "contains", city)
print(L.at().all("cityset/representative", "contains"))
# → ['Boston', 'Austin', 'Chicago']

# %% [markdown]
# ## A pipeline of stages
#
# Three stages, each a ledger function running the one below it: a daily comfort per city, a city comfort per city over a date range, and a comfort report over a city set and a date range.

# %%
show("demo-etl-pipeline")

# %% [markdown]
# ### The stages
#
# `daily_comfort` adds a column, a comfort score per day; `city_comfort` bins those days by comfort level, keeping only the days in its range; a range is a half-open pair of dates, `start` up to `end`.

# %%
show("comfort/stages.py")

# %%
show("comfort/report.py")

# %% [markdown]
# ### Mounting the code
#
# Mounting `comfort` makes its stages sandboxed under the names `mnt.comfort...` (a mounted name starts `mnt.`; the bare `comfort...` imports): each call runs in a fresh process of its own, and its code is the hash of every module file the run loaded.
# Its version is `comfort.__version__`, in the source; the first run from the clean checkout writes it to the ledger's `db/repo/comfort-repo/comfort` `db/version` clock, one per versioned package.
# A `# same as` line is the shell form, typed in the code's repo, whose justfile imports `run` and the ledger verbs from dvc-dat (`dvc_dat.just`).

# %%
with L.transaction(by="human:dan", why="mount the stages") as t:
    t.ns.mount("mnt.comfort", root="comfort", repo="comfort-repo")   # the two db/mount/comfort rows
report_fn = L.at().ns.load("mnt.comfort.report.comfort_report")
print("sandboxed:", report_fn.code.sandboxed, " code:", report_fn.code)
# → sandboxed: True  code: comfort@0.1.0

# %% [markdown]
# ### Asking for the comfort report
#
# `rev.run(name, **keys)` returns a stage's result, running it only when no sealed result whose dependencies hold was sealed for the same keys.
# The comfort report is a reduce over the city set: `rev.reduce(name, over=cities, **keys)` remembers each report under the sorted set of cities it covers, so a set that grows is reported by its growth and two sets already reported merge; its function, a `@dat.reduce_fn`, takes `accs`, reports over disjoint city sets already reduced, and `more`, the cities none of them covers.
# The set's rows are read here, by the caller, and the first report covers the whole year.

# %%
REPORT = "mnt.comfort.report.comfort_report"


def cities() -> list:
    """The city set's cities, read off its `contains` rows."""
    return L.at().all("cityset/representative", "contains")


def shown(report_value) -> dict:
    """A report's share of comfortable days and its two most comfortable cities."""
    return {k: report_value.obj[k] for k in ("comfortable", "top")}


counts_before = entry_counts()
comfort_report_value = L.at().reduce(REPORT, over=cities(), start="2026-01-01", end="2027-01-01")
print(shown(comfort_report_value))
# → {'comfortable': '213/1095 days', 'top': ['Austin', 'Boston']}
print(ran_since(counts_before))
# → {'daily_comfort': 3, 'city_comfort': 3, 'comfort_report': 1}
print("db/version:", L.at()["db/repo/comfort-repo/comfort", "db/version"])
# → db/version: 0.1.0: the clock, written by this first clean run
# same as:
#   just reduce mnt.comfort.report.comfort_report over=Boston,Austin,Chicago start=2026-01-01 end=2027-01-01

# %% [markdown]
# Everything ran: a daily comfort per city, a city comfort per city over the year, and the comfort report, one step over the three cities.

# %%
counts_before = entry_counts()
again_value = L.at().reduce(REPORT, over=cities(), start="2026-01-01", end="2027-01-01")
print(again_value.subject == comfort_report_value.subject)
# → True
print(ran_since(counts_before))
# → {'daily_comfort': 0, 'city_comfort': 0, 'comfort_report': 0}

# %% [markdown]
# Asked again, nothing ran: the comfort report is a hit.
# In practice a pipeline is asked for from the shell, and `just reduce` is this same `rev.reduce` call: here, a third hit, the cities in another order, which is the same set.

# %%
# !cd {repo_path} && just reduce mnt.comfort.report.comfort_report over=Chicago,Boston,Austin start=2026-01-01 end=2027-01-01
# → mnt.comfort.report.comfort_report: #<8 hex>, over 3
# → reduced from: (none); more: "Austin", "Boston", "Chicago"

# %% [markdown]
# ## Summer, and one more city
#
# The report is asked for summer, June through August: a new range is a new memo key for every city comfort and for the report, whose steps over one range never stand in for another's.
# The daily comfort does not depend on the range, so it is a hit.

# %%
counts_before = entry_counts()
summer_value = L.at().reduce(REPORT, over=cities(), start="2026-06-01", end="2026-09-01")
print(shown(summer_value))
# → {'comfortable': '117/276 days', 'top': ['Boston', 'Chicago']}
print(ran_since(counts_before))
# → {'daily_comfort': 0, 'city_comfort': 3, 'comfort_report': 1}

# %% [markdown]
# Now Denver joins the set. The summer report over four cities finds the report over three, its largest subset already reduced, and runs one step: `accs` that report alone, `more` Denver alone.

# %%
with L.transaction(by="human:dan", why="Denver joins") as t:
    t.add("cityset/representative", "contains", "Denver")
counts_before = entry_counts()
comfort_report_value = L.at().reduce(REPORT, over=cities(), start="2026-06-01", end="2026-09-01")
with L.transaction(by="human:dan", why="name the summer report") as t:
    t.add("report/summer", "db/alias", comfort_report_value.subject)
print(shown(comfort_report_value))
# → {'comfortable': '175/368 days', 'top': ['Denver', 'Boston']}
print(ran_since(counts_before))
# → {'daily_comfort': 1, 'city_comfort': 1, 'comfort_report': 1}
rev = L.at()
print("from:", rev[comfort_report_value.subject, "db/reduce/from"] == [summer_value.subject],
      " more:", rev[comfort_report_value.subject, "db/reduce/more"])
# → from: True  more: ['Denver']
# the step, same as:
#   just reduce mnt.comfort.report.comfort_report over=Boston,Austin,Chicago,Denver start=2026-06-01 end=2026-09-01

# %% [markdown]
# Denver's daily comfort and its summer city comfort ran, and the report ran one step over Denver; Austin's, Boston's and Chicago's stages were not asked for at all, their counts carried in the three-city report.

# %% [markdown]
# ## Two reports merged
#
# Two people report autumn, September through November, each over half the set: one over Austin and Boston, one over Chicago and Denver.
# Asked for the whole set, the reduce finds both reports, disjoint subsets of the ask, and runs one step: `accs` the two reports, `more` empty. Nothing below the report runs: each city's counts are carried in its half's report.

# %%
two_value = L.at().reduce(REPORT, over=["Austin", "Boston"], start="2026-09-01", end="2026-12-01")
other_two_value = L.at().reduce(REPORT, over=["Chicago", "Denver"], start="2026-09-01", end="2026-12-01")
counts_before = entry_counts()
autumn_value = L.at().reduce(REPORT, over=cities(), start="2026-09-01", end="2026-12-01")
print(shown(autumn_value))
# → {'comfortable': '60/364 days', 'top': ['Austin', 'Boston']}
print(ran_since(counts_before))
# → {'daily_comfort': 0, 'city_comfort': 0, 'comfort_report': 1}
rev = L.at()
print("from:", rev[autumn_value.subject, "db/reduce/from"] == sorted([two_value.subject, other_two_value.subject]),
      " more:", rev[autumn_value.subject, "db/reduce/more"])
# → from: True  more: []
fresh_value = L.at().reduce(REPORT, over=cities(), start="2026-09-01", end="2026-12-01", fresh=True)
print("same as from scratch:", fresh_value.same_as(autumn_value))
# → same as from scratch: True

# %% [markdown]
# ## Changing a city's data
#
# A new version of a city's weather is a new value with the alias re-pointed, so every result that loaded the alias is stale.

# %%
seal_weather("Boston", seed=22)                 # Boston re-reported
counts_before = entry_counts()
comfort_report_value = L.at().reduce(REPORT, over=cities(), start="2026-06-01", end="2026-09-01")
with L.transaction(by="human:dan", why="name the summer report") as t:
    t.add("report/summer", "db/alias", comfort_report_value.subject)
print(ran_since(counts_before))
# → {'daily_comfort': 1, 'city_comfort': 1, 'comfort_report': 1}
print("more:", L.at()[comfort_report_value.subject, "db/reduce/more"])
# → more: ['Austin', 'Boston', 'Chicago', 'Denver']

# %% [markdown]
# Boston's daily comfort ran, then its summer city comfort; the other three cities were hits, since they never read `weather/Boston`.
# The report ran one step over all four: every report remembered held Boston's old counts, so none was a subset it could start from. A change to an early member costs the whole reduce, though not the stages below it.

# %% [markdown]
# ## Changing one stage's code
#
# An edit to one stage's module changes that stage's code hash, so that stage reruns; stages whose runs never loaded the module are hits.

# %%
report_path = repo_path / "comfort/report.py"
report_source = report_path.read_text().replace("[:2]", "[:1]").replace("two most comfortable cities", "most comfortable city")
report_path.write_text(report_source)
commit("report: the one most comfortable city", "comfort/report.py")
counts_before = entry_counts()
comfort_report_value = L.at().reduce(REPORT, over=cities(), start="2026-06-01", end="2026-09-01")
with L.transaction(by="human:dan", why="name the summer report") as t:
    t.add("report/summer", "db/alias", comfort_report_value.subject)
print(shown(comfort_report_value))
# → {'comfortable': '182/368 days', 'top': ['Boston']}
print(ran_since(counts_before))
# → {'daily_comfort': 0, 'city_comfort': 0, 'comfort_report': 1}

# %% [markdown]
# The comfort report ran one step over the four cities: its run loaded `report.py`, and every report under the old code is stale, so the new one starts from none of them.
# The stages below were hits: they ran nested inside the report's body, in its worker, and a nested run records only the modules it loaded itself, `stages.py` and `values.py`, never `report.py`, which its caller loaded.
# Read back as hits, their results were decoded in the report's own body, so `values.py`, the module of their kind, is part of the report's code item this time.
# No version bump was needed: a sandboxed stage's identity is the bytes of the modules its run loaded, so the edit alone made the comfort report a miss, and a miss runs at HEAD, clean or dirty (F520 Q39).

# %% [markdown]
# ## Reading a result's dependencies back
#
# A result's dependencies list every input it read: each stage below by its result's bytes (`eval:`), its own code (`code`, the snapshot, and `fn`, the function's name in it) and the environment; a reduce step built on an earlier one would list that report too, by its bytes (`ref:`). The set's rows are not among them: the caller read them, and the report is keyed by the cities themselves.

# %%
for item in sorted(comfort_report_value.dependencies):
    print(item)
# → code
#   eval:mnt.comfort.stages.city_comfort{"city":"Austin","end":"2026-09-01","start":"2026-06-01"}
#   eval:mnt.comfort.stages.city_comfort{"city":"Boston","end":"2026-09-01","start":"2026-06-01"}
#   eval:mnt.comfort.stages.city_comfort{"city":"Chicago","end":"2026-09-01","start":"2026-06-01"}
#   eval:mnt.comfort.stages.city_comfort{"city":"Denver","end":"2026-09-01","start":"2026-06-01"}
#   fn
#   platform
#   platform/record
print(sorted(L.at()[comfort_report_value.dependencies["code"], "db/modules"]))
# → ['comfort/__init__.py', 'comfort/report.py', 'comfort/values.py']

# %% [markdown]
# `just why` reads the same back from the shell: the summer report's dependencies one level down, whether they still hold, and what moved since `report/summer`'s last target (the Boston change's report): the code alone; and, a reduce step, what it was built from and the cities it added.

# %%
# !cd {repo_path} && just why report/summer
# → report/summer: #<8 hex>, matches the head
# → dependencies: code <8 hex>, eval:mnt.comfort.stages.city_comfort{"city":"Austin","end":"2026-09-01","start":"2026-06-01"} ComfortCounts:<8 hex>, eval:mnt.comfort.stages.city_comfort{"city":"Boston","end":"2026-09-01","start":"2026-06-01"} ComfortCounts:<8 hex>, eval:mnt.comfort.stages.city_comfort{"city":"Chicago","end":"2026-09-01","start":"2026-06-01"} ComfortCounts:<8 hex>, eval:mnt.comfort.stages.city_comfort{"city":"Denver","end":"2026-09-01","start":"2026-06-01"} ComfortCounts:<8 hex>, fn mnt.comfort.report.comfort_report, platform <platform>, platform/record <record>
# → since #<8 hex>, its last target: code <8 hex> -> <8 hex>
# → reduced from: (none); more: "Austin", "Boston", "Chicago", "Denver"

# %%
# clean up
shutil.rmtree(scratch_path, ignore_errors=True)   # a second run finds it gone
