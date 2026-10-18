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
# # Ledger: dats
#
# A `Dat` is a `Value`: a folder, encoded as its content manifest.
# A dat constructor, `dat(spec, …)`, builds one from its spec and
# runs it, and its preds merge spec keys with result metrics under
# one namespace. An ETL pipeline is then a set of value functions
# and nothing else: three stages, each a dat built on the one
# before, re-derived only where its trace moved. A game set is a
# pred, "the latest model for every game of a set" is a query over
# refs, and a release is a bump of the ledger's own version that
# pins every code subject at once.
#
# Written to the ledger design of 2026-10-18 (Ledger Module, Values
# ideas 10 and 12, Versions § 4, F447 A39–A51). It runs once
# `ledger2` is rebuilt to that design (T534); until then it is the
# design, not a demo.

# %% [markdown]
# Two questions are still open on F447, and this notebook is
# written to their leans. Q36 (A): a function that produces a dat
# declares `work: Path`, and the eval binds it to a fresh scratch
# folder. Q37 (A): the one `fn` trace item hashes the modules the
# run actually loaded, not the static import closure.

# %%
import importlib, json, shutil, subprocess, sys
from pathlib import Path

from dvc_dat.ledger import Ledger, Ref, bump
from dvc_dat.ledger import NotEvaluated, Unindexed
from dvc_dat.ledger import UnmountedImport, UntracedRead

scratch_ledger_path = Path("scratch/dats-demo/ledger").resolve()
L = Ledger(scratch_ledger_path, create=True)   # the one explicit act

# %% [markdown]
# ### A real code repository
#
# Every value function runs in a git checkout, the ledger records
# which commit, and the notebook makes a tiny one of its own: the
# `demo_game` package beside this notebook, copied into scratch.
# Discovery finds it from the imported module's folder, and a
# mount's root resolves against it (A40).

# %%
demo_repo_path = Path("scratch/dats-demo/demo-game").resolve()
shutil.copytree("demo_game", demo_repo_path,
                ignore=shutil.ignore_patterns("__pycache__"))


def git(*args: str) -> str:
    """Run git in the demo repository; return its stdout."""
    cmd = ["git", "-c", "user.name=demo",
           "-c", "user.email=demo@example.com", *args]
    done = subprocess.run(cmd, cwd=demo_repo_path, check=True,
                          capture_output=True, text=True)
    return done.stdout.strip()


git("init", "-q")
git("add", ".")
git("commit", "-q", "-m", "demo-game 0.1.0")
commit_sha = git("rev-parse", "HEAD")
sys.path.insert(0, str(demo_repo_path))

# %% [markdown]
# ## The module: `demo_game.etl`
#
# The kind and the stages live in `demo_game/etl/`, one module
# per stage. From `dat.py`, the constructor:
#
# ```python
# def build(rev, spec: dict, work: Path, **kwargs) -> StageDat:
#     """Build a dat from its spec in `work`: the constructor's body."""
#     module, name = spec["main"].rsplit(".", 1)
#     main = getattr(importlib.import_module(module), name)
#     args = {k: v for k, v in spec.items() if k != "main"}
#     result = main(rev, work, **args, **kwargs)
#     (work / "_spec_.yaml").write_text(yaml.safe_dump(spec))
#     (work / "_result_.yaml").write_text(yaml.safe_dump(result))
#     d = StageDat(work)
#     d.preds.update({k: spec[k] for k in SPEC_PREDS if k in spec})
#     for m in METRICS:
#         d.preds[f"metrics.{m}"] = attr(result, f"metrics.{m}")
#     return d
#
#
# @ledger_fn
# def dat(rev, *, spec: dict, work: Path, **kwargs) -> StageDat:
#     """The dat constructor: `spec` the question, `work` the folder."""
#     return build(rev, spec, work, **kwargs)
# ```
#
# `StageDat` is a `Dat` whose `@ledger_class` names its preds: the
# spec keys `game`, `stage`, `bins`, then `gameset` and
# `metrics.count`, `metrics.score`. A stage is a value function
# that builds its dat with its spec fixed, so its key is the game
# alone; its `main` reaches the stage below by a nested `eval`,
# never by an import. From `track.py`:
#
# ```python
# @ledger_fn
# def tracks(rev, *, game: str, work: Path) -> StageDat:
#     return build(rev, {**SPEC, "game": game}, work)
#
#
# def link(rev, work, *, game, **_):
#     dets = rev.eval("demo_game.etl.detect.detections", game=game)
#     boxes = json.loads((dets.path / "boxes.json").read_text())
#     runs = [b for a, b in zip(boxes, boxes[1:]) if a <= b]
#     (work / "tracks.json").write_text(json.dumps(runs))
#     score = round(len(runs) / len(boxes), 3)
#     return {"metrics": {"count": len(runs), "score": score}}
# ```
#
# And from `model.py`, the one stage that reads the ledger by name:
#
# ```python
# @ledger_fn
# def train(rev, *, game: str, work: Path) -> StageDat:
#     epochs = int(rev["cfg/train", "epochs"])            # traced
#     d = build(rev, {"main": "demo_game.etl.model.fit",
#                     "stage": "model", "game": game,
#                     "epochs": epochs}, work)
#     d.preds["gameset"] = rev[f"game/{game}", "gameset"]  # traced
#     return d
# ```

# %%
from demo_game.etl.dat import StageDat, build

# %% [markdown]
# ## The ledger: games, a config, a mount

# %%
with L.transaction(by="human:dan", why="dats demo") as t:
    t.add("db", "version", "3.1.4")
    t["code/demo-game"] = {"version": "0.1.0",
                           "commit": commit_sha}
    t["code/dvc-dat"] = {"version": "5.0.0", "commit": "a1b2c3d4"}
    t.add("db/mount/demo_game.etl", "db/root", "demo_game/etl")
    t.add("db/mount/demo_game.etl", "db/repo", "demo-game")
    t["cfg/train"] = {"epochs": "8"}
    for g, court, gameset in [("G1", "north", "normie"),
                              ("G2", "east", "normie"),
                              ("G3", "south", "pro"),
                              ("G4", "west", "pro")]:
        t[f"game/{g}"] = {"court": court, "gameset": gameset}
rev = L.at()
tracks_fn = rev.load_fn("demo_game.etl.track.tracks")
print(tracks_fn.mode, tracks_fn.mount)  # sandbox demo_game.etl
print(tracks_fn.module)  # <demo_repo_path>/demo_game/etl/track.py

# %% [markdown]
# The mount row names its repo, and discovery finds the `demo-game`
# checkout; `db/root` is relative to it. Every `demo_game.etl` name
# now runs in the sandbox, whose trace pins the code a run loaded
# rather than the whole repo's `code/demo-game`.
#
# In a real checkout a file at its root does this setup:
#
# ```yaml
# ledger: /data/ledgers/demo-game
# mounts:
#   demo_game.etl: demo_game/etl
# ```
#
# That is the whole of `.datconfig.yaml`. `Ledger()`, with no path,
# finds it: it walks up from the cwd to the nearest `.datconfig.yaml`
# with a `ledger:` key and opens the ledger it names. `mounts:` is
# sugar that `Ledger()` asserts as the `db/root` and `db/repo` rows
# when they are missing, the repo being the checkout the file sits
# in. `DAT_LEDGER`, when set, overrides the walk: it is how a sandbox
# worker in a scratch cwd finds its parent's ledger (A44).

# %% [markdown]
# ## The dat constructor

# %%
detect_spec_record = {"main": "demo_game.etl.detect.find",
                      "stage": "detect", "game": "G1", "bins": 16}
spec_dat = rev.eval("demo_game.etl.dat.dat",
                    spec=detect_spec_record)
print(dict(sorted(spec_dat.preds.items())))
# {"bins": "16", "game": "G1", "metrics.count": "40",
#  "metrics.score": "…", "stage": "detect"}
print(sorted(file_path.name for file_path in spec_dat.path.iterdir()))
# ["_result_.yaml", "_spec_.yaml", "boxes.json"]
print(L.at()[spec_dat.subject, "db/keys"])  # the question, one row
# {"spec": {"bins": 16, "game": "G1",
#           "main": "demo_game.etl.detect.find",
#           "stage": "detect"}}

# %% [markdown]
# The spec is the whole question: one key, a JSON object (A38), in
# the one `db/keys` row, numbers kept native. `work` is not a key:
# the eval bound it to a fresh scratch folder, the function built
# the dat there, and the seal moved the folder into the art store
# by its manifest (Q36). The preds are a different thing, the
# handles the value is found by: spec keys and result metrics under
# one namespace, numbers as strings.

# %% [markdown]
# `dat` imports the stage named by the spec's `main` key, at run
# time. Under Q37's lean the `fn` item hashes the modules the run
# loaded, so this entry's code is `dat.py` and `detect.py`: an edit
# to `detect.py` misses it, and a spec naming another stage points
# at another `fn` subject.

# %%
module_paths = L.at()[spec_dat.trace["fn"], "db/modules"]
print(sorted(module_paths))
# ["demo_game/etl/dat.py", "demo_game/etl/detect.py"]

# %%
detections_dat = rev.eval("demo_game.etl.detect.detections",
                          game="G1")
print(detections_dat.same_as(spec_dat),
      detections_dat.subject != spec_dat.subject)   # True True
print(Ref(L.at(), detections_dat.subject).preds["metrics.count"])  # 40

# %% [markdown]
# The stage function and the constructor given the same spec make
# the same bytes: two memo entries, two subjects, one blob in the
# art store.

# %% [markdown]
# ## An ETL chain

# %%
rev = L.at()
model_dat = rev.eval("demo_game.etl.model.train", game="G1")
print(model_dat, model_dat.preds["stage"], model_dat.preds["gameset"])
# <8 hex> model normie
for item in sorted(model_dat.trace):
    print(item, "->", model_dat.trace[item])
# cfg/train epochs -> 8
# eval:demo_game.etl.track.tracks{"game":"G1"}
#     -> ref:demo_game.etl.dat.StageDat:<hash>
# fn -> db/fn/demo_game.etl.model.train/<hash>
# game/G1 gameset -> normie
# platform -> darwin-arm64-py3.11
# uv.lock -> sha256:<hash>
for g in ("G2", "G3"):
    rev.eval("demo_game.etl.model.train", game=g)
print(L.at().select(("stage", "metrics.count"), kind=StageDat,
                    game="G1"))
# two ("detect", "40"), one track, one model: no promised order

# %% [markdown]
# `train` missed; its `fit` evaluated `tracks`, which evaluated
# `detections` (a hit: the stage function sealed it above), and
# each miss sealed its own dat. The model's trace holds its own
# code (`fn`: `model.py` and `dat.py`, since the modules a nested
# eval loads are that entry's), the two rows it read by name, and
# the stage below as a nested eval keyed by its result's bytes.

# %%
rev = L.at()
tracks_g3_dat = rev.eval("demo_game.etl.track.tracks",
                         game="G3")                # a hit
fit_spec_record = {"main": "demo_game.etl.model.fit",
                   "stage": "model", "game": "G3", "epochs": 20}
work_path = Path("scratch/dats-demo/by-hand").resolve()
work_path.mkdir(parents=True, exist_ok=True)
hand_dat = build(rev, fit_spec_record, work_path)
hand_dat.preds["gameset"] = "pro"
with L.transaction(by="human:dan", why="a long run by hand") as t:
    t.add_value(hand_dat, deps=[tracks_g3_dat],
                provenance="human:dan")
print(dict(sorted(hand_dat.trace.items())))
# {"code/demo-game": "0.1.0+<8 hex>",
#  "platform": "darwin-arm64-py3.11",
#  "ref:demo_game.etl.dat.StageDat:<hash>": "ref:…StageDat:<hash>",
#  "uv.lock": "sha256:<hash>"}

# %% [markdown]
# The same stage run by hand and sealed with `add_value`: its trace
# is declared, the `deps` handed over plus the environment, not
# recorded. It is trusted, not proven, and its provenance says so.

# %% [markdown]
# A consumer that needs proof (the fingerprint gate) asks for an
# `eval:` value, and the hand run drops out.

# %%
rev = L.at()
print(len(rev.refs(kind=StageDat, stage="model", game="G3")))  # 2
proof_refs = rev.refs(kind=StageDat, stage="model", game="G3",
                      where={"db/provenance": "eval:sandbox"})
print(len(proof_refs))                                         # 1

# %% [markdown]
# ## What the sandbox refuses
#
# `demo_game.etl.stray` holds two functions that reach past the
# mount. The first imports `demo_game.shots`, which is in the repo
# but under no mount.

# %%
try:
    rev.eval("demo_game.etl.stray.borrow", game="G1")
except UnmountedImport as e:
    print("UnmountedImport:", e)

# %% [markdown]
# The second reads a file outside the mounts, the dats and the
# worker's scratch.

# %%
try:
    rev.eval("demo_game.etl.stray.snoop", game="G1")
except UntracedRead as e:
    print("UntracedRead:", e)         # /etc/hosts

# %% [markdown]
# Each refusal comes back from the worker with its traceback, and
# nothing is sealed: an incomplete mount table is a crash, never a
# silently wider trace.

# %% [markdown]
# ## A code bump re-derives only where the trace moved

# %%
rev = L.at()
tracks_dat = rev.eval("demo_game.etl.track.tracks",
                      game="G1")                   # a hit
pre_bump_rev = rev

track_path = demo_repo_path / "demo_game/etl/track.py"
track_path.write_text(track_path.read_text()
                      + "\n# tidied: no change in behaviour\n")
try:
    with L.transaction(by="human:dan", why="tidy track") as t:
        bump(t, "code/demo-game")
except ValueError as e:
    print("ValueError:", e)       # a dirty checkout: nothing written

# %% [markdown]
# The edit is not committed yet, so there is no commit for `bump`
# to pin. Commit it, re-import, and bump.

# %%
git("commit", "-q", "-am", "tidy track")
commit_sha = git("rev-parse", "HEAD")
import demo_game.etl.track
importlib.reload(demo_game.etl.track)    # sandbox workers import anew
with L.transaction(by="human:dan", why="tidy track") as t:
    bump(t, "code/demo-game")            # 0.1.1, the new commit
rev = L.at()
print(detections_dat.matches(rev),
      tracks_dat.matches(rev))                  # True False
print(model_dat.matches(rev))                   # False, for now

# %% [markdown]
# A sandbox trace pins the modules a stage loaded, not the repo's
# version, so the bump alone moves nothing: `detections` still
# matches. `track.py` changed, so the tracks' `fn` item moved. The
# model reads as stale too: `matches` never runs a stage (A42), and
# its nested `tracks` item has no entry that holds at this rev yet.

# %%
model_hit_dat = rev.eval("demo_game.etl.model.train", game="G1")
retracked_dat = rev.eval("demo_game.etl.track.tracks",
                         game="G1")                # a hit
print(retracked_dat.subject != tracks_dat.subject)  # True: re-derived
print(retracked_dat.same_as(tracks_dat))  # True: the same bytes
print(model_hit_dat.subject == model_dat.subject)  # True: the model hit
print(model_dat.matches(L.at()))        # True, now
print(tracks_dat.diff(retracked_dat))
# {"fn": ("db/fn/demo_game.etl.track.tracks/<a>",
#         "db/fn/demo_game.etl.track.tracks/<b>")}

# %% [markdown]
# Asking for the model re-derived the tracks (their code moved) and
# stopped there: the edit changed no behaviour, the new tracks have
# the same bytes, and the model holds the tracks by their bytes, so
# the model is a hit. A dependency is its bytes, not the entry it
# came from: that is the cutoff.

# %% [markdown]
# ## A game set is a pred

# %%
rev = L.at()
print(rev.refs(kind=StageDat, stage="model", gameset="normie"))
# [<8 hex>, <8 hex>]: G1 and G2
print(rev.select(("game", "metrics.score"), kind=StageDat,
                 stage="model", gameset="pro"))
# ("G3", …) twice: the eval and the hand run

# %% [markdown]
# `gameset` is read from the game's own row by `train` and set on
# each model, so it is in the trace too: moving a game to another
# set makes its model stale (the table below shows it). A dotted
# predicate that no row carries and no declaration names is a
# typo, and says so.

# %%
try:
    rev.values(where={"metrics.scroe": "0.9"})
except Unindexed as e:
    print("Unindexed:", e)

# %% [markdown]
# ## A release pins every code subject

# %%
with L.transaction(by="human:dan", time=True,
                   why="October release") as t:
    bump(t, "db", "minor", confirm=lambda old, new: True)
release_rev = L.at("3.2.0")
print(release_rev.id == t.rev.id,
      release_rev["db", "version"])               # True 3.2.0
print(release_rev["code/demo-game", "version"],
      release_rev["code/dvc-dat", "version"])       # 0.1.1 5.0.0
print(release_rev["cfg/train", "epochs"])           # 8
print(sorted({s for s, p, o
              in release_rev.all(since=pre_bump_rev)}))

# %% [markdown]
# A release is a bump of `db`'s own `version`: one revision, named
# `3.2.0`, at which every code subject, config row and alias reads
# one way. `L.at("3.2.0")` is that moment by its name. The last line
# lists the subjects written since the code bump: the bump, the
# release, the re-derived tracks and their transactions.

# %%
with L.transaction(by="human:dan", why="train longer") as t:
    t["cfg/train", "epochs"] = "12"
rev = L.at()
for g in ("G1", "G2"):
    rev.eval("demo_game.etl.model.train", game=g)
print(len(L.at().refs(kind=StageDat, since=rev)))   # 2

# %% [markdown]
# A change after the release: two new models, one per normie game,
# and nothing below them, since only `train` read `cfg/train`.

# %% [markdown]
# ## A table over the set
#
# `demo_game.etl.report.scores(rev, *, gameset) -> Table` queries
# the set's models with `values` and returns their scores as a parquet
# `Table`, the shipped tabular `Value`.

# %%
rev = L.at()
scores_table = rev.eval("demo_game.etl.report.scores",
                        gameset="normie")
print(type(scores_table).__name__)       # Table
q_items = [k for k in scores_table.trace if k.startswith("q:")]
print(q_items)
# ['q:{"gameset":"normie","kind":"demo_game.etl.dat.StageDat",
#     "stage":"model"}']
print(len(json.loads(scores_table.trace[q_items[0]])))   # 4 models

# %% [markdown]
# The query inside the function is a trace item, `q:` and its where
# clause, holding the refs it answered (A41). Moving G3 into the set
# makes G3's model stale, its retrain is a fifth normie model, and
# the table's query now answers differently: a miss, not a stale
# hit.

# %%
with L.transaction(by="human:dan", why="G3 plays normie") as t:
    t["game/G3", "gameset"] = "normie"
rev = L.at()
rev.eval("demo_game.etl.model.train", game="G3")  # re-derived
print(scores_table.matches(rev))              # False
print(list(scores_table.diff(rev.eval("demo_game.etl.report.scores",
                                      gameset="normie"))))
# the q: item

# %% [markdown]
# ## The latest model for every game of a set

# %%
rev = L.at()
latest_refs = {}
for model_ref in rev.refs(kind=StageDat, stage="model",
                          gameset="normie"):
    g = model_ref.preds["game"]
    if (g not in latest_refs
            or model_ref.sealed_at.id > latest_refs[g].sealed_at.id):
        latest_refs[g] = model_ref
print({g: model_ref.preds["metrics.score"]
       for g, model_ref in latest_refs.items()})

# %% [markdown]
# Nothing is loaded: `Ref.preds` and `Ref.sealed_at` come with the
# rows, so "latest" by revision is a compare of `sealed_at` (A41).
# By `version` it would be a semver compare, since preds are
# strings.

# %% [markdown]
# ## Running at an old revision

# %%
release_rev = L.at("3.2.0")
old_model_dat = release_rev.eval("demo_game.etl.model.train",
                                 game="G1")
print(old_model_dat.subject == model_dat.subject)  # True: epochs 8
now_model_dat = L.at().eval("demo_game.etl.model.train",
                            game="G1")
print(now_model_dat.subject == old_model_dat.subject)  # False: 12
print(old_model_dat.diff(now_model_dat))
# {"cfg/train epochs": ("8", "12")}

# %% [markdown]
# The memo lookup is over every entry, at the top, and each
# candidate's trace is matched against the revision asked at. At
# `3.2.0` the config said 8 epochs, so the model sealed under that
# binding is the hit, and nothing runs.

# %% [markdown]
# G4 was never trained, and `pre_bump_rev` says `code/demo-game`
# is the first commit while the checkout is at the second, so a
# miss there will not run.

# %%
try:
    pre_bump_rev.eval("demo_game.etl.model.train", game="G4")
except NotEvaluated as e:
    print("NotEvaluated:", e)

# %% [markdown]
# A revision can be read forever; it can be run only by an
# environment whose code matches its `code/<repo>` row. A miss at a
# revision this environment cannot run raises instead of sealing a
# result with false provenance.
