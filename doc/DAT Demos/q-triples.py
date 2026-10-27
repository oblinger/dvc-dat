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

from dvc_dat.ledger import Ledger, Unlocked, bump

scratch_path = Path("scratch/q-triples").resolve()
shutil.rmtree(scratch_path, ignore_errors=True)   # a re-run starts clean
for module_name in [m for m in sys.modules if m.split(".")[0] == "demo_game"]:
    del sys.modules[module_name]

# %% [markdown]
# # Quick: triples
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
for r in rev2.rows("game/G1", "court"):
    print("row:", r)                   # both rows are still stored
#    1 + game/G1   court   north
#    2 + game/G1   court   south

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
# One level is the subject's record; two levels is one predicate.
# Writing mirrors reading, and a record write takes a list for a
# `many` key.

# %%
with L.transaction(by="human:dan", lock=10) as t:      # the record write reads: lock=
    t["game/G1", "court"] = "west"                       # two levels
    t["game/G2"] = {"home": "G1", "away": "G3",          # one level
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
print("officials:", rev.all("game/G1", "officials"))         # ['kim', 'ortiz']
print("court rows:", len(rev.rows("game/G1", "court")))      # 4: the history

# %% [markdown]
# `get` answers a default instead of raising, `in` tests one triple,
# `all` lists what a pattern leaves open, and `rows` is the unfolded
# history.

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

# %%
with L.transaction(by="human:dan") as t:
    t["env/prod", "rev"] = str(rev2.id)
prod_rev = L.at(L.at()["env/prod", "rev"])
print("prod id, court:", prod_rev.id, prod_rev.get("game/G1", "court"))   # 2 south

# %% [markdown]
# A name is any subject's `rev` row; `L.at` takes the id it holds.

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
# ## Connecting to code
#
# A `db/repo/<repo>/<package>` subject is a version clock tied to a git
# checkout: the version of that package's code that runs were exposed
# to. The version lives in the source, as `__version__`; the first run
# from a clean checkout writes it, and its commit to `db/repo/<repo>`.

# %%
demo_repo_path = scratch_path / "demo-game"
(demo_repo_path / "demo_game").mkdir(parents=True, exist_ok=True)
(demo_repo_path / "demo_game/__init__.py").write_text('__version__ = "0.1.0"\n')
(demo_repo_path / "demo_game/hello.py").write_text(
    "from dvc_dat.ledger import ledger_fn\n\n\n"
    "@ledger_fn\ndef hello(rev, *, game: str) -> str:\n    return f\"hello {rev['game/' + game, 'court']}\"\n")
git_cmd = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com"]
for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "0.1.0"]):
    subprocess.run(git_cmd + args, cwd=demo_repo_path, check=True)
sys.path.insert(0, str(demo_repo_path))
import demo_game.hello

greeting = L.at().run("demo_game.hello.hello", game="G1")
print("greeting:", greeting.obj)   # greeting: hello west: G1's court now
print("db/repo/demo-game/demo_game:", L.at()["db/repo/demo-game/demo_game"])
# db/repo/demo-game/demo_game: {'version': '0.1.0'}
print("db/repo/demo-game:", L.at()["db/repo/demo-game"])
# db/repo/demo-game: {'commit': '<the demo commit>'}

# %% [markdown]
# ## Locking the ledger
#
# `bump` raises any other clock, here a schema's.

# %%
with L.transaction(by="human:dan", lock=10) as t:
    print("schema/tape:", bump(t, "schema/tape"))   # schema/tape: 0.0.1

# %% [markdown]
# `bump` reads the version through `t.previous_rev`, then writes
# the next one. `lock=10` holds the write lock for the whole body,
# so no other writer slips between the read and the write; past 10
# seconds the body is interrupted and nothing is written.
#
# A body can read through `t.previous_rev` itself, alter, and write
# back. Here one more official joins `game/G2`.

# %%
with L.transaction(by="human:dan", lock=10) as t:
    g2 = t.previous_rev["game/G2"]                 # the record as it stands now
    t["game/G2"] = {**g2, "officials": g2["officials"] + ["vance"]}   # one more, written back
print("officials:", t.rev.all("game/G2", "officials"))

# %% [markdown]
# `t.previous_rev` is the previous revision, the top as it stands
# while the body holds the write lock: the write is built on current
# data, and no other writer can commit between the read and the
# write. Without `lock=` there is no well-defined previous revision.
# Notice the ledger refuses the read.

# %%
try:
    with L.transaction(by="human:dan") as t:       # no lock=
        t.previous_rev["game/G2"]
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
