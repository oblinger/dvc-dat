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
# is a value, put in by hand. Cutting is a ledger function: it reads
# the game's rows and the video, and its cut is a new value. The
# game's current cut is an alias row on `game/G1` itself. Every
# value is found by its preds, and every one can say why it would
# no longer be the answer.
#
# Written to the ledger design of 2026-10-18 (Ledger Module, Values
# § The worked example, F447 A39–A51). It runs once
# `ledger2` is rebuilt to that design (T534); until then it is the
# design, not a demo. Revision numbers in the comments count from
# 1, the first transaction on this ledger.

# %% [markdown]
# ## Setup

# %%
import importlib
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dvc_dat.ledger import Ledger, Ref, bump
from dvc_dat.ledger import AliasLoop, Exists, Multiple, Undeclared

scratch_ledger_path = Path("scratch/values-demo/ledger").resolve()
L = Ledger(scratch_ledger_path, create=True)   # made, then opened

# %% [markdown]
# ### A real code repository
#
# Every ledger function runs in a git checkout, the ledger records
# which commit, and the notebook makes a tiny one of its own: the
# `demo_game` package beside this notebook, copied into scratch.

# %%
demo_repo_path = Path("scratch/values-demo/demo-game").resolve()
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
# The two games as plain rows written with the bracket, as the
# triples notebook taught, and the code clock `eval` checks against
# the commit it discovers.

# %%
with L.transaction(by="human:dan", why="season opener") as t:
    t["code/demo-game"] = {"version": "0.1.0",
                           "commit": commit_sha}
    t["game/G1"] = {"home": "G4", "away": "G5",
                    "date": "2026-10-11", "court": "north"}
    t["game/G2"] = {"home": "G1", "away": "G3",
                    "date": "2026-10-12", "court": "east"}
rev = L.at()
print(rev["game/G1"])
# {"home": "G4", "away": "G5", "date": "2026-10-11",
#  "court": "north"}

# %% [markdown]
# ## Values: large complex constants in the ledger
#
# A value is a thing you put in the ledger and get back, identified
# by its content.

# %% [markdown]
# ### A class
#
# A value's class lives in `demo_game/game.py`: a `Value` subclass
# defined in a cell has no dotted name for a later `load` to import.
# A raw video:
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
# ### Put it in, get a reference

# %%
video_value = PlainVideo(b"G1 wide camera, 9000 frames")
with L.transaction(by="human:dan") as t:
    video_ref_subject = t.add_value(video_value)
print(video_ref_subject)             # 64 hex: from the content
rev = L.at()
plain_ref = Ref(rev, video_ref_subject)
print(plain_ref, plain_ref.type)
# <8 hex> <class 'demo_game.game.PlainVideo'>

# %% [markdown]
# `add_value` returns the value's subject, a hash derived from its
# content: a name nobody typed. `Ref(rev, subject)` points at it
# without fetching a byte, and prints as the hash's first eight
# characters.

# %% [markdown]
# ### Load it back

# %%
loaded_video = rev.load(video_ref_subject)
print(type(loaded_video).__name__, loaded_video.frames)
# PlainVideo b'G1 wide camera, 9000 frames'
print(loaded_video.same_as(video_value))   # True: the same bytes

# %% [markdown]
# `load` decodes the bytes into the class they were put in as;
# `same_as` compares two values by their bytes.

# %% [markdown]
# ### A name: alias
#
# An alias is a `db/alias` row naming the subject. `add_value(…,
# alias="video/G1")` writes it in the same transaction; here it is
# added later, by hand.

# %%
with L.transaction(by="human:dan") as t:
    t.add("video/G1", "db/alias", video_ref_subject)
rev = L.at()
named_video = rev.load("video/G1")
print(named_video.same_as(video_value))   # True
print(video_value)                        # video/G1: it has a name

# %% [markdown]
# A second name for the video. Notice it prints as the shorter one.

# %%
with L.transaction(by="human:dan") as t:
    t.add("raw/G1/wide-camera", "db/alias", video_ref_subject)
rev = L.at()
camera_ref = Ref(rev, "raw/G1/wide-camera")
print(camera_ref)            # video/G1: the shortest, as of the head
print(camera_ref.name)       # raw/G1/wide-camera: what you said
print(sorted(camera_ref.aliases))
# ["raw/G1/wide-camera", "video/G1"]

# %% [markdown]
# A value or its `Ref` prints as the shortest alias naming it, else
# the first eight characters of its hash. `Ref.aliases` lists every
# name.

# %% [markdown]
# ### The game record carries its alias
#
# The name's own record, read with the bracket, beside the value it
# names.

# %%
print(rev["video/G1"])
# {"db/alias": "<the video's subject, 64 hex>"}
print(rev.load("video/G1"))          # video/G1: the value itself

# %% [markdown]
# `rev["video/G1"]` is literal: the name's own rows, its `db/alias`
# row's object the subject as a plain `str`. `load` follows the
# row. A game carries its current cut the same way, shown once a
# cut exists (Ledger evaluation).

# %% [markdown]
# ## Predicates: what a value is found by, and why it is frozen

# %% [markdown]
# ### Declaring a kind's preds
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
# import. `Cut` has the same shape, holding `clip`, under
# `@ledger_class(preds=("game", "version", "video", "team"))`.

# %%
from demo_game.game import Video, Cut, Still

# %% [markdown]
# Three pred declarations the values below rely on; Topics § A many
# pred says what each one does.

# %%
with L.transaction(by="human:dan") as t:
    t.add("db/pred/team", "db/cardinality", "many")
    t.add("db/pred/video", "db/type", "demo_game.game.Video")
    t.add("db/pred/span", "db/type", "json")

# %% [markdown]
# ### Preds on the object, then the seal

# %%
wide_video = Video(b"G1 wide camera, 9000 frames")
wide_video.preds.update(game="G1", camera="wide", span=[0, 9000])
with L.transaction(by="human:dan") as t:
    t.add_value(wide_video, alias="video/G1",
                provenance="import:archive")
print(wide_video)                    # video/G1
print(wide_video.subject[:8], wide_video.sealed)   # <8 hex> True
print(wide_video.preds)
# {"game": "G1", "camera": "wide", "span": [0, 9000]}

# %% [markdown]
# Preds are set on the object before the seal, by whoever builds
# it; `add_value` takes no `preds=`. The seal fixes `subject` and
# `rev` and freezes `preds`. The preds are in the subject's hash, so
# the same frames make a new subject; `video/G1` now names it, an
# alias being one row whose latest add wins.

# %% [markdown]
# Notice that once sealed, `preds` is read-only.

# %%
try:
    wide_video.preds["camera"] = "tele"
except TypeError as e:
    print("TypeError:", e)

# %% [markdown]
# G2's video the same way, for the second game.

# %%
g2_video = Video(b"G2 wide camera, 8400 frames")
g2_video.preds.update(game="G2", camera="wide", span=[0, 8400])
with L.transaction(by="human:dan") as t:
    t.add_value(g2_video, alias="video/G2",
                provenance="import:archive")

# %% [markdown]
# ### What the ledger holds
#
# The G1 seal's revision as rows, unfolded. Notice everything the
# seal wrote on the new subject, and the alias row on `video/G1`.

# %%
seal_rev = wide_video.rev
for row in seal_rev.rows(since=L.at(seal_rev.id - 1)):
    print(row)
# rev subject  predicate               object
#   6 <hash>   db/value                ref:demo_game.game.Video:<hash>
#   6 <hash>   db/kind                 demo_game.game.Video
#   6 <hash>   db/provenance           import:archive
#   6 <hash>   db/preds                ["game","camera","span"]
#   6 <hash>   db/trace/code/demo-game 0.1.0+<8 hex>
#   6 <hash>   db/trace/platform       darwin-arm64-py3.11
#   6 <hash>   db/trace/uv.lock        sha256:<hash>
#   6 <hash>   game                    G1
#   6 <hash>   camera                  wide
#   6 <hash>   span                    [0, 9000]
#   6 video/G1 db/alias                <hash>
#   6 db/tx/6  db/by                   human:dan

# %% [markdown]
# `db/value` names the bytes by class and hash. `db/kind` is the
# class. `db/provenance` is the caller's word. `db/preds` lists the
# preds the kind declared at this seal, the ones now frozen. The
# `db/trace/…` rows are the trace, under Ledger evaluation §
# Provenance. Then one row per pred, and the alias.

# %% [markdown]
# ### Finding values by preds

# %%
rev = L.at()
print(rev.values(game="G1"))         # [video/G1]
print(rev.values(kind=Video))        # video/G1 and video/G2
print(rev.values(camera="wide"))     # video/G1 and video/G2

# %% [markdown]
# `values` is the main way into the value table: a where clause
# over preds, the matches loaded, in no promised order. A bare
# keyword names a pred, whoever wrote it; `kind=` narrows to a
# class. The plain video carries no preds, so no clause finds it.

# %% [markdown]
# `value` is exactly one, or it raises: two videos match
# `kind=Video`.

# %%
print(rev.value(game="G1").same_as(wide_video))    # True
try:
    rev.value(kind=Video)
except Multiple as e:
    print("Multiple:", e)

# %%
video_refs = rev.refs(kind=Video)
print([(video_ref, video_ref.preds["span"])
       for video_ref in video_refs])
# (video/G1, [0, 9000]) and (video/G2, [0, 8400])
print(max(video_refs, key=lambda r: r.sealed_at.id))   # video/G2
print(rev.select(("game", "span"), kind=Video))
# ("G1", [0, 9000]) and ("G2", [0, 8400])

# %% [markdown]
# `refs` says who matched without loading: `Ref.preds` and
# `Ref.sealed_at`, the revision of the `db/value` row, come with
# the rows, so refs can be filtered and sorted before any bytes
# move, and the latest is a `max` over `sealed_at`. `select`
# projects chosen preds to tuples.

# %% [markdown]
# ### Frozen: Exists
#
# A pred the seal wrote cannot be edited in place: an `add` on it
# raises `Exists` at commit and writes nothing.

# %%
try:
    with L.transaction(by="human:dan") as t:
        t.add(wide_video.subject, "camera", "tele")
except Exists as e:
    print("Exists:", e)

# %% [markdown]
# ### Annotation versus correction
#
# A new pred on every game's video: annotation.

# %%
with L.transaction(by="human:dan", why="court survey") as t:
    for video_ref in L.at().refs(kind=Video):
        t.add(video_ref.subject, "texture", "hardwood")
rev = L.at()
print(Ref(rev, "video/G1").preds["texture"])    # hardwood
print(len(rev.values(kind=Video, texture="hardwood")))   # 2

# %% [markdown]
# `texture` is not one of the preds the seals froze (each `db/preds`
# row lists what the kind declared at its seal), so it is
# annotation: allowed on a sealed value in any later transaction,
# and part of the one view of its preds.

# %% [markdown]
# A wrong pred is corrected by a new seal. A hand trim of G1's
# video, sealed and named in one transaction. Notice the typo in
# `team`.

# %%
trim_cut = Cut(wide_video.frames[:12])          # trimmed by hand
trim_cut.preds.update(game="G1",
                      team=["G4", "G6"],          # G6: a typo
                      video=wide_video)
with L.transaction(by="human:dan") as t:
    wrong_subject = t.add_value(trim_cut, deps=[wide_video],
                                alias="trim/G1",
                                provenance="human:dan")
print(sorted(Ref(L.at(), "trim/G1").preds["team"]))  # G4, G6

# %% [markdown]
# The trim left `version` unset, so `version` is frozen absent. The
# fix is a new seal with the right preds, re-pointed.

# %%
fixed_cut = Cut(trim_cut.clip)                  # the same bytes
fixed_cut.preds.update(game="G1", team=["G4", "G5"],
                       video=trim_cut.preds["video"])
with L.transaction(by="human:dan", why="team typo") as t:
    right_subject = t.add_value(fixed_cut, deps=[wide_video],
                                alias="trim/G1",
                                provenance="human:dan")
rev = L.at()
print(right_subject != wrong_subject,
      fixed_cut.same_as(trim_cut))                # True True
print(sorted(Ref(rev, "trim/G1").preds["team"]))  # G4, G5
print(rev.refs(kind=Cut, team="G6"))            # [<8 hex>]

# %% [markdown]
# The same bytes make a new subject, sharing one blob. The wrong
# one stays, immutable, still found by `team="G6"`, printed by its
# hash since no alias names it now.

# %% [markdown]
# ### A new version: seal, then re-point

# %%
longer_cut = Cut(wide_video.frames[:14])        # a longer trim
longer_cut.preds.update(game="G1", version="2",
                        team=["G4", "G5"], video=wide_video)
with L.transaction(by="human:dan") as t:
    t.add_value(longer_cut, deps=[wide_video])
print(longer_cut)                        # <8 hex>: no alias yet
with L.transaction(by="human:dan", why="longer trim") as t:
    t.add("trim/G1", "db/alias", longer_cut.subject)
print(longer_cut, fixed_cut)             # trim/G1 <8 hex>

# %% [markdown]
# A value's `version` is a pred its constructor sets; a new version
# is a new value and the alias moved to it.

# %% [markdown]
# `bump` moves clocks (`code/<repo>`, `db`); on a name holding a
# `db/alias` row it raises, naming the alias.

# %%
try:
    with L.transaction(by="human:dan") as t:
        bump(t, "trim/G1")
except TypeError as e:
    print("TypeError:", e)

# %% [markdown]
# ### What a hand seal refuses
#
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
# taken out of the same object.

# %%
print(bad_video.sealed)              # False: nothing was written
del bad_video.preds["team"]

# %% [markdown]
# A hand seal may name any provenance but one beginning `eval:`,
# which `eval` alone writes.

# %%
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
# ## Ledger evaluation

# %% [markdown]
# ### A ledger function
#
# Cutting, in `demo_game/game.py`:
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
# `@ledger_fn` marks a ledger function, its return annotation
# required, and writes no row on import. The body reads the game's
# rows through `rev`, loads the video, sets the cut's `preds` and
# returns it. `cut_video` ignores the version, so two versions of a
# cut can be byte-identical. The module's other functions are
# quoted where they are used.

# %%
from demo_game.game import cut

rev = L.at()
plain_cut = cut(rev, game="G1", version="1.5.3")
print(type(plain_cut))               # <class 'demo_game.game.Cut'>
print(plain_cut.sealed)              # False
print(plain_cut.preds)
# {"game": "G1", "version": "1.5.3", "video": video/G1,
#  "team": ["G4", "G5"]}
print(L.at().id == rev.id)           # True: nothing written

# %% [markdown]
# Nothing was written: calling `cut` is an ordinary Python call.

# %% [markdown]
# `load_fn` resolves the name at `rev` to an `Fn`, called like the
# function with only the keywords, `rev` supplied; that call is
# `eval`, memoised and sealing.

# %%
cut_fn = rev.load_fn("demo_game.game.cut")
print(cut_fn.mode, cut_fn.signature)
# base (*, game: str, version: str)
print(cut_fn.sha[:8], cut_fn.subject)
# <8 hex> db/fn/demo_game.game.cut/<hash>

# %% [markdown]
# The `Fn` says which code a name resolves to at this rev:
# `signature` is the keywords it takes, `sha` the hash of its
# module's source, `subject` the one name for that resolution.

# %% [markdown]
# ### Evaluation and memoization
#
# `rev.eval` is `load_fn` and a call. Its first call for a
# question runs the body and seals the result.

# %%
rev = L.at()
cut_153 = rev.eval("demo_game.game.cut", game="G1", version="1.5.3")
print(cut_153.sealed, cut_153.rev.id > rev.id)  # True True
print(cut_153.same_as(plain_cut))    # True: the same bytes

# %% [markdown]
# The miss ran the body and sealed the cut in a revision of its
# own, which is `cut_153.rev`. The preds are what the body put in
# `c.preds`; the keys are one `db/keys` row, not preds.

# %%
top_id = L.at().id
again_cut = L.at().eval("demo_game.game.cut", game="G1",
                        version="1.5.3")
print(again_cut.subject == cut_153.subject)  # True: a hit
print(L.at().id == top_id)           # True: nothing written
print(again_cut.rev.id == cut_153.rev.id)   # True: the seal's rev

# %% [markdown]
# The second call is a memo hit: same function, same keys, every
# trace item unchanged. It writes nothing, and the value it hands
# back carries the revision it was sealed in.

# %% [markdown]
# `memo="get"` looks without running; `memo=False` runs without
# sealing, and its bytes are what a memoised call would return.

# %%
rev = L.at()
print(rev.eval("demo_game.game.cut", game="G1", version="1.5.4",
               memo="get"))          # None: never run
dry_cut = rev.eval("demo_game.game.cut", game="G1", version="1.5.3",
                   memo=False)
print(dry_cut.sealed, dry_cut.same_as(cut_153))  # False True
print(L.at().id == rev.id)           # True: nothing written

# %% [markdown]
# A memo entry is the seal's rows plus two of its own: `db/fn`, the
# code that ran, and `db/keys`, the question.

# %%
entry_rev = cut_153.rev
for row in entry_rev.rows(since=L.at(entry_rev.id - 1)):
    if row.predicate in ("db/fn", "db/keys"):
        print(row)
# <hash> db/fn   db/fn/demo_game.game.cut/<hash>
# <hash> db/keys {"game": "G1", "version": "1.5.3"}

# %% [markdown]
# Memo entries are subjects like any other: `fn=` finds every
# evaluation of a function, here after a second question, G2.

# %%
cut_g2 = L.at().eval("demo_game.game.cut", game="G2",
                     version="1.5.3")
rev = L.at()
for memo_ref in rev.refs(fn="demo_game.game.cut"):
    print(memo_ref, rev[memo_ref.subject, "db/keys"])
# <8 hex> {"game": "G1", "version": "1.5.3"}
# <8 hex> {"game": "G2", "version": "1.5.3"}
print(len(rev.values(fn="demo_game.game.cut")))    # 2, loaded

# %% [markdown]
# ### The game record carries its alias
#
# Each game's current cut becomes an alias row on the game itself.

# %%
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "db/alias", cut_153.subject)
    t.add("game/G2", "db/alias", cut_g2.subject)
rev = L.at()
print(rev["game/G1"])
# {"home": "G4", "away": "G5", "date": "2026-10-11",
#  "court": "north", "db/alias": "<cut_153's subject, 64 hex>"}

# %% [markdown]
# `rev["game/G1"]` is literal: the game's own rows, its `db/alias`
# row among them, whose object is the cut's subject as a plain
# `str`. `game/G1` holds no value of its own: it is rows.

# %%
current_cut = rev.load("game/G1")
print(current_cut.same_as(cut_153),
      current_cut.subject == cut_153.subject)     # True True
cut_video_ref = current_cut.preds["video"]
print(type(cut_video_ref).__name__, cut_video_ref.type)
# Ref <class 'demo_game.game.Video'>
print(cut_video_ref.preds)
# {"game": "G1", "camera": "wide", "span": [0, 9000],
#  "texture": "hardwood"}: no load
cut_video = cut_video_ref.load()     # fetches the bytes
print(type(cut_video), cut_video.sealed)
# <class 'demo_game.game.Video'> True

# %% [markdown]
# `rev.load("game/G1")` follows the alias to the current cut.
# Loading decodes the top value only: the cut's `video` is a `Ref`
# whose type and preds are readable without fetching a byte, until
# its own `load()`.

# %%
game_ref = Ref(rev, "game/G1")
print(game_ref, game_ref.name)       # game/G1 game/G1
print(game_ref.subject == cut_153.subject)  # True: alias resolved
print(game_ref.type)                 # <class 'demo_game.game.Cut'>
print(game_ref.preds["version"])     # 1.5.3: the cut's preds
print(cut_153)                       # game/G1: it has a name now

# %% [markdown]
# A `Ref` resolves the alias when made: `name` is what you said,
# `subject` the cut's hash, `preds` the cut's, read without a load.

# %% [markdown]
# ### Provenance: the trace
#
# The cut's trace rows first, as stored.

# %%
entry_rev = cut_153.rev
for row in entry_rev.rows(since=L.at(entry_rev.id - 1)):
    if row.predicate.startswith("db/trace/"):
        print(row)
# one db/trace/<item> row per item below

# %%
for item in sorted(cut_153.trace):
    print(item, "->", cut_153.trace[item])
# code/demo-game -> 0.1.0+<8 hex>
# fn -> db/fn/demo_game.game.cut/<hash>
# game/G1 away -> G5
# game/G1 home -> G4
# platform -> darwin-arm64-py3.11
# q:{"game":"G1","kind":"demo_game.game.Video"}
#     -> ["ref:demo_game.game.Video:<hash>"]
# ref:demo_game.game.Video:<hash> -> ref:demo_game.game.Video:<hash>
# uv.lock -> sha256:<hash>

# %% [markdown]
# The trace is recorded, not declared: `fn`, the code the name
# resolved to (in base mode too, beside `code/demo-game`, A39); the
# two game rows read by name; the `value` query as a `q:` item
# holding what it answered, so a second G1 video later is a miss
# rather than a stale hit (A41); the video by its bytes; and the
# environment, discovered.

# %% [markdown]
# A hand seal has a trace too: with no `deps`, the environment
# alone.

# %%
print(dict(sorted(wide_video.trace.items())))
# {"code/demo-game": "0.1.0+<8 hex>",
#  "platform": "darwin-arm64-py3.11", "uv.lock": "sha256:<hash>"}

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
print(rev.load("game/G1").subject == cut_153.subject)  # True
print(cut_153.matches(rev))              # True: cut read neither

# %% [markdown]
# `matches(rev)` re-reads every trace item at `rev`. The cut never
# read the court or the date, so their corrections changed nothing.
# It read `home`: notice correcting the teams makes it stale.

# %%
with L.transaction(by="human:dan", why="home was G6") as t:
    t["game/G1", "home"] = "G6"
rev = L.at()
print(cut_153.matches(rev))                 # False

# %%
cut_home_g6 = rev.eval("demo_game.game.cut", game="G1",
                       version="1.5.3")
print(cut_home_g6.subject != cut_153.subject)  # True: re-derived
print(sorted(cut_home_g6.preds["team"]))    # ["G5", "G6"]
print(cut_153.diff(cut_home_g6))
# {"game/G1 home": ("G4", "G6")}
print(rev.load("game/G1").subject == cut_153.subject)  # unmoved

# %% [markdown]
# The next `eval` misses and re-derives; `diff` names the one trace
# item that moved. The alias does not follow by itself: the current
# cut moves when someone re-points it.

# %% [markdown]
# A function that reaches a value by name traces the binding.
# `poster` reaches the game's current cut by its alias:
#
# ```python
# @ledger_fn
# def poster(rev, *, game: str) -> dict:
#     """Downstream of the game's current cut, reached by its alias."""
#     c = rev.load(f"game/{game}")    # traced: game/G1 db/alias
#     return {"game": game, "bytes": len(c.clip)}
# ```

# %%
poster_value = rev.eval("demo_game.game.poster", game="G1")
for item in sorted(poster_value.trace):
    if item.startswith(("game/", "ref:")):
        print(item, "->", poster_value.trace[item])
# game/G1 db/alias -> ref:demo_game.game.Cut:<cut_153 bytes>
# ref:demo_game.game.Cut:<cut_153 bytes>
#     -> ref:demo_game.game.Cut:<cut_153 bytes>

# %% [markdown]
# The load through `game/G1` recorded the binding, the name to the
# bytes it resolved to, beside the value item. Neither holds the
# subject (A35): what `poster` depends on is the bytes the name
# gives, not the entry they sit in. Re-pointing the game at the
# re-derived cut moves those bytes.

# %%
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "db/alias", cut_home_g6.subject)
rev = L.at()
print(poster_value.matches(rev))         # False
poster_g6_value = rev.eval("demo_game.game.poster", game="G1")
print(sorted(poster_value.diff(poster_g6_value)))
# the game/G1 db/alias binding, and each side's value item

# %% [markdown]
# ### Identity

# %%
rev = L.at()
cut_154 = rev.eval("demo_game.game.cut", game="G1", version="1.5.4")
print(cut_154.same_as(cut_home_g6),
      cut_154.subject != cut_home_g6.subject)     # True True

# %% [markdown]
# Two derivations, identical bytes: the 1.5.4 cut has the bytes of
# the re-derived 1.5.3 cut (the stand-in cutter ignores its
# version). Two memo entries, two subjects, one blob.

# %% [markdown]
# `thumb(rev, *, clip: Ref) -> dict` takes a cut as its key.

# %%
rev = L.at()
thumb3_value = rev.eval("demo_game.game.thumb",
                        clip=Ref(rev, cut_home_g6.subject))
top_id = L.at().id
thumb4_value = rev.eval("demo_game.game.thumb",
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
# A name works the same way: point `game/G1` at the 1.5.4 cut and
# `poster`'s entry from the 1.5.3 cut holds.

# %%
with L.transaction(by="human:dan", why="cutter 1.5.4") as t:
    t.add("game/G1", "db/alias", cut_154.subject)
rev = L.at()
print(cut_154, cut_home_g6)              # game/G1 <8 hex>
print(poster_g6_value.matches(rev))      # True: identical bytes
again_poster = rev.eval("demo_game.game.poster", game="G1")
print(again_poster.subject == poster_g6_value.subject)  # a hit

# %% [markdown]
# `game/G1` now names identical bytes, so the binding item is
# unchanged and `poster` hits (A35, A21).

# %% [markdown]
# Two entries for one question:
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
    return rev.eval("demo_game.game.noisy", game="G1")
with ThreadPoolExecutor(2) as pool:
    a_value, b_value = pool.map(ask, range(2))  # both miss, both run
print(a_value.same_as(b_value),
      a_value.subject != b_value.subject)         # False True
noisy_refs = L.at().refs(fn="demo_game.game.noisy")
print(len(noisy_refs))                  # 2: one question, both kept
latest_ref = max(noisy_refs, key=lambda r: r.sealed_at.id)
hit_value = L.at().eval("demo_game.game.noisy", game="G1")
print(hit_value.subject == latest_ref.subject)  # True: latest

# %% [markdown]
# Two callers asked the same question before either had sealed, so
# both ran. The answers differ, and both are kept (A20): `refs`
# lists the pair, which is the evidence nondeterminism leaves, and
# `eval` returns the latest-sealed entry whose trace matches.

# %% [markdown]
# A code change is a commit in the demo repository, then a bump of
# its clock. Notice the cut misses though its bytes do not change.

# %%
game_path = demo_repo_path / "demo_game/game.py"
game_path.write_text(game_path.read_text()
                     + "\n# tidied: no change in behaviour\n")
git("commit", "-q", "-am", "tidy game")
import demo_game.game
importlib.reload(demo_game.game)
with L.transaction(by="human:dan", why="tidy game") as t:
    bump(t, "code/demo-game")            # 0.1.1, the new commit
rev = L.at()
print(cut_154.matches(rev))              # False
recut = rev.eval("demo_game.game.cut", game="G1", version="1.5.4")
print(recut.subject != cut_154.subject,
      recut.same_as(cut_154))                     # True True
print(sorted(cut_154.diff(recut)))       # ["code/demo-game", "fn"]

# %% [markdown]
# In base mode the trace holds the repo's version and commit, and
# `fn` hashes the module's source, so an edit anywhere in
# `game.py` moves both: the eval re-runs, and the identical bytes
# land as a new subject on the old blob.

# %% [markdown]
# ## Topics

# %% [markdown]
# ### A many pred
#
# The three declarations from Predicates, as the values carry them.

# %%
rev = L.at()
print(rev["db/pred/team", "db/cardinality"])   # many
print(sorted(cut_153.preds["team"]))           # ["G4", "G5"]
print(rev.values(team="G1"))                   # [game/G2]
print(rev["db/pred/span", "db/type"])          # json
print(wide_video.preds["span"])                # [0, 9000]
print(rev["db/pred/video", "db/type"])         # demo_game.game.Video

# %% [markdown]
# `team` is declared `many`, so a cut's teams are a list, one row
# per member, and a keyword matches any member: team `G1` plays in
# game `G2`. `span` is typed `json`, so a `one` pred may hold a
# list (A36). `video` is typed: its object must be a `Video`,
# stored `ref:demo_game.game.Video:<hash>`, an edge of the value
# graph. A list under an untyped `one` pred is refused at the seal.

# %%
bad_video.preds["camera"] = ["tele", "wide"]
try:
    with L.transaction(by="human:dan") as t:
        t.add_value(bad_video)
except TypeError as e:
    print("TypeError:", e)           # camera: a one pred, not json

# %% [markdown]
# ### A renamed class: `db/moved`
#
# `Still` was `demo_game.legacy.Frame`; values sealed before the
# move keep the old dotted name in their `db/kind` row. One
# `db/moved` row records the move, and the loader and `kind=`
# follow it (A19, A32). `demo_game.legacy` survives only so this
# cell can seal under the old name.

# %%
from demo_game.legacy import Frame
old_frame = Frame(b"G1 frame 4500")
old_frame.preds["game"] = "G1"
with L.transaction(by="human:dan") as t:
    t.add_value(old_frame)
with L.transaction(by="human:dan", why="Frame is Still now") as t:
    t.add("db/kind/demo_game.legacy.Frame", "db/moved",
          "demo_game.game.Still")
new_still = Still(b"G1 frame 6000")
new_still.preds["game"] = "G1"
with L.transaction(by="human:dan") as t:
    t.add_value(new_still)
rev = L.at()
print(len(rev.refs(kind=Still)))       # 2: the old name followed
frame_ref = Ref(rev, old_frame.subject)
print(rev[frame_ref.subject, "db/kind"])  # demo_game.legacy.Frame
print(frame_ref.type)                  # <class 'demo_game.game.Still'>

# %% [markdown]
# ### `AliasLoop`
#
# An alias may name another alias, and `Ref` follows at most 8
# hops; a ninth, like a cycle, is `AliasLoop`.

# %%
with L.transaction(by="human:dan") as t:
    t.add("hop-chain/1", "db/alias", video_value.subject)
    for i in range(2, 10):
        t.add(f"hop-chain/{i}", "db/alias", f"hop-chain/{i - 1}")
hop8_ref = Ref(L.at(), "hop-chain/8")
print(hop8_ref.subject == video_value.subject)  # True
try:
    Ref(L.at(), "hop-chain/9")
except AliasLoop as e:
    print("AliasLoop:", e)

# %% [markdown]
# ### `Exists` on remove
#
# A `remove` of a frozen pred is refused like an `add` (A38).

# %%
try:
    with L.transaction(by="human:dan") as t:
        t.remove(wrong_subject, "team", "G6")
except Exists as e:
    print("Exists:", e)

# %% [markdown]
# ### A `ref:` row
#
# A `Ref` may be any row's object. `add` stores it as
# `ref:<class>:<hash>:<subject>`, the subject a hint; every pattern
# read hands it back as a `Ref`, unloaded, printed as its shortest
# alias, else the hash's first eight characters.

# %%
with L.transaction(by="human:dan") as t:
    t.add("review/G1", "cut", Ref(t.base, cut_154.subject))
pick_ref = L.at()["review/G1", "cut"]
print(pick_ref, pick_ref.subject == cut_154.subject)  # game/G1 True

# %% [markdown]
# ### The two doors are one
#
# A hand seal and `eval` (calling the `Fn` that `load_fn` hands back
# is `eval`) write the same rows, so every read above treats a value
# the same way whichever door sealed it; an eval's entry adds only
# `db/fn` and `db/keys`.
