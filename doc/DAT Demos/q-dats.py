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
import importlib, os, shutil, subprocess, sys
from pathlib import Path

from dvc_dat.ledger import Ledger, bump

demos_path = Path(globals().get("demos_path", Path.cwd()))   # survives the chdir
os.chdir(demos_path)
scratch_path = demos_path / "scratch/q-dats"
shutil.rmtree(scratch_path, ignore_errors=True)   # a re-run starts clean
for module_name in [m for m in sys.modules if m.split(".")[0] == "demo_game"]:
    del sys.modules[module_name]
sys.path[:] = [p for p in sys.path if p != str(scratch_path)]

shutil.copytree("demo_game", scratch_path,
                ignore=shutil.ignore_patterns("__pycache__"))
os.chdir(scratch_path)
git_cmd = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com"]
Path(".gitignore").write_text(".dat/\nby-hand/\n")
for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "demo-game"]):
    subprocess.run(git_cmd + args, check=True)
sys.path.insert(0, str(scratch_path))
L = Ledger(create=True)              # .datconfig.yaml + .dat/ledger

# %% [markdown]
# # Quick: dats
#
# A dat is a folder: a spec saying what to build, the files built
# from it, and a result saying how it went. On the ledger it is a
# value like any other. The quick tour: seal one by hand, build one
# with a ledger function, chain three stages, change code, release.

# %% [markdown]
# ## A dat is a value
#
# `demo_game/etl/dat.py` defines `StageDat`, a `Dat` whose preds are
# its spec keys and result metrics, and `build(rev, spec, path)`,
# which runs the function the spec's `main` names in `path`, then
# writes `_spec_.yaml` and `_result_.yaml` beside what it made.

# %%
from demo_game.etl.dat import StageDat, build

with L.transaction(by="human:dan", why="four games") as t:
    for game, court in [("G1", "north"), ("G2", "east"),
                        ("G3", "south"), ("G4", "west")]:
        t[f"game/{game}"] = {"court": court}

detect_spec_record = {"main": "demo_game.etl.detect.find",
                      "stage": "detect", "game": "G1", "bins": 16}
work_path = Path("by-hand/detect-G1").resolve()
work_path.mkdir(parents=True)
hand_dat = build(L.at(), detect_spec_record, work_path)
with L.transaction(by="human:dan") as t:
    hand_dat.seal(t, name="detect/G1")
print("dat:", repr(hand_dat), " sealed:", hand_dat.sealed)   # dat: <StageDat detect/G1>  sealed: <the seal's moment>

loaded_dat = L.at().load("detect/G1")
print("files:", sorted(p.name for p in loaded_dat.path.iterdir()))
# files: ['_result_.yaml', '_spec_.yaml', 'boxes.json']
print("preds:", dict(sorted(loaded_dat.preds.items())))
# preds: {'bins': '16', 'game': 'G1', 'metrics.count': '40', 'metrics.score': '0.494', 'stage': 'detect'}

# %% [markdown]
# Sealing sent the files to the art store by their hashes; the
# manifest naming them is the value's bytes. `load` rebuilds the
# folder from the store. The preds merge spec and result under one
# namespace, so dats are found like any value.

# %% [markdown]
# ## The dat constructor is a ledger function
#
# `dat(rev, *, spec, path)` just calls `build`, but under
# `@ledger_fn`: the spec is the question, and the answer is
# remembered. Its package is mounted and the code clock started
# first, so it runs in the sandbox.

# %%
with L.transaction(by="human:dan", why="mount the etl") as t:
    t.add("db/mount/demo_game.etl", "db/root", "demo_game/etl")
    t.add("db/mount/demo_game.etl", "db/repo", "demo-game")
    bump(t, "code/demo-game", "minor", confirm=lambda old, new: True)

spec_dat = L.at().run("demo_game.etl.dat.dat", spec=detect_spec_record)
print("dat:", repr(spec_dat))   # dat: <StageDat anonymous/Dat>: no name given

top_id = L.at().id
again_dat = L.at().run("demo_game.etl.dat.dat", spec=detect_spec_record)
print("same subject:", again_dat.subject == spec_dat.subject,
      " nothing written:", L.at().id == top_id)   # same subject: True  nothing written: True: a hit

# %% [markdown]
# The same spec is the same question: the second run is a memo hit,
# nothing runs and nothing is written.

# %% [markdown]
# ## An ETL chain
#
# Three stage functions — `detections`, `tracks`, `train` — each
# fixes its spec but the game, and each calls the one below with
# `rev.run`. `train` also reads `cfg/train` and the game's
# `gameset` from the ledger.

# %%
with L.transaction(by="human:dan", why="training") as t:
    t["cfg/train"] = {"epochs": "8"}
    for game, gameset in [("G1", "normie"), ("G2", "normie"),
                          ("G3", "pro"), ("G4", "pro")]:
        t[f"game/{game}", "gameset"] = gameset

model_dat = L.at().run("demo_game.etl.model.train", game="G1")
for item in sorted(model_dat.dependencies):
    print(item, "->", model_dat.dependencies[item])
# cfg/train epochs -> 8
# code -> db/code/<16 hex>
# eval:demo_game.etl.track.tracks{"game":"G1"} -> ref:demo_game.etl.dat.StageDat:<hash>
# fn -> demo_game.etl.model.train
# game/G1 gameset -> normie
# platform -> darwin-arm64-py3.11

# %% [markdown]
# The run recorded every dependency itself: its own code (`code`, and
# `fn` the function's name in it),
# the two rows it read, and the stage below, held by its bytes.

# %% [markdown]
# ## Only what moved is recomputed
#
# Edit `track.py` without changing behaviour, commit, bump.

# %%
tracks_dat = L.at().run("demo_game.etl.track.tracks", game="G1")
track_path = scratch_path / "demo_game/etl/track.py"
track_path.write_text(track_path.read_text() + "\n# tidied\n")
subprocess.run(git_cmd + ["commit", "-q", "-am", "tidy track"], check=True)
import demo_game.etl.track
importlib.reload(demo_game.etl.track)
with L.transaction(by="human:dan", why="tidy track") as t:
    bump(t, "code/demo-game")
print("matches:", tracks_dat.matches(L.at()))    # matches: False: its code moved

model_again_dat = L.at().run("demo_game.etl.model.train", game="G1")
retracked_dat = L.at().run("demo_game.etl.track.tracks", game="G1")
print("same bytes:", retracked_dat.same_as(tracks_dat))              # same bytes: True
print("same subject:", model_again_dat.subject == model_dat.subject)  # same subject: True: a hit

# %% [markdown]
# Asking for the model re-ran the tracks, whose code moved, and
# stopped there: the new tracks have the same bytes, and the model
# holds the tracks by their bytes, so the model is a hit.

# %% [markdown]
# ## Finding dats

# %%
L.at().run("demo_game.etl.model.train", game="G2")
print("scores:", L.at().select(("game", "metrics.score"), kind=StageDat,
                               stage="model", gameset="normie"))
# scores: [('G1', '0.927'), ('G2', '0.888')]

# %% [markdown]
# Spec keys and metrics are preds, so a query over them is an
# ordinary ledger query.

# %% [markdown]
# ## A release, and running at it
#
# A release is a bump of `db`'s own version: one named revision at
# which every clock and config reads one way.

# %%
with L.transaction(by="human:dan", why="October release") as t:
    bump(t, "db", "minor", confirm=lambda old, new: True)
with L.transaction(by="human:dan", why="train longer") as t:
    t["cfg/train", "epochs"] = "12"

old_model_dat = L.at("0.1.0").run("demo_game.etl.model.train", game="G1")
now_model_dat = L.at().run("demo_game.etl.model.train", game="G1")
print("same subject:", old_model_dat.subject == model_dat.subject)   # same subject: True: 8 epochs
print("diff:", old_model_dat.diff(now_model_dat))
# diff: {'cfg/train epochs': ('8', '12')}

# %% [markdown]
# At `0.1.0` the config said 8 epochs, so the model sealed then is
# the hit; at the head it says 12, so `train` ran again.
