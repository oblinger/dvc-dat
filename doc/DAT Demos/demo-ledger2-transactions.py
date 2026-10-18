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

# %%

# %% [markdown]
# # Demo: ledger2 transactions
#
# How does a fact get into the ledger, and what does it mean once it
# is there? Every write is one `with L.transaction(by=...)` block that
# becomes one revision; every row is `(subject, predicate, object)`;
# and the predicate's cardinality decides whether a second `add`
# replaces the first or joins it. This notebook writes a few facts
# about game G5 and the `normie` game set and reads them back at each
# revision.

# %%
import os, shutil, tempfile, time
from pathlib import Path

from dvc_dat.ledger2 import Ledger, LockTimeout

ledger_dir = Path(tempfile.mkdtemp(prefix="demo-l2-tx-"))
os.environ["DAT_LEDGER"] = str(ledger_dir)
L = Ledger.open()
print(L.at(), L.at().all())

# %% [markdown]
# `Ledger.open()` reads `DAT_LEDGER`. An empty ledger is revision 0;
# `L.at()` is a frozen view of the top, and `all()` lists every row.
#
# ## One block, one revision

# %%
with L.transaction(by="human:dan") as t:
    t.add("game/G5", "court", "hs-wood-2")
    t.add("game/G5", "season", "2026")
print(t.rev)
for row in L.at().all():
    print(row)

# %% [markdown]
# Two `add`s became revision 1. The block also wrote a third row:
# `by` on the transaction's own subject, `ledger/tx/1`.
#
# ## Keywords are predicates on the transaction

# %%
with L.transaction(by="agent:svp", time=True,
                   why="re-cut", ticket="T531") as t:
    t.add("game/G5", "venue", "Lincoln HS")
    t.add(t.tx, "checked", "G1,G4,G5")
print("inside the block t.tx was a placeholder:", t.tx[:22], "...")
for p, o in L.at().all(t.rev.tx):
    print(f"  {t.rev.tx}  {p:8} {o}")

# %% [markdown]
# `time=True` stamps the UTC clock; `why` and `ticket` are any
# keywords; `t.tx` names the same subject for a row decided inside the
# body, rewritten to `ledger/tx/2` at commit.

# %%
rev = L.at()
print(rev["game/G5", "court"])
print(rev.get("game/G5", "referee", default="(none)"))
print(rev[rev.tx, "by"])
print(rev.refs(s="ledger/tx/*", where={"ticket": "T531"}))

# %% [markdown]
# Provenance reads like any row: `[]` is exactly one match or raise,
# `get` at most one, and `refs` finds the transaction by its keyword.
#
# ## A second add on a `one` predicate replaces; `remove` clears

# %%
with L.transaction(by="human:dan") as t:
    t.add("game/G5", "court", "hs-wood-3")
with L.transaction(by="human:dan") as t:
    t.remove("game/G5", "court", "hs-wood-3")
for r in (L.at(1), L.at(3), L.at()):
    print(r, r.get("game/G5", "court"))
print("asserted at:", L.at()["game/G5", "court", "hs-wood-2"])

# %% [markdown]
# Every predicate is `one` unless declared otherwise: the latest
# `add` wins, and a `remove` of the held value leaves none. Old
# revisions still read the old values, and a three-position pattern
# returns the revision that asserted the triple.
#
# ## Declaring a predicate `many`

# %%
with L.transaction(by="human:dan") as t:
    t.add("gameset/normie", "contains", "game/G1")
    t.add("gameset/normie", "contains", "game/G4")
before = L.at()
print("one: ", before.all("gameset/normie", "contains"))

with L.transaction(by="human:dan") as t:
    t.add("ledger/pred/contains", "cardinality", "many")
    t.add("ledger/pred/contains", "doc", "a set's members")
with L.transaction(by="human:dan") as t:
    t.add("gameset/normie", "contains", "game/G1")
    t.add("gameset/normie", "contains", "game/G5")
print("many:", L.at().all("gameset/normie", "contains"))
print("before, still:", before.all("gameset/normie", "contains"))

# %% [markdown]
# Cardinality is itself rows, on the subject `ledger/pred/contains`.
# Under `one` the second `add` replaced G1; once `contains` is `many`
# the adds accumulate. The old view `before` keeps reading `one`.

# %%
with L.transaction(by="human:dan") as t:
    t.remove("gameset/normie", "contains", "game/G4")
rev = L.at()
print(rev.all("gameset/normie", "contains"))
print(("gameset/normie", "contains", "game/G4") in rev)
try:
    rev["gameset/normie", "contains"]
except LookupError as e:
    print(type(e).__name__, "-", e)

# %% [markdown]
# On a `many` predicate `remove` takes one member out. `in` asks
# about one triple; `[]` refuses a pattern with two matches.
#
# ## `lock=`: read and write against a top that cannot move

# %%
with L.transaction(by="agent:svp", lock=5) as t:
    season = t.base["game/G5", "season"]
    t.add("game/G5", "season", str(int(season) + 1))
print(L.at()["game/G5", "season"])

# %% [markdown]
# Under `lock=5` the block holds the write lock for at most 5 s, so
# `t.base` stays the top until exit: the read and the write cannot be
# split by another writer.

# %%
top = L.at().id
try:
    with L.transaction(by="agent:svp", lock=0.2) as t:
        t.add("game/G5", "season", "1999")
        time.sleep(2)
except LockTimeout as e:
    print("LockTimeout:", e)
print("revision unchanged:", L.at().id == top)

# %% [markdown]
# A body that runs past its limit is interrupted and writes nothing.
#
# ## What a transaction refuses

# %%
def refused(f):
    try:
        f()
        return "not refused"
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def add_int():
    with L.transaction(by="human:dan") as t:
        t.add("game/G5", "period", 3)


def raises_inside():
    with L.transaction(by="human:dan") as t:
        t.add("game/G5", "court", "outdoor-1")
        raise RuntimeError("vocabulary check failed")


bare = L.transaction(by="human:dan")
top = L.at().id
print(refused(add_int))
print(refused(lambda: bare.add("game/G5", "court", "x")))
print(refused(raises_inside))
print("revision unchanged:", L.at().id == top)

# %% [markdown]
# A number is written as its string (`"3"`); a transaction is used
# only as `with`; and an exception inside the block writes nothing.

# %%
shutil.rmtree(ledger_dir)
del os.environ["DAT_LEDGER"]
print("removed:", not ledger_dir.exists())
