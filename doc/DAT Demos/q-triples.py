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

from dvc_dat.ledger import Ledger, bump

scratch_path = Path("scratch/q-triples").resolve()
shutil.rmtree(scratch_path, ignore_errors=True)   # a re-run starts clean
sys.modules.pop("demo_game", None)

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
print(rev1.id, rev1.get("game/G1", "court"))   # 1 north

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
print(rev2.get("game/G1", "court"))   # south: the latest add
print(rev1.get("game/G1", "court"))   # north: rev1 never changes
for r in rev2.rows("game/G1", "court"):
    print(r)                          # both rows are still stored
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
print(rev3.get("game/G1", "court"))         # east
print(rev3.all("game/G1", "officials"))     # ['kim', 'ortiz']
print(rev1.get("game/G1", "court"),
      rev1.all("game/G1", "officials"))     # north []: looking back

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
with L.transaction(by="human:dan") as t:
    t["game/G1", "court"] = "west"                       # two levels
    t["game/G2"] = {"home": "G1", "away": "G3",          # one level
                    "officials": ["lee", "park"]}
rev = t.rev
print(rev["game/G1", "court"])   # west
print(rev["game/G2"])
# {'home': 'G1', 'away': 'G3', 'officials': ['lee', 'park']}

# %% [markdown]
# `rev[s, p]` on a `many` predicate raises and names `all`; a
# missing fact is a `KeyError`.

# %% [markdown]
# ## Triple reads

# %%
print(rev.get("game/G1", "score", default="tbd"))   # tbd: no raise
print(("game/G1", "home", "G4") in rev)             # True
print(rev.all("game/G1", "officials"))              # ['kim', 'ortiz']
print(len(rev.rows("game/G1", "court")))            # 4: the history

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
print(prod_rev.id, prod_rev.get("game/G1", "court"))   # 2 south

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
# A `code/<repo>` subject is a version clock tied to a git checkout.
# `bump` raises the version and writes the commit beside it, read
# from the checkout of that repo this process imported.

# %%
demo_repo_path = scratch_path / "demo-game"
(demo_repo_path / "demo_game").mkdir(parents=True, exist_ok=True)
(demo_repo_path / "demo_game/__init__.py").write_text("")
git_cmd = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com"]
for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "0.0.1"]):
    subprocess.run(git_cmd + args, cwd=demo_repo_path, check=True)
sys.path.insert(0, str(demo_repo_path))
import demo_game

with L.transaction(by="human:dan") as t:
    bump(t, "code/demo-game")
print(L.at()["code/demo-game"])
# {'version': '0.0.1', 'commit': '<the demo commit>'}

# %% [markdown]
# ## Locking the ledger

# %%
with L.transaction(by="human:dan", lock=10) as t:
    print(bump(t, "code/demo-game"))   # 0.0.2

# %% [markdown]
# `bump` reads the version, then writes the next one. `lock=10`
# holds the write lock for the whole body, so no other writer slips
# between the read and the write; past 10 seconds the body is
# interrupted and nothing is written.
