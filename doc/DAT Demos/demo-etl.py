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
# > **Plan** (delete once the sections carry it). An ETL pipeline computes over a set of inputs in stages, and the ledger recomputes only the stages whose inputs moved.
# >
# > 1. **Setup: the city data**: each city's year of daily weather is a sealed value found by an alias; the city set the pipeline runs over is rows.
# > 2. **A pipeline of stages**: a daily comfort per city (its weather plus a comfort column), a city comfort per city over a date range (the days binned by comfort level), a comfort report over a city set and a date range; asked once, every stage runs; asked again, every stage is a hit.
# > 3. **Summer, and one more city**: one edit narrows the range to summer and adds a city; only the new city's daily comfort runs, then every city's summer binning and the report.
# > 4. **Changing a city's data**: only that city's daily comfort and what is downstream of it run.
# > 5. **Changing one stage's code**: only that stage runs; the stages below it are hits.
# >
# > Each section ends on the count of stages that ran, read off the ledger.

# %% [markdown]
# #### Setup

# %%
import math
import random
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from importlib.resources import files
from pathlib import Path

from IPython.display import SVG, Code, display

from dvc_dat.ledger import Ledger, bump

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
    "ledger: ../ledger\n"
    'run: python3 -c "import sys, comfort; from dvc_dat import Dat; sys.exit(Dat.cli_main())"\n')
(repo_path / "justfile").write_text(
    f"import '{files('dvc_dat') / 'dvc_dat.just'}'  # run\n"
    f"import '{Path('justfile').resolve()}'  # the demo's ledger verbs\n")
sys.path.insert(0, str(repo_path))
L = Ledger(scratch_path / "ledger", create=True)

STAGES = ("comfort.stages.daily_comfort", "comfort.stages.city_comfort", "comfort.report.comfort_report")


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
# Mounting `comfort` makes its stages sandboxed: each call runs in a fresh process of its own, and its code is the hash of every module file the run loaded.
# A `# same as` line is the shell form, typed in the code's repo, whose justfile imports `run` from dvc-dat (`dvc_dat.just`) and the ledger verbs from the `justfile` beside this notebook.

# %%
with L.transaction(by="human:dan", why="mount the stages") as t:
    t.add("db/mount/comfort", "db/root", "comfort")
    t.add("db/mount/comfort", "db/repo", "comfort-repo")
    bump(t, "code/comfort-repo", "minor", confirm=lambda old, new: True)   # 0.1.0, at HEAD
print("sandboxed:", L.at().load_fn("comfort.report.comfort_report").code.sandboxed)
# → sandboxed: True
# the bump, same as:
#   echo yes | just bump code minor

# %% [markdown]
# ### Asking for the comfort report
#
# `rev.run(name, **keys)` returns the stage's result, running it only when no sealed result whose dependencies hold answers the same question.
# The first report covers the whole year.

# %%
counts_before = entry_counts()
comfort_report_value = L.at().run("comfort.report.comfort_report", cityset="cityset/representative",
                                  start="2026-01-01", end="2027-01-01")
print(comfort_report_value.obj)
# → {'comfortable': '213/1095 days', 'top': ['Austin', 'Boston']}
print(ran_since(counts_before))
# → {'daily_comfort': 3, 'city_comfort': 3, 'comfort_report': 1}
# same as:
#   just run comfort.report.comfort_report cityset=cityset/representative start=2026-01-01 end=2027-01-01

# %% [markdown]
# Everything ran: a daily comfort per city, a city comfort per city over the year, and the comfort report.

# %%
counts_before = entry_counts()
again_value = L.at().run("comfort.report.comfort_report", cityset="cityset/representative",
                         start="2026-01-01", end="2027-01-01")
print(again_value.subject == comfort_report_value.subject)
# → True
print(ran_since(counts_before))
# → {'daily_comfort': 0, 'city_comfort': 0, 'comfort_report': 0}
# same as (a hit):
#   just run comfort.report.comfort_report cityset=cityset/representative start=2026-01-01 end=2027-01-01

# %% [markdown]
# Asked again, nothing ran: the comfort report is a hit.

# %% [markdown]
# ## Summer, and one more city
#
# Two changes at once: Denver joins the set, and the report is asked for summer, June through August.
# A new range is a new question for every city comfort; the daily comfort under it does not depend on the range, so only the new city's runs.

# %%
with L.transaction(by="human:dan", why="Denver joins") as t:
    t.add("cityset/representative", "contains", "Denver")
counts_before = entry_counts()
comfort_report_value = L.at().run("comfort.report.comfort_report", cityset="cityset/representative",
                                  start="2026-06-01", end="2026-09-01")
print(comfort_report_value.obj)
# → {'comfortable': '175/368 days', 'top': ['Denver', 'Boston']}
print(ran_since(counts_before))
# → {'daily_comfort': 1, 'city_comfort': 4, 'comfort_report': 1}
# the run, same as:
#   just run comfort.report.comfort_report cityset=cityset/representative start=2026-06-01 end=2026-09-01

# %% [markdown]
# Denver's daily comfort ran; Austin's, Boston's and Chicago's were hits, scored once for the year and binned again for summer.
# All four city comforts ran over the new range, and the report ran once.

# %% [markdown]
# ## Changing a city's data
#
# A new version of a city's weather is a new value with the alias re-pointed, so every result that loaded the alias is stale.

# %%
seal_weather("Boston", seed=22)                 # Boston re-reported
counts_before = entry_counts()
comfort_report_value = L.at().run("comfort.report.comfort_report", cityset="cityset/representative",
                                  start="2026-06-01", end="2026-09-01")
print(ran_since(counts_before))
# → {'daily_comfort': 1, 'city_comfort': 1, 'comfort_report': 1}
# the run, same as:
#   just run comfort.report.comfort_report cityset=cityset/representative start=2026-06-01 end=2026-09-01

# %% [markdown]
# Boston's daily comfort ran, then its summer city comfort and the report; the other three cities were hits, since they never read `weather/Boston`.

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
comfort_report_value = L.at().run("comfort.report.comfort_report", cityset="cityset/representative",
                                  start="2026-06-01", end="2026-09-01")
print(comfort_report_value.obj)
# → {'comfortable': '182/368 days', 'top': ['Boston']}
print(ran_since(counts_before))
# → {'daily_comfort': 0, 'city_comfort': 0, 'comfort_report': 1}
# the run, same as:
#   just run comfort.report.comfort_report cityset=cityset/representative start=2026-06-01 end=2026-09-01

# %% [markdown]
# Only the comfort report ran: its run loaded `report.py`, and no other stage's run did.
# No `bump` was needed: a sandboxed stage's identity is the bytes of the modules its run loaded, so the edit alone made the comfort report a new question, and a miss runs at HEAD, clean or dirty (F520 Q39).

# %% [markdown]
# ## Reading a result's dependencies back
#
# A result's dependencies list every input it read: each stage below by its result's bytes (`eval:`), the set's rows (`q:`, the `all` call and its answer), its own code (`fn`) and the environment.

# %%
for item in sorted(comfort_report_value.dependencies):
    print(item)
# → eval:comfort.stages.city_comfort{"city":"Austin","end":"2026-09-01","start":"2026-06-01"}
#   eval:comfort.stages.city_comfort{"city":"Boston","end":"2026-09-01","start":"2026-06-01"}
#   eval:comfort.stages.city_comfort{"city":"Chicago","end":"2026-09-01","start":"2026-06-01"}
#   eval:comfort.stages.city_comfort{"city":"Denver","end":"2026-09-01","start":"2026-06-01"}
#   fn
#   platform
#   q:{"__call__":"all","args":["cityset/representative","contains"],"since":null}
print(sorted(L.at()[comfort_report_value.dependencies["fn"], "db/modules"]))
# → ['comfort/__init__.py', 'comfort/report.py', 'comfort/values.py']

# %%
# clean up
shutil.rmtree(scratch_path, ignore_errors=True)   # a second run finds it gone
