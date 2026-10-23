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
# # Demo: dats, dependencies and versions
#
# A **dat** is a folder: a call (`_spec_.yaml`, fixed when the folder is made), the data it
# produced, and a result (`_result_.yaml`, mutable until the seal, fixed after). Sealing stamps
# a hash of the folder and records every dat the run loaded as a **dependency**, by hash. A
# **version** is a row on the ledger, a predicate on the dat, nothing in the folder.
#
# The vehicle is two tiny dat kinds from `demo_kinds/compute.py`: `Numbers`, a list of integers,
# and `Compute`, whose call is an expression over other dats, `["+", a, b]` or `["*", c, a]`, so
# the dependencies are visible in the data itself. Reference: [concepts](../concepts.md).

# %% [markdown]
# ## A store, and two dats

# %%
# a throwaway dat store, and the two demo kinds
import os, tempfile
from pathlib import Path

from dvc_dat import Dat, DatManager
from demo_kinds.compute import Numbers, Compute

dat_store_path = Path(tempfile.mkdtemp(prefix="demo-dats-"))
Dat.manager = DatManager(dat_folders=[str(dat_store_path / "dats")], art_folder=str(dat_store_path / "art"))

a = Numbers.make("demo/a", [1, 2, 3, 4])
b = Numbers.make("demo/b", [10, 20, 30, 40])
print(f"{a.get_path_name()=}  {a.values()=}")
print("folder:", sorted(p.name for p in Path(a.get_path()).iterdir()))

# %% [markdown]
# `make` creates the folder from a spec (`dat.name`, `dat.kind`), writes one channel, `values`,
# and seals. The folder holds the spec, the channel, and the result the seal wrote.

# %%
# what the seal fixed: the standing, and the hash of the folder
result = a.get_results()["dat"]
print(f"standing={result['standing']}  sha256={result['sha256'][:26]}...")
print(f"same by name: {Dat.manager.load('demo/a').get_results()['dat']['sha256'] == result['sha256']}")

# %% [markdown]
# A sealed dat is frozen: its hash covers the folder, and loading it by name gives the same bytes.

# %% [markdown]
# ## A compute dat, and its dependencies

# %%
# c = a + b: the expression is the call; running it loads a and b, and the seal records them
c = Compute.make("demo/c", ["+", "demo/a", "demo/b"])
print(f"{c.expr()=}  {c.values()=}")
print("dependencies:", {k: v[:19] + "..." for k, v in Dat.get(c.get_results(), "dat.dependencies").items()})

# %% [markdown]
# `dat.dependencies` is name → hash of every dat the run loaded: the inputs, pinned to the bytes
# the run saw.

# %%
# d = c * (a + a): a compute over a compute; the seal keeps the roots, so a is reached through c
d = Compute.make("demo/d", ["*", "demo/c", ["+", "demo/a", "demo/a"]])
print(f"{d.values()=}")
print(f"d depends on: {sorted(Dat.get(d.get_results(), 'dat.dependencies'))}")
print(f"c depends on: {sorted(Dat.get(Dat.manager.load('demo/c').get_results(), 'dat.dependencies'))}")

# %% [markdown]
# The chain is read by following the records: `d` → `c` → `a`, `b`. A dependency that is already
# below another is not repeated (the seal trims to the roots).

# %%
# a sealed dat refuses a write; a changed input is a new dat, not a mutation
def refused(f):
    try:
        f()
        return "not refused"
    except Exception as e:
        return f"{type(e).__name__}: {str(e)[:70]}"

print("write to sealed a:", refused(lambda: a.write_channel("values", [])))
a2 = Numbers.make("demo/a2", [1, 2, 3, 5])
print(f"new dat, new hash: {a2.get_results()['dat']['sha256'] != result['sha256']}")

# %% [markdown]
# ## Versions

# %%
# a version is a predicate on the dat, kept on the ledger; a new version is a new add
from dvc_dat.ledger import Ledger

ledger_path = Path(tempfile.mkdtemp(prefix="demo-dats-ledger-"))
L = Ledger(ledger_path / "ledger", create=True)
with L.transaction(by="human:dan") as t:
    t.add("demo/c", "version", "1.0.0")
with L.transaction(by="human:dan") as t:
    t.add("demo/c", "version", "1.0.1")
print(f"{L.at().get('demo/c', 'version')=}")
print("history:", [(r.rev.id, r.object, r.added) for r in L.at().rows("demo/c", "version")])

# %% [markdown]
# Nothing in the folder changed: the version is a fact about the dat, recorded beside it, with
# its own history.

# %%
# clean up
import shutil
Dat.manager = None
for p in (dat_store_path, ledger_path):
    shutil.rmtree(p)
