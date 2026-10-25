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
import math, os, random, shutil, subprocess, sys
from datetime import date, timedelta
from importlib.resources import files
from pathlib import Path

import yaml

from dvc_dat.ledger import Ledger, bump

demo_dir_path = globals().get("demo_dir_path", Path.cwd())  # survives a re-run
os.chdir(demo_dir_path)
scratch_path = Path("scratch/q-cli").resolve()
shutil.rmtree(scratch_path, ignore_errors=True)   # a re-run starts clean
for module_name in [m for m in sys.modules if m.split(".")[0] in ("demo_game", "demo_main", "comfort")]:
    sys.modules.pop(module_name)
sys.path[:] = [p for p in sys.path if "scratch/q-cli" not in p]

shutil.copytree("demo_game", scratch_path,
                ignore=shutil.ignore_patterns("__pycache__"))
shutil.copytree("comfort-repo/comfort", scratch_path / "comfort",   # the ETL stages
                ignore=shutil.ignore_patterns("__pycache__"))
os.chdir(scratch_path)
os.environ["PATH"] = f"{Path(sys.executable).parent}:{os.environ['PATH']}"
os.environ["PYTHONPATH"] = str(scratch_path)      # the recipes import demo_game
sys.path.insert(0, str(scratch_path))

L = Ledger(create=True)                           # .datconfig.yaml + .dat/ledger
with open(".datconfig.yaml", "a") as config_file:
    config_file.write("run: python3 -m demo_main\n")
Path("justfile").write_text(
    f"import '{files('dvc_dat') / 'dvc_dat.just'}'  # run\n"
    "import '../../justfile'  # the demo's ledger verbs\n"
    "import? '.dat/targets.just'  # the declared commands\n")
Path("model-G1.yaml").write_text(
    yaml.safe_dump({"main": "demo_game.etl.model.train", "game": "G1"}))
Path(".gitignore").write_text(".dat/\n__pycache__/\n")
git_cmd = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com"]
for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "demo-game"]):
    subprocess.run(git_cmd + args, cwd=scratch_path, check=True)

# the data: one game, its video, a 1.5.3 cut, a home correction, a 1.5.4 cut
from demo_game.game import Video

with L.transaction(by="human:dan") as t:
    t.add("db", "version", "3.1.4")
    t.add("db/pred/team", "db/cardinality", "many")
    t.add("db/pred/video", "db/type", "demo_game.game.Video")
    t.add("db/pred/span", "db/type", "json")
with L.transaction(by="human:dan", lock=10) as t:
    bump(t, "code/demo-game", "minor", confirm=lambda old, new: True)
with L.transaction(by="human:dan", lock=10) as t:
    t["game/G1"] = {"home": "G4", "away": "G5", "court": "north"}
video_value = Video(b"G1 wide camera, 9000 frames")
video_value.preds.update(game="G1", camera="wide", span=[0, 9000])
with L.transaction(by="human:dan") as t:
    video_value.seal(t, name="video/G1", provenance="import:archive")
cut_153_value = L.at().run("demo_game.game.cut", game="G1", version="1.5.3")
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "db/alias", cut_153_value.subject)
with L.transaction(by="human:dan", why="home was G6") as t:
    t["game/G1", "home"] = "G6"
cut_154_value = L.at().run("demo_game.game.cut", game="G1", version="1.5.4")
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "db/alias", cut_154_value.subject)
    t["cfg/train", "epochs"] = "8"
    t["game/G1", "gameset"] = "normie"

# the ETL data: three cities' year of weather, each found by weather/<city>, and a city set
from comfort.values import Days

MEAN_F = {"Austin": 69, "Boston": 52, "Chicago": 50}
for seed, city in enumerate(MEAN_F, start=1):
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
with L.transaction(by="human:dan", why="the city set") as t:
    t.add("db/pred/contains", "db/cardinality", "many")
    for city in MEAN_F:
        t.add("cityset/representative", "contains", city)
with L.transaction(by="human:dan", why="mount the stages") as t:   # sandboxed: code = the module bytes a run loads
    t.add("db/mount/comfort", "db/root", "comfort")
    t.add("db/mount/comfort", "db/repo", "demo-game")
just_done = subprocess.run(["just", "mounts"], check=True, capture_output=True)   # writes .dat/targets.just, the declared commands

# %% [markdown]
# # Quick: the CLI
#
# A project's `justfile` imports dvc-dat's `run` and a set of ledger
# verbs, so from a shell every workflow is `just <verb>`, and each verb
# is one ledger call. The ledger holds **values** (stored objects named
# by the hash of their content), each carrying **predicates**, facts
# about it. `just --list` is the menu; `[run]` holds the commands the
# project's code declares.

# %%
# !just --list --color never
# → Available recipes:
# →     alias name target         # point a name at a value (a hash prefix is expanded)
# →     annotate subject *args    # a row on a subject: t[s, p] = o
# →     bump subject part="patch" # bump a clock: `code` is this checkout's code/<repo>; minor and major ask for `yes`
# →     history subject           # every row a subject has held, with each revision's db/by
# →     index pred                # declare a pred indexed
# →     mounts *args              # mounts [PREFIX]: the mounted names, with what each loads to
# →     run *args                 # run TARGET [ARG ...] [KEY=VALUE ...]: a mounted name, a dotted function, a spec
# →     value *args               # exactly one value matching the preds
# →     values *args              # the values matching k=v / k:=v preds (kind=<short class name> narrows)
# →     why name *args            # a value's dependencies, whether they hold at the head, and what moved since the alias's last target
# →
# →     [run]
# →     train *args               # game=…  train the model on one game's tracks

# %% [markdown]
# ## Running
#
# `just run` executes a function and returns its result as a value,
# sealed with what it read. Asked again with the same inputs and
# code, it finds the value instead of re-running.

# %%
# !just run demo_game.game.cut game=G1 version=1.5.3
# !just run demo_game.game.cut game=G1 version=1.5.3
# → ran  #<8 hex>  game=G1 version=1.5.3 video=video/G1 team=["G6", "G5"]
# → hit  #<8 hex>  game=G1 version=1.5.3 video=video/G1 team=["G6", "G5"]

# %% [markdown]
# A spec is a YAML file naming the function (`main`) and its keys;
# `alias=` names the result.

# %%
# !cat model-G1.yaml
# !just run model-G1.yaml alias=model/prod
# → game: G1
# → main: demo_game.etl.model.train
# → ran  model/prod  game=G1 stage=model metrics.count=12 metrics.score=0.927 gameset=normie

# %% [markdown]
# A function marked `@command` is its own verb: `just train` is
# `just run` of `model.train`. Same question as the spec, so a hit.

# %%
# !just train game=G1
# → hit  model/prod  game=G1 stage=model metrics.count=12 metrics.score=0.927 gameset=normie

# %% [markdown]
# ## An ETL pipeline
#
# Three stages, each a function calling the one below it: `daily_comfort`
# scores a city's year of weather, `city_comfort` bins one city's days by
# comfort over a date range, `comfort_report` sums a city set's cities
# (the package `comfort/`, from demo-etl). One `just run` of the report
# runs every stage it needs. A bare `2026-01-01` is a YAML date, which a
# ledger key refuses, so the dates are quoted.

# %%
# !just run comfort.report.comfort_report cityset=cityset/representative start="'2026-01-01'" end="'2027-01-01'"
# !just run comfort.report.comfort_report cityset=cityset/representative start="'2026-01-01'" end="'2027-01-01'"
# !just values fn=comfort.stages.daily_comfort
# → ran  #<8 hex>
# → hit  #<8 hex>
# → #<8 hex>  city=Austin
# → #<8 hex>  city=Boston
# → #<8 hex>  city=Chicago

# %% [markdown]
# Ran, then a hit; `values fn=` lists what one stage has sealed: a
# daily comfort per city. Summer is a new range, so each city comfort
# reruns; the daily comforts do not depend on the range, so they are
# hits (the same three).

# %%
# !just run comfort.report.comfort_report cityset=cityset/representative start="'2026-06-01'" end="'2026-09-01'" alias=report/summer
# !just values fn=comfort.stages.daily_comfort
# !just values fn=comfort.stages.city_comfort
print("summer:", L.at().load("report/summer").obj)   # the report itself
# → ran  report/summer
# → #<8 hex>  city=Austin
# → #<8 hex>  city=Boston
# → #<8 hex>  city=Chicago
# → #<8 hex>  city=Austin
# → #<8 hex>  city=Boston
# → #<8 hex>  city=Chicago
# → #<8 hex>  city=Austin
# → #<8 hex>  city=Boston
# → #<8 hex>  city=Chicago
# → summer: {'comfortable': '117/276 days', 'top': ['Boston', 'Chicago']}

# %% [markdown]
# A code edit: the report keeps one top city, not two. The stages are
# mounted (Setup), so a stage's code is the bytes of the modules its run
# loaded: only the report loaded `report.py`, so only the report reruns,
# and no `bump` is needed.

# %%
# !sed -i '' 's/\[:2\]/[:1]/' comfort/report.py
# !git -c user.name=demo -c user.email=demo@example.com commit -qam "report: one top city"
# !just run comfort.report.comfort_report cityset=cityset/representative start="'2026-06-01'" end="'2026-09-01'" alias=report/summer
# !just values fn=comfort.stages.city_comfort | wc -l   # still six: no city comfort reran
# !just values fn=comfort.report.comfort_report
# → ran  report/summer
# →        6
# → #<8 hex>
# → #<8 hex>
# → report/summer

# %% [markdown]
# `just why` on the summer report: what it was computed from (each city
# comfort, the set's rows, its code), whether that all still holds, and
# what moved since the alias's last target: the code alone.

# %%
# !just why report/summer
# → report/summer: #<8 hex>, matches the head
# → dependencies: code <8 hex>, eval:comfort.stages.city_comfort{"city":"Austin",…} ComfortCounts:<8 hex>, (Boston, Chicago the same), fn comfort.report.comfort_report, platform <platform>, query {"__call__":"all","args":["cityset/representative","contains"],"since":null} -> 3 value(s)
# → since #<8 hex>, its last target: code <8 hex> -> <8 hex>

# %% [markdown]
# ## Looking
#
# `just values` lists every value whose predicates match; `kind=`
# narrows to one class. A value prints by its name if it has one.

# %%
# !just values kind=Cut game=G1
# → #<8 hex>   game=G1 version=1.5.3 video=video/G1 team=G4,G5
# → game/G1    game=G1 version=1.5.4 video=video/G1 team=G6,G5
# → #<8 hex>   game=G1 version=1.5.3 video=video/G1 team=G6,G5

# %% [markdown]
# `just value` is the one value that matches.

# %%
# !just value game=G1 version=1.5.4
# → game/G1    game=G1 version=1.5.4 video=video/G1 team=G6,G5

# %% [markdown]
# `just history` is every predicate a subject has held, with who
# wrote it and when.

# %%
# !just history game/G1
# → rev  by         predicate  object
# →   3  human:dan  home       G4
# →   3  human:dan  away       G5
# →   3  human:dan  court      north
# →   6  human:dan  db/alias   #<the 1.5.3 cut, 8 hex>
# →   7  human:dan  home       G6
# →   9  human:dan  db/alias   #<the 1.5.4 cut, 8 hex>
# →   9  human:dan  gameset    normie

# %% [markdown]
# `just why` on the 1.5.4 cut: it no longer matches, since `demo_game`
# is installed code, identified by the checkout's commit
# (`code/demo-game`), and the report edit above committed. Its name moved
# from the 1.5.3 cut, whose difference is the home team.

# %%
# !just why game/G1
# → game/G1: #<8 hex>, does not match the head
# → dependencies: code <8 hex>, code/demo-game <8 hex>, fn demo_game.game.cut, game/G1 away G5, game/G1 home G6, platform <platform>, query {"game":"G1","kind":"demo_game.game.Video"} -> 1 value(s)
# → since #<8 hex>, its last target: game/G1 home G4 -> G6

# %% [markdown]
# ## Updating
#
# A write adds a predicate; nothing changes in place. `annotate`
# adds one fact to a subject, `alias` points a name at a value and
# prints what it pointed at before, and `index` makes a predicate
# fast to list by.

# %%
# !just annotate game/G1 texture=hardwood
# !just alias prod {cut_154_value.subject[:8]}
# !just index game
# → game/G1 texture=hardwood
# → prod: (none) -> #<the 1.5.4 cut, 8 hex>
# → game: indexed; 7 subjects hold it

# %% [markdown]
# ## Releasing
#
# A version is a clock on a subject; `just bump` advances it. `code`
# is this repo, and the commit is recorded beside the version. A
# bump of `db`, the ledger's own clock, is a release.

# %%
# !just bump code
# !echo yes | just bump db minor
# → code/demo-game: 0.1.0 -> 0.1.1 at <8 hex>
# → db: 3.1.4 -> 3.2.0? yes
# → db: 3.1.4 -> 3.2.0, a release

# %% [markdown]
# ## Other commands
#
# `just mounts` lists the mounted names and what each loads to:

# %%
# !just mounts
# → Base names matching: '*'
# →   dt                        -->  <module>
# →   model                     -->  <module>

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
