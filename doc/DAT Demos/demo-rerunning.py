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
# > **Plan** (delete once the sections carry it). The ledger keeps every past state of its rows, so a past execution can be reproduced two ways: today's code over the old rows, or the old code itself.
# >
# > 1. **Reading a past revision**: `L.at(which)` is the ledger as it stood at a revision.
# > 2. **Running today's code over a past revision**: `L.at(which).run(...)` runs the checkout's code over that revision's rows; `v.at` says what it read, `v.rev` where it was saved.
# > 3. **Sweeping a set of revisions**: `L.revs(...)` names past revisions by label; the sweep is a comprehension over it.
# > 4. **What a sweep recomputes**: one run per distinct set of reads; changed code misses at every revision.
# > 5. **Rerunning a value from its own commit**: `pin` tags and pushes the commit that made a value; `rerun` runs that commit's code again over the revision it read.

# %% [markdown]
# #### Setup

# %%
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from IPython.display import Code, display

import dvc_dat.ledger.txn as ledger_txn
from dvc_dat.ledger import Ledger, bump

for module_name in [m for m in sys.modules if m == "clips" or m.startswith("clips.")]:
    del sys.modules[module_name]                  # a re-run: forget the last run's code repo
sys.path[:] = [p for p in sys.path if not p.endswith("/clips-repo")]
scratch_path = Path(tempfile.mkdtemp(prefix="demo-rerunning-"))
repo_path = scratch_path / "clips-repo"           # the code's repo; the ledger keeps rows, never a checkout
remote_path = scratch_path / "clips-remote.git"   # where a pin pushes its tag
RATES = '''from dvc_dat import dat


@dat.fn
def frame_rate(rev, *, clip: str) -> float:
    return int(rev[f"clip/{clip}", "frames"]) / int(rev[f"clip/{clip}", "seconds"])
'''
(repo_path / "clips").mkdir(parents=True)
(repo_path / "clips/__init__.py").write_text('__version__ = "0.1.0"\n')
(repo_path / "clips/rates.py").write_text(RATES)


def git(*args: str, cwd: Path = repo_path) -> str:
    """Run git; return its stdout."""
    cmd = ["git", "-c", "user.name=demo", "-c", "user.email=demo@example.com",
           "-c", "init.defaultBranch=main", *args]
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(message: str) -> str:
    """Commit the code's repo; its commit, first 8."""
    git("add", ".")
    git("commit", "-q", "-m", message)
    return git("rev-parse", "HEAD")[:8]


def show() -> None:
    """The code's one module, as it is now."""
    display(Code(filename=str(repo_path / "clips/rates.py"), language="python"))


@contextmanager
def dated(moment: str):
    """Transactions in this block stamp `moment`: a year of history, written in one sitting."""
    now = ledger_txn.stamp
    ledger_txn.stamp = lambda: moment
    try:
        yield
    finally:
        ledger_txn.stamp = now


git("init", "-q", "--bare", str(remote_path), cwd=scratch_path)
git("init", "-q")
first_commit = commit("clips: a frame rate")
git("remote", "add", "origin", str(remote_path))
git("push", "-q", "-u", "origin", "main")
sys.path.insert(0, str(repo_path))
import clips  # noqa: E402,F401  (the environment finds the checkout through it)

L = Ledger(scratch_path / "ledger", create=True)
with L.transaction(by="human:dan", why="mount the code") as t:
    t.ns.mount("mnt.clips", root="clips", repo="clips-repo")
RATE = "mnt.clips.rates.frame_rate"


def runs_of(fn_name: str = RATE) -> int:
    """How many results of the function the ledger has sealed: each is one run."""
    return len(L.at().refs(fn=fn_name))


# %% [markdown]
# # Rerunning: reproducing past executions
#
# A ledger never rewrites a row, so every state it ever held can be read again.
# A past execution has two inputs, the rows it read and the code that ran, and the ledger answers for them differently: the rows are all here, at their revision, and the code is only named, by the commit it came from.
# So a new metric runs over last year's rows with one call, and running last year's code needs that commit to still exist, which a pin guarantees.

# %% [markdown]
# ## Reading a past revision
#
# `L.at(which)` is a frozen view of the ledger as it stood at a revision, named by its number, a release, a tag or a date.
#
# One clip's rows, corrected a few times over a year:

# %%
history = [("2025-11-20T12:00:00Z", "3000", "100"), ("2026-01-20T12:00:00Z", "3000", "120"),
           ("2026-03-20T12:00:00Z", "3600", "120"), ("2026-07-20T12:00:00Z", "3600", "100")]
for stamp_text, frame_count, second_count in history:
    with dated(stamp_text), L.transaction(by="human:dan", lock=10, why="a correction") as t:
        t["clip/C1", "frames"] = frame_count
        t["clip/C1", "seconds"] = second_count
        bump(t, "db")                             # a release: the ledger's version moves
with dated("2026-08-20T12:00:00Z"), L.transaction(by="human:dan") as t:
    t.add("x", "note", "nothing about the clip")
    t.add("db", "db/tag", "summer-review")

print("the top:", L.at().id, " frames there:", L.at()["clip/C1", "frames"])   # → the top: 6  frames there: 3600
print("rev 2, frames:", L.at(2)["clip/C1", "frames"])        # → rev 2, frames: 3000
print("release 0.0.2, seconds:", L.at("0.0.2")["clip/C1", "seconds"])   # → release 0.0.2, seconds: 120
print("2026-02-01, seconds:", L.at("2026-02-01")["clip/C1", "seconds"])   # → 2026-02-01, seconds: 120
print("tag, frames:", L.at("summer-review")["clip/C1", "frames"])   # → tag, frames: 3600

# %% [markdown]
# ## Running today's code over a past revision
#
# `L.at(which).run(target, **keys)` runs the checkout's code with its reads folded at that revision, and saves the result at the top.
#
# The function reads rows through the `Rev` it is handed, so it needs no argument saying when; the keys and the code are today's.

# %%
show()
february_rev = L.at("2026-02-01")
rate_value = february_rev.run(RATE, clip="C1")
print("rate:", rate_value.obj)                               # → rate: 25.0
print("read at:", rate_value.at.id, " saved at:", rate_value.rev.id)   # → read at: 3  saved at: 7
print("db/at row:", L.at()[rate_value.subject, "db/at"])     # → db/at row: 3

# %% [markdown]
# `v.at` is the revision the run read, the row `db/at`; `v.rev` is the revision that saved it.
# A result recomputed a year later has a recent `v.rev` and an old `v.at`.
# `L.at(...).run(..., clean=True)` is not this: it demands the commit that revision names, so it refuses present code.

# %% [markdown]
# ## Sweeping a set of revisions
#
# `L.revs(which, since=..., until=...)` names past revisions by label, and the sweep over them is a comprehension.
#
# `"release"` is one per release, labelled by the version; `"tag"` one per tag; `"month"` one per month start, the latest revision at or before it, as `L.at` reads that date; `"day"` and `"week"` the same; a list of `at` arguments, each its own label.
# A month before the first stamp is omitted.

# %%
print("by release:", L.revs("release"))
print("by tag:", L.revs("tag"))
print("by list:", L.revs([1, "2026-02-01", "summer-review"]))
month_revs = L.revs("month", since="2025-10", until="2026-08")
print("by month:", {month: rev.id for month, rev in month_revs.items()})

# %%
rate_by_month = {month: rev.run(RATE, clip="C1").obj for month, rev in month_revs.items()}
print("rate by month:", rate_by_month)

# %% [markdown]
# Each result says which revision it read, so a chart of a metric over time needs no bookkeeping beside it.

# %%
read_by_month = {month: rev.run(RATE, clip="C1").at.id for month, rev in month_revs.items()}
print("read at, by month:", read_by_month)

# %% [markdown]
# ## What a sweep recomputes
#
# A sweep costs one run per distinct set of reads, and a run answers for every revision where those reads still hold.
#
# The nine months above name four different revisions, each with its own rows, so the function ran four times, and sweeping again runs nothing.
# The tag's revision wrote nothing about the clip, so a run there reads what revision 5 read and is handed revision 5's entry: its `v.at` is 5, the revision it was computed from, not the 6 that was asked.

# %%
print("runs so far:", runs_of())                             # → runs so far: 4
again_by_month = {month: rev.run(RATE, clip="C1").obj for month, rev in month_revs.items()}
print("runs after a second sweep:", runs_of(), " same:", again_by_month == rate_by_month)
# → runs after a second sweep: 4  same: True
review_value = L.at("summer-review").run(RATE, clip="C1")
print("asked at:", L.at("summer-review").id, " read at:", review_value.at.id, " runs:", runs_of())
# → asked at: 6  read at: 5  runs: 4

# %% [markdown]
# Changing the code misses at every revision: the memo compares today's code with the code each entry ran, and the old entries stay, answering for the old checkout.

# %%
rates_path = repo_path / "clips/rates.py"
rates_path.write_text(RATES.replace("return int", "return 1000 * int"))
second_commit = commit("clips: frames per kilosecond")
show()
milli_by_month = {month: rev.run(RATE, clip="C1").obj for month, rev in month_revs.items()}
print("rate by month:", milli_by_month)
print("runs now:", runs_of())                                # → runs now: 8

# %% [markdown]
# ## Rerunning a value from its own commit
#
# `L.at().pin(value)` makes a value's code permanent, and `rev.rerun(value)` runs that code again and compares the bytes.
#
# `pin` tags the commit the value's run names, `dat/<commit12>`, and returns once the tag is pushed, so the commit outlives any branch.
# `rerun` checks that tag out beside the ledger, runs the function in a fresh interpreter over the revision the value read, `v.at`, and compares the hash: present code does not enter into it.

# %%
print("the checkout now:", second_commit, " the value's run:", first_commit)
print("pinned as:", L.at().pin(rate_value))
print("tags on the remote:", git("ls-remote", "--tags", "origin").split("refs/tags/")[-1])

# %%
rerun_result = L.at().rerun(rate_value)
print("outcome:", rerun_result.outcome)
print("hash, then and now:", rerun_result.expected[:12], rerun_result.hash[:12])
print("at commit:", rerun_result.commit[:8], " in:", "/".join(rerun_result.worktree.parts[-4:]))

# %% [markdown]
# `reproduced` means the bytes matched; a function that claims `@dat.fn(reproducible="exact")` and differs is an error, and a function with no claim that differs is only reported.
# The value above was computed by the first commit from the February rows, with the checkout now at the second commit and the rows moved twice since, so all that made it possible are the two things it named: `v.at` and its pinned commit.
