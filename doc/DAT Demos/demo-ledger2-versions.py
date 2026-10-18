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
# # Demo: ledger2 versions
#
# Which version of everything did a result use? Any subject may carry
# a `version` row (`MAJOR.MINOR.PATCH`), and every transaction moves
# one clock, the revision number, so one revision fixes the versions
# of the code, the data and the models at once. The subject `ledger`
# carries a version too: a release is a bump of it, and its number is
# the name people use for a moment. This notebook bumps components,
# cuts two releases, and compares them.

# %%
import os, shutil, tempfile
from pathlib import Path

from dvc_dat.ledger2 import Ledger, bump

ledger_dir = Path(tempfile.mkdtemp(prefix="demo-l2-ver-"))
os.environ["DAT_LEDGER"] = str(ledger_dir)
L = Ledger.open()

START = {"code/sv-pipe": "0.2.2", "data/norm": "7.0.0",
         "model/player-id": "2.1.0", "schema/tape": "3.0.0",
         "ledger": "3.0.4"}
with L.transaction(by="human:dan") as t:
    for subject, version in START.items():
        t.add(subject, "version", version)
    t.add("code/sv-pipe", "commit", "7d742989")
rev = L.at()
print(rev, {s: rev[s, "version"] for s in START})

# %% [markdown]
# Five versioned subjects, written in revision 1. `version` is an
# ordinary predicate: nothing about these subjects is reserved but
# the name `ledger`.

# %% [markdown]
# ## A patch bump

# %%
with L.transaction(by="human:dan", time=True,
                   why="T531 re-baseline") as t:
    new = bump(t, "code/sv-pipe", "patch")
    t.add("code/sv-pipe", "commit", "b48dca7c")
print(new, t.rev)
for r in (L.at(1), L.at(2)):
    print(r, r["code/sv-pipe", "version"],
          r["data/norm", "version"])

# %% [markdown]
# `bump` reads the version through `t.base`, adds the next one, and
# returns it. One subject moved; the clock advanced by one; every
# other version reads the same at 2 as at 1.

# %% [markdown]
# ## Minor and major bumps ask first

# %%
top = L.at().id
try:
    with L.transaction(by="human:dan") as t:
        bump(t, "model/player-id", "minor")
except ValueError as e:
    print("refused:", e)
print("revision unchanged:", L.at().id == top)

# %%
def yes(old, new):
    print(f"  confirm {old} -> {new}: yes")
    return True


with L.transaction(by="human:dan", why="retrain accepted") as t:
    bump(t, "model/player-id", "minor", confirm=yes)
print(L.at()["model/player-id", "version"])

# %% [markdown]
# A `minor` or `major` bump needs `confirm(old, new)` to answer
# `True`; without it the whole transaction is refused. A patch never
# asks.

# %% [markdown]
# ## A release is a bump of `ledger`

# %%
with L.transaction(by="human:dan", time=True,
                   why="September release") as t:
    bump(t, "ledger", "minor", confirm=yes)
sept = t.rev

with L.transaction(by="human:dan") as t:
    bump(t, "data/norm", "major", confirm=yes)
with L.transaction(by="human:dan") as t:
    bump(t, "code/sv-pipe", "patch")
    t.add("code/sv-pipe", "commit", "c1e5a7f0")
with L.transaction(by="human:dan", time=True,
                   why="October release") as t:
    bump(t, "ledger", "minor", confirm=yes)
print("releases at", sept, "and", t.rev)

# %% [markdown]
# Two releases, 3.1.0 and 3.2.0, with a data edition and a code patch
# between them.

# %% [markdown]
# ## `at(int)` and `at("M.m.p")`

# %%
print(L.at(4), L.at("3.1.0"), L.at("3.2.0"), L.at("4"))
print(L.at()["ledger", "version", "3.1.0"])
for name in ("3.1.0", "3.2.0"):
    r = L.at(name)
    print(name, {s: r[s, "version"] for s in START})

# %% [markdown]
# An `int` (or a digit string) is a revision; a `M.m.p` string is a
# ledger version, resolved to the revision that asserted it, which is
# what the three-position pattern `["ledger", "version", "3.1.0"]`
# returns. Each release names the whole combination.

# %% [markdown]
# ## Two releases, compared

# %%
a, b = L.at("3.1.0"), L.at("3.2.0")
for row in b.all(since=a):
    print(row)

# %% [markdown]
# `since=a` keeps only the rows asserted in `(a, b]`: everything that
# happened between the releases, provenance rows included.

# %%
moved = b.refs(where={"version": None}, since=a)
print([r.subject for r in moved])
print(b.select(("version",), where={"version": None}, since=a))
print("untouched:", sorted(set(START) - {r.subject for r in moved}))

# %% [markdown]
# `where={"version": None}` means "has a version row, any value", so
# with `since=` it lists the subjects whose version moved, and
# `select` returns their new versions as tuples.

# %%
for v in ("0.2.2", "0.2.3", "0.2.4"):
    print(v, "asserted at", b["code/sv-pipe", "version", v])
print([L.at(i)["code/sv-pipe", "version"] for i in range(1, b.id + 1)])

# %% [markdown]
# A two-position read is a fold: one held value per `one` predicate.
# The three-position pattern reads history instead, the revision that
# asserted each value; walking the clock shows the version at every
# revision.

# %%
shutil.rmtree(ledger_dir)
del os.environ["DAT_LEDGER"]
print("removed:", not ledger_dir.exists())
