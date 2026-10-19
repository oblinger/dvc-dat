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
# # Demo: ETL, datasets built on datasets
#
# A **gamey** is a list of integers. A **binning** is fit over a set of them. A **trial** places one
# gamey into a binning, and its result is a podium: the three fullest bins. **Metrics** describe a
# trial. Each is a dat built from the one below, so the chain is
# gamey → binning → trial → metrics, and each seal records the stage below it as a dependency.
# (The stage is a trial, not a run: in dvc-dat a run is the sub-dat an `execute` makes inside a dat.)
#
# The kinds are `demo_kinds/etl.py`; the dat mechanics (seal, hash, dependencies) are
# `demo-dats`'s. This is the bare bones: each stage is made by hand with its kind's `make`, and
# the game set and its version are rows on the ledger (`ledger-triples`).

# %%
# a fresh ledger and dat store in throwaway folders, and the four kinds
import os, tempfile
from pathlib import Path

from dvc_dat import Dat, DatManager
from dvc_dat.ledger import Ledger
from demo_kinds.etl import Gamey, Binning, Trial, Metrics

ledger_path = Path(tempfile.mkdtemp(prefix="demo-etl-"))
L = Ledger(ledger_path / "ledger", create=True)
dat_store_path = Path(tempfile.mkdtemp(prefix="demo-etl-dats-"))
Dat.manager = DatManager(dat_folders=[str(dat_store_path / "dats")], art_folder=str(dat_store_path / "art"))

# %% [markdown]
# ## Gameys

# %%
# three gameys from G numbers, reproducible from their seeds
for g in ("G1", "G2", "G3"):
    Gamey.make(f"gamey/{g}", n=200, seed=int(g[1:]))
g3 = Dat.manager.load("gamey/G3")
print(f"{len(g3.values())=}  first ten: {g3.values()[:10]}")
print(f"same seed, same list: {Gamey.make('gamey/G3-again', n=200, seed=3).values() == g3.values()}")

# %% [markdown]
# ## The normie game set

# %%
# the normie game set: assertions on the ledger, as NORM is made
with L.transaction(by="human:dan") as t:
    t.add("db/pred/contains", "db/cardinality", "many")   # a set, not one value
    for g in ("G1", "G2", "G3"):
        t.add("gameset/normie", "contains", f"gamey/{g}")
normie = L.at().all("gameset/normie", "contains")
print(f"{normie=}")

# %%
# a version on the set: one more row
with L.transaction(by="human:dan") as t:
    t.add("gameset/normie", "version", "0.1.0")
print(f"{L.at().get('gameset/normie', 'version')=}")

# %% [markdown]
# ## A binning over the set

# %%
# the binning for normie 0.1.0, fit over its games (bins and trim at defaults)
b = Binning.make("binning/normie-0.1.0", normie)
print(f"{b.kwargs()=}")
print(f"edges={[round(e, 1) for e in b.edges()]}")

# %%
# another binning, same set, other parameters: made the same way, named by its parameters
b16 = Binning.make("binning/normie-0.1.0-bins16-trim0", normie, bins=16, trim=0.0)
print(f"{len(b16.edges())=}  {b16.edges()[0]=}  {b16.edges()[-1]=}")

# %% [markdown]
# Trim drops the tails before the edges are drawn, so the default binning spans less than the
# untrimmed one and its bins are narrower.

# %% [markdown]
# ## A trial and its metrics

# %%
# a trial: G3 placed into the binning; the podium is the three fullest bins
r = Trial.make("trial/normie-0.1.0-G3", "gamey/G3", b.get_path_name())
print(f"podium={r.podium()}")
print(r.table("placements").head(5))

# %%
# metrics over the trial, a dat of its own: values max / min / mean, and the residual inside each bin
m = Metrics.make("metrics/normie-0.1.0-G3", r.get_path_name())
res = m.get_results()
print(f"max={res['max']}  min={res['min']}  mean={res['mean']:.1f}")
print(f"residual: min={res['residual']['min']:.3f}  mean={res['residual']['mean']:.3f}  spread={res['residual']['spread']:.3f}")

# %% [markdown]
# ## The chain, read back

# %%
# each seal lists the stage below it; the seal keeps the roots
for d in (m, r, b):
    print(f"{d.get_path_name():30} depends on {sorted(Dat.get(d.get_results(), 'dat.dependencies'))}")

# %% [markdown]
# The trial loaded both G3 and the binning, but G3 is already below the binning (normie holds it),
# so the seal keeps only the binning: the chain is followed metrics → trial → binning → G1, G2, G3.
# `$MANUAL` marks a dat sealed by hand rather than by a run; it is trimmed wherever an input
# already carries it.

# %%
# clean up
import shutil
Dat.manager = None
for p in (dat_store_path, ledger_path):
    shutil.rmtree(p)
