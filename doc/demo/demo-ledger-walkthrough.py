# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.6
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

# %% [markdown]
# # The ledger beside the dat
#
# A dat is space: a folder with a `_spec_.yaml`. The ledger is time: one
# append-only table of events, `(added, rev, subject, predicate, object)`, where
# every write is a transaction under a new rev and every read is a function of a
# rev. This notebook opens a ledger on a temp SQLite file and prints the rows
# each step lands, exactly as stored.

# %%
import os, sqlite3, tempfile
from pathlib import Path
from dvc_dat import Dat, DatManager
from dvc_dat.ledger import Ledger, Ref, json

HOME = Path(tempfile.mkdtemp(prefix="ledger-")).resolve()
Dat.manager = DatManager(dat_folders=[str(HOME / "dats")])   # space: where dats live
os.environ["DAT_LEDGER"] = str(HOME)   # time: a folder holding ledger.db and ledger.art/
L = Ledger.open()                       # also becomes Ledger.default

def rows(rev=None):
    """The events table as stored, one transaction or all of it."""
    sql = "SELECT added, id, subject, predicate, object FROM events"
    sql += f" WHERE id = {rev}" if rev else ""
    for added, r, s, p, o in sqlite3.connect(L.path).execute(sql + " ORDER BY id, ord"):
        print(f"{'+' if added else '-'} {r:>2}  {s:<12} {p:<8} {o}")

print("rev", L.rev(), "| events", L.query())

# %% [markdown]
# ## A transaction
#
# `assign` says the predicate now holds one object; `add` puts one more member in
# a set. Everything in the block lands under one rev, with the transaction's own
# `by` and `time` rows on `tx/<rev>`.

# %%
with L.transaction(by="juan") as tx:
    tx.assign("game/G7", "sport", "bb")
    tx.assign("game/G7", "court", "hs-wood-2")
    tx.add("gameset", "NORM", Ref("game/G7"))
rows(tx.rev)

# %% [markdown]
# ## Assign again, and read at a rev
#
# `set_spec` is one `assign` per key: a removal of what the key held and an
# addition, under one rev. Nothing is rewritten, so a read at the old rev still
# sees the old value.

# %%
old = L.rev()
new = L.set_spec("game/G7", {"court": "hs-wood-3"}, by="dan")
rows(new)
print("at", old, L.get_spec("game/G7", rev=old))
print("at", new, L.get_spec("game/G7", rev=new))

# %%
for e in L.history("game/G7", "court"):
    print(e.rev, "+" if e.added else "-", e.object, "by", L.last(f"tx/{e.rev}", "by"), "on", L.time(e.rev))
print("games on hs-wood-3:", L.subjects("court", "hs-wood-3"))

# %% [markdown]
# ## Artifacts and dats
#
# `save` puts bytes on the ledger's shelf, content-addressed, and hands back a
# `Ref`: plain data, written into a triple like any other value. A dat is
# referenced the same way, by its name, and loads through `Dat.manager`.

# %%
shots = L.save({"shots": [12, 40, 77]}, type=json)
run = Dat.create(path="runs/G7-r1", spec={"main": {"game": "game/G7"}})
with L.transaction(by="dan") as tx:
    tx.assign("game/G7", "annot:shots", shots)
    tx.assign("game/G7", "run", Ref(run.get_path_name(), type=Dat))
rows(tx.rev)
print(L.last("game/G7", "annot:shots").load())
print(L.last("game/G7", "run").load().get_spec())

# %% [markdown]
# ## The whole table

# %%
rows()

# %% [markdown]
# ## Clean up

# %%
import shutil
L.close()
del os.environ["DAT_LEDGER"]
shutil.rmtree(HOME)
