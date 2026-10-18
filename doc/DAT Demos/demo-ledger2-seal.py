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
# # Demo: ledger2 seal
#
# How does a value made by hand become something the ledger vouches
# for? `t.seal(v, deps=[...])` freezes a `Value` into an immutable
# subject named by its content and its declared inputs, and writes
# rows saying what it is and what it was made from. This notebook
# classifies the shots of game G5 by hand, seals the table against
# the run and the model it used, gives it a readable name, and loads
# it back.

# %%
import inspect, os, shutil, sys, tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, "demo_svp")          # the stand-in svp package
from dvc_dat.ledger2 import Code, Env, Exists, Ledger
from dvc_dat.ledger2 import set_env_provider
from svp.shots import Shots

ENV = Env({"sv-pipe": Code("0.2.2", "7d742989")},
          lock="sha256:5e1f", platform="darwin-arm64-py3.11")
old_provider = set_env_provider(lambda module: ENV)
ledger_dir = Path(tempfile.mkdtemp(prefix="demo-l2-seal-"))
os.environ["DAT_LEDGER"] = str(ledger_dir)
L = Ledger.open()

# %% [markdown]
# The environment is pinned (sv-pipe 0.2.2 at `7d742989`) so the
# output is the same on every machine.

# %% [markdown]
# ## A hand-made `Value`

# %%
print(inspect.getsource(Shots))

# %% [markdown]
# A `Value` subclass says how it becomes bytes and back. It lives in
# a module, `svp.shots`, because a loaded value finds its class by
# dotted name.

# %%
frames = pd.DataFrame({"frame": [120, 388, 902],
                       "x": [0.41, 0.77, 0.52]})
with L.transaction(by="human:dan") as t:
    t.add("code/sv-pipe", "version", "0.2.2")
    t.add("code/sv-pipe", "commit", "7d742989")
    t.add("model/shot", "version", "1.0.0")
    t.add("model/shot", "value", {"threshold": 0.6})
    t.add("run/0-2-2/G5", "value", Shots(frames))
rev = L.at()
run, model = rev.load("run/0-2-2/G5"), rev.load("model/shot")
print(type(run).__name__, run.subject, run.sealed)
print(type(model).__name__, model.obj, model.sealed)

# %% [markdown]
# `add(s, "value", v)` stores the bytes by hash and points the
# subject at them; `rev.load(s)` brings the object back. Neither is
# sealed: a `value` row can be replaced by the next `add`.

# %% [markdown]
# ## `seal`

# %%
def classify(run, model):
    made = run.table["x"] > model.obj["threshold"]
    return run.table.assign(made=made)


hand = Shots(classify(run, model))
with L.transaction(by="human:dan", time=True) as t:
    subj = t.seal(hand, deps=[run, model])
print(subj, hand.sealed, hand.subject == subj)
for item, value in hand.trace.items():
    print(f"  {item:22} {value[:30]}")

# %% [markdown]
# The subject is `<kind>/<hash>`, hashed over the bytes and the trace.
# The trace is what the value was made from: each declared dep by its
# hash, plus the code, the lock and the platform it was made in.

# %%
for p, o in L.at().all(subj):
    print(f"  {p:24} {str(o)[:40]}")

# %% [markdown]
# The rows `seal` wrote: the `value` (an artifact `Ref`), the `kind`,
# the `provenance` (`seal`, the verb), and one `trace.` row per item.

# %% [markdown]
# ## Sealed is immutable

# %%
def add_row(p, o):
    with L.transaction(by="human:dan") as t:
        t.add(subj, p, o)


try:
    add_row("kind", "Tracks")
except Exists as e:
    print("Exists:", e)
add_row("note", "by hand, G5")
print(L.at()[subj, "note"])

# %% [markdown]
# A sealed subject's own predicates are written once: rewriting one
# raises `Exists` at commit. Any other predicate is an annotation and
# is free.

# %%
rev = L.at()
run, model = rev.load("run/0-2-2/G5"), rev.load("model/shot")
again = Shots(classify(run, model))
with L.transaction(by="human:dan") as t:
    same = t.seal(again, deps=[run, model])
print(same == subj, t.rev.all(since=L.at(t.rev.id - 1)))

# %% [markdown]
# Sealing the same bytes with the same deps is the same subject, and
# writes nothing but the transaction's `by` row. (A dep loaded at an
# older revision than `t.base` is traced as `dat:<subject>@<rev>`,
# which makes a different subject; so the deps are reloaded here.)

# %% [markdown]
# ## A readable name is a pointer

# %%
with L.transaction(by="human:dan") as t:
    t.add("shots/G5-byhand", "value", hand)
rev = L.at()
print(rev["shots/G5-byhand", "value"])
back = rev.load("shots/G5-byhand")
print(back.subject, back.sealed, back.same_as(hand))
print(back.table.to_string(index=False))

# %% [markdown]
# `shots/G5-byhand` holds a `value` row that points at the sealed
# subject. `rev.load(name)` follows it and hands back the sealed value
# with its subject and trace restored.

# %%
with L.transaction(by="human:dan") as t:
    t.add("model/shot", "value", {"threshold": 0.5})
print("still holds at rev:", back.matches(back.rev))
print("holds at the top:  ", back.matches(L.at()))

# %% [markdown]
# `matches(rev)` re-checks every trace item at a revision: the model
# it declared has moved since, so at the top it no longer holds. The
# sealed subject itself is unchanged.

# %%
set_env_provider(old_provider)
shutil.rmtree(ledger_dir)
del os.environ["DAT_LEDGER"]
print("removed:", not ledger_dir.exists())
