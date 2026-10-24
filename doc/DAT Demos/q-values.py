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
import shutil, subprocess, sys
from pathlib import Path

from IPython.display import SVG, display

from dvc_dat.ledger import Ledger, Ref

scratch_path = Path("scratch/q-values").resolve()
shutil.rmtree(scratch_path, ignore_errors=True)   # a re-run starts clean
for module_name in ("geometry", "plane", "plane.measure", "clips"):
    sys.modules.pop(module_name, None)
sys.path.insert(0, str(Path("demo_game").resolve()))   # the Video class

L = Ledger(scratch_path / "ledger", create=True)

# %% [markdown]
# # Quick: values
#
# A value is a Python object stored in the ledger by its content: its
# hash is its subject, and once stored it never changes. The quick
# tour: store and name a value, find it by its preds, compute values
# with ledger functions, and let the ledger remember their results.

# %%
display(SVG(filename="q-values.svg"))   # black: the parts every value has; gray: an example

# %% [markdown]
# ## Values
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

video_value = Video(b"G1 wide camera, 9000 frames")
video_value.preds.update(game="G1", camera="wide")
with L.transaction(by="human:dan") as t:
    video_subject = video_value.seal(t, name="video/G1")
print(video_value)          # → video/G1
print(len(video_subject))   # → 64: a hash of the content

# %% [markdown]
# `seal` stores the value and names it in one step. After the seal
# the value, its preds included, is frozen.

# %% [markdown]
# ### Referring to it: by name or by hash

# %%
rev1 = L.at()
by_name_video = rev1.load("video/G1")
by_hash_video = rev1.load(video_subject)
print(by_name_video.frames)                        # → b'G1 wide camera, 9000 frames'
print(by_name_video.subject == by_hash_video.subject)   # → True

# %% [markdown]
# ## Assigning preds, and finding values by them
#
# Preds set before the seal are written with it, as rows on the
# value's subject.

# %%
g2_video = Video(b"G2 wide camera, 8400 frames")
g2_video.preds.update(game="G2", camera="wide")
with L.transaction(by="human:dan") as t:
    g2_subject = g2_video.seal(t, name="video/G2")
rev2 = L.at()
print(rev2.values(camera="wide"))           # → [video/G1, video/G2]
print(rev2.value(game="G1", camera="wide")) # → video/G1
print(rev2.refs(kind=Video))                # → [video/G1, video/G2]

# %% [markdown]
# `values` loads every match, `value` exactly one, `refs` the
# matches unloaded.

# %% [markdown]
# ### Updating a pred
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
print(rev3.values(status="raw"))        # → [video/G2]
print(L.at().values(status="raw"))      # → []
print(L.at().values(status="reviewed")) # → [video/G2]

# %% [markdown]
# ## Values are immutable; their names, aliases and preds are not
#
# The bytes behind a hash, and the preds sealed with them, never
# change. A name, an alias or any other pred is a row beside the
# value, and rows can be written any time.

# %% [markdown]
# ### Adding an alias
#
# An alias is a `db/alias` row pointing at the value's subject. Any
# number may point at one value; its name is the alias written
# latest.

# %%
with L.transaction(by="human:dan") as t:
    t.add("raw/G1/wide-camera", "db/alias", video_subject)
camera_ref = Ref(L.at(), "video/G1")
print(sorted(camera_ref.aliases))   # → ['raw/G1/wide-camera', 'video/G1']
print(camera_ref.name)              # → raw/G1/wide-camera

# %% [markdown]
# A `Ref` points at a value without fetching its bytes.

# %% [markdown]
# ### Renaming: a new alias, the old one removed

# %%
with L.transaction(by="human:dan") as t:
    t.add("game/G2/baseline", "db/alias", g2_subject)
    t.remove("video/G2", "db/alias", g2_subject)
g2_ref = Ref(L.at(), g2_subject)
print(g2_ref.aliases, g2_ref.name)   # → ['game/G2/baseline'] game/G2/baseline

# %% [markdown]
# ### Adding and changing a pred
#
# A pred the class never declared can be added too.

# %%
with L.transaction(by="human:dan", why="format survey") as t:
    for video_ref in L.at().refs(kind=Video):
        t.add(video_ref.subject, "resolution", "1080p")
with L.transaction(by="human:dan", why="G2 was re-encoded") as t:
    t[g2_subject, "resolution"] = "720p"
print(Ref(L.at(), video_subject).preds["resolution"])   # → 1080p
print(Ref(L.at(), g2_subject).preds["resolution"])      # → 720p

# %% [markdown]
# ## Ledger functions
#
# A ledger function is a Python function the ledger knows by dotted
# name; it takes the revision first, and its result is sealed as a
# value. It lives in a git repository, so the ledger can record
# exactly which code ran. One is made here.

# %%
repo_path = scratch_path / "geometry"
repo_path.mkdir(parents=True)
git_cmd = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com"]
(repo_path / "geometry.py").write_text('''\
import math
from dvc_dat.ledger import ledger_fn


@ledger_fn
def distance(rev, a, b=(0, 0)) -> float:
    return math.dist(a, b)
''')
for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "distance"]):
    subprocess.run(git_cmd + args, cwd=repo_path, check=True)
sys.path.insert(0, str(repo_path))

distance_fn = L.at().load_fn("geometry.distance")
hypotenuse_value = distance_fn(a=(3, 4))
print(hypotenuse_value.obj, hypotenuse_value.sealed)
# → 5.0 <the seal's moment>

# %% [markdown]
# `load_fn` finds the function; calling it runs it and seals the
# plain `float` it returns as a value (`.obj` unboxes it).

# %% [markdown]
# ### Sandboxed functions
#
# A sandboxed function runs isolated, seeing only its mounted source
# folder, so its version is a checksum of the files it loaded rather
# than a git commit. A mount is two rows.

# %%
(repo_path / "plane").mkdir()
(repo_path / "plane/measure.py").write_text('''\
import math
from dvc_dat.ledger import ledger_fn


@ledger_fn
def length(rev, a, b) -> float:
    return math.dist(a, b) * 0.5     # metres per unit
''')
for args in (["add", "."], ["commit", "-q", "-m", "plane"]):
    subprocess.run(git_cmd + args, cwd=repo_path, check=True)
with L.transaction(by="human:dan") as t:
    t.add("db/mount/plane", "db/root", "plane")
    t.add("db/mount/plane", "db/repo", "geometry")

length_fn = L.at().load_fn("plane.measure.length")
segment_value = length_fn(a=(0, 0), b=(3, 4))
print(length_fn.mode, segment_value.obj)   # → sandbox 2.5

# %% [markdown]
# ## Ledger evaluation
#
# `rev.run(name, **keys)` is a lookup and a call, traced: the result
# records what it depended on, and is remembered, so asking again is
# answered from the ledger.

# %%
far_value = L.at().run("geometry.distance", a=(6, 8))
print(far_value.obj)                       # → 10.0
print(sorted(far_value.dependencies))      # → ['code/geometry', 'fn', 'platform']
top_id = L.at().id
again_value = L.at().run("geometry.distance", a=(6, 8))
print(again_value.subject == far_value.subject,
      L.at().id == top_id)                 # → True True: a hit, nothing written

# %% [markdown]
# The dependencies are the code's commit, the function, and the
# platform.

# %% [markdown]
# ### A new version, and a stale result
#
# A function that loads the video a name points at records that
# binding. Seal a new version under the same name and the name
# moves; the old result no longer holds, so `run` recomputes.

# %%
(repo_path / "clips.py").write_text('''\
from dvc_dat.ledger import ledger_fn
from demo_game.game import Video


@ledger_fn
def clip(rev, *, video: str, start: int, end: int) -> Video:
    return Video(rev.load(video).frames[start:end])
''')
for args in (["add", "."], ["commit", "-q", "-m", "clips"]):
    subprocess.run(git_cmd + args, cwd=repo_path, check=True)
opening_clip = L.at().run("clips.clip", video="video/G1", start=0, end=8)
print(opening_clip.frames)                 # → b'G1 wide '

retake_video = Video(b"G1 retake, 9100 frames")
retake_video.preds.update(game="G1", camera="wide")
with L.transaction(by="human:dan", why="the retake") as t:
    retake_video.seal(t, name="video/G1")   # the name moves
rev4 = L.at()
print(opening_clip.matches(rev4))          # → False: video/G1 moved
retake_clip = rev4.run("clips.clip", video="video/G1", start=0, end=8)
print(retake_clip.frames)                  # → b'G1 retak'
print(rev4.load(video_subject).frames)     # → b'G1 wide camera, 9000 frames'

# %% [markdown]
# A value never changes; a name moves. The old video and the old
# clip stay, found by their hashes.
