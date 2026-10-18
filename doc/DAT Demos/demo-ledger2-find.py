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
# # Demo: ledger2 find
#
# How do you find things in the ledger without knowing their names?
# Treat it as a table whose rows are subjects and whose columns are
# predicates: `refs` returns the subjects matching a where clause, as
# `Ref`s; `select` returns chosen columns of them, as tuples. This
# notebook fills a ledger with runs, versions and identity-model memo
# entries, then asks questions of it.

# %%
import os, shutil, sys, tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, "demo_svp")          # the stand-in svp package
from dvc_dat.ledger2 import Code, Env, Ledger, Unindexed
from dvc_dat.ledger2 import set_env_provider
from svp.shots import Shots

ENV = Env({"sv-pipe": Code("0.2.2", "7d742989")},
          lock="sha256:5e1f", platform="darwin-arm64-py3.11")
old_provider = set_env_provider(lambda module: ENV)
ledger_dir = Path(tempfile.mkdtemp(prefix="demo-l2-find-"))
os.environ["DAT_LEDGER"] = str(ledger_dir)
L = Ledger.open()
with L.transaction(by="human:dan") as t:
    t.add("code/sv-pipe", "version", "0.2.2")
    t.add("code/sv-pipe", "commit", "7d742989")
    t.add("model/player-id", "version", "2.1.0")
    t.add("model/shot", "version", "0.2.2")
    for g in ("G1", "G4", "G5"):
        frames = pd.DataFrame({"frame": range(int(g[1:]))})
        t.add(f"run/0-2-2/{g}", "value", Shots(frames))
    t.add("run/0-2-1/G5", "value", Shots(pd.DataFrame({"f": [0]})))
    t.add("ledger/pred/result.acc", "index", "true")
    t.add("ledger/pred/result.loss", "index", "true")

rev = L.at()
for game, epochs in (("G1", 8), ("G4", 8), ("G5", 8), ("G5", 12)):
    rev.eval("svp.identity.train", game=game, epochs=epochs)
print(L.at())

# %% [markdown]
# Four runs, three versioned subjects, four memo entries. Two dotted
# predicates are declared indexed: `result.acc` and `result.loss`.

# %% [markdown]
# ## `refs`: which subjects

# %%
rev = L.at()
print(rev.refs(s="run/0-2-2/*"))
print(rev.refs(s="run/0-2-1/G5"))
print([r.subject for r in rev.refs(where={"version": None})])
print([r.subject for r in rev.refs(where={"version": "0.2.2"})])

# %% [markdown]
# `s=` is an exact subject or a prefix ending in `*`. `where` maps a
# predicate to a value, or to `None` for "any value".

# %%
entries = rev.refs(fn="svp.identity.train", game="G5")
print(entries)
e = entries[-1]
print(dict(e.rev.all(e.subject))["kwargs.epochs"], e.load().obj)

# %% [markdown]
# A bare keyword is a key of a memo entry (`kwargs.<k>`), and `fn=` is
# its function. A `Ref` is one subject at one revision: its rows are
# readable without loading, and `load()` fetches the value.

# %% [markdown]
# ## `select`: which values

# %%
for row in rev.select(("game", "epochs", "result.acc"),
                      fn="svp.identity.train"):
    print(row)

# %% [markdown]
# `keys` names the columns, in order; each match comes back as a
# tuple. `game` and `epochs` are keys; `result.acc` is the indexed
# attribute `seal` computed from the result. Values come back as text.

# %%
print(rev.select(("game", "epochs"), fn="svp.identity.train",
                 where={"result.acc": "0.93"}))
print(rev.select(("version",), s="model/*"))

# %% [markdown]
# Keys, `where` and `s=` combine: the G5 entries by accuracy, and the
# version of every `model/` subject.

# %% [markdown]
# ## An index declared later

# %%
with L.transaction(by="human:dan") as t:
    t.add("ledger/pred/result.frames", "index", "true")
rev = L.at()
rev.eval("svp.identity.train", game="G4", epochs=12)
print(rev.select(("game", "epochs"), fn="svp.identity.train",
                 where={"result.frames": None}))
print(L.at().select(("game", "epochs", "result.frames"),
                    fn="svp.identity.train",
                    where={"result.frames": None}))

# %% [markdown]
# A declaration covers the seals made after it; earlier entries do
# not get the row. `select` reads as of its revision, so the new G4
# entry shows only at the top.

# %% [markdown]
# ## `one=`

# %%
rev = L.at()
print(rev.refs(fn="svp.identity.train", game="G1", one=True))
for game in ("G5", "G7"):
    try:
        rev.refs(fn="svp.identity.train", game=game, one=True)
    except LookupError as e:
        print(type(e).__name__, "-", e)

# %% [markdown]
# `one=True` returns the single match itself, and raises `Multiple`
# for several and `KeyError` for none.

# %% [markdown]
# ## `Unindexed`

# %%
print(rev.refs(where={"result.loss": "0.1"}))
try:
    rev.refs(where={"result.accuracy": "0.93"})
except Unindexed as e:
    print("Unindexed:", e)

# %% [markdown]
# A dotted predicate that is declared but has no rows answers `[]`. One
# neither declared nor present on any row (here a typo) raises.

# %%
set_env_provider(old_provider)
shutil.rmtree(ledger_dir)
del os.environ["DAT_LEDGER"]
print("removed:", not ledger_dir.exists())
