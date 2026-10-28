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
import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dvc_dat.ledger import Ledger, Ref, bump
from dvc_dat.ledger import NotClean, Unindexed
from dvc_dat.ledger import UnmountedImport, UntracedRead

scratch_project_path = Path("scratch/dats-demo").resolve()
shutil.copytree("demo_game", scratch_project_path,
                ignore=shutil.ignore_patterns("__pycache__"))
os.chdir(scratch_project_path)
L = Ledger(create=True)              # .datconfig.yaml + .dat/ledger

# demo repo


def git(*args: str) -> str:
    """Run git in the scratch folder; return its stdout."""
    cmd = ["git", "-c", "user.name=demo",
           "-c", "user.email=demo@example.com", *args]
    done = subprocess.run(cmd, cwd=scratch_project_path, check=True,
                          capture_output=True, text=True)
    return done.stdout.strip()


Path(".gitignore").write_text(".dat/\nby-hand/\n")
git("init", "-q")
git("add", ".")
git("commit", "-q", "-m", "demo-game")
sys.path.insert(0, str(scratch_project_path))

# %% [markdown]
# # Ledger: dats
#
# A dat is a folder: a spec saying what to build, the files built
# from it, and a result saying how the build went. On the ledger a
# dat is a value like any other. Its files go to the art store
# once, by their hashes; the dat's bytes are the manifest naming
# them, so its subject is fixed by its content; and its preds are
# its spec keys and its result metrics under one namespace, so dats
# are found the way every value is found. A dat that is computed is
# the result of a ledger function: built once per memo key, and
# built again only where something it read has moved.

# %% [markdown]
# ## A dat is a value

# %% [markdown]
# ### A dat is a folder with a spec and a result
#
# The kind lives in `demo_game/etl/dat.py`, with `build`, which
# makes one in a folder you hand it:
#
# ```python
# SPEC_PREDS = ("game", "stage", "bins")
# METRICS = ("count", "score")
#
#
# @ledger_class(preds=SPEC_PREDS + ("gameset",)
#               + tuple(f"metrics.{m}" for m in METRICS))
# class StageDat(Dat):
#     """One stage's dat: `_spec_.yaml`, `_result_.yaml`, its files."""
#
#
# def build(rev, spec: dict, path: Path, **kwargs) -> StageDat:
#     """Build a dat from its spec in `path`: the constructor's body."""
#     module, name = spec["main"].rsplit(".", 1)
#     main = getattr(importlib.import_module(module), name)
#     args = {k: v for k, v in spec.items() if k != "main"}
#     result = main(rev, path, **args, **kwargs)
#     (path / "_spec_.yaml").write_text(yaml.safe_dump(spec))
#     (path / "_result_.yaml").write_text(yaml.safe_dump(result))
#     d = StageDat(path)
#     d.preds.update({k: spec[k] for k in SPEC_PREDS if k in spec})
#     for m in METRICS:
#         d.preds[f"metrics.{m}"] = attr(result, f"metrics.{m}")
#     return d
# ```
#
# `Dat` is the shipped folder `Value`: it encodes as its content
# manifest, and the files the manifest names go to the art store.
# `StageDat` adds only its preds: the spec keys `game`, `stage`,
# `bins`, then `gameset` and `metrics.count`, `metrics.score`.
# `build` runs the function the spec's `main` names in `path`, then
# writes the spec and the result beside what it made.

# %%
from demo_game.etl.dat import StageDat, build

# %% [markdown]
# ### Storing a dat by hand
#
# The first stage, detection, reads the game's court. The four
# games:

# %%
with L.transaction(by="human:dan", why="four games", lock=10) as t:
    for game, court in [("G1", "north"), ("G2", "east"),
                        ("G3", "south"), ("G4", "west")]:
        t[f"game/{game}"] = {"court": court}

# %%
rev = L.at()
detect_spec_record = {"main": "demo_game.etl.detect.find",
                      "stage": "detect", "game": "G1", "bins": 16}
work_path = Path("by-hand/detect-G1").resolve()
work_path.mkdir(parents=True)
hand_dat = build(rev, detect_spec_record, work_path)
print("files:", sorted(file_path.name for file_path in work_path.iterdir()))
# → files: ["_result_.yaml", "_spec_.yaml", "boxes.json"]
with L.transaction(by="human:dan") as t:
    hand_dat.seal(t, name="detect/G1", provenance="human:dan")
print("dat:", repr(hand_dat), " sealed:", hand_dat.sealed)     # → dat: <StageDat detect/G1>  sealed: <the seal's moment>

# %% [markdown]
# `build` made the dat in a folder of yours; `v.seal(t)` sealed it.
# The three files went to the art store by their hashes, the
# manifest naming them is the value's bytes, and the subject is
# the hash of those bytes with what they depend on. A hand seal
# records what it is told: here no `deps`, so the environment
# alone, and not the court `find` read.

# %% [markdown]
# ### Loading it back

# %%
rev = L.at()
loaded_dat = rev.load("detect/G1")
print("loaded:", repr(loaded_dat))  # → loaded: <StageDat detect/G1>
print("files:", sorted(file_path.name
                       for file_path in loaded_dat.path.iterdir()))
# → files: ["_result_.yaml", "_spec_.yaml", "boxes.json"]
print("new folder:", loaded_dat.path != work_path)  # → new folder: True: from the manifest

# %% [markdown]
# `load` decodes the manifest into a folder of its own, fetched
# from the art store; the folder it was built in is not needed
# again.

# %% [markdown]
# ### Its preds come from its spec and its result

# %%
print("preds:", dict(sorted(loaded_dat.preds.items())))
# → preds: {"bins": "16", "game": "G1", "metrics.count": "40",
#           "metrics.score": "0.494", "stage": "detect"}
print("spec bins:", repr(loaded_dat.spec["bins"]),
      " pred bins:", repr(loaded_dat.preds["bins"]))   # → spec bins: 16  pred bins: '16'
print("G1 dats:", rev.values(kind=StageDat, game="G1"))    # → G1 dats: [<StageDat detect/G1>]

# %% [markdown]
# A dat keeps `_spec_` and `_result_` apart on disk; its preds merge
# the two under one namespace, spec keys bare and result metrics
# dotted, so `values(game="G1")` and `preds["metrics.score"]` are
# one view. Preds are strings; the spec inside the folder keeps its
# numbers.

# %% [markdown]
# ## The dat constructor

# %% [markdown]
# ### dat(spec, …) is a ledger function
#
# From `dat.py`:
#
# ```python
# @ledger_fn
# def dat(rev, *, spec: dict, path: Path, **kwargs) -> StageDat:
#     """The dat constructor: `spec` the memo key, `path` the folder."""
#     return build(rev, spec, path, **kwargs)
# ```
#
# `demo_game.etl` is mounted, so `dat` runs in the sandbox. Its
# version is `demo_game/etl/__init__.py`'s `__version__`, and the
# ledger's `db/repo/demo-game/demo_game.etl` `db/version` clock starts at
# the first clean run, with the commit beside it as `db/repo/demo-game`
# `db/commit`. Both predicates are the ledger's, so they carry `db/`.

# %%
with L.transaction(by="human:dan", why="mount the etl") as t:
    t.ns.mount("demo_game.etl", root="demo_game/etl", repo="demo-game")   # two db/mount rows
rev = L.at()
dat_fn = rev.ns.load("demo_game.etl.dat.dat")
print("sandboxed:", dat_fn.code.sandboxed, " mount:", dat_fn.mount)     # → sandboxed: True  mount: demo_game.etl
print("code:", dat_fn.code)     # → code: demo_game.etl@0.1.0

# %%
spec_dat = rev.run("demo_game.etl.dat.dat",
                    spec=detect_spec_record)
print("dat:", repr(spec_dat), " sealed:", spec_dat.sealed)     # → dat: <StageDat anonymous/Dat>  sealed: <the seal's moment>: no name= given, so it gets one
print("preds:", dict(sorted(spec_dat.preds.items())))
# → preds: {"bins": "16", "game": "G1", "metrics.count": "40",
#           "metrics.score": "0.494", "stage": "detect"}
print("keys:", L.at()[spec_dat.subject, "db/keys"])
# → keys: {"spec": {"bins": 16, "game": "G1",
#             "main": "demo_game.etl.detect.find",
#             "stage": "detect"}}
print("db/version:", L.at()["db/repo/demo-game/demo_game.etl", "db/version"])
# → db/version: 0.1.0: this first clean run wrote the clock

# %% [markdown]
# The spec is the whole memo key: one key, a JSON object (A38), in
# the one `db/keys` row, numbers kept native. `path` is not a key
# (Q36): the run bound it to a fresh scratch folder, the function
# built the dat there, and the seal moved the folder into the art
# store by its manifest, as `v.seal(t)` did by hand. With no
# `path=` on the call the result is named `anonymous/Dat{unique}`;
# `path="games/G1"` would name it and rebuild its folder there.
# The preds are the same as the hand-built dat's.

# %% [markdown]
# `dat` imports the stage its spec's `main` names at run time, so
# which code ran is known only after the run.

# %%
module_paths = L.at()[spec_dat.dependencies["code"], "db/modules"]
print("modules:", sorted(module_paths))
# → modules: ["demo_game/etl/__init__.py", "demo_game/etl/dat.py",
#    "demo_game/etl/detect.py"]: the package's __init__ runs too

# %% [markdown]
# The `code` item hashes the modules the run loaded (Q37, open;
# lean): this entry's code is `dat.py` and `detect.py`. An edit to
# `detect.py` misses it, and a spec naming another stage is
# another `code` subject; `fn` names the function inside it.

# %% [markdown]
# ### Asked twice, computed once

# %%
top_id = L.at().id
again_dat = L.at().run("demo_game.etl.dat.dat",
                        spec=detect_spec_record)
print("same subject:", again_dat.subject == spec_dat.subject)   # → same subject: True: a hit
print("nothing written:", L.at().id == top_id)           # → nothing written: True

# %% [markdown]
# The same spec is the same memo key, and every dependency item holds:
# a memo hit, nothing run, nothing written. Asked another way, the
# stage function `detections`, which fixes the spec but the game:

# %%
detections_dat = rev.run("demo_game.etl.detect.detections",
                          game="G1")
print("same bytes:", detections_dat.same_as(spec_dat),
      " new subject:", detections_dat.subject != spec_dat.subject)   # → same bytes: True  new subject: True
detections_ref = Ref(L.at(), detections_dat.subject)
print("count:", detections_ref.preds["metrics.count"])        # → count: 40

# %% [markdown]
# Another function is another memo key, so it ran; the spec it
# built is the same, so the bytes are. `same_as` compares only the
# bytes hash: two memo entries, two subjects, one blob in the art
# store.

# %% [markdown]
# ## An ETL chain

# %% [markdown]
# ### Three functions, each depending on the last
#
# Detection, tracking, a model: each stage a function that builds
# its dat with its spec fixed, so its key is the game alone. From
# `track.py`:
#
# ```python
# @ledger_fn
# def tracks(rev, *, game: str, path: Path) -> StageDat:
#     return build(rev, {**SPEC, "game": game}, path)
#
#
# def link(rev, path, *, game, **_):
#     dets = rev.run("demo_game.etl.detect.detections", game=game)
#     boxes = json.loads((dets.path / "boxes.json").read_text())
#     runs = [b for a, b in zip(boxes, boxes[1:]) if a <= b]
#     (path / "tracks.json").write_text(json.dumps(runs))
#     score = round(len(runs) / len(boxes), 3)
#     return {"metrics": {"count": len(runs), "score": score}}
# ```
#
# From `model.py`, the one stage that also reads the ledger by
# name:
#
# ```python
# @command(args="game=…", help="train the model on one game's tracks")
# @ledger_fn
# def train(rev, *, game: str, path: Path) -> StageDat:
#     epochs = int(rev["cfg/train", "epochs"])            # traced
#     d = build(rev, {"main": "demo_game.etl.model.fit",
#                     "stage": "model", "game": game,
#                     "epochs": epochs}, path)
#     d.preds["gameset"] = rev[f"game/{game}", "gameset"]  # traced
#     return d
# ```
#
# `fit`, the model's `main`, evaluates `tracks` the same way.
# `@command` only lets a shell type `just train` (ledger-just). The
# config and each game's set, which `train` reads:

# %%
with L.transaction(by="human:dan", why="training", lock=10) as t:
    t["cfg/train"] = {"epochs": "8"}
    for game, gameset in [("G1", "normie"), ("G2", "normie"),
                          ("G3", "pro"), ("G4", "pro")]:
        t[f"game/{game}", "gameset"] = gameset

# %%
rev = L.at()
model_dat = rev.run("demo_game.etl.model.train", game="G1")
print("model:", repr(model_dat), " stage:", model_dat.preds["stage"],
      " gameset:", model_dat.preds["gameset"])    # → model: <StageDat anonymous/Dat_<n>>  stage: model  gameset: normie
for item in sorted(model_dat.dependencies):
    print(item, "->", model_dat.dependencies[item])
# → cfg/train epochs -> 8
#   code -> db/code/<16 hex>
#   eval:demo_game.etl.track.tracks{"game":"G1"}
#       -> ref:demo_game.etl.dat.StageDat:<hash>
#   fn -> demo_game.etl.model.train
#   game/G1 gameset -> normie
#   platform -> darwin-arm64-py3.11

# %% [markdown]
# `train` missed; its `fit` evaluated `tracks`, which evaluated
# `detections` (a hit: sealed above), and each miss sealed its own
# dat. A stage depends on the one below by a nested `run`, never
# by an import and never by a `deps=` list: the run records it.
# The model's dependencies hold its own code (`code`: `model.py` and
# `dat.py`, since the modules a nested run loads are that
# entry's), the two rows it read by name, and the stage below as a
# nested run, held by its result's bytes.

# %%
for game in ("G2", "G3"):
    rev.run("demo_game.etl.model.train", game=game)
print("G1 counts:", L.at().select(("stage", "metrics.count"), kind=StageDat,
                                  game="G1"))
# → G1 counts: [("detect", "40"), ("detect", "40"), ("detect", "40"),
#    ("track", "12"), ("model", "12")]: in no promised order

# %% [markdown]
# G1's dats: three detections (by hand, by the constructor, by the
# stage function), its tracks, its model.

# %% [markdown]
# ### Only what moved is recomputed
#
# A code change: an edit to `track.py` that changes no behaviour.

# %%
rev = L.at()
tracks_dat = rev.run("demo_game.etl.track.tracks",
                      game="G1")                   # a hit
pre_edit_rev = rev
track_path = scratch_project_path / "demo_game/etl/track.py"
track_path.write_text(track_path.read_text()
                      + "\n# tidied: no change in behaviour\n")

# %% [markdown]
# A declared version counts only from a clean checkout. Notice the
# uncommitted edit: the code is named by its commit, marked dirty,
# so no run on it can move the `db/repo/demo-game/demo_game.etl` clock.

# %%
print("track code:", L.at().ns.load("demo_game.etl.track.tracks").code)
# → track code: demo_game.etl@<8 hex>+dirty

# %% [markdown]
# Commit it and re-import.

# %%
git("commit", "-q", "-am", "tidy track")
import demo_game.etl.track
importlib.reload(demo_game.etl.track)    # sandbox workers import anew
rev = L.at()
print("track code:", rev.ns.load("demo_game.etl.track.tracks").code)   # → track code: demo_game.etl@0.1.0
print("detections match:", detections_dat.matches(rev),
      " tracks match:", tracks_dat.matches(rev))   # → detections match: True  tracks match: False
print("model matches:", model_dat.matches(rev))     # → model matches: False, for now

# %% [markdown]
# A sandboxed value's dependencies pin the modules a stage loaded,
# not the repo's commit, so `detections` still matches. `track.py` changed, so the tracks' `code` item moved. The
# model reads as stale too: `matches` never runs a stage (A42), and
# its nested `tracks` item has no entry that holds at this rev yet.

# %%
model_hit_dat = rev.run("demo_game.etl.model.train", game="G1")
retracked_dat = rev.run("demo_game.etl.track.tracks",
                         game="G1")                # a hit
print("new subject:", retracked_dat.subject != tracks_dat.subject)  # → new subject: True
print("same bytes:", retracked_dat.same_as(tracks_dat))     # → same bytes: True
print("same subject:", model_hit_dat.subject == model_dat.subject)   # → same subject: True: a hit
print("model matches:", model_dat.matches(L.at()))             # → model matches: True, now
print("diff:", tracks_dat.diff(retracked_dat))
# → diff: {"code": ("db/code/<a>", "db/code/<b>")}
print("db/version:", L.at()["db/repo/demo-game/demo_game.etl", "db/version"])
# → db/version: 0.1.0: no version moved, so neither did the clock

# %% [markdown]
# Asking for the model re-derived the tracks (their code moved) and
# stopped there: the edit changed no behaviour, the new tracks have
# the same bytes, and the model holds the tracks by their bytes, so
# the model is a hit. A dependency is its bytes, not the entry it
# came from: that is the cutoff.

# %% [markdown]
# ### A consumer that wants proof
#
# G3's model again, a long run done by hand and sealed with
# `v.seal(t)`.

# %%
rev = L.at()
tracks_g3_dat = rev.run("demo_game.etl.track.tracks",
                         game="G3")    # re-derived: track.py moved
fit_spec_record = {"main": "demo_game.etl.model.fit",
                   "stage": "model", "game": "G3", "epochs": 20}
work_path = Path("by-hand/model-G3").resolve()
work_path.mkdir(parents=True)
hand_model_dat = build(rev, fit_spec_record, work_path)
hand_model_dat.preds["gameset"] = "pro"
with L.transaction(by="human:dan", why="a long run by hand") as t:
    hand_model_dat.seal(t, deps=[tracks_g3_dat],
                        provenance="human:dan")
print("deps:", dict(sorted(hand_model_dat.dependencies.items())))
# → deps: {"code/demo-game": "<8 hex>",
#          "platform": "darwin-arm64-py3.11",
#    "ref:demo_game.etl.dat.StageDat:<hash>":
#        "ref:demo_game.etl.dat.StageDat:<hash>"}

# %% [markdown]
# Its dependencies are declared, the `deps` handed over plus the
# environment, not recorded. It is trusted, not proven, and its
# provenance says so. A consumer that needs proof (the fingerprint
# gate) asks for an `eval:` value, and the hand run drops out.

# %%
rev = L.at()
model_refs = rev.refs(kind=StageDat, stage="model", game="G3")
print("models:", len(model_refs))                         # → models: 2
proof_refs = rev.refs(kind=StageDat, stage="model", game="G3",
                      where={"db/provenance": "eval:sandbox"})
print("traced models:", len(proof_refs))                  # → traced models: 1

# %% [markdown]
# ### The game set is a pred

# %%
print("normie models:", rev.refs(kind=StageDat, stage="model", gameset="normie"))
# → normie models: [<Ref anonymous/Dat_<n>>, <Ref …>]: G1 and G2
print("pro scores:", rev.select(("game", "metrics.score"), kind=StageDat,
                                stage="model", gameset="pro"))
# → pro scores: [("G3", "0.958"), ("G3", "0.983")]: the run and the hand run

# %% [markdown]
# `gameset` is read from the game's own row by `train` and set on
# each model, so it is in the dependencies too: moving a game to another
# set makes its model stale (Edge cases § A table over a set). A
# dotted predicate that no row carries and no declaration names is
# a typo; notice the query refuses it rather than finding nothing.

# %%
try:
    rev.values(where={"metrics.scroe": "0.9"})
except Unindexed as e:
    print("Unindexed:", e)           # → Unindexed: metrics.scroe

# %% [markdown]
# ## Releases and old revisions

# %% [markdown]
# ### A release pins every clock

# %%
with L.transaction(by="human:dan", lock=10,
                   why="October release") as t:
    bump(t, "db", "minor",                   # 0.0.0 -> 0.1.0
         confirm=lambda old, new: True)
release_rev = L.at("0.1.0")
print("release rev:", release_rev.id == t.rev.id,
      " version:", release_rev["db", "version"])          # → release rev: True  version: 0.1.0
print("db/version:", release_rev["db/repo/demo-game/demo_game.etl", "db/version"])     # → db/version: 0.1.0
print("epochs:", release_rev["cfg/train", "epochs"])           # → epochs: 8
print("subjects since:", sorted({row.subject
                                 for row in release_rev.history(since=pre_edit_rev)}))
# → subjects since: the re-derived tracks, the hand run, the release,
#   db/repo/demo-game (the clean re-run's db/commit) and their db/tx/<n> subjects

# %% [markdown]
# A release is a bump of `db`'s own `version`: one revision, named
# `0.1.0`, at which every code clock, config row and alias reads
# one way. `L.at("0.1.0")` is that moment by its name.

# %% [markdown]
# ### Running at an old revision
#
# A change after the release: longer training, and the normie
# games retrained.

# %%
with L.transaction(by="human:dan", why="train longer") as t:
    t["cfg/train", "epochs"] = "12"
rev = L.at()
for game in ("G1", "G2"):
    rev.run("demo_game.etl.model.train", game=game)
print("new dats:", len(L.at().refs(kind=StageDat, since=rev)))   # → new dats: 3: two
#   models, and G2's tracks, re-derived since track.py moved

# %% [markdown]
# Two new models and nothing below them, since only `train` read
# `cfg/train`. Asked at the release, then at the head:

# %%
release_rev = L.at("0.1.0")
old_model_dat = release_rev.run("demo_game.etl.model.train",
                                 game="G1")
print("same subject:", old_model_dat.subject == model_dat.subject)  # → same subject: True: 8
now_model_dat = L.at().run("demo_game.etl.model.train",
                            game="G1")
print("same subject:", now_model_dat.subject == old_model_dat.subject)  # → same subject: False
print("diff:", old_model_dat.diff(now_model_dat))
# → diff: {"cfg/train epochs": ("8", "12")}

# %% [markdown]
# The memo lookup is over every entry, at the top, and each
# candidate's dependencies are matched against the revision asked at. At
# `0.1.0` the config said 8 epochs, so the model sealed under that
# binding is the hit, and nothing runs.
#
# G4 was never trained, and `pre_edit_rev`'s `db/repo/demo-game`
# `db/commit` is the first commit while the checkout is at the second. Notice a
# miss there asked with `clean=True` refuses to run.

# %%
try:
    pre_edit_rev.run("demo_game.etl.model.train", game="G4",
                      clean=True)
except NotClean as e:
    print("NotClean:", e)       # → NotClean: … binds db/repo/demo-game

# %% [markdown]
# A revision can be read forever. A sandboxed miss runs at HEAD,
# clean or dirty, and its `code` item records the bytes of every
# module it loaded, which is its identity. `clean=True` is for a
# reader who must say which version ran: the checkout clean and at
# the revision's `db/repo/<repo>` `db/commit`, else `NotClean` (a
# `NotEvaluated`), raised before anything runs.

# %% [markdown]
# ### The latest model for every game in a set

# %%
rev = L.at()
latest_refs = {}
for model_ref in rev.refs(kind=StageDat, stage="model",
                          gameset="normie"):
    game = model_ref.preds["game"]
    if (game not in latest_refs
            or model_ref.sealed_at.id > latest_refs[game].sealed_at.id):
        latest_refs[game] = model_ref
print("latest scores:", {game: model_ref.preds["metrics.score"]
                         for game, model_ref in latest_refs.items()})
# → latest scores: {"G1": "0.95", "G2": "0.922"}: the 12-epoch models

# %% [markdown]
# Nothing is loaded: `Ref.preds` and `Ref.sealed_at` come with the
# rows, so "latest" by revision is a compare of `sealed_at` (A41).
# By `version` it would be a semver compare, since preds are
# strings.

# %% [markdown]
# ## Edge cases

# %% [markdown]
# ### A table over a set
#
# `demo_game.etl.report.scores(rev, *, gameset) -> Value.Table` queries
# the set's models with `values` and returns their scores as a
# parquet `Value.Table`, the shipped tabular `Value`.

# %%
rev = L.at()
scores_table = rev.run("demo_game.etl.report.scores",
                        gameset="normie")
print("table:", repr(scores_table))       # → table: <Table #<8 hex>>
q_items = [k for k in scores_table.dependencies if k.startswith("q:")]
print("query items:", q_items)
# → query items: ['q:{"gameset":"normie","kind":"demo_game.etl.dat.StageDat",
#                  "stage":"model"}']
print("models read:", len(json.loads(scores_table.dependencies[q_items[0]])))   # → models read: 4

# %% [markdown]
# The query inside the function is a dependency item, `q:` and its where
# clause, holding the refs it answered (A41): four models, two per
# normie game. Moving G3 into the set makes G3's model stale, its
# retrain is a fifth normie model, and the table's query now
# answers differently: a miss, not a stale hit.

# %%
with L.transaction(by="human:dan", why="G3 plays normie") as t:
    t["game/G3", "gameset"] = "normie"
rev = L.at()
rev.run("demo_game.etl.model.train", game="G3")  # re-derived
rev = L.at()                                  # after its seal
print("matches:", scores_table.matches(rev))              # → matches: False
rescored_table = rev.run("demo_game.etl.report.scores",
                          gameset="normie")
print("diff:", list(scores_table.diff(rescored_table)))
# → diff: [the q: item, the fifth model's ref: item]: values loads each

# %% [markdown]
# ### The config file is sugar for rows

# %%
print("config:", Path(".datconfig.yaml").read_text())   # → config: ledger: .dat/ledger

# %% [markdown]
# `Ledger(create=True)` wrote it. `Ledger()`, with no path, walks up
# from the cwd to the nearest `.datconfig.yaml` with a `ledger:` key
# and opens the ledger it names; `DAT_LEDGER`, when set, overrides
# the walk, which is how a sandbox worker in a scratch cwd finds its
# parent's ledger (A44). A `mounts:` key is sugar for the mount
# rows this notebook wrote by hand:
#
# ```yaml
# ledger: .dat/ledger
# mounts:
#   demo_game.etl: demo_game/etl
# ```
#
# `Ledger()` asserts the `db/root` and `db/repo` rows when they are
# missing, the repo being the checkout the file sits in.

# %% [markdown]
# ### What the sandbox refuses
#
# `demo_game.etl.stray` holds two functions that reach past the
# mount. The first imports `demo_game.shots`, which is in the repo
# but under no mount.

# %%
try:
    rev.run("demo_game.etl.stray.borrow", game="G1")
except UnmountedImport as e:
    print("UnmountedImport:", e)     # → … demo_game.shots

# %% [markdown]
# The second reads a file outside the mounts, the dats and its
# path folder.

# %%
try:
    rev.run("demo_game.etl.stray.snoop", game="G1")
except UntracedRead as e:
    print("UntracedRead:", e)        # → UntracedRead: /etc/hosts

# %% [markdown]
# Each refusal comes back from the worker with its traceback, and
# nothing is sealed: an incomplete mount table is a crash, never a
# silently wider set of dependencies.
