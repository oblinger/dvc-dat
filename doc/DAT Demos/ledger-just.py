# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# #### Setup

# %%
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from dvc_dat.ledger import Ledger, Ref, bump
from dvc_dat.ledger import LedgerError, Multiple

# %%
scratch_project_path = Path("scratch/just-demo").resolve()
shutil.copytree("demo_game", scratch_project_path,
                ignore=shutil.ignore_patterns("__pycache__"))
os.chdir(scratch_project_path)
L = Ledger(create=True)              # .datconfig.yaml + .dat/ledger
user_name = os.environ.get("USER", "dan")

# demo repo


def git(*args: str) -> str:
    """Run git in the scratch folder; return its stdout."""
    cmd = ["git", "-c", "user.name=demo",
           "-c", "user.email=demo@example.com", *args]
    done = subprocess.run(cmd, cwd=scratch_project_path, check=True,
                          capture_output=True, text=True)
    return done.stdout.strip()


spec_record = {"main": "demo_game.etl.model.fit",
               "stage": "model", "game": "G1", "epochs": 8}
Path("model-G1.yaml").write_text(yaml.safe_dump(spec_record))
Path(".gitignore").write_text(".dat/\n")
git("init", "-q")
git("add", ".")
git("commit", "-q", "-m", "demo-game")
sys.path.insert(0, str(scratch_project_path))
os.environ["PYTHONPATH"] = str(scratch_project_path)  # for recipes

# one game, its video, a 1.5.3 cut, a home correction, a 1.5.4 cut

from demo_game.game import Video, Cut

with L.transaction(by="human:dan") as t:
    t.add("db", "version", "3.1.4")
    t.add("db/pred/team", "db/cardinality", "many")
    t.add("db/pred/video", "db/type", "demo_game.game.Video")
    t.add("db/pred/span", "db/type", "json")
with L.transaction(by="human:dan") as t:                 # rev 2
    bump(t, "code/demo-game", "minor",       # 0.0.0 -> 0.1.0
         confirm=lambda old, new: True)
with L.transaction(by="human:dan") as t:                 # rev 3
    t["game/G1"] = {"home": "G4", "away": "G5", "court": "north"}
video_value = Video(b"G1 wide camera, 9000 frames")
video_value.preds.update(game="G1", camera="wide", span=[0, 9000])
with L.transaction(by="human:dan") as t:                 # rev 4
    video_value.seal(t, alias="video/G1",
                     provenance="import:archive")
cut_153_value = L.at().eval("demo_game.game.cut",       # rev 5
                            game="G1", version="1.5.3")
with L.transaction(by="human:dan") as t:                 # rev 6
    t.add("game/G1", "db/alias", cut_153_value.subject)
with L.transaction(by="human:dan", why="home was G6") as t:
    t["game/G1", "home"] = "G6"                          # rev 7
cut_154_value = L.at().eval("demo_game.game.cut",       # rev 8
                            game="G1", version="1.5.4")
with L.transaction(by="human:dan") as t:                 # rev 9
    t.add("game/G1", "db/alias", cut_154_value.subject)

# %% [markdown]
# # Ledger: just
#
# A person reaches the ledger from a shell, and the `just` recipes
# are the verbs they type there. Each recipe is one API call under a
# name a human would type, with what a program spells out each time
# (who is acting, the confirmation, which ledger) supplied by the
# recipe instead. No recipe hides a seal behind a verb that reads
# like an edit. The recipes are a proposal for the just layer (F447
# Q4: hand recipes in the project's justfile calling the API),
# designed from these use cases down; the `justfile` beside this
# notebook holds them.
#
# A shell cell and the code cell after it are one act written
# two ways; each output is the one it gives run alone.

# %% [markdown]
# ## The ledger from a shell

# %% [markdown]
# ### One recipe is one API call

# %%
# !just values game=G1
# → video/G1  game=G1 camera=wide span=[0, 9000]
# → <8 hex>   game=G1 version=1.5.3 video=video/G1 team=G4,G5
# → game/G1   game=G1 version=1.5.4 video=video/G1 team=G6,G5

# %% [markdown]
# Sugar for `L.at().values(game="G1")`, each value printed in its
# alias form with its preds.

# %%
for game_value in L.at().values(game="G1"):
    print(game_value, dict(game_value.preds))
# → video/G1 {"game": "G1", "camera": "wide", "span": [0, 9000]}
# → <8 hex> {"game": "G1", "version": "1.5.3",
#            "video": video/G1, "team": ["G4", "G5"]}
# → game/G1 {"game": "G1", "version": "1.5.4",
#            "video": video/G1, "team": ["G6", "G5"]}

# %% [markdown]
# Every value of the game: the video and both cuts, the 1.5.4 cut
# printed as `game/G1` because the game names it.

# %%
# !just values span:='[0, 9000]'
# → video/G1  game=G1 camera=wide span=[0, 9000]

# %% [markdown]
# Sugar for `L.at().values(span=[0, 9000])`.

# %%
print(L.at().values(span=[0, 9000]))     # → [video/G1]

# %% [markdown]
# `k:=v` is JSON, so `span:='[0, 9000]'` is the list a Python caller
# writes and `epochs:=8` the number 8; `k=v` is always a string, so
# `version=1.5` stays `"1.5"` (A17).

# %% [markdown]
# ### Finding the ledger

# %%
# !cat .datconfig.yaml
# → ledger: .dat/ledger

# %% [markdown]
# Every recipe opens the ledger with `Ledger()`, which walks up from
# the cwd to the nearest `.datconfig.yaml` and opens the ledger its
# `ledger:` line names. Notice `DAT_LEDGER` wins over the walk, here
# naming a ledger that does not exist.

# %%
# !DAT_LEDGER=../no-ledger just values game=G1
# → LedgerError: no ledger at ../no-ledger

# %% [markdown]
# Sugar for `Ledger()` with `DAT_LEDGER` set in the environment.

# %%
os.environ["DAT_LEDGER"] = "../no-ledger"
try:
    Ledger()
except LedgerError as e:
    print("LedgerError:", e)  # → LedgerError: no ledger at ../no-ledger
del os.environ["DAT_LEDGER"]

# %% [markdown]
# Set, `DAT_LEDGER` names the ledger and the walk never runs (A44.4):
# a recipe run from a scratch folder, or a sandbox worker, reaches
# the project's ledger this way.

# %% [markdown]
# ## Finding values

# %% [markdown]
# ### Only one kind

# %%
# !just values kind=Cut game=G1
# → <8 hex>   game=G1 version=1.5.3 video=video/G1 team=G4,G5
# → game/G1   game=G1 version=1.5.4 video=video/G1 team=G6,G5

# %% [markdown]
# Sugar for `L.at().values(kind=Cut, game="G1")`.

# %%
for cut_value in L.at().values(kind=Cut, game="G1"):
    print(cut_value, cut_value.preds["version"])
# → <8 hex> 1.5.3
# → game/G1 1.5.4

# %% [markdown]
# The video is gone: `kind=` narrows to a class. The recipe matches
# the short `Cut` against the `db/kind` rows and refuses it when two
# kinds share it.

# %% [markdown]
# ### Exactly one value

# %%
# !just value game=G1 version=1.5.3
# → <8 hex>   game=G1 version=1.5.3 video=video/G1 team=G4,G5

# %% [markdown]
# Sugar for `L.at().value(game="G1", version="1.5.3")`.

# %%
cut_value = L.at().value(game="G1", version="1.5.3")
print(cut_value, dict(cut_value.preds))
# → <8 hex> {"game": "G1", "version": "1.5.3",
#            "video": video/G1, "team": ["G4", "G5"]}

# %% [markdown]
# Asked for one where three match, `value` refuses and names them
# rather than picking one.

# %%
# !just value game=G1
# → Multiple: game=G1 matches 3: video/G1, <8 hex>, game/G1

# %% [markdown]
# Sugar for `L.at().value(game="G1")`, the `Multiple` printed.

# %%
try:
    L.at().value(game="G1")
except Multiple as e:
    print("Multiple:", e)
# → Multiple: game=G1 matches 3: video/G1, <8 hex>, game/G1

# %% [markdown]
# ### What a subject has held

# %%
# !just history game/G1
# → rev  by         predicate  object
# →   3  human:dan  home       G4
# →   3  human:dan  away       G5
# →   3  human:dan  court      north
# →   6  human:dan  db/alias   <the 1.5.3 cut, 8 hex>
# →   7  human:dan  home       G6
# →   9  human:dan  db/alias   <the 1.5.4 cut, 8 hex>

# %% [markdown]
# Sugar for `rev.rows()` filtered to the subject, with each
# revision's `db/by`.

# %%
rev = L.at()
for row in rev.rows():
    if row.subject == "game/G1":
        by = rev[row.rev.tx, "db/by"]
        print(row.rev.id, by, "+" if row.added else "-",
              row.predicate, row.object)
# → 3 human:dan + home G4
# → 3 human:dan + away G5
# → 3 human:dan + court north
# → 6 human:dan + db/alias <the 1.5.3 cut, 64 hex>
# → 7 human:dan + home G6
# → 9 human:dan + db/alias <the 1.5.4 cut, 64 hex>

# %% [markdown]
# The game's own rows and its alias moves, in order: the home team
# corrected at 7, the current cut moved at 9. No fold gives this;
# `rows()` is the ledger unfolded, removes included.

# %% [markdown]
# ### Why a value is what it is

# %%
# !just why game/G1
# → game/G1: <8 hex>, matches the head
# → trace: code/demo-game 0.1.0+<8 hex>, fn <8 hex>,
# →   game/G1 away G5, game/G1 home G6, video/G1,
# →   platform darwin-arm64-py3.11, uv.lock <8 hex>
# → since <8 hex>, its last target: game/G1 home G4 -> G6

# %% [markdown]
# Sugar for `v.trace`, `v.matches(rev)` and `v.diff(prev)`, `prev`
# the alias's previous target from `rev.asserted(s, "db/alias")`.

# %%
rev = L.at()
current_cut = rev.load("game/G1")
for item in sorted(current_cut.trace):
    print(item, "->", current_cut.trace[item])
# → code/demo-game -> 0.1.0+<8 hex>
# → fn -> db/fn/demo_game.game.cut/<hash>
# → game/G1 away -> G5
# → game/G1 home -> G6
# → platform -> darwin-arm64-py3.11
# → q:{"game":"G1","kind":"demo_game.game.Video"}
#     -> ["ref:demo_game.game.Video:<hash>"]
# → ref:demo_game.game.Video:<hash>
#     -> ref:demo_game.game.Video:<hash>
# → uv.lock -> sha256:<hash>
print(current_cut.matches(rev))          # → True
alias_moves = rev.asserted("game/G1", "db/alias")
previous_subject = alias_moves[-2][1]
print(current_cut.diff(rev.load(previous_subject)))
# → {"game/G1 home": ("G6", "G4")}

# %% [markdown]
# Everything the cut read is in its trace; `matches` re-reads each
# item at the head, and `diff` against the cut the game named before
# names the one item that moved, the home team. Given a bare hash,
# which has no previous target, the recipe takes `against=`.

# %% [markdown]
# ## Writing

# %% [markdown]
# ### A fact beside a value

# %%
# !just annotate game/G1 texture=hardwood
# → game/G1 texture=hardwood

# %% [markdown]
# Sugar for `t["game/G1", "texture"] = "hardwood"`.

# %%
with L.transaction(by=f"human:{user_name}") as t:
    t["game/G1", "texture"] = "hardwood"
print(L.at()["game/G1", "texture"])          # → hardwood

# %% [markdown]
# A row on the named subject, literal (A34): on `game/G1` it is a
# fact about the game, not about its cut, and it is never a seal.
# There is no `just set <hash> game=G2`: a wrong pred on a sealed
# value is a new seal and an alias move, made by `just eval` or, in
# code, by `v.seal(t)`.

# %% [markdown]
# ### Giving a value a name

# %%
# !just alias prod {cut_153_value.subject[:8]}
# → prod: (none) -> <the 1.5.3 cut, 8 hex>
# !just alias prod {cut_154_value.subject[:8]}
# → prod: <the 1.5.3 cut, 8 hex> -> <the 1.5.4 cut, 8 hex>

# %% [markdown]
# Sugar for `rev.get("prod", "db/alias")`, then
# `t.add("prod", "db/alias", s)`.

# %%
for named_cut_value in (cut_153_value, cut_154_value):
    rev = L.at()
    hash_prefix = named_cut_value.subject[:8]
    target_ref = rev.refs(s=f"{hash_prefix}*", one=True)
    print(rev.get("prod", "db/alias"))
    with L.transaction(by=f"human:{user_name}") as t:
        t.add("prod", "db/alias", target_ref.subject)
# → None
# → <the 1.5.3 cut, 64 hex>
print(Ref(L.at(), "prod").subject == cut_154_value.subject)  # → True

# %% [markdown]
# The second move prints what `prod` named before it, so a wrong
# move is undone by hand. A short hash is expanded with
# `refs(s="<prefix>*", one=True)`, refused when two subjects share
# the prefix.

# %% [markdown]
# ### A pred worth finding fast

# %%
# !just index game
# → game: indexed; 3 subjects hold it

# %% [markdown]
# Sugar for `t.add("db/pred/game", "db/index", "true")`.

# %%
with L.transaction(by=f"human:{user_name}") as t:
    t.add("db/pred/game", "db/index", "true")
holder_refs = L.at().refs(where={"game": None})   # has a game row
print(len(holder_refs))              # → 3: the video and two cuts

# %% [markdown]
# The store builds the index over existing rows itself (Q18), so
# there is nothing to back-fill; the count says how much the index
# covers.

# %% [markdown]
# ## Versions and releases

# %% [markdown]
# ### Moving the code's version

# %%
# !just bump code
# → code/demo-game: 0.1.0 -> 0.1.1 at <8 hex>
# !echo yes | just bump code minor
# → code/demo-game: 0.1.1 -> 0.2.0? yes
# → code/demo-game: 0.1.1 -> 0.2.0 at <8 hex>

# %% [markdown]
# Sugar for `bump(t, "code/demo-game", part, confirm=…)`.

# %%
with L.transaction(by=f"human:{user_name}") as t:
    bump(t, "code/demo-game")                  # patch
with L.transaction(by=f"human:{user_name}") as t:
    bump(t, "code/demo-game", "minor",
         confirm=lambda old, new: True)        # the recipe asks
print(L.at()["code/demo-game"])
# → {"commit": "<the demo commit>", "version": "0.2.0"}

# %% [markdown]
# `code` is the recipe's word for the repo the justfile sits in.
# `bump` reads the commit from that checkout and writes it beside
# the version; a minor or major move waits for `yes`, which is
# `confirm=`. A project's own version-sync line follows in the
# recipe (Q4 (A)).

# %% [markdown]
# ### A release

# %%
# !echo yes | just bump db minor
# → db: 3.1.4 -> 3.2.0? yes
# → db: 3.1.4 -> 3.2.0, a release

# %% [markdown]
# Sugar for `bump(t, "db", "minor", confirm=…)` with `why="release"`.

# %%
with L.transaction(by=f"human:{user_name}",
                   why="release") as t:
    bump(t, "db", "minor", confirm=lambda old, new: True)
release_version = t.rev["db", "version"]
print(release_version,
      L.at(release_version).id == t.rev.id)    # → 3.2.0 True

# %% [markdown]
# The ledger's own version names this moment: `L.at("3.2.0")` is
# the revision, every code version and alias as they stood.

# %% [markdown]
# ### A name has no version

# %% [markdown]
# A bump of a name that points at a value is refused, naming the
# alias.

# %%
# !just bump game/G1
# → TypeError: game/G1 is an alias; seal a new value and re-point

# %% [markdown]
# Sugar for `bump(t, "game/G1")`, the `TypeError` printed.

# %%
try:
    with L.transaction(by=f"human:{user_name}") as t:
        bump(t, "game/G1")
except TypeError as e:
    print("TypeError:", e)
# → TypeError: game/G1 is an alias; seal a new value and re-point

# %% [markdown]
# A value's version is a pred its constructor set; a new version is
# a new value and an alias move.

# %% [markdown]
# ## Computing

# %% [markdown]
# ### Derived once, then found

# %%
# !just eval demo_game.game.cut game=G1 version=1.5.3
# → ran  <8 hex>
# !just eval demo_game.game.cut game=G1 version=1.5.3
# → hit  <8 hex>

# %% [markdown]
# Sugar for `rev.eval(name, **keys)`, `memo="get"` asked first.

# %%
rev = L.at()
keys_record = {"game": "G1", "version": "1.5.3"}
hit_value = rev.eval("demo_game.game.cut", memo="get",
                     **keys_record)
cut_value = hit_value or rev.eval("demo_game.game.cut",
                                  **keys_record)
print("hit" if hit_value else "ran", cut_value)   # → ran <8 hex>

# %% [markdown]
# The 1.5.3 cut on the ledger read the old home team and the old
# code version, so the first ask re-derives it and the second finds
# it. The `memo="get"` look is how the recipe can say which.

# %% [markdown]
# ### Running a spec

# %%
# !cat model-G1.yaml
# → epochs: 8
# → game: G1
# → main: demo_game.etl.model.fit
# → stage: model

# %%
# !just run model-G1.yaml alias=model/prod
# → ran  model/prod  game=G1 stage=model metrics.score=…

# %% [markdown]
# Sugar for `rev.eval("demo_game.etl.dat.dat", spec=…)`, then
# `t.add("model/prod", "db/alias", s)`.

# %%
spec_from_file = yaml.safe_load(Path("model-G1.yaml").read_text())
model_dat = L.at().eval("demo_game.etl.dat.dat", spec=spec_from_file)
with L.transaction(by=f"human:{user_name}") as t:
    t.add("model/prod", "db/alias", model_dat.subject)
print(Ref(L.at(), "model/prod"), model_dat.preds["metrics.score"])
# → model/prod …

# %% [markdown]
# The dat constructor as a verb: the file's contents are the whole
# question, and handing the model to prod is an alias move, the seal
# being the eval's own. Written to the leans of Q36 (the eval hands
# the function a `work` folder) and Q37 (the `fn` item hashes the
# modules the run loaded), both still open on F447.

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
# - **The repo** — `code` is `code/<the repo the justfile sits in>`.
# - **The environment** — discovered from the checkout the recipe
#   runs in, never passed.
# - **Keys and preds** — `k=v` a string, `k:=v` JSON.
# - **Kinds** — a short class name, matched against `db/kind`.
# - **Hashes** — a prefix, expanded by `refs(s="<prefix>*",
#   one=True)`.
# - **Hit or ran** — `memo="get"` before `eval`.
# - **Printing** — each value in its alias form with its preds; a
#   moved alias with its old target.
# - **Project policy** — a version-sync line after `just bump code`.
