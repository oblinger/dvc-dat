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
# # Ledger: just
#
# What a human types, against what a program calls. Each section is
# one recipe: a shell cell, one line naming the API call it is
# sugar for, and a code cell making that call. Every recipe is one
# call from the values and dats notebooks under a name a human
# would type; no recipe hides a seal behind a verb that reads like
# an edit.
#
# **The justfile does not exist.** These recipes are the proposal
# for F447 Q4 (A): hand recipes in sv-pipe's justfile calling the
# API, SV policy as recipe lines, designed from these use cases
# down. Running both cells of a pair does a write twice; the pair is
# for reading side by side.
#
# Written to the ledger design of 2026-10-18 (SVP447 Ledger Module,
# Values § The three notebooks, F447 A39–A44). It runs once
# `ledger2` is rebuilt to that design (T534); until then it is the
# design, not a demo.

# %%
import os, sys
from pathlib import Path

import yaml

from dvc_dat.ledger import Ledger, Ref, bump
from dvc_dat.ledger import Code, Env, set_env_provider

sys.path.insert(0, "demo_svp")           # the stand-in svp package
scratch_ledger_path = Path("scratch/just-demo/ledger").resolve()
L = Ledger(scratch_ledger_path, create=True)   # the one explicit act
os.environ["DAT_LEDGER"] = str(scratch_ledger_path)  # for recipes
os.environ["PYTHONPATH"] = "demo_svp"
USER = os.environ.get("USER", "dan")

ENV = Env({"sv-pipe": Code("0.2.2", "7d742989")},
          lock="sha256:5e1f", platform="darwin-arm64-py3.11")
set_env_provider(lambda module: ENV)


def moves(rev, subject):
    """Each (rev id, predicate, object) on subject, in order."""
    move_tuples = []
    for i in range(1, rev.id + 1):
        since = L.at(i - 1) if i > 1 else None
        for p, o in L.at(i).all(subject, since=since):
            move_tuples.append((i, p, o))
    return move_tuples

# %% [markdown]
# A shell cell is a process of its own: it opens this notebook's
# ledger through `DAT_LEDGER`, which overrides `Ledger()`'s walk up
# to `.datconfig.yaml` (A44), and finds its environment by git
# discovery in the sv-pipe checkout it runs from. The code cells use
# the stand-in provider, since a notebook runs inside no checkout.
# `moves` walks the revisions one at a time: no read lists every
# object a subject's predicates have held, and `why` and `history`
# need that list.

# %%
from svp.game import Video, Cut

with L.transaction(by="human:dan", why="seed") as t:
    t.add("db", "version", "3.1.4")
    t["code/sv-pipe"] = {"version": "0.2.2", "commit": "7d742989"}
    t["game/G1"] = {"home": "G4", "away": "G5", "court": "north"}
    t.add("db/pred/team", "db/cardinality", "many")
    t.add("db/pred/video", "db/type", "svp.game.Video")
video_value = Video(b"G1 wide camera, 9000 frames")
video_value.preds.update(game="G1", camera="wide")
with L.transaction(by="human:dan") as t:
    t.add_value(video_value, alias="video/G1",
                provenance="import:alg2")
cut_153 = L.at().eval("svp.game.cut", game="G1", version="1.5.3")
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "db/alias", cut_153.subject)
    t["game/G1", "home"] = "G6"          # a correction
cut_154 = L.at().eval("svp.game.cut", game="G1", version="1.5.4")
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "db/alias", cut_154.subject)

# %% [markdown]
# The values notebook's game, cut short and seeded through the API:
# G1, its video, a 1.5.3 cut, a correction to the home team, and a
# 1.5.4 cut that `game/G1` now names. Everything below is a recipe.

# %% [markdown]
# ## `just bump pipe [minor|major]`

# %%
# !just bump pipe
# !echo yes | just bump pipe minor

# %% [markdown]
# Sugar for `bump` on `code/sv-pipe` (`pipe` is the recipe's name
# for it) under `by=human:$USER`, then `python -m svp.version sync`
# (Q4 (A)); minor and major print the move and wait for `yes`,
# which is `confirm=`.

# %%
with L.transaction(by=f"human:{USER}") as t:
    bump(t, "code/sv-pipe")                    # patch
with L.transaction(by=f"human:{USER}") as t:
    bump(t, "code/sv-pipe", "minor",
         confirm=lambda old, new: True)        # the recipe asks
print(t.rev["code/sv-pipe"])    # {"version": …, "commit": "7d742989"}

# %% [markdown]
# ## `just bump db minor`: a release

# %%
# !echo yes | just bump db minor

# %% [markdown]
# Sugar for `bump(t, "db", "minor", confirm=…)` with `time=True`:
# the ledger's own version, the name of this moment.

# %%
with L.transaction(by=f"human:{USER}", time=True,
                   why="release") as t:
    bump(t, "db", "minor", confirm=lambda old, new: True)
release_version = t.rev["db", "version"]
print(release_version,
      L.at(release_version).id == t.rev.id)   # <version> True

# %% [markdown]
# ## `just values kind=Cut game=G1`

# %%
# !just values kind=Cut game=G1
#   game/G1    game=G1 version=1.5.4 team=G6,G5 video=video/G1
#   <8 hex>    game=G1 version=1.5.3 team=G4,G5 video=video/G1

# %% [markdown]
# Sugar for `rev.values(kind=…, **preds)` at the top, each value
# printed in its alias form with its preds; the short `Cut` is
# resolved against the `db/kind` rows, refused when ambiguous.

# %%
for cut in L.at().values(kind=Cut, game="G1"):
    print(cut, dict(cut.preds))

# %% [markdown]
# ## `just value game=G1 version=1.5.3`

# %%
# !just value game=G1 version=1.5.3

# %% [markdown]
# Sugar for `rev.value(**preds)`: exactly one, else the recipe
# prints the `KeyError` or `Multiple`.

# %%
cut_value = L.at().value(game="G1", version="1.5.3")
print(cut_value, dict(cut_value.preds))

# %% [markdown]
# ## `just eval svp.game.cut game=G1 version=1.5.3`

# %%
# !just eval svp.game.cut game=G1 version=1.5.3
#   ran  <8 hex>    (the home correction made 1.5.3 stale)

# %% [markdown]
# Sugar for `rev.eval(name, **keys)`, with `memo="get"` asked first
# so the recipe can say hit or ran. `k=v` is a string key and
# `k:=v` a JSON one, so `epochs:=8` is the key `8` a Python caller
# writes, while `version=1.5` stays `"1.5"` (A17).

# %%
rev = L.at()
keys_record = {"game": "G1", "version": "1.5.3"}
hit_cut = rev.eval("svp.game.cut", memo="get", **keys_record)
cut_value = hit_cut or rev.eval("svp.game.cut", **keys_record)
print("hit" if hit_cut else "ran", cut_value)

# %% [markdown]
# ## `just why <alias|hash>`

# %%
# !just why game/G1

# %% [markdown]
# Sugar for `v.trace`, `v.matches(L.at())` and `v.diff(prev)`,
# `prev` the value the alias named before; given a bare hash, the
# recipe takes `against=<alias|hash>` instead.

# %%
rev = L.at()
current_cut = rev.load("game/G1")
print(dict(sorted(current_cut.trace.items())))
print(current_cut.matches(rev))                # True
alias_targets = [o for i, p, o in moves(rev, "game/G1")
                 if p == "db/alias"]
print(current_cut.diff(rev.load(alias_targets[-2])))
# {"game/G1 home": ("G6", "G4")}

# %% [markdown]
# ## `just history game/G1`

# %%
# !just history game/G1

# %% [markdown]
# Sugar for the `moves` walk with each revision's `db/by` beside
# it: the game's own rows and its alias moves, in order. `asserted`
# answers *when* only for a triple already known.

# %%
rev = L.at()
for i, p, o in moves(rev, "game/G1"):
    print(i, rev[f"db/tx/{i}", "db/by"], p, o)

# %% [markdown]
# ## `just annotate game/G1 texture=hardwood`

# %%
# !just annotate game/G1 texture=hardwood

# %% [markdown]
# Sugar for `t[s, p] = o`: a row on the named subject, literal
# (A34), never a seal; on `game/G1` it is a fact about the game,
# not about its cut.

# %%
with L.transaction(by=f"human:{USER}") as t:
    t["game/G1", "texture"] = "hardwood"
print(L.at()["game/G1", "texture"])          # hardwood

# %% [markdown]
# There is no `just set <hash> game=G2`: a wrong pred on a sealed
# value is a new seal and an alias move, made by `eval` or, in
# code, by `add_value`.

# %% [markdown]
# ## `just alias prod <hash>`

# %%
cut_subject = Ref(L.at(), "game/G1").subject
# !just alias prod {cut_subject[:8]}
#   prod: (none) -> game/G1

# %% [markdown]
# Sugar for `rev.get("prod", "db/alias")`, printed as the old
# target, then `t.add("prod", "db/alias", s)`; a short hash is
# expanded with `refs(s="<prefix>*", one=True)`.

# %%
rev = L.at()
target_subject = rev.refs(s=f"{cut_subject[:8]}*",
                          one=True).subject
print(rev.get("prod", "db/alias"))           # old target, or None
with L.transaction(by=f"human:{USER}") as t:
    t.add("prod", "db/alias", target_subject)
print(Ref(L.at(), "prod"))                   # prod: the shortest

# %% [markdown]
# ## `just index game`

# %%
# !just index game

# %% [markdown]
# Sugar for `t.add("db/pred/game", "db/index", "true")`. The store
# builds the index over existing rows itself (Q18), so there is no
# back-fill to write; the recipe reports how many subjects hold the
# pred.

# %%
with L.transaction(by=f"human:{USER}") as t:
    t.add("db/pred/game", "db/index", "true")
print(len(L.at().refs(where={"game": None})))   # the video, cuts

# %% [markdown]
# ## `just run <spec> …`
#
# The dat constructor as a verb, written to the leans of Q36 (the
# eval hands the function a `work` folder) and Q37 (the `fn` item
# hashes the modules the run loaded), both still open on F447.

# %%
spec_record = {"main": "svp.etl.model.fit", "stage": "model",
               "game": "G1", "epochs": 8}
spec_path = scratch_ledger_path.parent / "model-G1.yaml"
spec_path.write_text(yaml.safe_dump(spec_record))
# !just run {spec_path} alias=model/prod
#   ran  model/prod

# %% [markdown]
# Sugar for `rev.eval("svp.etl.dat.dat", spec=…)` on the file's
# contents, then, given `alias=`, `t.add(name, "db/alias", s)`:
# handing the model to prod is an alias move; the seal is the
# eval's own.

# %%
model_dat = L.at().eval("svp.etl.dat.dat",
                        spec=yaml.safe_load(spec_path.read_text()))
with L.transaction(by=f"human:{USER}") as t:
    t.add("model/prod", "db/alias", model_dat.subject)
print(Ref(L.at(), "model/prod"), model_dat.preds["metrics.score"])
