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
# # Demo: ledger2 eval
#
# When does a result have to be recomputed? `rev.eval(name, **keys)`
# runs a module function against a revision, records everything the
# function read, and seals the result as a memo entry. The next call
# with the same keys is a hit while everything it read still reads
# the same, and a miss once any of it moves. This notebook trains the
# identity model for games G5 and G1 with `svp.identity.train` and
# watches what turns a hit into a miss.

# %%
import inspect, os, shutil, sys, tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, "demo_svp")          # the stand-in svp package
from dvc_dat.ledger2 import Code, Env, Ledger, NotEvaluated
from dvc_dat.ledger2 import bump, set_env_provider
from svp.shots import Shots
import svp.identity

ENV = Env({"sv-pipe": Code("0.2.2", "7d742989")},
          lock="sha256:5e1f", platform="darwin-arm64-py3.11")
old_provider = set_env_provider(lambda module: ENV)
ledger_dir = Path(tempfile.mkdtemp(prefix="demo-l2-eval-"))
os.environ["DAT_LEDGER"] = str(ledger_dir)
L = Ledger.open()
with L.transaction(by="human:dan") as t:
    t.add("code/sv-pipe", "version", "0.2.2")
    t.add("code/sv-pipe", "commit", "7d742989")
    t.add("model/player-id", "version", "2.1.0")
    t.add("data/norm", "version", "7.0.0")
    for g, n in (("G5", 5), ("G1", 3)):
        frames = pd.DataFrame({"frame": range(n)})
        t.add(f"run/0-2-2/{g}", "value", Shots(frames))
print(inspect.getsource(svp.identity.train))

# %% [markdown]
# The function takes the revision first and its keys after. It reads
# a version row and loads a run, both through `rev`. The environment
# is pinned to sv-pipe 0.2.2 at `7d742989`, matching the ledger's
# `code/sv-pipe` rows, which is what lets it run.

# %% [markdown]
# ## A miss runs and seals; a hit writes nothing

# %%
rev = L.at()
m = rev.eval("svp.identity.train", game="G5")
print(m.obj)
print(m.subject, m.sealed, m.rev, "top:", L.at())

# %% [markdown]
# The first call missed: it ran, sealed the result as `Pickled/...`
# in a new revision (2), and handed back the value itself with its
# provenance on it. `m.rev` is the revision it was evaluated at.

# %%
hit = L.at().eval("svp.identity.train", game="G5")
print(hit.subject == m.subject, "top:", L.at())
for item, value in m.trace.items():
    print(f"  {item:30} {value[:26]}")

# %% [markdown]
# The second call hit: same subject, no new revision. The trace is
# what the hit test compares: the two reads (`model/player-id`, the
# run's hash), the code, the function's own subject, the lock and the
# platform. `data/norm` is not in it: the function never read it.

# %% [markdown]
# ## `memo="get"` and `memo=False`

# %%
rev = L.at()
print(rev.eval("svp.identity.train", game="G1", memo="get"))
c = rev.eval("svp.identity.train", game="G1", memo=False)
print(c.obj, c.sealed, c.subject, "top:", L.at())

# %% [markdown]
# `"get"` only looks: `None` for G1, never computed. `False` runs and
# seals nothing.

# %% [markdown]
# ## `load_fn`: resolve once, call many

# %%
f = L.at().load_fn("svp.identity.train")
print(f.name, f.mode, f.signature)
print(f.subject)
for game in ("G5", "G1"):
    print(game, f(game=game).subject)
print(f(game="G5", epochs=8).subject == m.subject)

# %% [markdown]
# `load_fn` returns the `Fn`; calling it is `eval` at the revision it
# was loaded at. G5 hits and G1 runs. A key passed at its default is
# the same entry.

# %% [markdown]
# ## What turns a hit into a miss

# %%
with L.transaction(by="human:dan") as t:
    bump(t, "data/norm", "patch")
r = L.at().eval("svp.identity.train", game="G5")
print("after a data/norm bump: ", r.subject == m.subject)

with L.transaction(by="human:dan") as t:
    bump(t, "model/player-id", "patch")
r2 = L.at().eval("svp.identity.train", game="G5")
print("after a player-id bump:", r2.subject == m.subject)
print(r2.obj["base"], m.diff(r2))

# %% [markdown]
# A bump of something the function never read leaves it a hit; a bump
# of something it read is a miss, a run and a new entry. `diff` names
# exactly the item that moved.

# %%
with L.transaction(by="human:dan") as t:
    bump(t, "code/sv-pipe", "patch")
    t.add("code/sv-pipe", "commit", "b48dca7c")
try:
    L.at().eval("svp.identity.train", game="G5")
except NotEvaluated as e:
    print("NotEvaluated:", e)

# %% [markdown]
# A code bump in the ledger is a miss, and this environment is still
# 0.2.2 at `7d742989`: rather than seal a result with false
# provenance, `eval` refuses to run.

# %%
NEW = Env({"sv-pipe": Code("0.2.3", "b48dca7c")},
          lock=ENV.lock, platform=ENV.platform)
set_env_provider(lambda module: NEW)
r3 = L.at().eval("svp.identity.train", game="G5")
print(r2.diff(r3))

# %% [markdown]
# In an environment at the new commit it runs, and the trace says the
# code moved.

# %% [markdown]
# ## Stale entries are kept

# %%
top = L.at()
for e in top.refs(fn="svp.identity.train", game="G5"):
    rows = dict(e.rev.all(e.subject))
    print(e.subject, rows["trace.model/player-id"],
          rows["trace.code/sv-pipe"])
first = L.at(1).eval("svp.identity.train", game="G5", memo="get")
print("rev 1 still answers:", first.subject == m.subject)

# %% [markdown]
# Every entry stays, one per trace. A revision that still holds the
# old bindings, here revision 1, still finds its own entry.

# %%
set_env_provider(old_provider)
shutil.rmtree(ledger_dir)
del os.environ["DAT_LEDGER"]
print("removed:", not ledger_dir.exists())
