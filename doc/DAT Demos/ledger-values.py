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
import subprocess
import sys
from pathlib import Path

from dvc_dat.ledger import Ledger, Ref
from dvc_dat.ledger import AliasLoop, Exists, Multiple, Undeclared
from dvc_dat.ledger import ConfinedWrite, UnmountedImport

scratch_path = Path("scratch/values-demo").resolve()
scratch_ledger_path = scratch_path / "ledger"
L = Ledger(scratch_ledger_path, create=True)

sys.path.insert(0, str(Path("demo_game").resolve()))   # Video, PlainVideo

# %% [markdown]
# # Ledger: values
#
# A ledger value is a large or complex Python object stored in the
# ledger by its content, so it can be referred to, loaded back and
# depended on exactly. The ledger holds its bytes once, and a row
# that points at them; the object's hash is its subject. Once
# stored, a value never changes: a different object is a different
# value. Everything else here is built on that: aliases that point
# at values, preds that say what a value is, and functions whose
# results are values.

# %% [markdown]
# ## Values

# %% [markdown]
# ### Declaring a value class
#
# A value's class lives in a module, here `demo_game/game.py`: a
# `Value` subclass defined in a cell has no dotted name for a later
# `load` to import. A video:
#
# ```python
# class PlainVideo(Value):
#     """A game's raw video, as imported: no decorator, so no preds."""
#
#     def __init__(self, frames: bytes):
#         self.frames = frames
#
#     def encode(self) -> bytes:
#         return self.frames
#
#     @classmethod
#     def decode(cls, data: bytes, store) -> "PlainVideo":
#         return cls(data)
# ```
#
# `encode` and `decode` say how the object becomes bytes and back;
# here the bytes are the frames.

# %%
from demo_game.game import PlainVideo

# %% [markdown]
# ### Storing a value

# %%
video_value = PlainVideo(b"G1 wide camera, 9000 frames")
with L.transaction(by="human:dan") as t:
    video_subject = t.add_value(video_value)
print(video_subject)
# → 64 hex: from the content

# %% [markdown]
# `add_value` returns the value's subject, a hash derived from its
# content: a subject nobody typed.

# %% [markdown]
# ### Getting a reference

# %%
rev = L.at()
plain_ref = Ref(rev, video_subject)
print(plain_ref, plain_ref.type)
# → <8 hex> <class 'demo_game.game.PlainVideo'>

# %% [markdown]
# `Ref(rev, subject)` points at the value without fetching a byte,
# and prints as the hash's first eight characters.

# %% [markdown]
# ### Loading it back

# %%
loaded_video = rev.load(video_subject)
print(type(loaded_video).__name__, loaded_video.frames)
# → PlainVideo b'G1 wide camera, 9000 frames'
print(loaded_video.subject == video_subject)
# → True

# %% [markdown]
# `load` decodes the bytes into the class they were put in as: the
# same frames, the same hash.

# %% [markdown]
# ### Adding an alias
#
# An alias is a `db/alias` row naming the subject. `add_value(…,
# alias="video/G1")` writes it in the same transaction; here it is
# added later, by hand.

# %%
with L.transaction(by="human:dan") as t:
    t.add("video/G1", "db/alias", video_subject)
rev = L.at()
aliased_video = rev.load("video/G1")
print(aliased_video.subject == video_subject)
# → True
print(video_value)
# → video/G1

# %% [markdown]
# A second alias for the video. Notice it prints as the shorter one.

# %%
with L.transaction(by="human:dan") as t:
    t.add("raw/G1/wide-camera", "db/alias", video_subject)
rev = L.at()
camera_ref = Ref(rev, "raw/G1/wide-camera")
print(camera_ref)
# → video/G1: the shortest, as of the head
print(camera_ref.name)
# → raw/G1/wide-camera: what you said
print(sorted(camera_ref.aliases))
# → ['raw/G1/wide-camera', 'video/G1']

# %% [markdown]
# A value or its `Ref` prints as the shortest alias naming it, else
# the first eight characters of its hash. `Ref.aliases` lists every
# alias.

# %% [markdown]
# ### An alias is a row of its own
#
# The alias's own record, read with the bracket, beside the value it
# names.

# %%
print(rev["video/G1"])
# → {'db/alias': '<the video's subject, 64 hex>'}
print(rev.load("video/G1"))
# → video/G1: the value itself

# %% [markdown]
# `rev["video/G1"]` is literal: the alias's own rows, its `db/alias`
# row's object the subject as a plain `str`. `load` follows the row.

# %% [markdown]
# ### A new version is a new value
#
# A second take of G1's wide camera. `video/G1` names the current
# version of the video, so the alias re-points.

# %%
retake_video = PlainVideo(b"G1 wide camera, retake, 9100 frames")
with L.transaction(by="human:dan") as t:
    retake_subject = t.add_value(retake_video)
with L.transaction(by="human:dan", why="the retake") as t:
    t.add("video/G1", "db/alias", retake_subject)
rev = L.at()
print(rev.load("video/G1").frames)
# → b'G1 wide camera, retake, 9100 frames'
print(rev.load(video_subject).frames)
# → b'G1 wide camera, 9000 frames': the old one, by its subject
print(video_value)
# → raw/G1/wide-camera: video/G1 moved

# %% [markdown]
# A value never changes; an alias moves.

# %% [markdown]
# ## Value predicates
#
# Preds are the aspects of a value it is found by: string-valued
# rows beside its bytes, declared by its kind, set during
# construction and frozen by the seal.

# %% [markdown]
# ### A kind declares its preds
#
# ```python
# @ledger_class(preds=("game", "camera", "span"))
# class Video(Value):
#     """A game's raw video, as imported."""
#     ...                     # the body of PlainVideo, unchanged
# ```
#
# The decorator is the only change from `PlainVideo`. It names the
# preds a kind may carry, never their values, and writes no row on
# import.

# %%
from demo_game.game import Video

# %% [markdown]
# `span` holds a frame range, a list, so its pred is declared
# `json` (Edge cases § A pred with many values says why).

# %%
with L.transaction(by="human:dan") as t:
    t.add("db/pred/span", "db/type", "json")

# %% [markdown]
# ### Preds are assigned during construction

# %%
wide_video = Video(b"G1 wide camera, 9000 frames")
wide_video.preds.update(game="G1", camera="wide", span=[0, 9000])
with L.transaction(by="human:dan") as t:
    t.add_value(wide_video, alias="video/G1",
                provenance="import:archive")
print(wide_video)
# → video/G1
print(wide_video.subject[:8])
# → <8 hex>
print(wide_video.preds)
# → {'game': 'G1', 'camera': 'wide', 'span': [0, 9000]}

# %% [markdown]
# Preds are set on the object before it is stored, by whoever builds
# it; `add_value` takes no `preds=`. Storing fixes `subject` and
# `rev`. The preds are in the subject's hash, so frames already on
# the ledger make a new subject here; `video/G1` moves to it, an
# alias being one row whose latest add wins.

# %% [markdown]
# G2's video the same way, for a second game.

# %%
g2_video = Video(b"G2 wide camera, 8400 frames")
g2_video.preds.update(game="G2", camera="wide", span=[0, 8400])
with L.transaction(by="human:dan") as t:
    t.add_value(g2_video, alias="video/G2",
                provenance="import:archive")

# %% [markdown]
# ### What a value looks like on the ledger
#
# The revision that stored G1's video, as rows, unfolded. Notice
# everything written on the new subject, and the alias row on
# `video/G1`.

# %%
stored_rev = wide_video.rev
for row in stored_rev.rows(since=L.at(stored_rev.id - 1)):
    print(row)
# →    7 + <hash>   db/value              ref:demo_game.game.Video:<hash>
# →    7 + <hash>   db/kind               demo_game.game.Video
# →    7 + <hash>   db/provenance         import:archive
# →    7 + <hash>   db/preds              ["game","camera","span"]
# →    7 + <hash>   db/trace/platform     darwin-arm64-py3.12
# →    7 + <hash>   db/trace/uv.lock      sha256:<hash>
# →    7 + <hash>   game                  G1
# →    7 + <hash>   camera                wide
# →    7 + <hash>   span                  [0,9000]
# →    7 + video/G1 db/alias              <hash>
# →    7 + db/tx/7  db/by                 human:dan

# %% [markdown]
# `db/value` names the bytes by class and hash. `db/kind` is the
# class. `db/provenance` is the caller's word. `db/preds` lists the
# preds the kind declared when the value was stored. The
# `db/trace/…` rows are the trace (Ledger evaluation § Evaluation
# is a lookup, a call and a trace): a hand seal records the environment it
# runs in. Then one row per pred, and the alias.

# %% [markdown]
# ### Finding values by preds

# %%
rev = L.at()
print(rev.values(game="G1"))
# → [video/G1]
print(rev.values(kind=Video))
# → [video/G1, video/G2]
print(rev.values(camera="wide"))
# → [video/G1, video/G2]
print(rev.value(game="G1", camera="wide"))
# → video/G1

# %% [markdown]
# `value` means exactly one. Notice it refuses when two match,
# naming both, rather than picking one.

# %%
try:
    rev.value(kind=Video)            # two videos match
except Multiple as e:
    print("Multiple:", e)
# → Multiple: kind=demo_game.game.Video matches 2: video/G1, video/G2

# %% [markdown]
# `refs` hands back the same values unloaded: a `Ref` shows its
# preds and its revision without fetching a byte.

# %%
video_refs = rev.refs(kind=Video)
print(video_refs)
# → [video/G1, video/G2]
print(type(video_refs[0]).__name__)
# → Ref: no bytes fetched
[g1_ref] = rev.refs(game="G1")
print(g1_ref.preds)
# → {'game': 'G1', 'camera': 'wide', 'span': [0, 9000]}
print(g1_ref.sealed_at)
# → Rev(7)
print(max(video_refs, key=lambda r: r.sealed_at.id))
# → video/G2
print(rev.select(("game", "span"), kind=Video))
# → [('G1', [0, 9000]), ('G2', [0, 8400])]

# %% [markdown]
# `values` is the main way into the value table: a where clause
# over preds, the matches loaded, in no promised order. A bare
# keyword names a pred, whoever wrote it; `kind=` narrows to a
# class. The plain videos carry no preds, so no clause finds them.
# `value` is exactly one, or it raises `Multiple`.
#
# `refs` says who matched without loading: `Ref.preds` and
# `Ref.sealed_at`, the revision of the `db/value` row, come with
# the rows, so refs can be filtered and sorted before any bytes
# move, and the latest is a `max` over `sealed_at`. `select`
# projects chosen preds to tuples.

# %% [markdown]
# ### Sealing a value
#
# Values are immutable once they are sealed. During construction
# everything is mutable; `add_value` is the act of sealing, and from
# then on nothing changes: the bytes, the preds the seal wrote, and
# the rows it wrote (`db/value`, `db/kind`, `db/preds`,
# `db/provenance`) are fixed forever, and the subject is their
# hash. Rows that are not the seal's, annotations, can be added.

# %% [markdown]
# On the object, a sealed value's `preds` is read-only.

# %%
print(wide_video.sealed)
# → True
try:
    wide_video.preds["camera"] = "tele"
except TypeError as e:
    print("TypeError:", e)
# → TypeError: cannot modify a sealed value's preds

# %% [markdown]
# On the ledger, an `add` on a pred the seal wrote raises `Exists`
# as the transaction closes, and writes nothing.

# %%
try:
    with L.transaction(by="human:dan") as t:
        t.add(wide_video.subject, "camera", "tele")
except Exists as e:
    print("Exists:", e)
# → Exists: <12 hex>… is sealed: 'camera' is one of its own predicates,
#   written once (add refused); annotate with another predicate, or
#   seal anew and re-point

# %% [markdown]
# ### What a seal refuses
#
# A pred the kind did not declare is refused at the seal.

# %%
tele_video = Video(b"G1 tele camera, 9000 frames")
tele_video.preds.update(game="G1", camera="tele", lens="85mm")
try:
    with L.transaction(by="human:dan") as t:
        t.add_value(tele_video)
except Undeclared as e:
    print("Undeclared:", e)
# → Undeclared: 'lens': not a pred of demo_game.game.Video
#   (@ledger_class(preds=('game', 'camera', 'span')))

# %% [markdown]
# A refused seal leaves the value exactly as it was, unsealed, its
# `preds` a plain dict (A43), so the stray `lens` can simply be
# taken out of the same object.

# %%
print(tele_video.sealed)
# → False: nothing was written
del tele_video.preds["lens"]

# %% [markdown]
# A hand seal names its own provenance (`eval:` provenance is
# written by evaluation alone; see Ledger evaluation).

# %%
try:
    with L.transaction(by="human:dan") as t:
        t.add_value(tele_video, provenance="eval:sandbox")
except ValueError as e:
    print("ValueError:", e)
# → ValueError: provenance 'eval:sandbox': eval: provenance is written
#   by eval alone

# %% [markdown]
# Bytes enter the ledger by `add_value` alone: `add` refuses a
# `Value` and names `add_value`.

# %%
try:
    with L.transaction(by="human:dan") as t:
        t.add("video/G1-tele", "note", tele_video)
except TypeError as e:
    print("TypeError:", e)
# → TypeError: add takes a str, a JSON document or a Ref, not a Video:
#   bytes enter the ledger by t.add_value(value) alone

# %% [markdown]
# ## Revising a value
#
# A value is immutable, so you cannot revise the value itself.
# Instead, revision happens at three levels, and the level you pick
# is the level of what changed: a fact beside the value, a wrong
# pred, or a new version.

# %% [markdown]
# ### Annotation: rows beside the value
#
# A new pred on every video.

# %%
with L.transaction(by="human:dan", why="format survey") as t:
    for video_ref in L.at().refs(kind=Video):
        t.add(video_ref.subject, "resolution", "1080p")
rev = L.at()
print(Ref(rev, "video/G1").preds["resolution"])
# → 1080p
print(len(rev.values(kind=Video, resolution="1080p")))
# → 2
print(rev[wide_video.subject, "db/preds"])
# → ['game', 'camera', 'span']: the seal's own, unchanged

# %% [markdown]
# `resolution` is not a pred the seal wrote, so it is annotation:
# allowed on a sealed value in any later transaction, and part of
# the one view of its preds that `Ref.preds` reads. The seal's rows
# are untouched; its `db/preds` row still lists only its own.

# %% [markdown]
# ### Correction: re-seal and re-point
#
# G1's tele video, sealed and named in one transaction. Notice the
# typo in `camera`.

# %%
tele_video.preds["camera"] = "tlee"              # a typo
with L.transaction(by="human:dan") as t:
    wrong_subject = t.add_value(tele_video, alias="video/G1-tele",
                                provenance="import:archive")
print(Ref(L.at(), "video/G1-tele").preds["camera"])
# → tlee

# %% [markdown]
# `camera` is a pred the seal wrote, so it cannot be edited. The fix
# is a new seal with the same bytes and the right preds, the alias
# re-pointed to it.

# %%
fixed_video = Video(tele_video.frames)           # the same bytes
fixed_video.preds.update(game="G1", camera="tele", span=[0, 9000])
with L.transaction(by="human:dan", why="camera typo") as t:
    right_subject = t.add_value(fixed_video, alias="video/G1-tele",
                                provenance="import:archive")
rev = L.at()
print(right_subject != wrong_subject,
      fixed_video.hash == tele_video.hash)
# → True True
print(Ref(rev, "video/G1-tele").preds["camera"])
# → tele
print(rev.refs(kind=Video, camera="tlee"))
# → [<8 hex>]

# %% [markdown]
# The same bytes make a new subject, sharing one blob. The wrong
# one stays with its history, immutable, still found by
# `camera="tlee"`, printed by its hash since no alias names it now.

# %% [markdown]
# ### A new version: a new value with new preds
#
# G1's wide video with the warm-up cut off: new bytes, a new `span`.

# %%
trimmed_video = Video(b"G1 wide camera, frames 600-9000")
trimmed_video.preds.update(game="G1", camera="wide", span=[600, 9000])
with L.transaction(by="human:dan") as t:
    t.add_value(trimmed_video, deps=[wide_video])
print(trimmed_video)
# → <8 hex>: no alias yet
with L.transaction(by="human:dan", why="warm-up trimmed") as t:
    t.add("video/G1", "db/alias", trimmed_video.subject)
print(trimmed_video, wide_video)
# → video/G1 <8 hex>

# %% [markdown]
# The new version is sealed as a new value, then the alias moves to
# it; the untrimmed video stays, unnamed. `deps=[wide_video]` puts
# the video it was cut from into its trace.

# %% [markdown]
# ## Ledger functions
#
# A ledger function is a Python function the ledger knows by name:
# it takes the revision first and keywords after, and its results
# are values, so the ledger can answer the same call again without
# running it.

# %% [markdown]
# ### Global functions
#
# A global function is one that is simply in the code you are
# running, found by its dotted name and run in this process. It
# runs inside the ledger's own Python environment, so everything
# there, every module and every global, is available to it: that is
# its advantage. The ledger cannot control such code; it can only
# record which code it was.

# %% [markdown]
# #### Connecting the ledger to the code
#
# To define a function precisely, the ledger ties it to the commit
# that holds it, so a global function lives in a git repository.
# This one is made here, in the scratch folder, and put on the path.

# %%
scratch_repo_path = scratch_path / "geometry"
scratch_repo_path.mkdir()


def git(*args: str) -> str:
    """Run git in the scratch repo; return its stdout."""
    cmd = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com",
           "-c", "init.defaultBranch=main", *args]
    done = subprocess.run(cmd, cwd=scratch_repo_path, check=True,
                          capture_output=True, text=True)
    return done.stdout.strip()


print(git("init"))
# → Initialized empty Git repository in .../values-demo/geometry/.git/
sys.path.insert(0, str(scratch_repo_path))

# %% [markdown]
# #### Defining a global function

# %%
geometry_source = '''\
"""`geometry`: any Python function can be a ledger function."""
import math

from dvc_dat.ledger import ledger_fn

ORIGIN = (0, 0)


@ledger_fn
def distance(rev, a, b=ORIGIN, *, metric="euclidean") -> float:
    """The distance between points `a` and `b`, by default the origin."""
    if metric == "manhattan":
        return float(sum(abs(p - q) for p, q in zip(a, b)))
    return math.dist(a, b)                 # Pythagoras
'''
(scratch_repo_path / "geometry.py").write_text(geometry_source)
git("add", "geometry.py")
git("commit", "-m", "geometry: distance")
print(git("log", "--oneline"))
# → <7 hex> geometry: distance

# %% [markdown]
# `@ledger_fn` marks `distance` as a ledger function and leaves it a
# plain function: nothing is wrapped and no row is written on
# import; the return annotation is required. `a` is positional, `b`
# defaults to the module's `ORIGIN`, and `metric` is keyword-only:
# any signature works whose first parameter is the revision.

# %% [markdown]
# #### Loading and calling it

# %%
rev = L.at()
distance_fn = rev.load_fn("geometry.distance")
print(distance_fn.mode)
# → base
print(distance_fn.signature)
# → (a, b=(0, 0), *, metric='euclidean')
print(distance_fn.subject)
# → db/fn/geometry.distance/<16 hex>

# %% [markdown]
# The ledger finds the function by its dotted name at `rev` and
# hands back an `Fn` saying which code the name resolves to: `mode`
# is `base` for a global function, `signature` the keywords it
# takes, `subject` the one name for that resolution.

# %%
hypotenuse_value = distance_fn(a=(3, 4))
print(hypotenuse_value, hypotenuse_value.obj)
# → <8 hex> 5.0
print(hypotenuse_value.sealed, hypotenuse_value.rev.id > rev.id)
# → True True
print(hypotenuse_value.trace["code/geometry"] == "+" + git("rev-parse", "HEAD")[:8])
# → True

# %% [markdown]
# Calling the `Fn` ran `distance` and sealed its result as a value
# in a revision of its own. The trace's `code/geometry` item is the
# commit of the scratch repo, named by its folder: that is the code
# the result came from.

# %% [markdown]
# ### Sandboxed functions
#
# A sandboxed function is one the ledger controls: its source is
# mounted into an isolated Python run where every import is traced
# and every write is confined, so its version is a checksum over the
# source files the run loaded, with no reference to the host Python
# environment or to a git commit. This is what gives precise
# provenance and reproducibility; the price is the global function's
# advantage, since nothing outside what is mounted is available.

# %% [markdown]
# #### Mounting a source tree
#
# A folder `plane/` in the same geometry repo: `measure.py`, whose
# one import of its own is `units.py` beside it.

# %%
plane_path = scratch_repo_path / "plane"
plane_path.mkdir()
(plane_path / "units.py").write_text('SCALE = 0.5             # metres per unit\n')
measure_source = '''\
"""`plane.measure`: a length in metres."""
import math

from dvc_dat.ledger import ledger_fn

from .units import SCALE                   # the one import of its own


@ledger_fn
def length(rev, a, b) -> float:
    """The length of the segment from `a` to `b`, in metres."""
    return math.dist(a, b) * SCALE
'''
(plane_path / "measure.py").write_text(measure_source)
git("add", "plane")
git("commit", "-m", "plane: measure, units")

with L.transaction(by="human:dan", why="mount plane") as t:
    # plane.measure is loaded from plane/measure.py in the geometry repo
    t.add("db/mount/plane", "db/root", "plane")
    t.add("db/mount/plane", "db/repo", "geometry")
rev = L.at()
print(rev["db/mount/plane"])
# → {'db/root': 'plane', 'db/repo': 'geometry'}

# %% [markdown]
# Mounting says where a function's source is read from. It is rows
# on the ledger: a dotted prefix (`plane`), the folder it resolves
# to (`db/root`, relative to the repo's checkout) and the repo
# (`db/repo`). Every name under the prefix now resolves inside that
# folder: `plane.measure` is `plane/measure.py`. A `.datconfig.yaml`
# `mounts:` entry is sugar for these rows.

# %% [markdown]
# #### A function under a mount

# %%
length_fn = rev.load_fn("plane.measure.length")
print(length_fn.mode, length_fn.mount)
# → sandbox plane
segment_value = length_fn(a=(0, 0), b=(3, 4))
print(segment_value.obj, sorted(segment_value.trace))
# → 2.5 ['fn', 'platform', 'uv.lock']
print(L.at()[segment_value.trace["fn"], "db/modules"])
# → {'plane/measure.py': '<hash>', 'plane/units.py': '<hash>'}

# %% [markdown]
# Loaded and called like the global function, it ran in a worker
# whose path holds the standard library, `site-packages` and the
# mounted folders, nothing else. The run pulled in `units.py`
# through the import, and `db/modules` records each source file
# loaded with its checksum: that is the function's version. The
# trace carries no `code/geometry` item.

# %% [markdown]
# #### What the sandbox refuses
#
# A function under the mount that imports `geometry` by its global
# name.

# %%
reach_source = '''\
"""`plane.reach`: two functions the sandbox refuses."""
from pathlib import Path

from dvc_dat.ledger import ledger_fn


@ledger_fn
def from_origin(rev, p) -> float:
    from geometry import distance       # geometry.py, outside plane/
    return distance(rev, p)


@ledger_fn
def note(rev, text) -> int:
    return Path("/tmp/plane-note.txt").write_text(text)   # outside its folder
'''
(plane_path / "reach.py").write_text(reach_source)
git("add", "plane/reach.py")
git("commit", "-m", "plane: reach")

try:
    from_origin_fn = rev.load_fn("plane.reach.from_origin")
    from_origin_fn(p=(3, 4))
except UnmountedImport as e:
    print("UnmountedImport:", e)
# → UnmountedImport: geometry from plane.reach; mount it or move it

# %% [markdown]
# The sandbox looks up every import that is not under a mount in
# the mounted repo's checkout; `geometry.py` is there, outside
# `plane/`, so the import is refused by name rather than silently
# reaching code the trace would not record. A module found nowhere
# is simply not there: a plain `ModuleNotFoundError`. Nothing is
# sealed.

# %% [markdown]
# #### Where a sandboxed function writes
#
# A write outside the function's own folder is refused.

# %%
try:
    note_fn = rev.load_fn("plane.reach.note")
    note_fn(text="hello")
except ConfinedWrite as e:
    print("ConfinedWrite:", e)
# → ConfinedWrite: /private/tmp/plane-note.txt: a sandboxed function
#   writes only in its work folder

# %% [markdown]
# The refusal is raised as `ConfinedWrite`; a read outside the
# allowed folders is `UntracedRead`. The sandbox confines writes
# to the function's own work folder, the dat being produced (not
# the worker's scratch, not the store); reads are confined to the
# mounted folders, the store and that work folder. Open (Q36; lean): a function
# that builds a folder declares a parameter `work: Path`, reserved
# beside `memo` and never a key; the run binds it to a fresh folder
# in the scratch, and the seal moves what was built there into the
# store.

# %% [markdown]
# ## Ledger evaluation
#
# Evaluating a ledger function is a lookup of the function by name
# followed by a call, with tracing: every read the run makes is
# recorded, so the result carries its provenance, and the result is
# kept, so the same question is answered from the ledger next time.

# %% [markdown]
# ### Evaluation is a lookup, a call and a trace

# %%
rev = L.at()
far_value = rev.eval("geometry.distance", a=(6, 8))
print(far_value.obj, far_value.sealed)
# → 10.0 True
for item in sorted(far_value.trace):
    print(item, "->", far_value.trace[item])
# → code/geometry -> +<8 hex>
# → fn -> db/fn/geometry.distance/<16 hex>
# → platform -> darwin-arm64-py3.12
# → uv.lock -> sha256:<hash>

# %% [markdown]
# `rev.eval(name, **keys)` is `rev.load_fn(name)` and then the
# call, as in Ledger functions. What makes it more than a call is
# the trace, recorded during the run, not declared, item by item:
#
# - `code/geometry` — `distance` is global, so the code it ran is
#   known only as its repo's commit.
# - `fn` — the code the name resolved to, its `Fn` subject: for a
#   global function the commit, beside the hash of the module's
#   source and what it imports from its repo (A39).
# - `platform`, `uv.lock` — the environment, discovered.
#
# `distance` reads nothing through `rev`, so nothing else is in its
# trace; a function that reads rows or loads values adds an item for
# each (§ When an entry goes stale).

# %% [markdown]
# A hand seal has a trace too: with no `deps`, the environment
# alone; with them, each dep by its bytes.

# %%
print(dict(sorted(wide_video.trace.items())))
# → {'platform': 'darwin-arm64-py3.12', 'uv.lock': 'sha256:<hash>'}
print(sorted(trimmed_video.trace))
# → ['platform', 'ref:demo_game.game.Video:<hash>', 'uv.lock']

# %% [markdown]
# ### Evaluation is memoized
#
# Asked twice, computed once.

# %%
top_id = L.at().id
again_value = L.at().eval("geometry.distance", a=(6, 8))
print(again_value.subject == far_value.subject)
# → True: a hit
print(L.at().id == top_id)
# → True: nothing written
print(again_value.rev.id == far_value.rev.id)
# → True: the seal's rev

# %% [markdown]
# The second call is a memo hit: same function, same keys, every
# trace item unchanged. It writes nothing, and the value it hands
# back carries the revision it was sealed in.

# %% [markdown]
# A memo entry is the seal's rows plus two of its own: `db/fn`, the
# code that ran, and `db/keys`, the question. Notice the defaults,
# `b` and `metric`, are part of the question.

# %%
entry_rev = far_value.rev
for row in entry_rev.rows(since=L.at(entry_rev.id - 1)):
    if row.predicate in ("db/fn", "db/keys"):
        print(row)
# →   17 + <hash> db/fn   geometry.distance
# →   17 + <hash> db/keys {"a":[6,8],"b":[0,0],"metric":"euclidean"}

# %% [markdown]
# Memo entries are subjects like any other: `fn=` finds every
# evaluation of a function.

# %%
rev = L.at()
for memo_ref in rev.refs(fn="geometry.distance"):
    print(memo_ref, rev[memo_ref.subject, "db/keys"])
# → <8 hex> {'a': [3, 4], 'b': [0, 0], 'metric': 'euclidean'}
# → <8 hex> {'a': [6, 8], 'b': [0, 0], 'metric': 'euclidean'}
print(len(rev.values(fn="geometry.distance")))
# → 2, loaded

# %% [markdown]
# ### A bare return is boxed into a value

# %%
print(type(far_value).__name__, far_value.obj)
# → Pickled 10.0
print(L.at()[far_value.trace["fn"], "db/returns"])
# → float

# %% [markdown]
# `distance` returns a plain `float`. `-> float` names no `Value`
# subclass, so the float was boxed in `Pickled` and sealed like any
# value; `.obj` unboxes it. The annotation is kept as `db/returns`
# on the function's `db/fn/…` subject. `Pickled` declares no preds,
# so the entry is found by `db/fn` and `db/keys` alone.

# %% [markdown]
# ### When an entry goes stale
#
# A function that cuts a clip out of the video an alias names,
# written as a second module of the geometry repo and committed.

# %%
clips_source = '''\
"""`clips`: a ledger function that returns a Video."""
from dvc_dat.ledger import ledger_fn
from demo_game.game import Video


@ledger_fn
def clip(rev, *, video: str, start: int, end: int) -> Video:
    """Frames `start` to `end` of the video `video` names."""
    source = rev.load(video)                 # traced: the alias, the bytes
    c = Video(source.frames[start:end])
    c.preds["span"] = [start, end]
    return c
'''
(scratch_repo_path / "clips.py").write_text(clips_source)
git("add", "clips.py")
git("commit", "-m", "clips")

rev = L.at()
opening_clip = rev.eval("clips.clip", video="video/G1", start=0, end=8)
print(type(opening_clip).__name__, opening_clip.frames, opening_clip.preds)
# → Video b'G1 wide ' {'span': [0, 8]}
for item in sorted(opening_clip.trace):
    if item.startswith(("video/", "ref:")):
        print(item, "->", opening_clip.trace[item])
# → ref:demo_game.game.Video:<trimmed> -> ref:demo_game.game.Video:<trimmed>
# → video/G1 db/alias -> ref:demo_game.game.Video:<trimmed>

# %% [markdown]
# `-> Video` names a `Value` subclass, so the clip is sealed as it
# was returned, no boxing. The load through `video/G1` recorded the
# binding, the name to the bytes it resolved to, beside the value
# item. Neither holds the subject (A35): what `clip` depends on is
# the bytes the name gives, not the entry they sit in.

# %% [markdown]
# A new version of the video, stabilised, and `video/G1` re-pointed
# at it. Notice the same question now misses.

# %%
stable_video = Video(b"G1 stabilised, frames 600-9000")
stable_video.preds.update(game="G1", camera="wide", span=[600, 9000])
with L.transaction(by="human:dan", why="stabilised") as t:
    t.add_value(stable_video, deps=[trimmed_video], alias="video/G1")
rev = L.at()
stable_clip = rev.eval("clips.clip", video="video/G1", start=0, end=8)
print(stable_clip.subject != opening_clip.subject, stable_clip.frames)
# → True b'G1 stabi'
print(sorted(opening_clip.diff(stable_clip)))
# → ['ref:demo_game.game.Video:<stabilised>',
#    'ref:demo_game.game.Video:<trimmed>', 'video/G1 db/alias']

# %% [markdown]
# The binding moved, so the old entry's trace no longer holds: the
# `eval` missed and re-derived. `diff` names the items that moved:
# the `video/G1` binding, and each side's value item. The old clip
# stays, found by its hash.

# %% [markdown]
# ### Same bytes, different values

# %%
rev = L.at()
shifted_value = rev.eval("geometry.distance", a=(1, 1), b=(4, 5))
print(shifted_value.obj, shifted_value.same_as(hypotenuse_value),
      shifted_value.subject != hypotenuse_value.subject)
# → 5.0 True True

# %% [markdown]
# Two questions, identical bytes: both distances are `5.0`. Two memo
# entries, two subjects, one blob. `same_as` compares only the bytes
# hash, so two values from different derivations, or with different
# preds, can be the same bytes.

# %% [markdown]
# A name works the same way. A correction of the stabilised video's
# preds is a new subject on the same bytes; point `video/G1` at it
# and the clip's entry holds.

# %%
restamped_video = Video(stable_video.frames)     # the same bytes
restamped_video.preds.update(game="G1", camera="wide", span=[600, 8990])
with L.transaction(by="human:dan", why="span off by ten") as t:
    t.add_value(restamped_video, deps=[trimmed_video], alias="video/G1")
rev = L.at()
print(restamped_video, stable_video)
# → video/G1 <8 hex>
again_clip = rev.eval("clips.clip", video="video/G1", start=0, end=8)
print(again_clip.subject == stable_clip.subject)
# → True: a hit

# %% [markdown]
# `video/G1` now names identical bytes, so the binding item is
# unchanged and `clip` hits (A35, A21).

# %% [markdown]
# ### Checking an entry, and evaluating without keeping
#
# Whether an entry still holds can be asked without evaluating:
# `matches(rev)` returns a bool, whether every item of the entry's
# trace still reads the same at `rev`.

# %%
rev = L.at()
print(opening_clip.matches(rev))
# → False: video/G1 has moved on
print(stable_clip.matches(rev))
# → True: it names identical bytes

# %% [markdown]
# `memo="get"` looks the entry up without running; `memo=False`
# runs without sealing, and its bytes are what a memoized call would
# return.

# %%
print(rev.eval("geometry.distance", a=(5, 12), memo="get"))
# → None: never run
dry_value = rev.eval("geometry.distance", a=(6, 8), memo=False)
print(dry_value.sealed, dry_value.hash == far_value.hash)
# → False True
print(L.at().id == rev.id)
# → True: nothing written

# %% [markdown]
# ## Edge cases

# %% [markdown]
# ### A pred with many values
#
# A pred declared `many` holds a list, one row per member; tags on
# the videos, as annotation.

# %%
with L.transaction(by="human:dan") as t:
    t.add("db/pred/tag", "db/cardinality", "many")
with L.transaction(by="human:dan", why="tagging") as t:
    t.add(restamped_video.subject, "tag", "opener")
    t.add(restamped_video.subject, "tag", "home-court")
    t.add(g2_video.subject, "tag", "home-court")
rev = L.at()
print(sorted(Ref(rev, "video/G1").preds["tag"]))
# → ['home-court', 'opener']
print(rev.values(tag="home-court"))
# → [video/G1, video/G2]
print(rev["db/pred/span", "db/type"])
# → json
print(wide_video.preds["span"])
# → [0, 9000]

# %% [markdown]
# `tag` is declared `many`, so a video's tags are a list and a
# keyword matches any member. `span` is typed `json`, so a `one`
# pred may hold a list (A36). A list under an untyped `one` pred is
# refused at the seal.

# %%
two_camera_video = Video(b"G1 both cameras, 9000 frames")
two_camera_video.preds["camera"] = ["tele", "wide"]
try:
    with L.transaction(by="human:dan") as t:
        t.add_value(two_camera_video)
except TypeError as e:
    print("TypeError:", e)
# → TypeError: pred 'camera': a list under a one pred; declare
#   (db/pred/camera, db/cardinality, many) or (db/pred/camera,
#   db/type, json)

# %% [markdown]
# ### An alias chain has a limit
#
# An alias may name another alias, and `Ref` follows at most 8
# hops; a ninth, like a cycle, is `AliasLoop`.

# %%
with L.transaction(by="human:dan") as t:
    t.add("hop-chain/1", "db/alias", video_value.subject)
    for i in range(2, 10):
        t.add(f"hop-chain/{i}", "db/alias", f"hop-chain/{i - 1}")
hop8_ref = Ref(L.at(), "hop-chain/8")
print(hop8_ref.subject == video_value.subject)
# → True
try:
    Ref(L.at(), "hop-chain/9")
except AliasLoop as e:
    print("AliasLoop:", e)
# → AliasLoop: 'hop-chain/9': the db/alias chain runs past 8 hops (or
#   loops) at rev 25

# %% [markdown]
# ### A sealed pred cannot be removed
#
# A `remove` of a frozen pred is refused like an `add` (A38).

# %%
try:
    with L.transaction(by="human:dan") as t:
        t.remove(wrong_subject, "camera", "tlee")
except Exists as e:
    print("Exists:", e)
# → Exists: <12 hex>… is sealed: 'camera' is one of its own predicates,
#   written once (remove refused); annotate with another predicate, or
#   seal anew and re-point

# %% [markdown]
# ### A row can point at a value
#
# A `Ref` may be any row's object. `add` stores it as
# `ref:<class>:<hash>:<subject>`, the subject a hint; every pattern
# read hands it back as a `Ref`, unloaded, printed as its shortest
# alias, else the hash's first eight characters.

# %%
with L.transaction(by="human:dan") as t:
    t.add("review/G1", "clip", Ref(t.base, stable_clip.subject))
pick_ref = L.at()["review/G1", "clip"]
print(pick_ref, pick_ref.subject == stable_clip.subject)
# → <8 hex> True

# %% [markdown]
# ### A hand seal and an eval write the same rows
#
# A hand seal and `eval` (calling the `Fn` that `load_fn` hands back
# is `eval`) write the same rows, so every read above treats a value
# the same way whichever door sealed it; an eval's entry adds only
# `db/fn` and `db/keys`.
