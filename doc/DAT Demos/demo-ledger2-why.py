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
# # Demo: ledger2 why
#
# Why does this value exist, and what would re-derive it? Every sealed
# value carries its trace, and every row it was written with belongs
# to a transaction, so a value can be walked back to the inputs it
# read, the function and code that made it, and the person or agent
# that asked. This notebook takes a hand-sealed report built on an
# identity model for G5, walks it back to its roots, then moves one of
# them and asks what has to be recomputed.

# %%
import os, shutil, sys, tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, "demo_svp")          # the stand-in svp package
from dvc_dat.ledger2 import Code, Env, Ledger, Pickled
from dvc_dat.ledger2 import bump, set_env_provider
from svp.shots import Shots

ENV = Env({"sv-pipe": Code("0.2.2", "7d742989")},
          lock="sha256:5e1f", platform="darwin-arm64-py3.11")
old_provider = set_env_provider(lambda module: ENV)
ledger_dir = Path(tempfile.mkdtemp(prefix="demo-l2-why-"))
os.environ["DAT_LEDGER"] = str(ledger_dir)
L = Ledger.open()
with L.transaction(by="human:dan") as t:
    t.add("code/sv-pipe", "version", "0.2.2")
    t.add("code/sv-pipe", "commit", "7d742989")
    t.add("model/player-id", "version", "2.1.0")
    frames = pd.DataFrame({"frame": range(5)})
    t.add("run/0-2-2/G5", "value", Shots(frames))

model = L.at().eval("svp.identity.train", game="G5")
report = Pickled({"game": "G5", "verdict": "ship",
                  "model": model.obj["base"]})
with L.transaction(by="human:ana", time=True,
                   why="identity sign-off", ticket="T540") as t:
    t.seal(report, deps=[model])
    t.add("report/identity-G5", "value", report)
print(L.at())

# %% [markdown]
# Revision 1 holds the inputs, revision 2 the memo entry the `eval`
# sealed, revision 3 Ana's report, sealed by hand against the model
# and named `report/identity-G5`.

# %% [markdown]
# ## Start from a name

# %%
rev = L.at()
v = rev.load("report/identity-G5")
print(v.obj)
print(v.subject, v.sealed)
for item, value in v.trace.items():
    print(f"  {item:32} {value[:24]}")

# %% [markdown]
# The name points at a sealed subject. Its trace says it was made from
# one dat, the model's subject, at a given hash, in sv-pipe 0.2.2.

# %% [markdown]
# ## Who sealed it, and when

# %%
made = rev[v.subject, "provenance", "seal"]
print(made, rev[v.subject, "provenance"])
for p, o in rev.all(made.tx):
    print(f"  {made.tx}  {p:7} {o}")

# %% [markdown]
# The three-position pattern returns the revision that asserted the
# seal; that revision's transaction subject says who, when and why.

# %% [markdown]
# ## Its dependency

# %%
dep = next(k for k in v.trace if k.startswith("dat:"))[4:]
d = rev.load(dep)
print(dep, rev[dep, "provenance"], rev[dep, "fn"])
print("keys:", {p: o for p, o in rev.all(dep)
                if p.startswith("kwargs.")})
print("same bytes as declared:", d.hash == v.trace["dat:" + dep])

# %% [markdown]
# The dep is a memo entry: `provenance` `eval`, its function's dotted
# name, and its keys.

# %%
d_made = rev[dep, "provenance", "eval"]
print(d_made, rev[d_made.tx, "by"])
for item, value in d.trace.items():
    print(f"  {item:22} {value[:34]}")

# %% [markdown]
# `eval` sealed it in its own transaction, `by` the function. Its
# trace is recorded, not declared: the version it read, the run it
# loaded, the code, and `fn`, the subject naming the exact code.

# %% [markdown]
# ## The function

# %%
code = dict(rev.all(d.trace["fn"]))
print(code["name"], code["mode"], Path(code["module"]).name)
print(code["sha"][:23])
f = rev.load_fn(rev[dep, "fn"])
print("still this code:", f.subject == d.trace["fn"])

# %% [markdown]
# `ledger/fn/<name>/<hash>` records the code a name resolved to: its
# module file and that file's hash. `load_fn` resolves the name now;
# the same subject means the same source.

# %% [markdown]
# ## What would re-derive it

# %%
print("report holds:", v.matches(rev), "| model holds:",
      d.matches(rev))
with L.transaction(by="human:dan") as t:
    bump(t, "model/player-id", "patch")
top = L.at()
print("report holds:", v.matches(top), "| model holds:",
      d.matches(top))
for row in top.all(since=rev):
    print(row)

# %% [markdown]
# Both held at revision 3. After the player-id bump the model no
# longer matches; `since=` lists exactly what moved. The report still
# matches: its trace pins the model's bytes, and those have not
# changed.

# %%
keys = {p[len("kwargs."):]: o for p, o in rev.all(dep)
        if p.startswith("kwargs.")}
fresh = top.eval(rev[dep, "fn"], **keys)
print(fresh.subject != d.subject, d.diff(fresh))
print("report would change:", fresh.obj["base"] != v.obj["model"])

# %% [markdown]
# Re-deriving is the same call with the same keys at the new revision:
# a miss, a new entry, and `diff` names the one item that moved. The
# old entry and the report built on it stay, readable at their
# revisions.

# %%
set_env_provider(old_provider)
shutil.rmtree(ledger_dir)
del os.environ["DAT_LEDGER"]
print("removed:", not ledger_dir.exists())
