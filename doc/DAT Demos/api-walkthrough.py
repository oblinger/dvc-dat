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
# > **Plan** — API walkthrough (what this sheet teaches; delete once the sections
# > carry it on their own)
# >
# > The dvc-dat ledger keeps facts, the values computed from them and the
# > folders of data they name, so every result can be found again and
# > traced to what made it. Four parts, each building on the one before:
# >
# > 1. **Triples**: the ledger is a store of facts, each a row
# >    `(rev, subject, predicate, object)`, written in transactions and
# >    read at a revision.
# > 2. **Values**: a value is a Python object stored by its content,
# >    named and found by its preds; a ledger function computes values,
# >    and the ledger remembers each result with what it depended on.
# > 3. **Dats**: a dat is a folder of data made from a spec, a recursive
# >    dict of parameters, by look-up, expansion and instantiation; on a
# >    ledger it is a value, its runs remembered and found by their preds.
# > 4. **The CLI**: a ledger project is worked from a shell with
# >    `just <verb>`, each verb one API call: running, finding, updating,
# >    releasing, and the namespace.
# >
# > Triples and Values share one ledger; Dats and the CLI each work in
# > their own project folder, with its own ledger.

# %% [markdown]
# #### Setup

# %%
import os, shutil, subprocess, sys, textwrap
from importlib.resources import files
from pathlib import Path

from IPython.display import SVG, display

from dvc_dat import Dat
from dvc_dat.ledger import Ledger, Ref, Unlocked, bump

demos_path = Path(globals().get("demos_path", Path.cwd()))   # survives the chdirs into the Dats and CLI projects
os.chdir(demos_path)
scratch_path = demos_path / "scratch/api-walkthrough"
shutil.rmtree(scratch_path, ignore_errors=True)   # a re-run starts clean
for module_name in [m for m in sys.modules
                    if m.split(".")[0] in ("geometry", "plane", "clips", "mymodule", "q_cli_main")]:
    del sys.modules[module_name]                  # the modules the parts write into scratch
sys.path[:] = [p for p in sys.path if not p.startswith(str(scratch_path))]
scratch_path.mkdir(parents=True)

demo_game_path = str(demos_path / "demo_game")
if demo_game_path not in sys.path:
    sys.path.insert(0, demo_game_path)            # the Video class
os.environ["DAT_KEPT"] = str(scratch_path / "kept")   # where v.seal() records local seals
os.environ["PATH"] = f"{Path(sys.executable).parent}:{os.environ['PATH']}"   # `just run` execs this venv's python3
Dat.manager = None                                # the dat world reloads from this folder
git_cmd = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com"]
dats_project_path = scratch_path / "q-dats"       # the Dats project; its folder and pyproject name it q-dats
cli_project_path = scratch_path / "q-cli"         # the CLI project; its folder and pyproject name it q-cli


def show(name):
    """The figure `<name>.svg` beside this notebook."""
    display(SVG(filename=str(demos_path / f"{name}.svg")))


# %% [markdown]
# # Triples
#
# The ledger is a quad store: every fact is a row
# `(rev, subject, predicate, object)`, every write is one
# transaction, and every read is a view of one revision. The quick
# tour: write, fold, one and many, `[]`, the triple reads, then the
# ledger's own settings.

# %% [markdown]
# ## A ledger and a transaction

# %%
L = Ledger(scratch_path / "ledger", create=True)

with L.transaction(by="human:dan", why="season opener") as t:
    t.add("game/G1", "home", "G4")
    t.add("game/G1", "away", "G5")
    t.add("game/G1", "court", "north")
rev1 = t.rev
print("rev1 id, court:", rev1.id, rev1.get("game/G1", "court"))   # 1 north

# %% [markdown]
# `by` is required; `why` and any other keyword are rows on the
# transaction's own subject. The `with` block commits one revision.

# %% [markdown]
# ## A second transaction, and folding
#
# A read folds the rows at or before its revision into the state
# they mean: on an undeclared predicate the latest add wins.

# %%
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "court", "south")
rev2 = t.rev
print("rev2 court:", rev2.get("game/G1", "court"))   # south: the latest add
print("rev1 court:", rev1.get("game/G1", "court"))   # north: rev1 never changes
for r in rev2.history("game/G1", "court"):
    print("row:", r)                   # both rows are still stored
# row:    1 + game/G1              court                    north
# row:    2 + game/G1              court                    south

# %% [markdown]
# ## One and many
#
# A predicate is `one` unless declared `many`. Declare `officials`
# many, then write both kinds in one transaction: the `one`
# predicate replaces, the `many` one accumulates.

# %%
with L.transaction(by="human:dan") as t:
    t.add("db/pred/officials", "db/cardinality", "many")
    t.add("game/G1", "court", "east")       # one: replaces south
    t.add("game/G1", "officials", "kim")    # many: accumulates
    t.add("game/G1", "officials", "ortiz")
rev3 = t.rev
print("rev3 court:", rev3.get("game/G1", "court"))           # east
print("rev3 officials:", rev3.all("game/G1", "officials"))   # ['kim', 'ortiz']
print("rev1 court, officials:", rev1.get("game/G1", "court"),
      rev1.all("game/G1", "officials"))                        # north []: looking back

# %% [markdown]
# The declaration is itself a row, on `db/pred/officials`. Any
# earlier revision still reads as it did: `L.at(n)` is revision `n`.

# %% [markdown]
# ## The `[]` accessor
#
# Two keys assign the triples of one predicate; one key assigns all the triples of one subject.
# Writing mirrors reading, and a record write takes a list for a
# `many` key.

# %%
with L.transaction(by="human:dan", lock=10) as t:      # the record write reads: lock=
    t["game/G1", "court"] = "west"                       # one predicate
    t["game/G2"] = {"home": "G1", "away": "G3",          # all of one subject
                    "officials": ["lee", "park"]}
rev = t.rev
print("court:", rev["game/G1", "court"])   # west
print("game/G2:", rev["game/G2"])
# {'home': 'G1', 'away': 'G3', 'officials': ['lee', 'park']}

# %% [markdown]
# `rev[s, p]` on a `many` predicate raises and names `all`; a
# missing fact is a `KeyError`.

# %% [markdown]
# `t.update(s, {...})` is an `add` per key of the record, on one
# subject: a list under a `many` key adds each element. It reads
# nothing and retracts nothing, so it takes no `lock=`; `db/` keys
# go in as `add` takes them.

# %%
with L.transaction(by="human:dan") as t:        # no lock=: nothing is read
    t.update("game/G2", {"court": "north"})      # one add; the rest stays
print("game/G2:", t.rev["game/G2"])
#   game/G2: {'home': 'G1', 'away': 'G3',
#    'officials': ['lee', 'park'], 'court': 'north'}

# %% [markdown]
# `t["game/G2"] = {"court": "north"}` would instead make the rows
# equal to the dict: it retracts `home`, `away` and `officials`,
# which the dict omits, so it reads first and takes `lock=`.

# %% [markdown]
# ## Reading triple data

# %%
print("score:", rev.get("game/G1", "score", default="tbd"))   # tbd: no raise
print("has home G4:", ("game/G1", "home", "G4") in rev)      # True
print("G1 officials:", rev.all("game/G1", "officials"))      # ['kim', 'ortiz']
print("G2 officials:", rev.all("game/G2", "officials"))      # ['lee', 'park']
print("G2:", rev.all("game/G2"))                             # one position fixed: its (predicate, object) pairs
#   [('home', 'G1'), ('away', 'G3'), ('officials', 'lee'), ('officials', 'park')]
print("courts:", rev.all("game/*", "court"))                 # a glob subject: (subject, object) pairs
#   [('game/G1', 'west')]
for r in rev.history("game/G1", "court"):                       # the unfolded history, removes included
    print("row:", r)
# row:    1 + game/G1              court                    north
# row:    2 + game/G1              court                    south
# row:    3 + game/G1              court                    east
# row:    4 + game/G1              court                    west

# %% [markdown]
# `get` answers a default instead of raising, `in` tests one triple,
# `all` lists what a pattern leaves open: with two positions fixed
# the objects, with one the (predicate, object) pairs, and a glob in
# the subject binds the subject too. `history` is the unfolded history
# of a pattern.

# %% [markdown]
# A read by value is a subject read. `refs(**preds)` is every
# subject holding each given triple. `select(keys, **preds)` is SQL's
# `SELECT keys WHERE preds`: the keywords are the filter, the tuple of
# predicate names is what comes back, one tuple per matching subject.

# %%
print("court=west:", rev.refs(court="west"))                     # [<Ref game/G1>]: which games are on the west court
print("home=G1:", rev.refs(home="G1"))                           # [<Ref game/G2>]: which game has G1 at home
print("west teams:", rev.select(("home", "away"), court="west"))   # [('G4', 'G5')]: game/G1 is the one west-court game; its home and away

# %% [markdown]
# ## Declaring an index

# %%
with L.transaction(by="human:dan") as t:
    t.add("db/pred/home", "db/index", "true")

# %% [markdown]
# An index is storage only: queries on `home` answer the same,
# faster.

# %% [markdown]
# ## Naming a revision
#
# A revision is named by the ledger version set in it, and
# `L.at("M.m.p")` is that revision.

# %%
with L.transaction(by="human:dan", lock=10) as t:      # bump reads: lock=
    db_version = bump(t, "db", "minor", confirm=lambda old, new: True)
print("db version:", db_version)
# db version: 0.1.0
named_rev = L.at("0.1.0")
print("named rev id, court:", named_rev.id, named_rev.get("game/G1", "court"))
# named rev id, court: 7 west

# %% [markdown]
# ## Typing a predicate

# %%
with L.transaction(by="human:dan") as t:
    t.add("db/pred/date", "db/type", "str")
try:
    with L.transaction(by="human:dan") as t:
        t.add("game/G1", "date", {"y": 2026, "m": 10})
except TypeError as e:
    print("TypeError:", e)   # json under a str predicate: not written

# %% [markdown]
# ## Locking the ledger
#
# Locking the ledger lets a transaction depend on the immediately
# preceding revision, so a read-then-write is built on current data
# and no other writer can land between the read and the write.
#
# `bump` advances any version number associated with any subject;
# here it advances a schema's, and the minor part.

# %%
with L.transaction(by="human:dan", lock=10) as t:
    print("schema/tape:",
          bump(t, "schema/tape", "minor", confirm=lambda old, new: True))
# schema/tape: 0.1.0

# %% [markdown]
# `bump` reads the version through `t.previous_rev`, then writes
# the next one; a minor or major bump needs `confirm=`. `lock=10`
# holds the write lock for the whole body; past 10 seconds the body
# is interrupted and nothing is written.
#
# A transaction reads the previous revision and writes the next;
# its own pending writes are not seen until it closes. So a body
# reads with `t[s]`, alters, and writes back. Here one more
# official joins `game/G2`.

# %%
with L.transaction(by="human:dan", lock=10) as t:
    g2 = t["game/G2"]                              # the record as it stands now
    t["game/G2"] = {**g2, "officials": g2["officials"] + ["vance"]}   # one more, written back
print("officials:", t.rev.all("game/G2", "officials"))

# %% [markdown]
# `t[s]` reads `t.previous_rev`, the top as it stands while the
# body holds the write lock. Without `lock=` there is no
# well-defined previous revision; notice the ledger refuses the read.

# %%
try:
    with L.transaction(by="human:dan") as t:       # no lock=
        t["game/G2"]
except Unlocked as e:
    print("Unlocked:", e)

# %% [markdown]
# `bump`, `t[s] = {...}` and `del` read through `t.previous_rev` and
# take `lock=`; `t[s, p] = o`, `t.update` and `t.add` read nothing
# and need none.

# %%
with L.transaction(by="human:dan") as t:           # no lock=: nothing is read
    t["game/G2", "court"] = "east"                 # an add on a one predicate
    t.add("game/G2", "officials", "wu")            # an add on a many predicate
print("game/G2:", t.rev["game/G2"])

# %% [markdown]
# # Values
#
# A value is a Python object stored in the ledger by its content: its
# hash is its subject, and once stored it never changes. The quick
# tour: store and name a value, find it by its preds, compute values
# with ledger functions, and let the ledger remember their results.

# %%
show("q-values")   # black: the parts every value has; gray: an example

# %% [markdown]
# ## Value objects
#
# A value's class is a `Value` subclass in a module (here
# `demo_game/game.py`), saying how the object becomes bytes and back,
# and which preds (searchable string rows) it carries:
#
# ```python
# @ledger_class(preds=("game", "camera", "span"))
# class Video(Value):
#     def __init__(self, frames: bytes):
#         self.frames = frames
#     def encode(self) -> bytes:
#         return self.frames
#     @classmethod
#     def decode(cls, data: bytes, store) -> "Video":
#         return cls(data)
# ```

# %% [markdown]
# ### Storing a value, with its name

# %%
from demo_game.game import Video

# create a new value
video_value = Video(b"G1 wide camera, 9000 frames")
# add preds to the value
video_value.preds.update(game="G1", camera="wide")
# save the value under its name
with L.transaction(by="human:dan") as t:
    video_subject = video_value.seal(t, name="video/G1")

print("video:", repr(video_value))           # → video: <Video video/G1>
print("subject:", video_subject)             # → the sha256 of the content, 64 hex chars

# %% [markdown]
# `seal` stores the value and names it in one step. After the seal
# the value, its preds included, is frozen.

# %% [markdown]
# ### Referring to it: by name or by hash

# %%
rev1 = L.at()
by_name_video = rev1.load("video/G1")
by_hash_video = rev1.load(video_subject)
print("loaded by name:", by_name_video.frames)   # → b'G1 wide camera, 9000 frames'
print("same value by hash:", by_name_video.subject == by_hash_video.subject)   # → True

# %% [markdown]
# ### Assigning preds, and finding values by them
#
# Preds set before the seal are written with it, as rows on the
# value's subject.

# %%
# create a second value, add its preds, save it under its name
g2_video = Video(b"G2 wide camera, 8400 frames")
g2_video.preds.update(game="G2", camera="wide")
with L.transaction(by="human:dan") as t:
    g2_subject = g2_video.seal(t, name="video/G2")

rev2 = L.at()
print("camera=wide:", rev2.values(camera="wide"))           # → [<Video video/G1>, <Video video/G2>]
print("game=G1, camera=wide:", repr(rev2.value(game="G1", camera="wide")))   # → <Video video/G1>
print("every Video:", rev2.refs(kind=Video))                # → [<Ref video/G1>, <Ref video/G2>]

# %% [markdown]
# `values` loads every match, `value` exactly one, `refs` the
# matches unloaded.

# %% [markdown]
# #### Updating a pred
#
# The preds the class declares (`game`, `camera`, `span`) are sealed
# with the value and never change. Any other pred is a row written
# beside it: assigned in one transaction, updated in the next, and
# the finders follow it.

# %%
with L.transaction(by="human:dan") as t:
    t[g2_subject, "status"] = "raw"
rev3 = L.at()
with L.transaction(by="human:dan", why="G2 reviewed") as t:
    t[g2_subject, "status"] = "reviewed"
print("raw, before the update:", rev3.values(status="raw"))        # → [<Video video/G2>]
print("raw, after:", L.at().values(status="raw"))      # → []
print("reviewed, after:", L.at().values(status="reviewed")) # → [<Video video/G2>]

# %% [markdown]
# ### Values are immutable; their names, aliases and preds are not
#
# The bytes behind a hash, and the preds sealed with them, never
# change. A name, an alias or any other pred is a row beside the
# value, and rows can be written any time.

# %% [markdown]
# #### Adding an alias
#
# An alias is a `db/alias` row pointing at the value's subject. Any
# number may point at one value; its name is the alias written
# latest.

# %%
with L.transaction(by="human:dan") as t:
    t.add("raw/G1/wide-camera", "db/alias", video_subject)
camera_ref = Ref(L.at(), "video/G1")
print("aliases:", sorted(camera_ref.aliases))   # → ['raw/G1/wide-camera', 'video/G1']
print("name:", camera_ref.name)              # → raw/G1/wide-camera

# %% [markdown]
# A `Ref` points at a value without fetching its bytes.

# %% [markdown]
# #### Renaming: a new alias, the old one removed

# %%
with L.transaction(by="human:dan") as t:
    t.add("game/G2/baseline", "db/alias", g2_subject)
    t.remove("video/G2", "db/alias", g2_subject)
g2_ref = Ref(L.at(), g2_subject)
print("aliases:", g2_ref.aliases, " name:", g2_ref.name)   # → ['game/G2/baseline'] game/G2/baseline

# %% [markdown]
# #### Adding and changing a pred
#
# A pred the class never declared can be added too.

# %%
with L.transaction(by="human:dan", why="format survey") as t:
    for video_ref in L.at().refs(kind=Video):
        t.add(video_ref.subject, "resolution", "1080p")
with L.transaction(by="human:dan", why="G2 was re-encoded") as t:
    t[g2_subject, "resolution"] = "720p"
print("G1 resolution:", Ref(L.at(), video_subject).preds["resolution"])   # → 1080p
print("G2 resolution:", Ref(L.at(), g2_subject).preds["resolution"])      # → 720p

# %% [markdown]
# ## Ledger functions
#
# A ledger function is a Python function the ledger knows by dotted
# name; it takes the revision first, and its result is sealed as a
# value. It lives in a git repository, so the ledger can record
# exactly which code ran.

# %% [markdown]
# ### Set up repo and code
#
# One git repository, `geometry`, holds both functions used below:
# `geometry.distance` runs in this process; `plane.measure.length`
# runs sandboxed. Each package declares its version, `__version__`.

# %%
# setup: create the repo in a folder, with these source files, and commit them
repo_path = scratch_path / "geometry"
(repo_path / "plane").mkdir(parents=True)
(repo_path / "geometry.py").write_text('''\
import math
from dvc_dat.ledger import ledger_fn

__version__ = "5.3.9"

@ledger_fn
def distance(rev, a, b) -> float:
    return math.dist(a, b)
''')

(repo_path / "plane/__init__.py").write_text('''\
__version__ = "2.7.1"
''')

(repo_path / "plane/measure.py").write_text('''\
import math
from dvc_dat.ledger import ledger_fn

@ledger_fn
def length(rev, a, b) -> float:
    return math.dist(a, b) * 0.5     # metres per unit
''')

git_cmd = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com"]
subprocess.run(git_cmd + ["init", "-q"], cwd=repo_path, check=True)
subprocess.run(git_cmd + ["add", "."], cwd=repo_path, check=True)
subprocess.run(git_cmd + ["commit", "-q", "-m", "geometry and plane"], cwd=repo_path, check=True)

sys.path.insert(0, str(repo_path))

# %% [markdown]
# ### The ledger namespace

# %%
show("q-values-ns")

# %% [markdown]
# The ledger namespace, `ns`, is the bridge between the ledger and
# Python: Python's namespace, modules, functions and objects by dotted
# name, on the ledger, so every name has a history of revisions tied
# to the git commit history of its code. `rev.ns` is the namespace at
# a revision; `t.ns` is the namespace at a transaction, reading the
# revision before it.
#
# `ns.load(name)` is the object a dotted name denotes.
# `ns.name_of(obj)` is the dotted name `load` takes back to an object.
# `t.ns.mount(at, root=, repo=)` writes the two `db/mount/<at>` rows
# that put a repo's folder under a name; a transaction's `ns` is the
# one that mounts. `ns.mounts()` is the mount table at that revision.

# %%
ns = L.at().ns
dist_fn = ns.load("math.dist")
print("loaded:", dist_fn)                   # → loaded: <built-in function dist>
print("its name:", ns.name_of(dist_fn))     # → its name: math.dist
with L.transaction(by="human:dan") as t:
    t.ns.mount("plane", root="plane", repo="geometry")
print("mounts:", L.at().ns.mounts())
# → mounts: {'plane': {'root': 'plane', 'repo': 'geometry'}}

# %% [markdown]
# ### Accessing and using Python functions

# %%
distance_fn = L.at().ns.load("geometry.distance")
print("fn:", repr(distance_fn), " code:", repr(distance_fn.code))
# → fn: <Fn geometry.distance@5.3.9>  code: <Code geometry@5.3.9>
hypotenuse_value = distance_fn(a=(0, 0), b=(3, 4))
print("result:", hypotenuse_value.obj, " sealed at:", hypotenuse_value.sealed)
# → result: 5.0  sealed at: <the seal's moment>
print("db/repo/geometry/geometry:", L.at()["db/repo/geometry/geometry"])
# → db/repo/geometry/geometry: {'db/version': '5.3.9'}
print("db/repo/geometry:", L.at()["db/repo/geometry"])
# → db/repo/geometry: {'db/commit': '<the commit>'}

# %% [markdown]
# `L.at().ns.load(name)` is what a dotted name denotes on the ledger;
# for a function, an `Fn`. Calling it runs it and seals the
# plain `float` it returns as a value (`.obj` unboxes it). A
# function's repr is `<Fn name@version>`; `code` is the code it
# is loaded from, the package `geometry` at the version it declares.
#
# A repo is one git checkout and has one commit; it can hold several
# packages, each with its own `__version__`. So the commit is a
# `db/commit` row on `db/repo/<repo>` and each package's version a
# `db/version` row on `db/repo/<repo>/<package>`; the ledger writes
# both, so both predicates carry `db/`. Here the repo `geometry` holds the
# packages `geometry` and `plane`, which is why `geometry` appears
# twice. This first clean run wrote both rows.

# %% [markdown]
# ### Sandboxed functions
#
# A sandboxed function runs isolated, seeing only its mounted source
# folder: here `plane`, mounted above. Its version is the mounted
# package's `__version__`, read after importing it; the checksum of
# the files it loaded (`sha`) is its identity.

# %%
length_fn = L.at().ns.load("plane.measure.length")
segment_value = length_fn(a=(0, 0), b=(3, 4))
print("fn:", repr(length_fn), " code:", repr(length_fn.code), " sandboxed:", length_fn.code.sandboxed)
# → fn: <Fn plane.measure.length@2.7.1>  code: <Code plane@2.7.1>  sandboxed: True
print("result:", segment_value.obj)                 # → result: 2.5
print("geometry db/version:", L.at()["db/repo/geometry/geometry", "db/version"])   # → geometry db/version: 5.3.9
print("plane db/version:", L.at()["db/repo/geometry/plane", "db/version"])         # → plane db/version: 2.7.1

# %% [markdown]
# `geometry` and `plane` share one checkout, the repo `geometry`, and each package keeps its own version clock, written by its first clean run.

# %% [markdown]
# #### A sandbox is a snapshot of the code
#
# Loading a sandboxed function takes a snapshot of the code it runs;
# `code` is that snapshot, the sandbox: `modules` are the files in
# it, `version` the name the package gives it. The function is looked
# up by name inside it, and the version it shows is the snapshot's.
# Only the snapshot has identity, `subject` `db/code/<16 hex>`; a
# result names it and the function in it apart, as `code` and `fn`,
# and the snapshot records every module the run loaded
# (`plane/__init__.py` too).

# %%
sandbox = length_fn.code
print("sandbox:", repr(sandbox), " version:", sandbox.version, " modules:", sandbox.modules)
# → sandbox: <Code plane@2.7.1>  version: 2.7.1  modules: ['plane/__init__.py', 'plane/measure.py']
print("result's code:", segment_value.dependencies["code"], " is the sandbox:",
      segment_value.dependencies["code"] == sandbox.subject)
# → result's code: db/code/04ebdaea96da6a7b  is the sandbox: True
print("result's fn:", segment_value.dependencies["fn"])
# → result's fn: plane.measure.length

# %% [markdown]
# Change the code, and bump the version with it, and the snapshot is
# a new one. The old result still names the snapshot that made it.

# %%
measure_path = repo_path / "plane/measure.py"
measure_path.write_text(measure_path.read_text().replace("* 0.5 ", "* 0.25"))
(repo_path / "plane/__init__.py").write_text('__version__ = "2.7.2"\n')
subprocess.run(git_cmd + ["commit", "-q", "-am", "quarter metres"], cwd=repo_path, check=True)
new_length_fn = L.at().ns.load("plane.measure.length")
print("new fn:", repr(new_length_fn), " sandbox:", repr(new_length_fn.code))
# → new fn: <Fn plane.measure.length@2.7.2>  sandbox: <Code plane@2.7.2>
print("new result:", new_length_fn(a=(0, 0), b=(3, 4)).obj)    # → new result: 1.25
print("old result's code:", segment_value.dependencies["code"], " fn:", segment_value.dependencies["fn"],
      " holds:", segment_value.obj)
# → old result's code: db/code/04ebdaea96da6a7b  fn: plane.measure.length  holds: 2.5

# %% [markdown]
# ## Ledger evaluation
#
# `rev.run(name, **keys)` is a lookup and a call, traced: the result
# records what it depended on, and is remembered, so asking again is
# answered from the ledger.

# %%
far_value = L.at().run("geometry.distance", a=(0, 0), b=(6, 8))
print("result:", far_value.obj)                       # → 10.0
top_id = L.at().id

again_value = L.at().run("geometry.distance", a=(0, 0), b=(6, 8))
print("same value:", again_value.subject == far_value.subject, " nothing written:",
      L.at().id == top_id)                 # → True True: a hit, nothing written

# %% [markdown]
# ### Splitting the run method into discrete actions
#
# `run` is three separable steps: load the function, run it with its
# provenance captured, put the result on the ledger. `seal=False`
# stops after the second, so the result can be looked at first;
# `.seal(t)` is the third. Nothing runs twice.

# %%
distance_fn = L.at().ns.load("geometry.distance")                   # (1) load the function
print("fn:", repr(distance_fn))                                     # → fn: <Fn geometry.distance@5.3.9>
draft_value = distance_fn(a=(0, 0), b=(9, 12), seal=False)          # (2) run it, provenance captured, nothing kept
print("draft:", draft_value.obj, " sealed:", draft_value.sealed)    # → 15.0 None
with L.transaction(by="human:dan", why="keep it") as t:             # (3) put it on the ledger
    draft_value.seal(t)
kept_value = L.at().run("geometry.distance", a=(0, 0), b=(9, 12))   # the same call: a hit
print("hit:", kept_value.subject == draft_value.subject)            # → True: nothing ran

# %% [markdown]
# `seal=` says how far a call goes: `"get"` only looks, `False` runs
# and keeps nothing, `True` also seals the result on this machine, a
# ledger or a transaction saves it there. Left out, it saves to the
# function's own ledger, as `run` does.

# %% [markdown]
# ## Provenance
#
# A value a ledger function returns records what it depended on: the
# function at its version, the code's commit, the platform, and every
# name and value it read. That record is its provenance.

# %% [markdown]
# ### When a name is pointed to a new value, a result goes stale
#
# A result records every name it read and the value it pointed at.
# Seal a new video under the same name and the name is pointed to
# it; the old result no longer matches the ledger, so `run`
# recomputes.

# %%
(repo_path / "clips.py").write_text('''\
from dvc_dat.ledger import ledger_fn
from demo_game.game import Video

@ledger_fn
def clip(rev, *, video: str, start: int, end: int) -> Video:
    return Video(rev.load(video).frames[start:end])
''')

subprocess.run(git_cmd + ["add", "."], cwd=repo_path, check=True)
subprocess.run(git_cmd + ["commit", "-q", "-m", "clips"], cwd=repo_path, check=True)

# Computing a Value on the Ledger
opening_clip = L.at().run("clips.clip", video="video/G1", start=0, end=8)
print("opening clip:", opening_clip.frames)                 # → b'G1 wide '

retake_video = Video(b"G1 retake, 9100 frames")
retake_video.preds.update(game="G1", camera="wide")
with L.transaction(by="human:dan", why="the retake") as t:
    retake_video.seal(t, name="video/G1")   # video/G1 is pointed to the retake
rev4 = L.at()
print("opening clip still holds:", opening_clip.matches(rev4))          # → False: video/G1 points to the retake
retake_clip = rev4.run("clips.clip", video="video/G1", start=0, end=8)
print("retake clip:", retake_clip.frames)                  # → b'G1 retak'
print("first video, by hash:", rev4.load(video_subject).frames)     # → b'G1 wide camera, 9000 frames'

# %% [markdown]
# A value never changes; a name is pointed to a progression of new
# values. The old video and the old clip stay, found by their hashes.

# %% [markdown]
# ### What a result depends on

# %%
for dep_key, dep_value in sorted(retake_clip.dependencies.items()):
    print(f"{dep_key[:28]:30}= {dep_value[:56]}")

# %% [markdown]
# - `code/geometry`: the commit of the repo `geometry` the function
#   ran at.
# - `code`: the snapshot of the code the function ran from, by its
#   subject; here the package `clips` at its version, as for the
#   sandbox above.
# - `fn`: the function's dotted name inside that snapshot.
# - `platform`: the operating system, CPU and Python version it ran
#   on, a tag, not a file.
# - `ref:…`: the video bytes it loaded.
# - `video/G1 db/alias`: the value the name `video/G1` pointed at.
#
# That last row is how `matches` knew the opening clip was stale: it
# names the first video, and the name now points to the retake.

# %%
first_hash = rev4.load(video_subject).hash
print("opening clip read the first video:", opening_clip.dependencies["video/G1 db/alias"].endswith(first_hash))   # → True: the first video
print("retake clip read the retake:", retake_clip.dependencies["video/G1 db/alias"].endswith(retake_video.hash))   # → True: the retake

# %% [markdown]
# ### Sealing a value by hand
#
# Sealing fixes a value: its bytes' hash and its preds, so it can be
# checked but not changed. Saving puts the sealed value on the
# ledger's timeline. `v.seal(t)` does both at once; here they are
# apart.

# %%
highlight_video = Video(b"G1 highlights, 600 frames")                 # 1. make a value
highlight_video.preds.update(game="G1", camera="wide")

print("sealed, hash:", highlight_video.seal()[:12])                   # 2. seal it, on this machine only
print("sealed at:", highlight_video.sealed)                           # → <the seal's moment>
try:
    highlight_video.preds["camera"] = "baseline"
except Exception as error:
    print("change refused:", type(error).__name__, error)             # → TypeError cannot modify a sealed value's preds
print("G1 videos on the ledger:", L.at().values(game="G1"))           # not on the timeline yet

with L.transaction(by="human:dan", why="keep the highlights") as t:   # 3. keep it
    highlight_video.seal(t, name="video/G1/highlights")
print("G1 videos on the ledger:", L.at().values(game="G1"))           # now it is

# %% [markdown]
# # Dats
#
# A dat is a handle for a folder of arbitrary data, derived from and
# specified by a recursive dictionary of parameters: its spec. On a
# ledger it is also a value: sealed, loaded, memoized, found.

# %%
show("q-dats")

# %% [markdown]
# #### Project setup
#
# The Dats part works in its own project, a git checkout named `q-dats` whose `.datconfig.yaml` makes it a plain dat project, its dats in `data/`; `mymodule` holds a run function and two template specs.

# %%
dats_project_path.mkdir(parents=True)
os.chdir(dats_project_path)
Path(".gitignore").write_text(".dat/\ndata/\n")
Path("pyproject.toml").write_text('[project]\nname = "q-dats"\nversion = "0.1.0"\n')
for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "q-dats"]):
    subprocess.run(git_cmd + args, check=True)
sys.path.insert(0, str(dats_project_path))
Path(".datconfig.yaml").write_text("dat_folders: data\n")   # a plain dat project: its dats live in data/
Dat.manager = None                   # the dat world reloads from this folder

# %%
# the files: a run function in mult.py, two template specs in specs/
module_path = Path("mymodule")
(module_path / "specs").mkdir(parents=True)
(module_path / "__init__.py").write_text('__version__ = "0.1.0"\n')   # the code's version, in its source
(module_path / "mult.py").write_text('''\
import csv
from pathlib import Path


def write_table(folder, n=10, start=1):
    """`table.csv`, the n x n multiplication table from `start`; its cell count."""
    numbers = range(start, start + n)
    with open(Path(folder, "table.csv"), "w", newline="") as f:
        csv.writer(f).writerows([[a * b for b in numbers] for a in numbers])
    return n * n


def build_table(dat, n=10, start=1):
    """The run function: `Dat.manager.run` calls it with the new dat and the spec's kwargs."""
    cells = write_table(dat.get_path(), n, start)
    Path(dat.get_path(), "log.txt").write_text(f"{n} x {n} from {start}\\n")
    dat.get_results()["cells"] = cells
    dat.save()
    return dat
''')
(module_path / "specs/table_base.yaml").write_text('''\
dat:
  kwargs: {start: 1}
notes: shared defaults
''')
(module_path / "specs/table12.yaml").write_text('''\
dat:
  base: mymodule.specs.table_base
  name: tables/{YYYY}/table12{unique}
  do: mymodule.mult.build_table
  kwargs: {n: 12}
''')
subprocess.run(git_cmd + ["add", "mymodule"], check=True)
subprocess.run(git_cmd + ["commit", "-q", "-m", "mymodule"], check=True)
Dat.ns.mount(folder="mymodule", at="mymodule")   # mymodule's files join the dat world's namespace:
# mymodule/specs/table12.yaml answers to mymodule.specs.table12, build_table in mult.py to mymodule.mult.build_table



# %% [markdown]
# A spec's `dat:` part is what the dat system reads: `do:` names the
# run function, `kwargs:` its arguments, `base:` a spec to inherit,
# `name:` a folder template; above, `table12` inherits `table_base`.

# %% [markdown]
# ## Dat creation
#
# A dat is created in three steps:
#
# 1. **Look up** its spec by name: `Dat.ns.load(name)` is the object
#    a dotted name names, here the spec file's dict as written.
# 2. **Expand** it: `Dat.manager.expand_spec(spec)` merges the spec
#    over its `dat.base`, which it drops, then fills every template
#    variable `{}`; `{YYYY}` is the year, `{unique}` empty.
# 3. **Instantiate** it: `Dat.create(spec=expanded_spec)` is the Dat
#    object, its folder made and `_spec_.yaml` written. Nothing runs.

# %%
spec = Dat.ns.load("mymodule.specs.table12")    # 1. the spec as written
expanded_spec = Dat.manager.expand_spec(spec)   # 2. dat.base merged in, every {…} filled
table12_dat = Dat.create(spec=expanded_spec)    # 3. the Dat and its folder

# %%
# print results
table12_path = Path(table12_dat.get_path())
print("SPEC:    ", spec)
print("EXPANDED:", expanded_spec)   # base: gone, kwargs gains start, notes appears, name: filled
print("DAT:     ", repr(table12_dat))
print("FILES:   ", sorted(os.listdir(table12_path)))
print("_SPEC_.YAML:\n" + textwrap.indent((table12_path / "_spec_.yaml").read_text(), "    "))
# _spec_.yaml: the expanded spec, plus kind: dvc_dat.core.Dat

# %% [markdown]
# ## `Dat.create`, the three steps in one call
#
# `Dat.create(spec=name)` is the shorthand: it looks the spec up,
# expands it (base merged, `{}` filled) and instantiates the dat.
# Nothing runs.

# %%
shorthand_dat = Dat.create(spec="mymodule.specs.table12")   # steps 1-3

# %%
# print results
shorthand_path = Path(shorthand_dat.get_path())
print("DAT:", repr(shorthand_dat))
print("MANUAL _SPEC_.YAML:\n" + textwrap.indent((table12_path / "_spec_.yaml").read_text(), "    "))
print("SHORTHAND _SPEC_.YAML:\n" + textwrap.indent((shorthand_path / "_spec_.yaml").read_text(), "    "))
# the same kwargs, do, kind and notes; name: tables/2026/table12 by hand, tables/{YYYY}/table12{unique} in the shorthand

# %% [markdown]
# One difference, in `name:`. The shorthand expands `{}` after it
# places the folder, with the placement's own `{YYYY}` and `{unique}`:
# `table12` is taken, so `{unique}` counts up to `_2`, and
# `_spec_.yaml` keeps `name:` as the template. By hand,
# `expand_spec` sees no folder, so `{unique}` is always empty and
# `name:` is filled once; were `tables/2026/table12` taken, step 3
# would raise `FileExistsError` instead of counting up.

# %% [markdown]
# ## Running a dat
#
# `Dat.manager.run(dat)` is the one way to run a dat: it calls the
# spec's run function with the dat and the spec's kwargs, in place,
# and records the run in `dat.run`. `save()` in the run function
# seals the folder, its results in `_result_.yaml`.
# The cell runs once: a sealed dat refuses a second run, which
# `RuntimeError: ... is sealed` reports.

# %%
Dat.manager.run(table12_dat)   # calls build_table in mult.py with this dat and n=12, start=1

# %%
# print results
print("FILES:", sorted(os.listdir(table12_path)))
print("CELLS:", table12_dat.get_results()["cells"])
print("TABLE.CSV:\n" + textwrap.indent("\n".join((table12_path / "table.csv").read_text().splitlines()[:3]), "    "))
print("_RESULT_.YAML:\n" + textwrap.indent((table12_path / "_result_.yaml").read_text(), "    "))

# %% [markdown]
# `dat.run` is the run's record, a sub-dat in the dat's `run/`
# folder: when and where it ran, on which commit, how long it took
# and the hash it sealed. It is outside the dat's own hash.

# %%
run_results = table12_dat.run.get_results()["dat"]
print("run:", repr(table12_dat.run))   # run: <Dat: tables/2026/table12/run>
print("run_at:", run_results["run_at"])   # run_at: when the run started
print("run_time:", run_results["run_time"])   # run_time: how long build_table took
print("code:", run_results["code"])   # code: the branch, commit and dirty flag of the checkout holding mult.py

# %% [markdown]
# Given a name, `Dat.manager.run` creates the dat from the spec
# first: it returns what the run function returned, a new folder
# every call.

# %%
again_dat = Dat.manager.run("mymodule.specs.table12")   # same as: Dat.manager.run(Dat.create(spec="mymodule.specs.table12"))
print("dat:", repr(again_dat))   # dat: <Dat: tables/2026/table12_3>
print("files:", sorted(os.listdir(again_dat.get_path())))
# files: ['_result_.yaml', '_spec_.yaml', 'log.txt', 'run', 'table.csv']

# %% [markdown]
# ## Running and storing a dat on the ledger
#
# A ledger remembers: a run is a memo entry, found again rather than
# rerun; a dat is a value, sealed under a name and loaded back; dats
# are found by their preds.
#
# `Ledger(create=True)` makes the ledger in this folder and adds
# `ledger:` to `.datconfig.yaml`; the reloaded dat world names
# through it. In a ledger project names come from the ledger's
# mounts alone and `Dat.ns.mount` is refused, so `mymodule` is
# mounted with `t.ns.mount`, which writes two `db/mount` rows; the
# earlier mount went with the old world.
#
# #### Setup

# %%
L = Ledger(create=True)              # .dat/ledger, and ledger: in .datconfig.yaml
Dat.manager = None                   # the dat world reloads, its namespace the ledger's
print(".datconfig.yaml:", Path(".datconfig.yaml").read_text().splitlines())
# → .datconfig.yaml: ['dat_folders: data', 'ledger: .dat/ledger']
import mymodule                      # discovery finds the checkout, the repo q-dats
with L.transaction(by="human:dan", why="mount mymodule") as t:
    t.ns.mount("mymodule", root="mymodule")   # the two db/mount rows: the folder, and the repo, by default this project's, q-dats
try:
    Dat.ns.mount(folder="mymodule", at="mymodule")
except TypeError as e:
    print("refused:", str(e).split(" (")[0])
# → refused: a ledger project names things through its db/mount rows

# %% [markdown]
# ### Ledger run
#
# `L.at().run(name)` is a run remembered on the ledger: the result
# found if this code computed it before, else run and sealed as the
# memo entry. One call creates the dat in the three steps, runs it,
# and remembers it.

# %%
table12_value = L.at().run("mymodule.specs.table12")
print("ran:", repr(table12_value))   # ran: <Dat tables/2026/table12>: the spec's template, filled in the ledger's data folder

# %% [markdown]
# #### What the run did, piece by piece
#
# The run took the three creation steps, through the ledger's
# mounts: `Dat.ns.load` read the spec off the mounted file, never
# imported; `expand_spec` merged its base and filled its `{}`. The
# expanded spec, `dat.name` removed and `dat.kind` set, is the memo
# key, stored as the value's `db/keys`.

# %%
# print results
print("SPEC:    ", Dat.ns.load("mymodule.specs.table12"))
print("EXPANDED:", Dat.manager.expand_spec(Dat.ns.load("mymodule.specs.table12")))
print("DB/KEYS: ", L.at()[table12_value.subject, "db/keys"])   # the memo key

# %% [markdown]
# The run function loads as an `Fn`, a ledger function: kind `dat`
# (undecorated, run through a spec), sandboxed because it is
# mounted. It ran in a sandboxed worker, its code the mounted files
# it loaded; `db/fn` names it, and the first clean run wrote the
# package's version clock, `db/repo/q-dats/mymodule` `db/version`.

# %%
# print results
run_fn = Dat.ns.load("mymodule.mult.build_table")
print("FN:         ", repr(run_fn), " kind:", run_fn.kind, " sandboxed:", run_fn.code.sandboxed)
print("DB/FN:      ", L.at()[table12_value.subject, "db/fn"])
print("DB/VERSION: ", L.at()["db/repo/q-dats/mymodule", "db/version"])   # db/repo/q-dats/mymodule

# %% [markdown]
# The same spec asked again is a memo hit: nothing runs, nothing is
# written.

# %%
top_id = L.at().id
again_value = L.at().run("mymodule.specs.table12")
print("hit:", again_value.subject == table12_value.subject,
      " nothing written:", L.at().id == top_id)   # hit: True  nothing written: True

# %% [markdown]
# ### Storing a handmade dat on the ledger
#
# On a ledger a dat is a value: sealed under a name, loaded back,
# found by its preds. The hand-made `table12_dat` is sealed here; nothing
# runs. Its preds are its spec's `kwargs` and its result's entries,
# read from the folder.

# %%
with L.transaction(by="human:dan") as t:
    table12_dat.seal(t, name="table/12")   # the folder's files go to the art store; the row names the kind, dvc_dat.core.Dat
print("dat:", repr(table12_dat), " sealed:", table12_dat.sealed)   # dat: <Dat table/12>  sealed: <the seal's moment>

loaded_dat = L.at().load("table/12")       # the folder rebuilt from the store; nothing runs
print("files:", sorted(os.listdir(loaded_dat.get_path())))
# files: ['_result_.yaml', '_spec_.yaml', 'log.txt', 'run', 'table.csv']
print("cells:", loaded_dat.get_results()["cells"])   # cells: 144
print("preds:", dict(sorted(loaded_dat.preds.items())))
# preds: {'cells': '144', 'n': '12', 'start': '1'}

# %% [markdown]
# Sealing sent the files to the art store by their hashes; the
# manifest naming them is the value's bytes. `load` rebuilds the
# folder from the store, a view in the ledger's data folder; it does
# not run anything.

# %% [markdown]
# ### Finding dats
#
# A dat on the ledger is found by its preds: its spec's kwargs and
# its results. `values(kind=Dat, **preds)` is every dat whose preds
# equal the given ones; `value(...)` the one dat, an error on none
# or several; `select(keys, ...)` the matches as tuples of the
# named preds. First, two more runs, n=5 and n=9, to find among.

# %%
for n in (5, 9):
    L.at().run("mymodule.specs.table12", n=n)   # kwargs update the spec's dat.kwargs, as with Dat.manager.run

# %%
# print results
print("ALL:     ", L.at().values(kind=Dat))
print("N=12:    ", L.at().values(kind=Dat, n=12))       # the run and the handmade table/12
print("CELLS=81:", repr(L.at().value(kind=Dat, cells=81)))   # exactly one: the n=9 run
print("N, CELLS:", L.at().select(("n", "cells"), kind=Dat))   # every dat, two preds each
print("N=5:     ", L.at().select(("cells",), kind=Dat, n=5))   # one pred of the n=5 dat

# %% [markdown]
# # The CLI
#
# A project's `justfile` imports dvc-dat's `run` and its ledger
# verbs. Each verb is syntactic sugar for one API call, shown beside
# every command below as `# same as:`, so a shell line and a Python
# line are the same call. `just --list` is the menu; `[run]` holds
# the commands the project's code declares.

# %% [markdown]
# #### Project setup
#
# The CLI part works in its own project, `q-cli`, with a fresh ledger: the Dats part's `mymodule` copied in, its `table12` spec marked `command: true`, and a `justfile` importing dvc-dat's verbs.

# %%
cli_project_path.mkdir(parents=True)
os.chdir(cli_project_path)
for module_name in [m for m in sys.modules if m.split(".")[0] == "mymodule"]:
    del sys.modules[module_name]                  # the Dats project's mymodule; this project has its own
sys.path[:] = [p for p in sys.path if p != str(dats_project_path)]
os.environ["PYTHONPATH"] = str(cli_project_path)  # the verbs import mymodule
sys.path.insert(0, str(cli_project_path))
Dat.manager = None                                # the dat world reloads from this folder

# the Dats project's mymodule; specs/table12.yaml also carries command: true
shutil.copytree(dats_project_path / "mymodule", "mymodule", ignore=shutil.ignore_patterns("__pycache__"))
with open("mymodule/specs/table12.yaml", "a") as spec_file:
    spec_file.write("command: true\n")
Path("q_cli_main.py").write_text('''\
"""The project's main: `just run` execs it (`run:` in .datconfig.yaml)."""
import sys

from dvc_dat import Dat

if __name__ == "__main__":
    sys.exit(Dat.cli_main())
''')
L = Ledger(create=True)                           # .datconfig.yaml + .dat/ledger
with open(".datconfig.yaml", "a") as config_file:
    config_file.write("run: python3 -m q_cli_main\n")
Path("justfile").write_text(
    f"import '{files('dvc_dat') / 'dvc_dat.just'}'  # run, the ledger verbs\n"
    "import? '.dat/targets.just'  # the declared commands\n")
Path("pyproject.toml").write_text('[project]\nname = "q-cli"\nversion = "0.1.0"\n')
Path(".gitignore").write_text(".dat/\ndata/\n__pycache__/\n")
for args in (["init", "-q"], ["config", "user.name", "demo"], ["config", "user.email", "demo@example.com"],
             ["add", "."], ["commit", "-q", "-m", "q-cli"]):
    subprocess.run(["git", *args], check=True)

import mymodule.mult                              # discovery finds the checkout, the repo q-cli
with L.transaction(by="human:dan", why="mount mymodule") as t:   # mymodule's code is the mount's: its files, hashed
    t.ns.mount("mymodule", root="mymodule")   # the two db/mount/mymodule rows; the repo is the project's, q-cli
    t.add("db", "db/version", "3.1.4")
just_done = subprocess.run(["just", "mounts"], check=True, capture_output=True)   # writes .dat/targets.just, the declared commands

# %%
# !just --list --color never
# → Available recipes:
# →     bump name part="patch" # bump a version: <module> edits its __version__ in the source; db is the ledger's release (a/b: a ledger clock); minor and major ask for yes
# →     history subject        # every row a subject has held, with each revision's db/by
# →     index pred             # declare a pred indexed
# →     mounts *args           # mounts [PREFIX]: the mounted names, with what each loads to
# →     run *args              # run TARGET [ARG ...] [KEY=VALUE ...]: a mounted name, a dotted function, a spec
# →     set subject *args      # rows on a subject: k=v a fact, alias=TARGET the name's value (a hash prefix is expanded)
# →     value *args            # exactly one value matching the preds
# →     values *args           # the values matching k=v preds (kind=<short class name> narrows)
# →     why name *args         # a value's dependencies, whether they hold at the head, and what moved since the alias's last target
# →
# →     [run]
# →     table12 *args

# %% [markdown]
# ## Running
#
# The project is the Dats part's `mymodule`, mounted on the ledger in its project setup:
#
# ```python
# t.ns.mount("mymodule", root="mymodule")   # repo: this project, q-cli
# ```
#
# Those rows are the project's names: `mymodule/specs/table12.yaml`
# is `mymodule.specs.table12`. `just run` of a spec makes the dat,
# runs it and seals it as a value; `alias=` names it. The spec is the
# memo key. `mymodule` is mounted, so its run function runs in a
# sandboxed worker, and its code is the files that run loaded.

# %%
# !just run mymodule.specs.table12 alias=table/12
# same as: L.at().run("mymodule.specs.table12", path="table/12")
# → ran  table/12  start=1 n=12 cells=144

# %% [markdown]
# Asked again with the same spec and code, it finds the value
# instead of re-running.

# %%
# !just run mymodule.specs.table12 alias=table/12
# same as: L.at().run("mymodule.specs.table12", path="table/12"), a memo hit
# → hit  table/12  start=1 n=12 cells=144

# %% [markdown]
# A mounted spec with `command: true` is its own verb: `just table12`
# is `just run mymodule.specs.table12`.

# %%
# !just table12
# same as: L.at().run("mymodule.specs.table12")
# → hit  table/12  start=1 n=12 cells=144

# %% [markdown]
# ## Finding computed values
#
# `just values` lists every value whose predicates match; `kind=`
# narrows to one class. A value prints by its name if it has one.

# %%
# !just values kind=Dat
# same as: L.at().values(kind=Dat)
# → table/12   start=1 n=12 cells=144

# %% [markdown]
# `just value` is the one value that matches.

# %%
# !just value n=12
# same as: L.at().value(n="12")
# → table/12   start=1 n=12 cells=144

# %% [markdown]
# `just history` is every row a subject has held, with who wrote it:
# `table/12` got its alias from the run.

# %%
# !just history table/12
# same as: [r for r in L.at().history() if r.subject == "table/12"]
# → rev  by         predicate  object
# →   3  name       db/alias   #<8 hex>

# %% [markdown]
# `just why` is what a value was computed from, and whether that all
# still holds. A sandboxed run names no commit: `code` is the bytes of
# the files it loaded, so a commit that leaves them alone leaves the
# value current.

# %%
# !just why table/12
# same as: v = L.at().load("table/12"); v.matches(L.at()), v.dependencies
# → table/12: #<8 hex>, matches the head
# → dependencies: code <8 hex>, fn mymodule.mult.build_table, platform <platform>

# %% [markdown]
# ## Updating
#
# A write adds a row; nothing changes in place. `set` adds one fact
# to a subject; a name is one more row on its subject (`db/alias`), so
# `set table/prod alias=<hash prefix>` points it at a value and prints
# what it pointed at before. `index` makes a predicate fast to list by.

# %%
table12_prefix = L.at().load("table/12").subject[:8]   # the value's hash, short
# !just set table/12 checked=yes
# same as: with L.transaction(by="human:$USER") as t: t["table/12", "checked"] = "yes"
# !just set table/prod alias={table12_prefix}
# same as: with L.transaction(by=…) as t: t.add("table/prod", "db/alias", subject)
# !just index n
# same as: with L.transaction(by=…) as t: t.add("db/pred/n", "db/index", "true")
# → table/12 checked=yes
# → table/prod: (none) -> #<8 hex>
# → n: indexed; 1 subjects hold it

# %% [markdown]
# ## Releasing
#
# A code version lives in its source: `just bump mymodule` edits the
# `__version__` line in `mymodule/__init__.py` and does nothing else,
# not even commit.

# %%
# !just bump mymodule
# same as: bump_source("mymodule", "patch")
# → mymodule: 0.1.0 -> 0.1.1 in mymodule/__init__.py
# → commit it: git commit -am "mymodule 0.1.1"

# %% [markdown]
# The ledger's `db/repo/q-cli/mymodule` `db/version` clock is the version of `mymodule` runs were exposed to.
# The first run (rev 2) put `0.1.0` there; after the commit, the next run from the clean checkout moves it to `0.1.1`, and `db/repo/q-cli` `db/commit` to that run's commit.

# %%
# !git commit -qam "mymodule 0.1.1"
# !just run mymodule.specs.table12
# !just history db/repo/q-cli/mymodule
# same as: [r for r in L.at().history() if r.subject == "db/repo/q-cli/mymodule"]
# !just history db/repo/q-cli
# → ran  tables/2026/table12  start=1 n=12 cells=144
# → rev  by         predicate  object
# →   2  eval:mymodule.mult.build_table db/version 0.1.0
# →   7  eval:mymodule.mult.build_table db/version 0.1.1
# → rev  by         predicate  object
# →   2  eval:mymodule.mult.build_table db/commit  <40 hex>
# →   7  eval:mymodule.mult.build_table db/commit  <40 hex>

# %% [markdown]
# A bump of `db`, the ledger's own clock, is a release: a row on the
# ledger, behind a typed `yes` for minor and major.

# %%
# !echo yes | just bump db minor
# same as: with L.transaction(by=…, lock=10, why="release") as t: bump(t, "db", "minor", confirm=…)
# → db: 3.1.4 -> 3.2.0? yes
# → db: 3.1.4 -> 3.2.0, a release

# %% [markdown]
# ## Other commands
#
# `just mounts` lists the names the project mounts, the ledger's
# `db/mount` prefixes beside dvc-dat's own `dt`:

# %%
# !just mounts
# same as: dvc_dat.dat_tools.cmd_list(""), in Dat.manager.ns
# → Base names matching: '*'
# →   dt                        -->  <module>
# →   mymodule                  -->  <module>

# %% [markdown]
# The rest, not run here:
#
# | Command | What it does |
# | --- | --- |
# | `x TARGET k=v` | `bin/x`, the same as `just run TARGET k=v` |
# | `dat TARGET k=v` | the `dat` console script: `Dat.manager.run(TARGET, …)` from a shell, no ledger; `dat --list`, `dat --info` ([DAT CLI](../DAT%20Design/DAT%20API/DAT%20CLI.md)) |
# | `just sealed` | in the dvc-dat repo: values sealed with `v.seal()` and never saved; `just sealed purge older=14d` drops the old ones |
# | `just test` | in the dvc-dat repo: the test suite |
# | `just demo` | in the dvc-dat repo: sync and execute the `demo-*` notebooks |
# | `just docs` | in the dvc-dat repo: the documentation site, `doc/` to `site/` |
