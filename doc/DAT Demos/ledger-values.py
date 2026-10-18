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
# Written to the ledger design of 2026-10-18 (SVP447 Ledger Module,
# Values § The worked example, F447 A39–A44). It runs once
# `ledger2` is rebuilt to that design (T534); until then it is the
# design, not a demo.

# %%
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dvc_dat.ledger import Ledger, Ref, bump
from dvc_dat.ledger import AliasLoop, Exists, Multiple, Undeclared
from dvc_dat.ledger import Code, Env, set_env_provider

sys.path.insert(0, "demo_svp")           # the stand-in svp package
scratch_ledger_path = Path("scratch/values-demo/ledger").resolve()
L = Ledger(scratch_ledger_path, create=True)   # the one explicit act

ENV = Env({"sv-pipe": Code("0.2.2", "7d742989")},
          lock="sha256:5e1f", platform="darwin-arm64-py3.11")
set_env_provider(lambda module: ENV)

# %% [markdown]
# A notebook runs inside no sv-pipe checkout, so the environment
# provider stands in for one: it is what `eval` and `bump` ask for
# the commit the code is at.

# %% [markdown]
# ## The module: `svp.game`
#
# The kinds and value functions live in `demo_svp/svp/game.py`: a
# `Value` subclass defined in a cell has no dotted name for a later
# `load` to import. The kind of a raw video:
#
# ```python
# @ledger_class(preds=("game", "camera", "span"))
# class Video(Value):
#     """A game's raw video, as imported."""
#
#     def __init__(self, frames: bytes):
#         self.frames = frames
#
#     def encode(self) -> bytes:
#         return self.frames
#
#     @classmethod
#     def decode(cls, data: bytes, store) -> "Video":
#         return cls(data)
# ```
#
# `Cut` has the same shape, holding `clip`, under
# `@ledger_class(preds=("game", "version", "video", "team"))`.
# Cutting:
#
# ```python
# @ledger_fn
# def cut(rev, *, game: str, version: str) -> Cut:
#     """Cut a game: rows read through `rev`, the video by preds."""
#     home = rev[f"game/{game}", "home"]      # traced: game/G1 home
#     away = rev[f"game/{game}", "away"]      # traced: game/G1 away
#     raw = rev.value(kind=Video, game=game)  # traced: q: and bytes
#     c = Cut(cut_video(raw, home, away))
#     c.preds.update(game=game, version=version,
#                    video=raw,               # a Video-typed pred
#                    team=[home, away])       # a many pred: a list
#     return c
# ```
#
# `@ledger_class` names the preds a kind may carry, never their
# values; `@ledger_fn` marks a value function, its return annotation
# required. Neither writes a row on import. `cut_video` ignores the
# version, so two versions of a cut can be byte-identical. The
# module's other functions are quoted where they are used.

# %%
from svp.game import Video, Cut, Still

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
    t.add("db/pred/span", "db/type", "json")
rev = L.at()
print(rev["game/G1"])
# {"home": "G4", "away": "G5", "date": "2026-10-11",
#  "court": "north"}
print(rev["db/pred/video", "db/type"])    # svp.game.Video

# %% [markdown]
# `game/G1` holds no value: it is rows. `team` is declared `many`,
# so a cut's teams are a list. `video` is typed: its object must be
# a `Video`, stored `ref:svp.game.Video:<hash>`, an edge of the
# value graph. `span` is typed `json`, so a `one` pred may hold a
# list (A36).

# %% [markdown]
# ## A hand-made value: the raw video

# %%
video_values = {}
for g, n in (("G1", 9000), ("G2", 8400)):
    video = Video(f"{g} wide camera, {n} frames".encode())
    video.preds.update(game=g, camera="wide", span=[0, n])
    video_values[g] = video
with L.transaction(by="human:dan") as t:
    for g, video in video_values.items():
        t.add_value(video, alias=f"video/{g}",
                    provenance="import:alg2")
video_value = video_values["G1"]
print(video_value.sealed, video_value)  # True video/G1
print(video_value.subject[:8])       # the hash the alias names
print(video_value.preds["span"])     # [0, 9000]: one pred, a list
print(dict(sorted(video_value.trace.items())))
# {"code/sv-pipe": "0.2.2+7d742989",
#  "platform": "darwin-arm64-py3.11", "uv.lock": "sha256:5e1f"}

# %% [markdown]
# Preds are set on the object before the seal, by whoever builds
# it; `add_value` takes no `preds=`. The seal fixes `subject`,
# `rev` and `trace` and freezes `preds`. With no `deps` the trace
# is the environment alone. The subject is a hash of the trace, the
# preds and the bytes; `video/G1` is a `db/alias` row naming it, and
# the value prints as that name.

# %% [markdown]
# Once sealed, `preds` is read-only.

# %%
try:
    video_value.preds["camera"] = "tele"
except TypeError as e:
    print("TypeError:", e)

# %% [markdown]
# A pred the kind did not declare is refused at the seal.

# %%
bad_video = Video(b"G1 tele camera, 9000 frames")
bad_video.preds.update(game="G1", camera="tele", team="G4")
try:
    with L.transaction(by="human:dan") as t:
        t.add_value(bad_video)
except Undeclared as e:
    print("Undeclared:", e)          # team: not a Video pred

# %% [markdown]
# A refused seal leaves the value exactly as it was, unsealed, its
# `preds` a plain dict (A43), so the wrong `team` can simply be
# taken out of the same object. A list under an untyped `one` pred
# is refused next.

# %%
print(bad_video.sealed)              # False: nothing was written
del bad_video.preds["team"]
bad_video.preds["camera"] = ["tele", "wide"]
try:
    with L.transaction(by="human:dan") as t:
        t.add_value(bad_video)
except TypeError as e:
    print("TypeError:", e)           # camera: a one pred, not json

# %% [markdown]
# A hand seal may name any provenance but one beginning `eval:`,
# which `eval` alone writes.

# %%
bad_video.preds["camera"] = "tele"
try:
    with L.transaction(by="human:dan") as t:
        t.add_value(bad_video, provenance="eval:sandbox")
except ValueError as e:
    print("ValueError:", e)

# %% [markdown]
# Bytes enter the ledger by `add_value` alone: `add` refuses a
# `Value` and names `add_value`.

# %%
try:
    with L.transaction(by="human:dan") as t:
        t.add("video/G1-tele", "note", bad_video)
except TypeError as e:
    print("TypeError:", e)

# %% [markdown]
# ## Cutting is a value function

# %%
rev = L.at()
cut_153 = rev.eval("svp.game.cut", game="G1", version="1.5.3")
print(cut_153, cut_153.sealed)       # <8 hex> True: no alias yet
print(cut_153.rev.id > rev.id)       # True: sealed in its own rev
print(sorted(cut_153.preds["team"]), cut_153.preds["video"])
# ["G4", "G5"] video/G1
for item in sorted(cut_153.trace):
    print(item, "->", cut_153.trace[item])
# code/sv-pipe -> 0.2.2+7d742989
# fn -> db/fn/svp.game.cut/<hash>
# game/G1 away -> G5
# game/G1 home -> G4
# platform -> darwin-arm64-py3.11
# q:{"game":"G1","kind":"svp.game.Video"}
#     -> ["ref:svp.game.Video:<hash>"]
# ref:svp.game.Video:<hash> -> ref:svp.game.Video:<hash>
# uv.lock -> sha256:5e1f

# %% [markdown]
# The miss ran the body and sealed the cut in a revision of its
# own, which is `cut_153.rev`. The trace is recorded, not
# declared: `fn`, the code the name resolved to (in base mode too,
# beside `code/sv-pipe`, A39); the two game rows read by name; the
# `value` query as a `q:` item holding what it answered, so a second
# G1 video later is a miss rather than a stale hit (A41); the video
# by its bytes. The preds are what the body put in `c.preds`; the keys
# are one `db/keys` row, not preds.

# %%
top_id = L.at().id
again_cut = L.at().eval("svp.game.cut", game="G1", version="1.5.3")
print(again_cut.subject == cut_153.subject)  # True: a hit
print(L.at().id == top_id)           # True: nothing written
print(again_cut.rev.id == cut_153.rev.id)  # True: still the seal's rev

# %% [markdown]
# The second call is a memo hit: same function, same keys, every
# trace item unchanged. It writes nothing, and the value it hands
# back carries the revision it was sealed in.

# %% [markdown]
# `memo="get"` looks without running; `memo=False` runs without
# sealing, and its bytes are what a memoised call would return.

# %%
rev = L.at()
print(rev.eval("svp.game.cut", game="G2", version="1.5.3",
               memo="get"))          # None: never run
dry_cut = rev.eval("svp.game.cut", game="G1", version="1.5.3",
                   memo=False)
print(dry_cut.sealed, dry_cut.same_as(cut_153))  # False True
print(L.at().id == rev.id)           # True: nothing written

# %% [markdown]
# `eval` is `load_fn` and a call. The `Fn` says which code a name
# resolves to at this rev, and calling it is the eval.

# %%
cut_fn = rev.load_fn("svp.game.cut")
print(cut_fn.mode, cut_fn.signature)
# base (*, game: str, version: str)
print(cut_fn.sha[:8], cut_fn.subject)
# <8 hex> db/fn/svp.game.cut/<hash>
print(cut_153.trace["fn"] == cut_fn.subject)   # True: the code ran
cut_g2 = cut_fn(game="G2", version="1.5.3")  # a miss: runs and seals

# %% [markdown]
# Memo entries are subjects like any other: `fn=` finds every
# evaluation of a function, and each one's question is its
# `db/keys` row.

# %%
rev = L.at()
for memo_ref in rev.refs(fn="svp.game.cut"):
    print(memo_ref, rev[memo_ref.subject, "db/keys"])
# <8 hex> {"game": "G1", "version": "1.5.3"}
# <8 hex> {"game": "G2", "version": "1.5.3"}
print(len(rev.values(fn="svp.game.cut")))    # 2, loaded

# %% [markdown]
# ## The current cut is an alias on the game

# %%
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "db/alias", cut_153.subject)
    t.add("game/G2", "db/alias", cut_g2.subject)
rev = L.at()
print(rev["game/G1"])
# {"home": "G4", "away": "G5", "date": "2026-10-11",
#  "court": "north", "db/alias": "<c3's subject, 64 hex>"}
print(cut_153)                       # game/G1: it has a name now

# %% [markdown]
# `rev["game/G1"]` is literal: the game's own rows, its `db/alias`
# row among them, whose object is the cut's subject as a plain
# `str`. The cut now prints as `game/G1`, its shortest alias as of
# the head.

# %% [markdown]
# ### A `ref:` row
#
# A `Ref` may be any row's object. `add` stores it as
# `ref:<class>:<hash>:<subject>`, the subject a hint; every pattern
# read hands it back as a `Ref`, unloaded, printed as its shortest
# alias, else the hash's first eight characters.

# %%
with L.transaction(by="human:dan") as t:
    t.add("review/G1", "cut", Ref(t.base, cut_153.subject))
pick_ref = L.at()["review/G1", "cut"]
print(pick_ref, pick_ref.subject == cut_153.subject)  # game/G1 True

# %%
current_cut = rev.load("game/G1")
print(current_cut.same_as(cut_153),
      current_cut.subject == cut_153.subject)     # True True
video_ref = current_cut.preds["video"]
print(type(video_ref).__name__, video_ref.type)
# Ref <class 'svp.game.Video'>
print(video_ref.preds)
# {"game": "G1", "camera": "wide", "span": [0, 9000]}: no load
loaded_video = video_ref.load()   # the one explicit act
print(type(loaded_video), loaded_video.sealed)
# <class 'svp.game.Video'> True

# %% [markdown]
# `rev.load("game/G1")` follows the alias to the current cut.
# Loading decodes the top value only: the cut's `video` is a `Ref`
# whose type and preds are readable without fetching a byte, until
# its own `load()`.

# %%
game_ref = Ref(rev, "game/G1")
print(game_ref, game_ref.name)    # game/G1 game/G1
print(game_ref.subject == cut_153.subject)  # True: the alias, resolved
print(game_ref.type)              # <class 'svp.game.Cut'>
print(game_ref.preds["version"])  # 1.5.3: the cut's preds
print(game_ref.sealed_at.id == cut_153.rev.id)  # True: its db/value row

# %% [markdown]
# A `Ref` resolves the alias when made: `name` is what you said,
# `subject` the cut's hash, `preds` the cut's. `sealed_at` is the
# revision of the `db/value` row, read from rows the `Ref` already
# holds.

# %% [markdown]
# The game's own rows are corrected with the bracket, literal on
# `game/G1` though it holds an alias row (A34): one row, or the
# whole record. The record form ranges over user rows only, so the
# `db/alias` row survives it.

# %%
with L.transaction(by="human:dan", why="court renamed") as t:
    t["game/G1", "court"] = "C2"
with L.transaction(by="human:dan", why="date typo") as t:
    t["game/G1"] = {"home": "G4", "away": "G5",
                    "date": "2026-10-10", "court": "C2"}
rev = L.at()
print(rev["game/G1", "date"], rev["game/G1", "court"])
# 2026-10-10 C2
print(rev.load("game/G1").same_as(cut_153))  # True: alias untouched
print(cut_153.matches(rev))              # True: cut read neither

# %% [markdown]
# ## Values are found by their preds

# %%
rev = L.at()
print(rev.values(game="G1"))       # video/G1 and game/G1
print(rev.values(kind=Cut, game="G1"))   # [game/G1]
print(rev.values(team="G1"))             # [game/G2]: any member

# %% [markdown]
# `values` is the main way into the value table: a where clause
# over preds, the matches loaded, in no promised order. A bare
# keyword names a pred, whoever wrote it, so `game="G1"` finds the
# video and the cut; `kind=` narrows to a class. On a `many` pred a
# keyword matches any member: team `G1` plays in game `G2`.

# %% [markdown]
# `value` is exactly one, or it raises: two cuts match `kind=Cut`.

# %%
print(rev.value(game="G1", version="1.5.3").same_as(cut_153))  # True
try:
    rev.value(kind=Cut)
except Multiple as e:
    print("Multiple:", e)

# %%
cut_refs = rev.refs(kind=Cut)
print([(cut_ref, sorted(cut_ref.preds["team"]))
       for cut_ref in cut_refs])
# (game/G1, ["G4", "G5"]) and (game/G2, ["G1", "G3"])
print(max(cut_refs, key=lambda r: r.sealed_at.id))   # game/G2
print(rev.select(("game", "version"), kind=Cut))
# ("G1", "1.5.3") and ("G2", "1.5.3")

# %% [markdown]
# `refs` says who matched without loading: `Ref.preds` and
# `Ref.sealed_at` come with the rows, so refs can be filtered and
# sorted before any bytes move, and the latest is a `max` over
# `sealed_at`. `select` projects chosen preds to tuples.

# %% [markdown]
# ## A value read through an alias
#
# `poster` reaches the game's current cut by its name:
#
# ```python
# @ledger_fn
# def poster(rev, *, game: str) -> dict:
#     """Downstream of the game's current cut, reached by its alias."""
#     c = rev.load(f"game/{game}")    # traced: game/G1 db/alias
#     return {"game": game, "bytes": len(c.clip)}
# ```

# %%
rev = L.at()
poster_value = rev.eval("svp.game.poster", game="G1")
for item in sorted(poster_value.trace):
    if item.startswith(("game/", "ref:")):
        print(item, "->", poster_value.trace[item])
# game/G1 db/alias -> ref:svp.game.Cut:<cut_153 bytes>
# ref:svp.game.Cut:<cut_153 bytes> -> ref:svp.game.Cut:<cut_153 bytes>

# %% [markdown]
# The load through `game/G1` recorded the binding, the name to the
# bytes it resolved to, beside the value item. Neither holds the
# subject (A35): what `poster` depends on is the bytes the name
# gives, not the entry they sit in.

# %% [markdown]
# ## A new version: seal, then re-point

# %%
cut_154 = rev.eval("svp.game.cut", game="G1", version="1.5.4")
print(cut_154)                           # <8 hex>: no alias yet
print(cut_154.same_as(cut_153),
      cut_154.subject != cut_153.subject)         # True True
with L.transaction(by="human:dan", why="cutter 1.5.4") as t:
    t.add("game/G1", "db/alias", cut_154.subject)
rev = L.at()
print(cut_154, cut_153)                  # game/G1 <8 hex>
print(poster_value.matches(rev))         # True: identical bytes
poster4_value = rev.eval("svp.game.poster", game="G1")
print(poster4_value.subject == poster_value.subject)  # True: a hit

# %% [markdown]
# A value's `version` is a pred its constructor sets; a new version
# is a new value and the alias moved to it. The 1.5.4 cut has the
# bytes of 1.5.3 (the stand-in cutter ignores its version): two
# memo entries, two subjects, one blob. `game/G1` now names
# identical bytes, so `poster` still hits (A35, A21).

# %% [markdown]
# `bump` moves clocks (`code/<repo>`, `db`); on a name holding a
# `db/alias` row it raises, naming the alias.

# %%
try:
    with L.transaction(by="human:dan") as t:
        bump(t, "game/G1")
except TypeError as e:
    print("TypeError:", e)

# %% [markdown]
# `thumb(rev, *, clip: Ref) -> dict` takes a cut as its key.

# %%
rev = L.at()
thumb3_value = rev.eval("svp.game.thumb",
                        clip=Ref(rev, cut_153.subject))
top_id = L.at().id
thumb4_value = rev.eval("svp.game.thumb",
                        clip=Ref(rev, cut_154.subject))
print(thumb4_value.subject == thumb3_value.subject,
      L.at().id == top_id)                        # True True
print(type(thumb3_value).__name__)       # Pickled: -> dict
print(L.at()[thumb3_value.trace["fn"], "db/returns"])  # dict

# %% [markdown]
# A `Value` or `Ref` enters keys and traces by its bytes,
# `ref:<class>:<hash>`, never by the entry it came from. So `thumb`
# keyed by the 1.5.4 cut hits the entry made for the 1.5.3 cut. A
# function annotated with a plain type returns `Pickled`, and the
# annotation is kept on its `db/fn/...` subject.

# %% [markdown]
# ## Annotation is open; a sealed pred is not

# %%
with L.transaction(by="human:dan", why="court survey") as t:
    for cut_ref in L.at().refs(kind=Cut):
        t.add(cut_ref.subject, "texture", "hardwood")
rev = L.at()
print(Ref(rev, "game/G1").preds["texture"])     # hardwood
print(len(rev.values(kind=Cut, texture="hardwood")))   # 3

# %% [markdown]
# `texture` is not one of the preds the seals froze (each `db/preds`
# row lists what the kind declared at its seal), so it is
# annotation: allowed on a sealed value in any later transaction,
# and part of the one view of its preds.

# %%
trim_cut = Cut(cut_154.clip[:12])              # trimmed by hand
trim_cut.preds.update(game="G1",
                      team=["G4", "G6"],          # G6: a typo
                      video=cut_154.preds["video"])   # a Ref is fine
with L.transaction(by="human:dan") as t:
    wrong_subject = t.add_value(trim_cut, deps=[cut_154],
                                alias="game/G1",
                                provenance="human:dan")
print(sorted(Ref(L.at(), "game/G1").preds["team"]))  # G4, G6

# %% [markdown]
# A hand trim, sealed and made the current cut in one transaction:
# seal, then re-point. It left `version` unset, so `version` is
# frozen absent. Its `team` is wrong, and a pred the seal wrote
# cannot be edited: an `add` on it raises `Exists` at commit and
# writes nothing.

# %%
try:
    with L.transaction(by="human:dan") as t:
        t.add(wrong_subject, "team", "G5")
except Exists as e:
    print("Exists:", e)

# %% [markdown]
# A `remove` of a frozen pred is refused the same way (A38).

# %%
try:
    with L.transaction(by="human:dan") as t:
        t.remove(wrong_subject, "team", "G6")
except Exists as e:
    print("Exists:", e)

# %%
fixed_cut = Cut(trim_cut.clip)                  # the same bytes
fixed_cut.preds.update(game="G1", team=["G4", "G5"],
                       video=trim_cut.preds["video"])
with L.transaction(by="human:dan", why="team typo") as t:
    right_subject = t.add_value(fixed_cut, deps=[cut_154],
                                alias="game/G1",
                                provenance="human:dan")
rev = L.at()
print(right_subject != wrong_subject,
      fixed_cut.same_as(trim_cut))                # True True
print(sorted(Ref(rev, "game/G1").preds["team"]))     # G4, G5
print(rev.refs(kind=Cut, team="G6"))            # [<8 hex>]

# %% [markdown]
# The correction is a new seal with the right preds and the alias
# re-pointed. Preds are in the subject's hash, so the same bytes
# make a new subject, sharing one blob. The wrong one stays,
# immutable, still found by `team="G6"`, printed by its hash since
# no alias names it now.

# %%
print(poster_value.matches(rev))         # False
poster5_value = rev.eval("svp.game.poster", game="G1")
print(sorted(poster_value.diff(poster5_value)))
# the game/G1 db/alias binding, and each side's value item

# %% [markdown]
# `game/G1` now names the trim, whose bytes differ from the 1.5.4
# cut's, so `poster`'s binding item moved and the next eval
# re-derives.

# %% [markdown]
# ## Why: `matches` and `diff`

# %%
rev = L.at()
print(cut_154.matches(rev))                 # True
with L.transaction(by="human:dan", why="home was G6") as t:
    t["game/G1", "home"] = "G6"
rev = L.at()
print(cut_154.matches(rev))                 # False

# %% [markdown]
# `matches(rev)` re-reads every trace item at `rev`. The cut never
# read the court or the date, so their corrections changed
# nothing; it read `home`, so correcting the teams makes it stale.

# %%
cut_home_g6 = rev.eval("svp.game.cut", game="G1", version="1.5.4")
print(cut_home_g6.subject != cut_154.subject)  # True: re-derived
print(sorted(cut_home_g6.preds["team"]))    # ["G5", "G6"]
print(cut_154.diff(cut_home_g6))
# {"game/G1 home": ("G4", "G6")}
print(rev.load("game/G1").same_as(fixed_cut))  # True: alias unmoved
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "db/alias", cut_home_g6.subject)

# %% [markdown]
# The next `eval` misses and re-derives; `diff` names the one trace
# item that moved. The alias does not follow by itself: the current
# cut moves when someone re-points it.

# %% [markdown]
# ## Names: the shortest alias, and every alias

# %%
with L.transaction(by="human:dan") as t:
    t.add("raw/G1/wide-camera", "db/alias", video_value.subject)
rev = L.at()
camera_ref = Ref(rev, "raw/G1/wide-camera")
print(camera_ref)            # video/G1: the shortest, as of the head
print(camera_ref.name)       # raw/G1/wide-camera: what you said
print(sorted(camera_ref.aliases))  # ["raw/G1/wide-camera", "video/G1"]

# %% [markdown]
# A sealed value or its `Ref` prints as the shortest alias naming
# it, else the first eight characters of its hash. `Ref.aliases`
# lists every name.

# %% [markdown]
# An alias may name another alias, and `Ref` follows at most 8
# hops; a ninth, like a cycle, is `AliasLoop`.

# %%
with L.transaction(by="human:dan") as t:
    t.add("hop-chain/1", "db/alias", video_value.subject)
    for i in range(2, 10):
        t.add(f"hop-chain/{i}", "db/alias", f"hop-chain/{i - 1}")
print(Ref(L.at(), "hop-chain/8").subject == video_value.subject)  # True
try:
    Ref(L.at(), "hop-chain/9")
except AliasLoop as e:
    print("AliasLoop:", e)

# %% [markdown]
# ## Two entries for one question
#
# ```python
# @ledger_fn
# def noisy(rev, *, game: str) -> dict:
#     """A nondeterministic stand-in (T527's case): runs disagree."""
#     time.sleep(1)                   # long enough for two to race
#     return {"game": game, "draw": random.random()}
# ```

# %%
rev = L.at()
def ask(_):
    return rev.eval("svp.game.noisy", game="G1")
with ThreadPoolExecutor(2) as pool:
    a_value, b_value = pool.map(ask, range(2))  # both miss, both run
print(a_value.same_as(b_value),
      a_value.subject != b_value.subject)         # False True
noisy_refs = L.at().refs(fn="svp.game.noisy")
print(len(noisy_refs))                  # 2: one question, both kept
latest_ref = max(noisy_refs, key=lambda r: r.sealed_at.id)
hit_value = L.at().eval("svp.game.noisy", game="G1")
print(hit_value.subject == latest_ref.subject)  # True: latest-sealed

# %% [markdown]
# Two callers asked the same question before either had sealed, so
# both ran. The answers differ, and both are kept (A20): `refs`
# lists the pair, which is the evidence nondeterminism leaves, and
# `eval` returns the latest-sealed entry whose trace matches.

# %% [markdown]
# ## A class that moved
#
# `Still` was `svp.legacy.Frame`; values sealed before the move
# keep the old dotted name in their `db/kind` row. One `db/moved`
# row records the move, and the loader and `kind=` follow it (A19,
# A32). `svp.legacy` survives only so this cell can seal under the
# old name.

# %%
from svp.legacy import Frame
old_frame = Frame(b"G1 frame 4500")
old_frame.preds["game"] = "G1"
with L.transaction(by="human:dan") as t:
    t.add_value(old_frame)
with L.transaction(by="human:dan", why="Frame is Still now") as t:
    t.add("db/kind/svp.legacy.Frame", "db/moved", "svp.game.Still")
new_still = Still(b"G1 frame 6000")
new_still.preds["game"] = "G1"
with L.transaction(by="human:dan") as t:
    t.add_value(new_still)
rev = L.at()
print(len(rev.refs(kind=Still)))       # 2: the old name followed
frame_ref = Ref(rev, old_frame.subject)
print(rev[frame_ref.subject, "db/kind"])  # svp.legacy.Frame: as sealed
print(frame_ref.type)                  # <class 'svp.game.Still'>
