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
# Written to the ledger design of 2026-10-18 (SVP447 Ledger Module,
# Values ideas 10 and 12, Versions § 4, F447 A39–A44). It runs once
# `ledger2` is rebuilt to that design (T534); until then it is the
# design, not a demo.

# %% [markdown]
# Two questions are still open on F447, and this notebook is
# written to their leans. Q36 (A): a function that produces a dat
# declares `work: Path`, and the eval binds it to a fresh scratch
# folder. Q37 (A): the one `fn` trace item hashes the modules the
# run actually loaded, not the static import closure.

# %%
import json, shutil, sys, tempfile
from pathlib import Path

from dvc_dat.ledger import Ledger, Ref, bump
from dvc_dat.ledger import NotEvaluated, Unindexed
from dvc_dat.ledger import UnmountedImport, UntracedRead
from dvc_dat.ledger import Code, Env, set_env_provider

tmp = Path(tempfile.mkdtemp(prefix="ledger-dats-"))
L = Ledger.create(tmp / "ledger")        # open() never creates
checkout = tmp / "sv-pipe"
shutil.copytree("demo_svp", checkout)
sys.path.insert(0, str(checkout))

def env(version, commit):
    code = Code(version, commit, path=checkout)
    return Env({"sv-pipe": code}, lock="sha256:5e1f",
               platform="darwin-arm64-py3.11")
ENV = {"now": env("0.2.2", "7d742989")}
set_env_provider(lambda module: ENV["now"])

# %% [markdown]
# A notebook runs inside no sv-pipe checkout, so the environment
# provider stands in for one: it says which commit `sv-pipe` is at
# and where its checkout is, which is where a mount's root resolves
# (A40). The stand-in package is copied to a scratch checkout only
# because a later cell edits a stage.

# %% [markdown]
# ## The module: `svp.etl`
#
# The kind and the stages live in `demo_svp/svp/etl/`, one module
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
#     dets = rev.eval("svp.etl.detect.detections", game=game)
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
#     d = build(rev, {"main": "svp.etl.model.fit", "stage": "model",
#                     "game": game, "epochs": epochs}, work)
#     d.preds["gameset"] = rev[f"game/{game}", "gameset"]  # traced
#     return d
# ```

# %%
from svp.etl.dat import StageDat, build

# %% [markdown]
# ## The ledger: games, a config, a mount

# %%
with L.transaction(by="human:dan", why="dats demo") as t:
    t.add("db", "version", "3.1.4")
    t["code/sv-pipe"] = {"version": "0.2.2", "commit": "7d742989"}
    t["code/dvc-dat"] = {"version": "5.0.0", "commit": "a1b2c3d4"}
    t.add("db/mount/svp.etl", "db/root", "svp/etl")
    t.add("db/mount/svp.etl", "db/repo", "sv-pipe")
    t["cfg/train"] = {"epochs": "8"}
    for g, court, gameset in [("G1", "north", "normie"),
                              ("G2", "east", "normie"),
                              ("G3", "south", "pro"),
                              ("G4", "west", "pro")]:
        t[f"game/{g}"] = {"court": court, "gameset": gameset}
rev = L.at()
f = rev.load_fn("svp.etl.track.tracks")
print(f.mode, f.mount)          # sandbox svp.etl
print(f.module)                 # <tmp>/sv-pipe/svp/etl/track.py

# %% [markdown]
# The mount row names its repo, and the provider maps `sv-pipe` to
# the checkout; `db/root` is relative to it. Every `svp.etl` name
# now runs in the sandbox, whose trace pins the code a run loaded
# rather than the whole repo's `code/sv-pipe`.
#
# In a real checkout a file at its root does this setup:
#
# ```yaml
# # .datconfig.yaml
# ledger: /data/ledgers/sv-pipe      # what Ledger.open() finds
# mounts:
#   svp.etl: svp/etl                 # asserted as db/mount rows
# ```
#
# `Ledger.open()` walks up from the cwd to the nearest
# `.datconfig.yaml` with a `ledger:` key; `mounts:` is sugar that
# `open()` asserts as the `db/root` and `db/repo` rows when they are
# missing, the repo being the checkout the file sits in. `DAT_LEDGER`,
# when set, overrides the walk: it is how a sandbox worker in a
# scratch cwd finds its parent's ledger (A44).

# %% [markdown]
# ## The dat constructor

# %%
spec = {"main": "svp.etl.detect.find", "stage": "detect",
        "game": "G1", "bins": 16}
d = rev.eval("svp.etl.dat.dat", spec=spec)
print(dict(sorted(d.preds.items())))
# {"bins": "16", "game": "G1", "metrics.count": "40",
#  "metrics.score": "…", "stage": "detect"}
print(sorted(p.name for p in d.path.iterdir()))
# ["_result_.yaml", "_spec_.yaml", "boxes.json"]
print(L.at()[d.subject, "db/keys"])     # the question, one row
# {"spec": {"bins": 16, "game": "G1",
#           "main": "svp.etl.detect.find", "stage": "detect"}}

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
mods = L.at()[d.trace["fn"], "db/modules"]
print(sorted(mods))      # ["svp/etl/dat.py", "svp/etl/detect.py"]

# %%
det1 = rev.eval("svp.etl.detect.detections", game="G1")
print(det1.same_as(d), det1.subject != d.subject)    # True True
print(Ref(L.at(), det1.subject).preds["metrics.count"])   # 40

# %% [markdown]
# The stage function and the constructor given the same spec make
# the same bytes: two memo entries, two subjects, one blob in the
# art store.

# %% [markdown]
# ## An ETL chain

# %%
rev = L.at()
m1 = rev.eval("svp.etl.model.train", game="G1")
print(m1, m1.preds["stage"], m1.preds["gameset"])
# <8 hex> model normie
for item in sorted(m1.trace):
    print(item, "->", m1.trace[item])
# cfg/train epochs -> 8
# eval:svp.etl.track.tracks{"game":"G1"}
#     -> ref:svp.etl.dat.StageDat:<hash>
# fn -> db/fn/svp.etl.model.train/<hash>
# game/G1 gameset -> normie
# platform -> darwin-arm64-py3.11
# uv.lock -> sha256:5e1f
for g in ("G2", "G3"):
    rev.eval("svp.etl.model.train", game=g)
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
trk3 = rev.eval("svp.etl.track.tracks", game="G3")    # a hit
spec = {"main": "svp.etl.model.fit", "stage": "model",
        "game": "G3", "epochs": 20}
(tmp / "by-hand").mkdir()
mine = build(rev, spec, tmp / "by-hand")
mine.preds["gameset"] = "pro"
with L.transaction(by="human:dan", why="a long run by hand") as t:
    t.add_value(mine, deps=[trk3], provenance="human:dan")
print(dict(sorted(mine.trace.items())))
# {"code/sv-pipe": "0.2.2+7d742989",
#  "platform": "darwin-arm64-py3.11",
#  "ref:svp.etl.dat.StageDat:<hash>": "ref:…StageDat:<hash>",
#  "uv.lock": "sha256:5e1f"}

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
proof = rev.refs(kind=StageDat, stage="model", game="G3",
                 where={"db/provenance": "eval:sandbox"})
print(len(proof))                                              # 1

# %% [markdown]
# ## What the sandbox refuses
#
# `svp.etl.stray` holds two functions that reach past the mount.
# The first imports `svp.shots`, which is in the repo but under no
# mount.

# %%
try:
    rev.eval("svp.etl.stray.borrow", game="G1")
except UnmountedImport as e:
    print("UnmountedImport:", e)

# %% [markdown]
# The second reads a file outside the mounts, the dats and the
# worker's scratch.

# %%
try:
    rev.eval("svp.etl.stray.snoop", game="G1")
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
trk1 = rev.eval("svp.etl.track.tracks", game="G1")    # a hit
pre_bump = rev

track_py = checkout / "svp/etl/track.py"
track_py.write_text(track_py.read_text()
                    + "\n# tidied: no change in behaviour\n")
ENV["now"] = env("0.2.3", "c0ffee12")    # the edit, committed
with L.transaction(by="human:dan", why="tidy track") as t:
    bump(t, "code/sv-pipe")              # 0.2.3, commit c0ffee12
rev = L.at()
print(det1.matches(rev), trk1.matches(rev))     # True False
print(m1.matches(rev))                          # False, for now

# %% [markdown]
# A sandbox trace pins the modules a stage loaded, not the repo's
# version, so the bump alone moves nothing: `detections` still
# matches. `track.py` changed, so the tracks' `fn` item moved. The
# model reads as stale too: `matches` never runs a stage (A42), and
# its nested `tracks` item has no entry that holds at this rev yet.

# %%
m1b = rev.eval("svp.etl.model.train", game="G1")
trk1b = rev.eval("svp.etl.track.tracks", game="G1")   # hit by now
print(trk1b.subject != trk1.subject)    # True: re-derived
print(trk1b.same_as(trk1))              # True: the same bytes
print(m1b.subject == m1.subject)        # True: the model hit
print(m1.matches(L.at()))               # True, now
print(trk1.diff(trk1b))
# {"fn": ("db/fn/svp.etl.track.tracks/<a>",
#         "db/fn/svp.etl.track.tracks/<b>")}

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
rel = L.at("3.2.0")
print(rel.id == t.rev.id, rel["db", "version"])     # True 3.2.0
print(rel["code/sv-pipe", "version"],
      rel["code/dvc-dat", "version"])               # 0.2.3 5.0.0
print(rel["cfg/train", "epochs"])                   # 8
print(sorted({s for s, p, o in rel.all(since=pre_bump)}))

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
    rev.eval("svp.etl.model.train", game=g)
print(len(L.at().refs(kind=StageDat, since=rev)))   # 2

# %% [markdown]
# A change after the release: two new models, one per normie game,
# and nothing below them, since only `train` read `cfg/train`.

# %% [markdown]
# ## A table over the set
#
# `svp.etl.report.scores(rev, *, gameset) -> Table` queries the
# set's models with `values` and returns their scores as a parquet
# `Table`, the shipped tabular `Value`.

# %%
rev = L.at()
s = rev.eval("svp.etl.report.scores", gameset="normie")
print(type(s).__name__)                  # Table
q = [k for k in s.trace if k.startswith("q:")]
print(q)
# ['q:{"gameset":"normie","kind":"svp.etl.dat.StageDat",
#     "stage":"model"}']
print(len(json.loads(s.trace[q[0]])))    # 4: the models it read

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
rev.eval("svp.etl.model.train", game="G3")    # re-derived
print(s.matches(rev))                         # False
print(list(s.diff(rev.eval("svp.etl.report.scores",
                           gameset="normie"))))   # the q: item

# %% [markdown]
# ## The latest model for every game of a set

# %%
rev = L.at()
latest = {}
for r in rev.refs(kind=StageDat, stage="model", gameset="normie"):
    g = r.preds["game"]
    if g not in latest or r.sealed_at.id > latest[g].sealed_at.id:
        latest[g] = r
print({g: r.preds["metrics.score"] for g, r in latest.items()})

# %% [markdown]
# Nothing is loaded: `Ref.preds` and `Ref.sealed_at` come with the
# rows, so "latest" by revision is a compare of `sealed_at` (A41).
# By `version` it would be a semver compare, since preds are
# strings.

# %% [markdown]
# ## Running at an old revision

# %%
old = L.at("3.2.0")
m_old = old.eval("svp.etl.model.train", game="G1")
print(m_old.subject == m1.subject)      # True: the epochs-8 model
m_now = L.at().eval("svp.etl.model.train", game="G1")
print(m_now.subject == m_old.subject)   # False: the epochs-12 one
print(m_old.diff(m_now))
# {"cfg/train epochs": ("8", "12")}

# %% [markdown]
# The memo lookup is over every entry, at the top, and each
# candidate's trace is matched against the revision asked at. At
# `3.2.0` the config said 8 epochs, so the model sealed under that
# binding is the hit, and nothing runs.

# %% [markdown]
# G4 was never trained, and `pre_bump` says `code/sv-pipe` is
# `7d742989` while this environment is `c0ffee12`, so a miss there
# will not run.

# %%
try:
    pre_bump.eval("svp.etl.model.train", game="G4")
except NotEvaluated as e:
    print("NotEvaluated:", e)

# %% [markdown]
# A revision can be read forever; it can be run only by an
# environment whose code matches its `code/<repo>` row. A miss at a
# revision this environment cannot run raises instead of sealing a
# result with false provenance.
