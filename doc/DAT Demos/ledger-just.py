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
# > **Plan** (what this notebook teaches; delete once the sections
# > carry it on their own)
# >
# > The ledger holds **values**: stored objects named by the hash of
# > their content, each carrying **predicates**, facts about it
# > (`version=1.5.3`, `camera=wide`). A **name** is a predicate that
# > points at a value. Every predicate ever written is kept, with who
# > wrote it and at which revision. From a shell a person works the
# > ledger by typing `just <verb>`; each verb is one ledger API call.
# > Three sections, one per thing a person does:
# >
# > 1. **Running** — `just run <function|spec> k=v …` executes it through the
# >    ledger: the result is a value, found if computed before, else made
# >    and sealed; `alias=` names it. A function marked `@command` runs as
# >    `just <name>` without `run`. `run` is dvc-dat's (`dvc_dat.just`).
# > 2. **Listing values by predicate** — `values` lists values by predicate;
# >    `value` gets exactly one; `history` lists every predicate a subject
# >    has held; `why` lists what a value was computed from.
# > 3. **Updating values** — `set` adds a predicate to a subject, a
# >    name's `alias=` among them; `index` makes a predicate fast
# >    to list by; `bump` edits a module's `__version__` in its source,
# >    or moves the ledger's own version (a release).
# >
# > A predicate on the command line is `k=v`: v is JSON when it parses
# > (a number, a list), else the text as typed (`G1`, `1.5.3`), the one
# > grammar `just run` uses too. The example data is one game, its video and two cuts of it;
# > the verbs are the same for any values. Each section: the shell line and
# > its output, one sentence saying what the verb does, then the API
# > call it wraps.

# %% [markdown]
# #### Setup

# %%
import os
import shutil
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

import yaml

from dvc_dat.ledger import Ledger, Ref
from dvc_dat.ledger import LedgerError, Multiple

# %%
scratch_project_path = Path("scratch/just-demo").resolve()
shutil.copytree("demo_game", scratch_project_path,
                ignore=shutil.ignore_patterns("__pycache__"))
os.chdir(scratch_project_path)
L = Ledger(create=True)              # .datconfig.yaml + .dat/ledger
with open(".datconfig.yaml", "a") as config_file:
    config_file.write("mounts:\n"                       # db/mount rows:
                      "  demo_game.etl: demo_game/etl\n"  # the ETL stages
                      "run: python3 -m demo_main\n")     # the main: cli
dvc_dat_just_path = files("dvc_dat") / "dvc_dat.just"
Path("justfile").write_text(
    f"import '{dvc_dat_just_path}'  # run, mounts, the ledger verbs\n"
    "import? '.dat/targets.just'  # the declared commands\n")
user_name = os.environ.get("USER", "dan")

# demo repo


def git(*args: str) -> str:
    """Run git in the scratch folder; return its stdout."""
    cmd = ["git", "-c", "user.name=demo",
           "-c", "user.email=demo@example.com", *args]
    done = subprocess.run(cmd, cwd=scratch_project_path, check=True,
                          capture_output=True, text=True)
    return done.stdout.strip()


spec_record = {"main": "demo_game.etl.model.train", "game": "G1"}
Path("model-G1.yaml").write_text(yaml.safe_dump(spec_record))
Path(".gitignore").write_text(".dat/\n")
git("init", "-q")
git("config", "user.name", "demo")
git("config", "user.email", "demo@example.com")
git("add", ".")
git("commit", "-q", "-m", "demo-game")
sys.path.insert(0, str(scratch_project_path))
os.environ["PYTHONPATH"] = str(scratch_project_path)  # for recipes
os.environ["PATH"] = f"{Path(sys.executable).parent}:{os.environ['PATH']}"  # recipes run this python

# one game, its video, a 1.5.3 cut, a home correction, a 1.5.4 cut

from demo_game.game import Video, Cut

with L.transaction(by="human:dan") as t:
    t.add("db", "db/version", "3.1.4")
    t.add("db/pred/team", "db/cardinality", "many")
    t.add("db/pred/video", "db/type", "demo_game.game.Video")
    t.add("db/pred/span", "db/type", "json")
with L.transaction(by="human:dan", lock=10) as t:                 # rev 2
    t["game/G1"] = {"home": "G4", "away": "G5", "court": "north"}
video_value = Video(b"G1 wide camera, 9000 frames")
video_value.preds.update(game="G1", camera="wide", span=[0, 9000])
with L.transaction(by="human:dan") as t:                 # rev 3
    video_value.seal(t, name="video/G1",
                     provenance="import:archive")
cut_153_value = L.at().run("demo_game.game.cut",       # rev 4, and db/repo/demo-game/demo_game 0.1.0
                            game="G1", version="1.5.3")
with L.transaction(by="human:dan") as t:                 # rev 5
    t.add("game/G1", "db/alias", cut_153_value.subject)
with L.transaction(by="human:dan", why="home was G6") as t:
    t["game/G1", "home"] = "G6"                          # rev 6
cut_154_value = L.at().run("demo_game.game.cut",       # rev 7
                            game="G1", version="1.5.4")
with L.transaction(by="human:dan") as t:                 # rev 8
    t.add("game/G1", "db/alias", cut_154_value.subject)
with L.transaction(by="human:dan") as t:                 # rev 9
    t["cfg/train", "epochs"] = "8"             # what train reads
    t["game/G1", "gameset"] = "normie"

# %% [markdown]
# # Ledger: just
#
# The ledger holds values, stored objects named by the hash of their
# content, each carrying predicates: facts about it, kept forever with
# who wrote each and when. A name is a predicate pointing at a value.
# The example data Setup put on the ledger is one game, `G1`: its
# video, a cut of it made by code version 1.5.3, a corrected home
# team, and a second cut by 1.5.4 that the name `game/G1` now points
# at; and the training config.
#
# From a shell a person works the ledger by typing `just <verb>`.
# Each verb is one ledger API call with the things a program would
# have to say every time (which ledger, who is acting, the yes to a
# confirmation) supplied by the recipe. No verb that reads like an
# edit hides a seal. The project's justfile imports them all from
# dvc-dat (`dvc_dat.just`): `run`, and the ledger verbs, each
# `python -m dvc_dat.ledger.recipes <verb>`.
#
# Under each heading one sentence says what the verb does; after its
# example, which API call it is. The Python notebooks show those calls.

# %% [markdown]
# ## Running
# `just run` executes a function or a spec; the result is a value, sealed once with what it read.
#
# ### A derived value
# `just run <fn> k=v …` returns the function's value, found if computed before.

# %%
# !just run demo_game.game.cut game=G1 version=1.5.3
# → targets: .dat/targets.just (1 command(s))
# → ran  #<8 hex>  game=G1 version=1.5.3 video=… team=["G6", "G5"]
# !just run demo_game.game.cut game=G1 version=1.5.3
# → hit  #<8 hex>  game=G1 version=1.5.3 video=… team=["G6", "G5"]

# %% [markdown]
# Found means computed before from the same inputs by the same code;
# otherwise the function runs and its result is sealed. It is
# `rev.run(name, **keys)`, with `seal="get"` asked first to say which.
#
# The 1.5.3 cut on the ledger read the old home team and the old
# code version, so the first ask re-derives it and the second finds
# it. The first `run` also wrote `.dat/targets.just`, below.
#
# ### A dat from a spec
# `just run <spec.yaml>` runs the function the file's `main` names, its other keys the keys; `alias=` names the result.

# %%
# !cat model-G1.yaml
# → game: G1
# → main: demo_game.etl.model.train

# %%
# !just run model-G1.yaml alias=model/prod
# → ran  model/prod  game=G1 stage=model metrics.count=12 …

# %% [markdown]
# The dat is a value. It is
# `rev.run("demo_game.etl.model.train", game="G1", path="model/prod")`:
# `path=` names the result and builds its folder there (Q36).
#
# The file's contents are the whole set of keys; a key on the line
# overrides the file's. Handing the model to prod is the name, the
# seal being the eval's own.
#
# ### A command
# `just <name> k=v …` is `just run` of a function marked `@command`.

# %%
# !just --list | tail -n 2
# →     [run]
# →     train *args # game=…  train the model on one game's tracks
# !just train game=G1
# → hit  model/prod  game=G1 stage=model metrics.count=12 …

# %% [markdown]
# `train` carries `@command(args="game=…", help="…")`, and its
# module is under the ledger's mount of `demo_game.etl` (`mounts:`
# in `.datconfig.yaml`); `run` reads the commands off the mounted
# files and writes one recipe per command into `.dat/targets.just`,
# which the justfile imports. It is
# `just run demo_game.etl.model.train game=G1`: the same keys as the
# spec, so a hit. Anything not marked stays `just run <target>`.

# %% [markdown]
# ## Listing values by predicate
# Many values sit on the ledger; `values` prints those whose predicates match.
#
# ### Values by predicate
# `just values k=v …` lists every value whose predicates match the ones given.

# %%
# !just values game=G1
# → video/G1   game=G1 camera=wide span=[0, 9000]
# → #<8 hex>   game=G1 version=1.5.3 video=video/G1 team=G4,G5
# → game/G1    game=G1 version=1.5.4 video=video/G1 team=G6,G5
# → #<8 hex>   game=G1 version=1.5.3 video=video/G1 team=G6,G5
# → anonymous/Dat game=G1 stage=detect bins=16 metrics.count=40 …
# → anonymous/Dat_2 game=G1 stage=track metrics.count=12 …
# → model/prod game=G1 stage=model metrics.count=12 … gameset=normie

# %% [markdown]
# One line per value: its name if it has one, else its hash, then its
# predicates. It is `L.at().values(game="G1")`.
#
# Every value of the game: the video; the 1.5.3 cut from Setup, the
# 1.5.4 cut printed as `game/G1` because the game names it, and the
# 1.5.3 cut `just run` re-derived; and the dats the model run made.

# %%
# !just values span='[0, 9000]'
# → video/G1   game=G1 camera=wide span=[0, 9000]

# %% [markdown]
# The same listing, matched on a JSON-valued pred: it is
# `L.at().values(span=[0, 9000])`.
#
# v is JSON when it parses, so `span='[0, 9000]'` is the list a Python
# caller writes and `epochs=8` the number 8; `version=1.5.3` is not
# JSON and stays the string `"1.5.3"`, while `version=1.5` is the number
# 1.5 and `version='"1.5"'` the string.
#
# ### Values of one kind
# `kind=` narrows a listing to one value class.

# %%
# !just values kind=Cut game=G1
# → #<8 hex>   game=G1 version=1.5.3 video=video/G1 team=G4,G5
# → game/G1    game=G1 version=1.5.4 video=video/G1 team=G6,G5
# → #<8 hex>   game=G1 version=1.5.3 video=video/G1 team=G6,G5

# %% [markdown]
# It is `L.at().values(kind=Cut, game="G1")`.
#
# The video and the dats are gone. The recipe matches
# the short `Cut` against the `db/kind` rows and refuses it when two
# kinds share it.
#
# ### Exactly one value
# `just value k=v …` returns the one matching value; none or several is refused.

# %%
# !just value game=G1 version=1.5.4
# → game/G1    game=G1 version=1.5.4 video=video/G1 team=G6,G5

# %% [markdown]
# It is `L.at().value(game="G1", version="1.5.4")`.
#
# Asked for one where several match, `value` refuses and names them
# rather than picking one.

# %%
# !just value game=G1
# → Multiple: game=G1 matches 7: video/G1, #<8 hex>, game/G1, …

# %% [markdown]
# The refusal when several match: `L.at().value(game="G1")` raising
# `Multiple`, printed.
#
# ### A subject's history
# `just history <subject>` lists every predicate a subject has held, in order.

# %%
# !just history game/G1
# → rev  by         predicate  object
# →   2  human:dan  home       G4
# →   2  human:dan  away       G5
# →   2  human:dan  court      north
# →   5  human:dan  db/alias   #<the 1.5.3 cut, 8 hex>
# →   6  human:dan  home       G6
# →   8  human:dan  db/alias   #<the 1.5.4 cut, 8 hex>
# →   9  human:dan  gameset    normie

# %% [markdown]
# Each line carries the revision it was written at and who wrote it.
# It is `rev.history()` filtered to the subject, with each
# revision's `db/by`.
#
# The game's own rows and its alias moves, in order: the home team
# corrected at 7, the current cut moved at 9. No fold gives this;
# `history()` is the ledger unfolded, removes included.
#
# ### A value's inputs
# `just why <name>` lists what a value was computed from, and what has moved.

# %%
# !just why game/G1
# → game/G1: #<8 hex>, matches the head
# → dependencies: code <8 hex>, code/demo-game <8 hex>, fn demo_game.game.cut,
# →   game/G1 away G5, game/G1 home G6, platform <platform>,
# →   query {"game":"G1","kind":"demo_game.game.Video"} -> 1 value(s)
# → since #<8 hex>, its last target: game/G1 home G4 -> G6

# %% [markdown]
# The dependencies are what it read when made; `matches` says whether each
# input still holds; `diff` names what moved since the name's previous
# value. It is `v.dependencies`, `v.matches(rev)` and `v.diff(prev)`, `prev` the
# alias's previous target from `rev.history(s, "db/alias")`.
#
# Everything the cut read is in its dependencies; `matches` re-reads each
# item at the head, and `diff` against the cut the game named before
# names the one item that moved, the home team. Given a bare hash,
# which has no previous target, the recipe takes `against=`.
#
# ## Updating values
# A write adds a predicate to a subject; nothing is changed in place.
#
# ### A predicate on a subject
# `just set <subject> k=v` adds one predicate to a subject.

# %%
# !just set game/G1 texture=hardwood
# → game/G1 texture=hardwood

# %% [markdown]
# It is
# `t["game/G1", "texture"] = "hardwood"`.
#
# A row on the named subject, literal (A34): on `game/G1` it is a
# fact about the game, not about its cut, and it is never a seal.
# There is no `just set <hash> game=G2`: a wrong pred on a sealed
# value is a new seal and an alias move, made by `just run` or, in
# code, by `v.seal(t)`.
#
# ### A name for a value
# A name is one more row on its subject, `db/alias`, so
# `just set <name> alias=<value>` points it at a value.

# %%
# !just set prod alias={cut_153_value.subject[:8]}
# → prod: (none) -> #<the 1.5.3 cut, 8 hex>
# !just set prod alias={cut_154_value.subject[:8]}
# → prod: #<the 1.5.3 cut, 8 hex> -> #<the 1.5.4 cut, 8 hex>

# %% [markdown]
# It prints what the name pointed at before. It is `rev.get("prod", "db/alias")`,
# then `t.add("prod", "db/alias", s)`.
#
# The second move prints what `prod` named before it, so a wrong
# move is undone by hand. A short hash is expanded with
# `refs(s="<prefix>*", one=True)`, refused when two subjects share
# the prefix.
#
# ### An indexed predicate
# `just index <pred>` keeps an index on a predicate, so listing by it stays fast.

# %%
# !just index game
# → game: indexed; 7 subjects hold it

# %% [markdown]
# It is
# `t.add("db/pred/game", "db/index", "true")`.
#
# The store builds the index over existing rows itself (Q18), so
# there is nothing to back-fill; the count says how much the index
# covers.
#
# ### A version bump
# A code version lives in its source; `just bump <module>` edits its `__version__` line.

# %%
# !just bump demo_game
# → demo_game: 0.1.0 -> 0.1.1 in demo_game/__init__.py
# → commit it: git commit -am "demo_game 0.1.1"

# %% [markdown]
# It is `bump_source("demo_game", "patch")`: one line rewritten,
# nothing committed, nothing written to the ledger. A minor or major
# move waits for `yes`, which is `confirm=`.
#
# The ledger's `db/repo/demo-game/demo_game` `db/version` clock is the
# version of `demo_game` runs were exposed to. The first cut (rev 4) put
# `0.1.0` there; after the commit, the next run from the clean checkout
# moves it, and `db/repo/demo-game` `db/commit` to that run's commit.

# %%
# !git commit -qam "demo_game 0.1.1"
# !just run demo_game.game.cut game=G1 version=1.5.5
# !just history db/repo/demo-game/demo_game
# → ran  #<8 hex>  game=G1 version=1.5.5 video=video/G1 team=["G6", "G5"]
# → rev  by         predicate  object
# →   4  eval:demo_game.game.cut db/version 0.1.0
# →  22  eval:demo_game.game.cut db/version 0.1.1

# %% [markdown]
# ### A release of the ledger
# A release is a bump of the ledger's own clock; the revision names this moment.

# %%
# !echo yes | just bump db minor
# → db: 3.1.4 -> 3.2.0? yes
# → db: 3.1.4 -> 3.2.0, a release

# %% [markdown]
# It is
# `bump(t, "db", "minor", confirm=…)` with `why="release"`.
#
# The ledger's own version names this moment: `L.at("3.2.0")` is
# the revision, every code version and alias as they stood.
#
# ### A name has no version
# A name cannot be bumped; the version belongs to the value it points at.

# %%
# !just bump game/G1
# → TypeError: game/G1 is an alias; seal a new value and re-point

# %% [markdown]
# It is `bump(t, "game/G1")`, the `TypeError` printed.
#
# A value's version is a pred its constructor set; a new version is
# a new value and an alias move.

# %% [markdown]
# ## What the recipes hide
#
# What the Python notebooks spell out on every call, and where each
# recipe gets it instead; this is the just layer's input (Q4).
#
# - **The ledger** — `Ledger()`: `DAT_LEDGER` if set, else the walk
#   up to `.datconfig.yaml`.
# - **`by=`** — `human:$USER` on every write.
# - **`confirm=`** — a `yes` typed at the prompt, for a minor or
#   major `bump`.
# - **`why=`** — on `just bump db`, the release.
# - **The environment** — discovered from the checkout the recipe
#   runs in, never passed.
# - **Keys and preds** — `k=v`, v JSON, else the text as typed.
# - **Kinds** — a short class name, matched against `db/kind`.
# - **Hashes** — a prefix, expanded by `refs(s="<prefix>*",
#   one=True)`.
# - **Hit or ran** — `seal="get"` before `run`.
# - **Printing** — each value in its alias form with its preds; a
#   moved alias with its old target.

# %% [markdown]
# ## Footnote: which ledger
# `Ledger()` climbs from the cwd to the nearest `.datconfig.yaml`; `DAT_LEDGER` overrides it.

# %%
# !cat .datconfig.yaml
# → ledger: .dat/ledger
# → mounts:
# →   demo_game.etl: demo_game/etl
# → run: python3 -m demo_main

# %% [markdown]
# Every recipe opens the ledger with `Ledger()`, which walks up from
# the cwd to the nearest `.datconfig.yaml` and opens the ledger its
# `ledger:` line names. Notice `DAT_LEDGER` wins over the walk, here
# naming a ledger that does not exist.

# %%
# !DAT_LEDGER=../no-ledger just values game=G1
# → LedgerError: no ledger at ../no-ledger

# %% [markdown]
# Set, `DAT_LEDGER` names the ledger and the walk never runs (A44.4):
# a recipe run from a scratch folder, or a sandbox worker, reaches
# the project's ledger this way.
