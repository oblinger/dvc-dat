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
# A dat constructor, `dat(spec, **kwargs)`, makes one from its spec
# and runs it, and its preds merge spec keys with result metrics
# under one namespace. An ETL pipeline is then a set of value
# functions and nothing else: three stages, each a dat built on the
# one before, re-derived only where its trace moved. A game set is a
# pred, "the latest model for every game of a set" is a `values`
# query, and a release is a bump of the ledger's own version that
# pins every code subject at once.
#
# Written to the ledger design of 2026-10-18 (SVP447 Ledger Module,
# Values ideas 10 and 12, Versions § 4). It runs once `ledger2` is
# rebuilt to that design (T534); until then it is the design, not a
# demo.

# %%
import os, shutil, sys, tempfile
from pathlib import Path

from dvc_dat.ledger import Ledger, ledger_fn, ledger_class, bump, attr
from dvc_dat.ledger import Dat, Ref, NotEvaluated, Unindexed
from dvc_dat.ledger import Code, Env, set_env_provider

work = Path(tempfile.mkdtemp(prefix="ledger-dats-"))
checkout = work / "sv-pipe"              # a stand-in sv-pipe checkout
shutil.copytree("demo_svp", checkout)
sys.path.insert(0, str(checkout))
os.environ["DAT_LEDGER"] = str(work / "ledger")
L = Ledger.open()

def env(version, commit):
    return Env({"sv-pipe": Code(version, commit)},
               lock="sha256:5e1f", platform="darwin-arm64-py3.11")
ENV = {"now": env("0.2.2", "7d742989")}
set_env_provider(lambda module: ENV["now"])

# %% [markdown]
# The stand-in `svp` package is copied into a scratch checkout so
# the notebook can edit a stage later without touching the repo.
# The environment provider says which sv-pipe commit that checkout
# stands at.

# %% [markdown]
# ## The module: `svp.etl`
#
# A `Value` subclass cannot live in a notebook cell (`Ref.type`
# resolves a dotted name, and `__main__` is none), so the cell below
# is the module's text, for reading, and its last lines import the
# real thing: in the real notebook these come from
# `demo_svp/svp/etl/`. One module per stage: `dat.py` (the kind and
# the constructor), `detect.py`, `track.py`, `model.py`; each
# stage's `main` (the plain function its spec names) is omitted.

# %%
# --- svp/etl/dat.py ---------------------------------------------
import importlib, yaml

SPEC_PREDS = ("game", "stage", "bins")
METRICS = ("count", "score")

@ledger_class(preds=SPEC_PREDS + ("gameset",)
              + tuple(f"metrics.{m}" for m in METRICS))
class StageDat(Dat):                     # svp.etl.dat.StageDat
    @property
    def spec(self) -> dict:
        return yaml.safe_load((self.path / "_spec_.yaml").read_text())

def build(rev, spec: dict, **kwargs) -> StageDat:
    module, name = spec["main"].rsplit(".", 1)
    main = getattr(importlib.import_module(module), name)
    folder = Path(tempfile.mkdtemp(prefix=f"{spec['stage']}-"))
    args = {k: v for k, v in spec.items() if k != "main"}
    result = main(rev, folder, **args, **kwargs)
    (folder / "_spec_.yaml").write_text(yaml.safe_dump(spec))
    (folder / "_result_.yaml").write_text(yaml.safe_dump(result))
    d = StageDat(folder)
    d.preds.update({k: spec[k] for k in SPEC_PREDS if k in spec})
    for m in METRICS:
        d.preds[f"metrics.{m}"] = attr(result, f"metrics.{m}")
    return d

@ledger_fn
def dat(rev, *, spec: dict, **kwargs) -> StageDat:
    return build(rev, spec, **kwargs)    # the dat constructor

# --- svp/etl/detect.py, track.py, model.py ----------------------
@ledger_fn
def detections(rev, *, game: str) -> StageDat:
    return build(rev, {"main": "svp.etl.detect.find",
                       "stage": "detect", "game": game, "bins": 16})

@ledger_fn
def tracks(rev, *, game: str) -> StageDat:
    dets = rev.eval("svp.etl.detect.detections", game=game)
    return build(rev, {"main": "svp.etl.track.link",
                       "stage": "track", "game": game}, dets=dets)

@ledger_fn
def train(rev, *, game: str) -> StageDat:
    trk = rev.eval("svp.etl.track.tracks", game=game)
    epochs = int(rev["cfg/train", "epochs"])            # traced
    d = build(rev, {"main": "svp.etl.model.fit",
                    "stage": "model", "game": game},
              tracks=trk, epochs=epochs)
    d.preds["gameset"] = rev[f"game/{game}", "gameset"]  # traced
    return d

from svp.etl.dat import StageDat, build      # the importable ones
import svp.etl.detect, svp.etl.track, svp.etl.model

# %% [markdown]
# `StageDat` is a `Dat` whose `@ledger_class` names its preds: spec
# keys and `metrics.*` side by side, one namespace. `build` is the
# constructor's body; `dat` is the constructor as a value function;
# each stage is a value function that builds its dat with its spec
# fixed, so its key is the game alone. A stage reaches the stage
# below by a nested `eval`, never by an import.

# %% [markdown]
# ## The ledger: games, a config, a mount

# %%
with L.transaction(by="human:dan", why="dats demo") as t:
    t.add("db", "version", "3.1.4")
    t["code/sv-pipe"] = {"version": "0.2.2", "commit": "7d742989"}
    t["code/dvc-dat"] = {"version": "5.0.0", "commit": "a1b2c3d4"}
    t.add("db/mount/svp.etl", "db/root", "svp/etl")
    t["cfg/train"] = {"epochs": "8"}
    for g, court, gameset in [("G1", "north", "normie"),
                              ("G2", "east", "normie"),
                              ("G3", "south", "pro"),
                              ("G4", "west", "pro")]:
        t[f"game/{g}"] = {"court": court, "gameset": gameset}
rev = L.at()
print(rev.load_fn("svp.etl.track.tracks").mode)    # "sandbox"

# %% [markdown]
# The mount row puts `svp.etl` in the sandbox: each `eval` traces
# the exact modules it loaded (through the `fn` item, the `Fn`
# subject) rather than the whole repo's `code/sv-pipe`.

# %% [markdown]
# ## The dat constructor

# %%
spec = {"main": "svp.etl.detect.find", "stage": "detect",
        "game": "G1", "bins": 16}
d = rev.eval("svp.etl.dat.dat", spec=spec)
print(d.preds)
# {"game": "G1", "stage": "detect", "bins": "16",
#  "metrics.count": "40", "metrics.score": "0.47"}
print(sorted(p.name for p in d.path.iterdir()))
# ["_result_.yaml", "_spec_.yaml", "boxes.json"]
print(L.at()[d.subject, "db/keys"])     # the question, one row
# {"spec": {"bins": 16, "game": "G1", "main": "svp.etl.detect.find",
#  "stage": "detect"}}

# %% [markdown]
# The spec is the first argument and the whole question: it is the
# memo key, in the one `db/keys` row, numbers kept native. The preds
# are a different thing, the handles the value is found by: spec
# keys and result metrics under one namespace, numbers as strings.

# %%
det1 = rev.eval("svp.etl.detect.detections", game="G1")
print(det1.same_as(d), det1.subject != d.subject)    # True True
print(Ref(L.at(), det1.subject).preds["metrics.count"])   # "40"

# %% [markdown]
# The stage function and the constructor called with the same spec
# make the same bytes: two memo entries, two subjects, one blob in
# the art store.

# %% [markdown]
# ## An ETL chain

# %%
rev = L.at()
m1 = rev.eval("svp.etl.model.train", game="G1")
print(m1, m1.preds["stage"], m1.preds["gameset"])  # ... model normie
print(m1.trace)
# {"fn": "db/fn/svp.etl.model.train/<hash>",
#  "uv.lock": "sha256:5e1f", "platform": "darwin-arm64-py3.11",
#  'eval:svp.etl.track.tracks{"game":"G1"}':
#      "ref:svp.etl.dat.StageDat:<hash>",
#  "cfg/train epochs": "8", "game/G1 gameset": "normie"}
for g in ("G2", "G3"):
    rev.eval("svp.etl.model.train", game=g)
print(L.at().select(("stage", "metrics.count"), kind=StageDat,
                    game="G1"))
# [("detect", "40"), ("detect", "40"), ("track", ...),
#  ("model", ...)]

# %% [markdown]
# `train` missed, evaluated `tracks`, which evaluated `detections`
# (a hit: the stage function sealed it above), and each miss sealed
# its own dat. The model's trace holds its own code (`fn`), the two
# rows it read by name, and the stage below as a nested eval keyed
# by its result's bytes. Every stage is a `StageDat`, told apart by
# its `stage` pred.

# %%
rev = L.at()
trk3 = rev.eval("svp.etl.track.tracks", game="G3")    # a hit
mine = build(rev, {"main": "svp.etl.model.fit", "stage": "model",
                   "game": "G3"}, tracks=trk3, epochs=20)
mine.preds["gameset"] = "pro"
with L.transaction(by="human:dan", why="a long run by hand") as t:
    t.add_value(mine, deps=[trk3], provenance="human:dan")
print(mine.trace)
# {"ref:svp.etl.dat.StageDat:<hash>": "ref:...StageDat:<hash>",
#  "code/sv-pipe": "0.2.2+7d742989", "uv.lock": "sha256:5e1f",
#  "platform": "darwin-arm64-py3.11"}
print(L.at()[mine.subject, "db/provenance"])          # "human:dan"

# %% [markdown]
# The same stage run by hand and sealed with `add_value`: its trace
# is declared, the `deps` handed over plus the environment, not
# recorded. It is trusted, not proven, and its provenance says so; a
# consumer that needs proof asks for an `eval:` value.

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

# %% [markdown]
# A sandbox trace pins the modules a stage loaded, not the repo's
# version, so the bump alone moves nothing: `detections` still
# matches. `track.py` changed, so the tracks' `fn` item, the hash
# of the code `tracks` resolves to, moved.

# %%
m1b = rev.eval("svp.etl.model.train", game="G1")
trk1b = rev.eval("svp.etl.track.tracks", game="G1")   # hit by now
print(trk1b.subject != trk1.subject)    # True: re-derived
print(trk1b.same_as(trk1))              # True: the same bytes
print(m1b.subject == m1.subject)        # True: the model hit
print(trk1.diff(trk1b))
# {"fn": ("db/fn/svp.etl.track.tracks/<a>",
#         "db/fn/svp.etl.track.tracks/<b>")}

# %% [markdown]
# Asking for the model re-derived the tracks (their code moved) and
# stopped there: the edit changed no behaviour, the new tracks have
# the same bytes, and the model's trace holds the tracks by their
# bytes, so the model is a hit. A dependency is its bytes, not the
# entry it came from: that is the cutoff.

# %% [markdown]
# ## A game set is a pred

# %%
rev = L.at()
print(rev.refs(kind=StageDat, stage="model", gameset="normie"))
# [Ref(<hash>), Ref(<hash>)]: G1 and G2
print(rev.select(("game", "metrics.score"), kind=StageDat,
                 stage="model", gameset="pro"))
# [("G3", ...), ("G3", ...)]: the eval and the hand run
try:
    rev.values(where={"metrics.scroe": "0.9"})
except Unindexed as e:
    print("Unindexed:", e)       # a dotted pred nothing carries

# %% [markdown]
# `gameset` is read from the game's own row by `train` and set on
# each model, so it is in the trace too: moving a game to another
# set makes its model stale. A dotted predicate that no row carries
# and no declaration names is a typo, and says so.

# %% [markdown]
# ## A release pins every code subject

# %%
with L.transaction(by="human:dan", time=True,
                   why="October release") as t:
    bump(t, "db", "minor", confirm=lambda old, new: True)
rel = L.at("3.2.0")
print(rel.id == t.rev.id, rel["db", "version"])     # True 3.2.0
print({s: rel[s, "version"] for s in ("code/sv-pipe", "code/dvc-dat")})
# {"code/sv-pipe": "0.2.3", "code/dvc-dat": "5.0.0"}
print(rel["cfg/train", "epochs"])                  # "8"
print(rel.all(since=pre_bump))     # what moved since the last pin

# %% [markdown]
# A release is a bump of `db`'s own `version`: one revision, named
# `3.2.0`, at which every code subject, config row and alias reads
# one way. `L.at("3.2.0")` is that moment by its name.

# %%
with L.transaction(by="human:dan", why="train longer") as t:
    t["cfg/train", "epochs"] = "12"
rev = L.at()
for g in ("G1", "G2"):
    rev.eval("svp.etl.model.train", game=g)
print(L.at().refs(kind=StageDat, since=rev))
# two new models; tracks and detections all hit

# %% [markdown]
# A change after the release: two more models, one per normie game,
# and nothing below them, since only `train` read `cfg/train`.

# %% [markdown]
# ## The latest model for every game of a set

# %%
rev = L.at()
latest = {}
for m in rev.values(kind=StageDat, stage="model", gameset="normie"):
    g = m.preds["game"]
    if g not in latest or m.rev.id > latest[g].rev.id:
        latest[g] = m
print({g: (m.rev.id, m.preds["metrics.score"])
       for g, m in latest.items()})

# %% [markdown]
# `values` returns every model of the set, loaded; "latest" by
# revision is each value's `rev`, the snapshot it was made under. By
# `version` it would be a semver compare, since preds are strings.

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

# %%
try:
    pre_bump.eval("svp.etl.model.train", game="G4")
except NotEvaluated as e:
    print("NotEvaluated:", e)
# G4 was never trained, and pre_bump's code/sv-pipe is 7d742989;
#   this environment is c0ffee12, so it will not run there

# %% [markdown]
# A revision can be read forever; it can be run only by an
# environment whose code matches its `code/<repo>` row. A miss at a
# revision this environment cannot run raises instead of sealing a
# result with false provenance.
