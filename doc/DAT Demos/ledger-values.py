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
# # Ledger: values
#
# The value space on its own, through one worked example: a game.
# `game/G1` is a plain subject, the game's identity. Its raw video
# is a value, sealed by hand. Cutting is a value function: it reads
# the game's rows and the video, and its cut is a new value whose
# preds the function sets. The game's current cut is an alias row
# on `game/G1` itself. Every value is found by its preds, and every
# one can say why it would no longer be the answer.
#
# Written to the ledger design of 2026-10-18 (SVP447 Ledger Module
# and Values § The worked example). It runs once `ledger2` is
# rebuilt to that design (T534); until then it is the design, not a
# demo.

# %%
import os, sys, tempfile
from pathlib import Path

from dvc_dat.ledger import Ledger, ledger_fn, ledger_class, bump, attr
from dvc_dat.ledger import Ref, Value, Exists, Undeclared, Multiple
from dvc_dat.ledger import Code, Env, set_env_provider

sys.path.insert(0, "demo_svp")           # the stand-in svp package
ledger_dir = Path(tempfile.mkdtemp(prefix="ledger-values-"))
os.environ["DAT_LEDGER"] = str(ledger_dir)
L = Ledger.open()

ENV = Env({"sv-pipe": Code("0.2.2", "7d742989")},
          lock="sha256:5e1f", platform="darwin-arm64-py3.11")
set_env_provider(lambda module: ENV)

# %% [markdown]
# ## The module: `svp.game`
#
# The kinds and the value functions. A `Value` subclass cannot live
# in a notebook cell: the `db/value` row names its class by dotted
# name (`Ref.type`), and a class defined in `__main__` has no name a
# later `load` can import. So the cell below is the module's text,
# for reading, and its last line imports the real thing: in the real
# notebook these come from `demo_svp/svp/game.py`.

# %%
@ledger_class(preds=("game", "camera"))
class Video(Value):                       # svp.game.Video
    def __init__(self, frames: bytes):
        self.frames = frames
    def encode(self) -> bytes:
        return self.frames
    @classmethod
    def decode(cls, data, store):
        return cls(data)


@ledger_class(preds=("game", "version", "video", "team"))
class Cut(Value):                         # svp.game.Cut
    def __init__(self, clip: bytes):
        self.clip = clip
    def encode(self) -> bytes:
        return self.clip
    @classmethod
    def decode(cls, data, store):
        return cls(data)


def cut_video(raw, home, away):           # the version is not in
    return raw.frames[:16] + f"|{home}-{away}".encode()   # the bytes


@ledger_fn
def cut(rev, *, game: str, version: str) -> Cut:     # svp.game.cut
    home = rev[f"game/{game}", "home"]      # traced: game/G1 home
    away = rev[f"game/{game}", "away"]      # traced: game/G1 away
    raw = rev.value(kind=Video, game=game)  # traced: by its bytes
    c = Cut(cut_video(raw, home, away))
    c.preds.update(game=game, version=version, video=raw,
                   team=[home, away])
    return c


@ledger_fn
def thumb(rev, *, clip: Ref) -> dict:     # svp.game.thumb
    c = clip.load()
    return {"bytes": len(c.clip), "head": c.clip[:4].hex()}


from svp.game import Video, Cut, cut, thumb   # the importable ones

# %% [markdown]
# `@ledger_class(preds=...)` names the preds a kind may carry, never
# their values. `@ledger_fn` marks a value function; its return
# annotation is required and is the kind it returns. Neither writes
# a row on import.

# %% [markdown]
# ## The game: a plain subject

# %%
with L.transaction(by="human:dan", why="season opener") as t:
    t["code/sv-pipe"] = {"version": "0.2.2", "commit": "7d742989"}
    t["game/G1"] = {"home": "G4", "away": "G5",
                    "date": "2026-10-11", "court": "north"}
    t["game/G2"] = {"home": "G1", "away": "G3",
                    "date": "2026-10-12", "court": "east"}
    t.add("db/pred/team", "db/cardinality", "many")
    t.add("db/pred/video", "db/type", "svp.game.Video")
rev = L.at()
print(rev["game/G1"])
print(rev["db/pred/video", "db/type"])    # "svp.game.Video"

# %% [markdown]
# `game/G1` holds no value: it is rows. `team` is declared `many`,
# so a cut's teams are a list. `video` is typed: its object must be
# a `Video`, stored as `ref:svp.game.Video:<hash>`, an edge of the
# value graph.

# %% [markdown]
# ## A hand-made value: the raw video

# %%
raws = {}
for g in ("G1", "G2"):
    raw = Video(f"{g} wide camera, frames 0-9000".encode())
    raw.preds.update(game=g, camera="wide")   # a dict until sealed
    raws[g] = raw
with L.transaction(by="human:dan") as t:
    for g, raw in raws.items():
        t.add_value(raw, alias=f"video/{g}",
                    provenance="import:alg2")
raw = raws["G1"]
print(raw.sealed, raw.subject[:8])   # True, its hash
print(raw)                           # video/G1: the shortest alias
print(raw.trace)                     # the environment: no deps
# {"code/sv-pipe": "0.2.2+7d742989", "uv.lock": "sha256:5e1f",
#  "platform": "darwin-arm64-py3.11"}

# %% [markdown]
# Preds are set on the object before the seal, by whoever builds
# it; `add_value` takes no `preds=`. The seal fixes `subject`,
# `rev` and `trace` and freezes `preds`. The subject is a hash of
# the trace, the preds and the bytes; `video/G1` is only a
# `db/alias` row naming it.

# %%
try:
    raw.preds["camera"] = "tele"
except TypeError as e:
    print("TypeError:", e)          # read-only once sealed

bad = Video(b"G1 tele camera")
bad.preds.update(game="G1", team="G4")
try:
    with L.transaction(by="human:dan") as t:
        t.add_value(bad)
except Undeclared as e:
    print("Undeclared:", e)         # team: not a Video pred

del bad.preds["team"]
try:
    with L.transaction(by="human:dan") as t:
        t.add_value(bad, provenance="eval:sandbox")
except ValueError as e:
    print("ValueError:", e)         # eval: is eval's word alone

try:
    with L.transaction(by="human:dan") as t:
        t.add("video/G1-tele", "db/value", bad)
except TypeError as e:
    print("TypeError:", e)          # names add_value

# %% [markdown]
# Four refusals, nothing written by any: a sealed value's preds are
# read-only; a pred the kind did not declare is `Undeclared`; a hand
# seal may give any provenance but `eval:...`, which only `eval`
# writes; and bytes enter the ledger by `add_value` alone.

# %% [markdown]
# ## Cutting is a value function

# %%
rev = L.at()
c3 = rev.eval("svp.game.cut", game="G1", version="1.5.3")
print(c3, c3.sealed, c3.rev.id)    # <hash[:8]> True <rev>
print(c3.preds)
# {"game": "G1", "version": "1.5.3",
#  "video": Ref(video/G1), "team": ["G4", "G5"]}
print(c3.trace)
# {"code/sv-pipe": "0.2.2+7d742989", "uv.lock": "sha256:5e1f",
#  "platform": "darwin-arm64-py3.11",
#  "game/G1 home": "G4", "game/G1 away": "G5",
#  "ref:svp.game.Video:<hash>": "ref:svp.game.Video:<hash>"}

# %% [markdown]
# The miss ran the body and sealed the cut in its own revision.
# The trace is recorded, not declared: the two game rows read by
# name, the video by its bytes, and (base mode: `svp.game` is not
# mounted) the code as `code/sv-pipe`. The preds are what the body
# put in `c.preds`; the keys are one `db/keys` row, not preds.

# %%
top = L.at().id
again = L.at().eval("svp.game.cut", game="G1", version="1.5.3")
print(again.subject == c3.subject)    # True: a hit
print(L.at().id == top)               # True: nothing written
print(L.at().eval("svp.game.cut", game="G2", version="1.5.3",
                  memo="get"))        # None: never run
c2 = L.at().eval("svp.game.cut", game="G2", version="1.5.3")

# %% [markdown]
# The second call is a memo hit: same function, same keys, every
# trace item unchanged. It writes nothing. `memo="get"` looks
# without running.

# %% [markdown]
# ## The current cut is an alias on the game

# %%
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "db/alias", c3.subject)
    t.add("game/G2", "db/alias", c2.subject)
rev = L.at()
print(rev["game/G1"])
# {"home": "G4", "away": "G5", "date": "2026-10-11",
#  "court": "north", "db/alias": Ref(game/G1)}
cur = rev.load("game/G1")
print(cur.same_as(c3))                # True
print(cur.preds["video"])             # Ref(video/G1): unloaded
print(cur.preds["video"].load())      # the video: the explicit act

# %% [markdown]
# `rev["game/G1"]` is literal: the game's own rows, its `db/alias`
# row among them as an unloaded `Ref` (printed by its shortest
# alias, which is `game/G1` itself). `rev.load("game/G1")` follows
# the alias to the current cut. Loading decodes the top value only:
# the cut's `video` stays a `Ref` until its own `load()`.

# %%
r = Ref(rev, "game/G1")
print(r.name, r.subject == c3.subject)   # game/G1 True
print(r.type, r.preds["version"])        # svp.game.Cut 1.5.3
try:
    with L.transaction(by="human:dan") as t:
        t["game/G1", "court"] = "south"
except TypeError as e:
    print("TypeError:", e)   # a bracket write on an alias name

# %% [markdown]
# A `Ref` resolves the alias when made: `name` is what you said,
# `subject` the cut's hash, `preds` the cut's. Because `game/G1` now
# holds an alias row, the bracket write refuses it; its plain rows
# are written with `add` (the last section does).

# %% [markdown]
# ## Values are found by their preds

# %%
rev = L.at()
print(rev.values(game="G1"))             # [video/G1, game/G1]
print(rev.values(kind=Cut, game="G1"))   # [game/G1]
v = rev.value(game="G1", version="1.5.3")
print(v.same_as(c3))                     # True: exactly one
print(rev.values(team="G1"))             # [game/G2]: any member
try:
    rev.value(kind=Cut)
except Multiple as e:
    print("Multiple:", e)                # two cuts

# %% [markdown]
# `values` and `value` are the main way into the value table: a
# where clause over preds, the matches loaded. A bare keyword names
# a pred, whoever wrote it, so `game="G1"` finds the video and the
# cut; `kind=` narrows to a class. On a `many` pred a keyword
# matches any member: team `G1` plays in game `G2`.

# %%
refs = rev.refs(kind=Cut)
print([(r, r.preds["version"], r.preds["team"]) for r in refs])
# [(game/G1, "1.5.3", ["G4", "G5"]), (game/G2, "1.5.3", [...])]
print(rev.select(("game", "version"), kind=Cut))
# [("G1", "1.5.3"), ("G2", "1.5.3")]

# %% [markdown]
# `refs` says who matched without loading; `Ref.preds` reads the
# preds as of the ref's revision, so refs can be filtered and sorted
# before any bytes move. `select` projects chosen preds to tuples.

# %% [markdown]
# ## Annotation is open; a sealed pred is not

# %%
with L.transaction(by="human:dan", why="court survey") as t:
    for r in L.at().refs(kind=Cut):
        t.add(r.subject, "texture", "hardwood")
rev = L.at()
print(Ref(rev, "game/G1").preds["texture"])     # "hardwood"
print(len(rev.values(kind=Cut, texture="hardwood")))   # 2

# %% [markdown]
# `texture` is not one of the preds the seal froze (the `db/preds`
# row lists what was declared at the seal), so it is annotation:
# allowed on a sealed value in any later transaction, and part of
# the one view of its preds.

# %%
cur = rev.load("game/G1")
trim = Cut(cur.clip[:12])                       # trimmed by hand
trim.preds.update(game="G1", team=["G4", "G6"],     # G6: a typo
                  video=cur.preds["video"])         # a Ref is fine
with L.transaction(by="human:dan") as t:
    wrong = t.add_value(trim, deps=[cur], alias="game/G1",
                        provenance="human:dan")
print(Ref(L.at(), "game/G1").preds["team"])     # ["G4", "G6"]
try:
    with L.transaction(by="human:dan") as t:
        t.add(wrong, "team", "G5")              # fix it in place
except Exists as e:
    print("Exists:", e)

# %% [markdown]
# A hand trim, sealed and made the current cut in one transaction
# (seal, then re-point). It left `version` unset, so `version` is
# frozen absent. Its `team` pred is wrong, and a pred the seal wrote
# cannot be edited: the in-place `add` raises `Exists` at commit and
# writes nothing.

# %%
fixed = Cut(trim.clip)                          # the same bytes
fixed.preds.update(game="G1", team=["G4", "G5"],
                   video=trim.preds["video"])
with L.transaction(by="human:dan", why="team typo") as t:
    right = t.add_value(fixed, deps=[cur], alias="game/G1",
                        provenance="human:dan")
rev = L.at()
print(right != wrong, fixed.same_as(trim))      # True True
print(Ref(rev, "game/G1").preds["team"])        # ["G4", "G5"]
print(rev.refs(kind=Cut, team="G6"))            # [<hash[:8]>]

# %% [markdown]
# The correction is a new seal with the right preds and the alias
# re-pointed. Preds are in the subject's hash, so the same bytes
# make a new subject, sharing one blob. The wrong one stays,
# immutable, still found by `team="G6"`, printed by its hash since
# no alias names it now.

# %% [markdown]
# ## A new version: seal, then re-point

# %%
rev = L.at()
c4 = rev.eval("svp.game.cut", game="G1", version="1.5.4")
print(c4)                                # its hash: no alias yet
print(c4.same_as(c3), c4.subject != c3.subject)   # True True
with L.transaction(by="human:dan", why="cutter 1.5.4") as t:
    t.add("game/G1", "db/alias", c4.subject)
print(c4)                                # game/G1
try:
    with L.transaction(by="human:dan") as t:
        bump(t, "game/G1")
except TypeError as e:
    print("TypeError:", e)               # names the alias

# %% [markdown]
# A value's `version` is a pred its constructor sets; a new version
# is a new value and the alias moved to it. `bump` is for clocks
# (`code/<repo>`, `db`) and refuses an alias name. The 1.5.4 cut has
# the same bytes as 1.5.3 (the stand-in cutter ignores its version):
# two memo entries, two subjects, one blob, `same_as` true.

# %%
rev = L.at()
t3 = rev.eval("svp.game.thumb", clip=Ref(rev, c3.subject))
top = L.at().id
t4 = rev.eval("svp.game.thumb", clip=Ref(rev, c4.subject))
print(t4.subject == t3.subject, L.at().id == top)   # True True
print(type(t3).__name__)                 # Pickled: -> dict
f = rev.load_fn("svp.game.thumb")
print(L.at()[f.subject, "db/returns"])   # "dict"

# %% [markdown]
# A `Value` or `Ref` enters keys and traces by its bytes,
# `ref:<class>:<hash>`, never by the entry it came from. So `thumb`
# keyed by the 1.5.4 cut hits the entry made for the 1.5.3 cut. A
# function annotated with a plain type returns `Pickled`, and the
# annotation is kept on its `db/fn/...` subject.

# %% [markdown]
# ## Why: `matches` and `diff`

# %%
rev = L.at()
print(c3.matches(rev), c4.matches(rev))     # True True
with L.transaction(by="human:dan", why="date typo") as t:
    t.add("game/G1", "date", "2026-10-10")
print(c4.matches(L.at()))                   # True: date not read
with L.transaction(by="human:dan", why="home was G6") as t:
    t.add("game/G1", "home", "G6")
rev = L.at()
print(c4.matches(rev))                      # False

# %% [markdown]
# `matches(rev)` re-reads every trace item at `rev`. The cut never
# read the date, so correcting it changes nothing; it read `home`,
# so correcting the teams makes it stale.

# %%
c5 = rev.eval("svp.game.cut", game="G1", version="1.5.4")
print(c5.subject != c4.subject)             # True: re-derived
print(c5.preds["team"])                     # ["G6", "G5"]
print(c4.diff(c5))
# {"game/G1 home": ("G4", "G6")}
print(rev.load("game/G1").same_as(c4))      # True: alias unmoved
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "db/alias", c5.subject)

# %% [markdown]
# The next `eval` misses and re-derives; `diff` names the one trace
# item that moved. The alias does not follow by itself: the current
# cut moves when someone re-points it.

# %% [markdown]
# ## Names: the shortest alias, and every alias

# %%
with L.transaction(by="human:dan") as t:
    t.add("raw/G1/wide-camera", "db/alias", raw.subject)
rev = L.at()
r = Ref(rev, "raw/G1/wide-camera")
print(r)                     # video/G1: the shortest, as of the head
print(r.name)                # raw/G1/wide-camera: what you said
print(r.aliases)             # ["raw/G1/wide-camera", "video/G1"]
print(r.preds)               # {"game": "G1", "camera": "wide"}

# %% [markdown]
# A sealed value or its `Ref` prints as the shortest alias naming
# it, else the first eight characters of its hash. `Ref.aliases`
# lists every name; `Ref.preds` reads the preds without loading.
