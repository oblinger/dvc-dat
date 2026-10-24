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

import yaml

from dvc_dat.ledger import Ledger, bump

demo_dir_path = globals().get("demo_dir_path", Path.cwd())  # survives a re-run
os.chdir(demo_dir_path)
scratch_path = Path("scratch/q-just").resolve()
shutil.rmtree(scratch_path, ignore_errors=True)   # a re-run starts clean
for module_name in [m for m in sys.modules if m.split(".")[0] in ("demo_game", "demo_main")]:
    sys.modules.pop(module_name)
sys.path[:] = [p for p in sys.path if "scratch/q-just" not in p]

shutil.copytree("demo_game", scratch_path,
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
Path(".gitignore").write_text(".dat/\n")
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
with L.transaction(by="human:dan") as t:
    bump(t, "code/demo-game", "minor", confirm=lambda old, new: True)
with L.transaction(by="human:dan") as t:
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

# %% [markdown]
# # Quick: just
#
# The ledger holds **values** (stored objects named by the hash of
# their content), each carrying **predicates**, facts about it. From
# a shell you type `just <verb>`, and each verb is one ledger call.
# The tour: run something, list what is there, then update it.

# %% [markdown]
# ## Running
#
# `just run` executes a function and returns its result as a value,
# sealed with what it read. Asked again with the same inputs and
# code, it finds the value instead of re-running. (The first run
# also writes `.dat/targets.just`, the recipes for commands, below.)

# %%
# !just run demo_game.game.cut game=G1 version=1.5.3
# !just run demo_game.game.cut game=G1 version=1.5.3
# → targets: .dat/targets.just (1 command(s))
# → ran  <8 hex>  game=G1 version=1.5.3 video=video/G1 team=["G6", "G5"]
# → hit  <8 hex>  game=G1 version=1.5.3 video=video/G1 team=["G6", "G5"]

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
# ## A command
#
# A function marked `@command` is its own verb: `just train` is
# `just run` of `model.train`. Same question as the spec, so a hit.

# %%
# !just train game=G1
# → hit  model/prod  game=G1 stage=model metrics.count=12 metrics.score=0.927 gameset=normie

# %% [markdown]
# ## Listing values
#
# `just values` lists every value whose predicates match; `kind=`
# narrows to one class. A value prints by its name if it has one.

# %%
# !just values kind=Cut game=G1
# → <8 hex>   game=G1 version=1.5.3 video=video/G1 team=G4,G5
# → game/G1   game=G1 version=1.5.4 video=video/G1 team=G6,G5
# → <8 hex>   game=G1 version=1.5.3 video=video/G1 team=G6,G5

# %% [markdown]
# `just value` is the one value that matches.

# %%
# !just value game=G1 version=1.5.4
# → game/G1   game=G1 version=1.5.4 video=video/G1 team=G6,G5

# %% [markdown]
# ## History and why
#
# `just history` is every predicate a subject has held, with who
# wrote it and when; `just why` is what a value was computed from,
# and what has moved since its name's previous value.

# %%
# !just history game/G1
# → rev  by         predicate  object
# →   3  human:dan  home       G4
# →   3  human:dan  away       G5
# →   3  human:dan  court      north
# →   6  human:dan  db/alias   <the 1.5.3 cut, 8 hex>
# →   7  human:dan  home       G6
# →   9  human:dan  db/alias   <the 1.5.4 cut, 8 hex>
# →   9  human:dan  gameset    normie

# %%
# !just why game/G1
# → game/G1: <8 hex>, matches the head
# → dependencies: code/demo-game <8 hex>, fn <8 hex>, game/G1 away G5, game/G1 home G6, platform <platform>, query {"game":"G1","kind":"demo_game.game.Video"} -> 1 value(s)
# → since <8 hex>, its last target: game/G1 home G4 -> G6

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
# → prod: (none) -> <the 1.5.4 cut, 8 hex>
# → game: indexed; 7 subjects hold it

# %% [markdown]
# ## Bumping a version
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
