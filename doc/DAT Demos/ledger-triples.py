# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# #### Setup

# %%
import os, time
from pathlib import Path

from dvc_dat.ledger import Ledger, bump
from dvc_dat.ledger import LockTimeout

scratch_ledger_path = Path("scratch/triples-demo/ledger").resolve()

# %% [markdown]
# # Ledger: triples
#
# The ledger as a quad store and nothing else. Every fact is a row
# `(rev, subject, predicate, object)`, every write is one
# transaction, every read is a function of one revision. No `eval`
# and no value functions here: the running example is plain
# metadata about games (`game/G1`: teams, date, court, officials)
# and a few clock subjects (`code/demo-game`, `schema/tape`).

# %% [markdown]
# ## One constructor

# %%
L = Ledger(scratch_ledger_path, create=True)   # made, then opened

# %% [markdown]
# `Ledger(path)` opens what is there and raises
# `LedgerError` when nothing is; `create=True` is the one explicit
# act that makes a ledger, so an empty one never appears by accident.

# %%
L = Ledger(scratch_ledger_path)                # reopened by path

# %% [markdown]
# ### A project's `.datconfig.yaml`
#
# In real code a project names its ledger once and every script in
# it says `Ledger()` with no argument. `Ledger(create=True)` with no
# path makes a project here: it writes `.datconfig.yaml` with a
# `ledger:` line and creates the ledger it names.

# %%
project_path = Path("scratch/triples-demo/project").resolve()
project_path.mkdir(parents=True, exist_ok=True)
os.chdir(project_path)
L = Ledger(create=True)                   # .datconfig.yaml + ledger

print((project_path / ".datconfig.yaml").read_text())
# ledger: .dat/ledger

# %% [markdown]
# The one line is the whole config this notebook needs: `ledger:`,
# a path relative to the file's own folder. The same file carries a
# project's `mounts:` (the values and dats notebooks), and dvc-dat's
# own keys; it is the file the dat manager already reads. `Ledger()`
# walks up from the working directory to the nearest `.datconfig.yaml`
# carrying `ledger:` and never creates anything.

# %%
L = Ledger()                              # the project's ledger

# %% [markdown]
# ## One transaction is one revision

# %%
with L.transaction(by="human:dan", time=True,
                   why="season opener") as t:
    t.add("game/G1", "home", "G4")
    t.add("game/G1", "away", "G5")
    t.add("game/G1", "date", "2026-10-11")
    t.add("game/G1", "court", "north")
rev1 = t.rev
print(rev1.id, rev1.tx)              # 1 db/tx/1
print(rev1.get(rev1.tx, "db/by"))    # human:dan
print(rev1.get(rev1.tx, "db/time"))  # 2026-10-18T15:52:07Z (UTC)
print(sorted(p for p, o in rev1.all(rev1.tx)))
# ['db/by', 'db/time', 'why']
print(rev1.get(rev1.tx, "why"))      # season opener

# %% [markdown]
# `time=True` asks for the wall-clock stamp; without it a revision
# carries no time, only its number and `by`. The stamp is a row like
# any other, so `asserted` and `since=` work on it too.

# %% [markdown]
# `by` is required, once per transaction. Every other keyword is a
# row on the transaction's own subject, `db/tx/<rev>`, and stays
# bare: user vocabulary, so `why` has no prefix and `db/by` does.

# %% [markdown]
# ### An exception in the body writes nothing
#
# The `with` block is the transaction: a clean exit commits one
# revision, an exception rolls back everything the body added.
# Notice the top did not move and `court` is still `north`.

# %%
try:
    with L.transaction(by="human:dan") as t:
        t.add("game/G1", "court", "east")
        raise RuntimeError("changed my mind")
except RuntimeError as e:
    print("RuntimeError:", e)
print(L.at().id == rev1.id)              # True: nothing written
print(L.at().get("game/G1", "court"))    # north

# %% [markdown]
# ## A second transaction, and the ledger as rows
#
# One more transaction: the court moves, and two officials are
# named. `t[s, p] = o` is an `add` (more under The `[]` accessor).

# %%
with L.transaction(by="human:dan") as t:
    t["game/G1", "court"] = "south"
    t.add("game/G1", "officials", "kim")
    t.add("game/G1", "officials", "ortiz")
rev2 = t.rev

# %% [markdown]
# Every row so far, unfolded, in revision order: `rows()` is the
# ledger as it is stored, the one read that does not fold. Notice
# the two game transactions stacked, a second `court` row after the
# first, and two `officials` rows side by side.

# %%
rows = L.at().rows()                      # every row, unfolded
print(f"{'rev':>3}  {'subject':<18} {'predicate':<15} object")
for r in rows:
    print(f"{r.rev.id:>3}  {r.subject:<18} {r.predicate:<15} "
          f"{r.object}")
# rev  subject            predicate       object
#   1  game/G1            home            G4
#   1  game/G1            away            G5
#   1  game/G1            date            2026-10-11
#   1  game/G1            court           north
#   1  db                 db/format       dvc-dat-ledger/1
#   1  db/tx/1            db/by           human:dan
#   1  db/tx/1            db/time         2026-10-18T15:52:07Z
#   1  db/tx/1            why             season opener
#   2  game/G1            court           south
#   2  game/G1            officials       kim
#   2  game/G1            officials       ortiz
#   2  db/tx/2            db/by           human:dan

# %% [markdown]
# ## Folding semantics
#
# Every read except `rows` and `asserted` folds: it turns the rows
# at or before its revision into the state they mean. How a
# predicate folds is its cardinality.

# %% [markdown]
# ### The ledger folds
#
# The same `game/G1` rows, read at the top. Notice one `court`,
# `south`: on a `one` predicate `add` is assignment and the latest
# add wins. No retraction row was ever written for `north`.

# %%
print(sorted(rev2.all("game/G1")))      # (predicate, object) pairs
# [('away', 'G5'), ('court', 'south'), ('date', '2026-10-11'),
#  ('home', 'G4'), ('officials', 'ortiz')]
print(rev2.get("game/G1", "court"))     # south
print(rev1.get("game/G1", "court"))     # north: rev1 never changes

# %% [markdown]
# `rev1` is a frozen view: a later transaction adds rows after it,
# never changes what it reads.

# %% [markdown]
# ### Without a declaration every predicate is one
#
# `officials` was asserted twice, `kim` and `ortiz`, and the fold
# kept only `ortiz`. Notice that this is wrong for officials: a game
# has several. Nothing declared `officials`, so it folds as `one`,
# the default, and the later add won.

# %%
print(rev2.get("game/G1", "officials"))   # ortiz
print(rev2.all("game/G1", "officials"))   # ['ortiz']

# %% [markdown]
# ### Declaring many, and the fold is as-of
#
# A declaration is itself a row, on the predicate's own subject,
# `db/pred/officials`, written by an ordinary transaction.

# %%
with L.transaction(by="human:dan") as t:
    t.add("db/pred/officials", "db/cardinality", "many")
rev3 = t.rev
print(rev3.all("game/G1", "officials"))   # ['kim', 'ortiz']
print(rev2.all("game/G1", "officials"))   # ['ortiz']
print(rev2.get("game/G1", "officials"))   # ortiz

# %% [markdown]
# Notice `kim` is back without being written again: from `rev3` on
# every earlier `officials` add is a set member. The declaration is
# as-of, so a read at `rev2` still folds `officials` as `one` and
# still answers `ortiz`; reads of the past do not change.

# %% [markdown]
# ### Accumulation
#
# On a `many` predicate the members are a set. Notice `kim`, added
# again while held, changes nothing.

# %%
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "officials", "lee")
    t.add("game/G1", "officials", "kim")   # held: no change
rev4 = t.rev
print(rev4.all("game/G1", "officials"))   # ['kim', 'ortiz', 'lee']

# %% [markdown]
# A remove, then a re-add. Notice `kim` comes back at the end.

# %%
with L.transaction(by="human:dan") as t:
    t.remove("game/G1", "officials", "kim")
rev5 = t.rev
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "officials", "kim")
rev6 = t.rev
print(rev5.all("game/G1", "officials"))   # ['ortiz', 'lee']
print(rev6.all("game/G1", "officials"))   # ['ortiz', 'lee', 'kim']

# %% [markdown]
# Members come in assertion order, each at the revision of its
# earliest add not since removed: re-adding a present member (`kim`
# at `rev4`) keeps its place; remove then re-add moves `kim` to the
# end, at `rev6`.

# %% [markdown]
# ### Flipping back
#
# Declaring `one` again: from that revision on the latest add wins.
# Notice the answer is `kim`, added last at `rev6`.

# %%
with L.transaction(by="human:dan", why="one lead official") as t:
    t.add("db/pred/officials", "db/cardinality", "one")
rev7 = t.rev
print(rev7.get("game/G1", "officials"))   # kim: latest add wins

# %% [markdown]
# `rev6` is frozen at a revision where `officials` is `many`.
# Notice `get` still refuses it there and names `all`.

# %%
try:
    rev6.get("game/G1", "officials")
except TypeError as e:
    print("TypeError:", e)                 # many: use all

# %% [markdown]
# A flip writes and removes no `officials` row, so flipping to
# `many` again brings the set back whole. Read at every revision:

# %%
with L.transaction(by="human:dan") as t:
    t.add("db/pred/officials", "db/cardinality", "many")
rev8 = t.rev
for n in range(rev1.id, rev8.id + 1):
    print(n, L.at(n).all("game/G1", "officials"))
# 1 []
# 2 ['ortiz']
# 3 ['kim', 'ortiz']
# 4 ['kim', 'ortiz', 'lee']
# 5 ['ortiz', 'lee']
# 6 ['ortiz', 'lee', 'kim']
# 7 ['kim']
# 8 ['ortiz', 'lee', 'kim']

# %% [markdown]
# Each `L.at(n)` folds every row at or before `n` by the
# declarations at or before `n`; a revision is a view, not a copy.

# %% [markdown]
# ## The `[]` accessor
#
# A second game first, so the reads have two subjects.

# %%
with L.transaction(by="human:dan") as t:
    t.add("game/G2", "home", "G1")
    t.add("game/G2", "away", "G3")
    t.add("game/G2", "date", "2026-10-12")
    t.add("game/G2", "court", "north")
rev9 = t.rev

# %% [markdown]
# `[]` reads the fold and returns the positions the pattern leaves
# open. Three positions first: rows have revisions, so a held
# triple answers with the revision of its earliest add not since
# removed, on a `many` predicate too.

# %%
rev = L.at()
print(rev["game/G1", "home", "G4"])           # Rev(1)
print(rev["game/G1", "officials", "kim"])     # Rev(6)
print(rev["game/G1", "officials", "ortiz"])   # Rev(2)

# %% [markdown]
# Notice a superseded or retracted triple raises rather than
# answering with history.

# %%
try:
    rev["game/G1", "court", "north"]
except KeyError as e:
    print("KeyError:", e)            # superseded at rev2: not held

# %% [markdown]
# Bracket reads take exact subjects: a glob is a `TypeError`, never
# an empty answer; globs live on `all` and `select`.

# %%
try:
    rev["game/*"]
except TypeError as e:
    print("TypeError:", e)

# %% [markdown]
# Two positions: the one object of a `one` predicate.

# %%
print(rev["game/G1", "home"])        # G4
print(rev["game/G1", "court"])       # south: the latest add

# %% [markdown]
# Nothing there is a `KeyError`. Notice `game/G1` has no `score`
# yet.

# %%
try:
    rev["game/G1", "score"]
except KeyError as e:
    print("KeyError:", e)

# %% [markdown]
# A `many` predicate is refused by its declaration, however many
# members it holds. Notice the message names `all`.

# %%
try:
    rev["game/G1", "officials"]
except TypeError as e:
    print("TypeError:", e)                 # many: use all

# %% [markdown]
# One position: the record, a `dict`, which is the fold. A `one`
# predicate maps to its object, a `many` predicate to its list, and
# `db/` rows are in it like any other.

# %%
print(rev["game/G1"])
# {'home': 'G4', 'away': 'G5', 'date': '2026-10-11',
#  'court': 'south', 'officials': ['ortiz', 'lee', 'kim']}
print(rev["game/G2"])
# {'home': 'G1', 'away': 'G3', 'date': '2026-10-12',
#  'court': 'north'}
print(rev["db/pred/officials"])      # {'db/cardinality': 'many'}

# %% [markdown]
# ### Writing through the bracket
#
# On a transaction the bracket is the mirror. `t[s, p] = o` is an
# `add`; `t[s] = {...}` is closed world over the user rows. A third
# game, written as a record, then rewritten without its `date`.

# %%
with L.transaction(by="human:dan") as t:
    t["game/G3"] = {"home": "G2", "away": "G5",
                    "date": "2026-10-13", "court": "east"}
with L.transaction(by="human:dan") as t:
    t["game/G3"] = {"home": "G2", "away": "G5", "court": "east"}
rev11 = t.rev
print(rev11["game/G3"] == {"home": "G2", "away": "G5",
                           "court": "east"})   # True: no date

# %% [markdown]
# Notice `date`, absent from the dict, was retracted. `del t[s, p]`
# retracts what the predicate holds.

# %%
with L.transaction(by="human:dan") as t:
    t["game/G3", "date"] = "2026-10-14"
    del t["game/G3", "court"]
rev12 = t.rev
print(rev12["game/G3", "date"])                # 2026-10-14
print(rev12.get("game/G3", "court"))           # None: retracted

# %%
with L.transaction(by="human:dan") as t:
    t["game/G3"] = t.base["game/G3"]
noop_rev = t.rev
print([row for row in noop_rev.all(since=rev12)
       if not row[0].startswith("db/tx/")])   # []: nothing moved

# %% [markdown]
# Writing a record back as it was writes no data row; only the
# transaction's own `db/tx/<rev>` rows are new. `db/` rows are
# never touched by `t[s] = {...}`: a `db/` key equal to the current
# row is ignored, which is what lets a record read with `db/` rows
# be written back. Notice one that differs is refused: machinery is
# not written through the bracket.

# %%
try:
    with L.transaction(by="human:dan") as t:
        t["game/G3"] = {**t.base["game/G3"], "db/doc": "a game"}
except TypeError as e:
    print("TypeError:", e)               # db/doc differs

# %% [markdown]
# `t[s, p] = o` writes `one` predicates only; a record write
# `t[s] = {...}` takes a list for a `many` key. Notice the refusal
# names the predicate's cardinality.

# %%
try:
    with L.transaction(by="human:dan") as t:
        t["game/G1", "officials"] = "park"
except TypeError as e:
    print("TypeError:", e)                 # t[s, p] = o: one only

# %%
with L.transaction(by="human:dan") as t:
    del t["game/G3"]
print(t.rev.get("game/G3", "home"))      # None: every row retracted

# %% [markdown]
# `del t[s]` retracts the user rows: `game/G3` now holds nothing,
# so `rev["game/G3"]` would raise `KeyError`.

# %% [markdown]
# ## Triple accessors
#
# Every read so far was one closed thing at one spot. These are the
# ways to reach the ledger as triples: the softer two-position read,
# the membership test, the history of a triple, every match of a
# pattern, and subjects as a table.

# %% [markdown]
# ### `get`, `in`, `asserted`

# %%
rev = L.at()
print(rev.get("game/G1", "score"))                # None
print(rev.get("game/G1", "score", default="tbd")) # tbd
print(("game/G1", "home", "G4") in rev)           # True
print(("game/G1", "court", "north") in rev)       # False
print(rev.asserted("game/G1", "court", "north"))  # [Rev(1)]
print(rev.asserted("game/G1", "court", "west"))   # []
print(rev.asserted("game/G1", "officials", "kim"))
# [Rev(2), Rev(4), Rev(6)]

# %% [markdown]
# `get` is `[]` answering `default` instead of raising on none.
# `in` is the no-raise membership test, by the same fold.
# `asserted` walks history: `north` is gone from the fold and still
# in the history, and every add of `kim` is listed, the removed one
# included.

# %% [markdown]
# ### `all` binds the open positions

# %%
print(sorted(rev.all("game/G1")))       # (predicate, object) pairs
# [('away', 'G5'), ('court', 'south'), ('date', '2026-10-11'),
#  ('home', 'G4'), ('officials', 'kim'), ('officials', 'lee'),
#  ('officials', 'ortiz')]
print(rev.all("game/G1", "home"))       # ['G4']: always a list
print(rev.all("game/G1", "home", "G4")) # [Rev(1)]
print([row for row in rev9.all(since=rev8)
       if not row[0].startswith("db/tx/")])
# game/G2's four rows: what (rev8, rev9] asserted
print(rev.get("game/G1", "court", since=rev1))  # south
print(rev.get("game/G1", "home", since=rev1))   # None: at rev1

# %% [markdown]
# `all` returns what the pattern leaves open, a list on either
# cardinality, ordered by revision; rows of one revision have no
# order, hence the `sorted`. `since=` restricts the rows considered
# to an interval: `rev.all(since=a)` is the delta from `a`.

# %% [markdown]
# ### Subjects as a table: `select`

# %%
print(sorted(rev.select(("home", "away"), s="game/*")))
# [('G1', 'G3'), ('G4', 'G5')]
print(rev.select(("away",), home="G1"))       # [('G3',)]
print(rev.select(("court",), s="game/G2"))    # [('north',)]

# %% [markdown]
# A bare keyword means *has this row*, `s=` constrains the name
# (exact or a prefix glob), and `select` projects predicates into
# tuples. The spec gives `select` no order, so the notebook sorts.

# %%
print(rev9.select(("home", "court"), where={"court": None},
                  since=rev8))               # [('G1', 'north')]

# %% [markdown]
# `since=` on the subject operations, in the Versions § 6 forms:
# `where={"court": None}` is *has a court row, any value*, and only
# `game/G2` asserted one in `(rev8, rev9]`; `game/G1`'s `south` is
# at `rev2`.

# %% [markdown]
# `select` has siblings, `refs`, `values`, `value` and `load`, and
# a `Ref` type: they hand back or instantiate values, and belong to
# the values notebook. At this level nothing is ever instantiated:
# every read here returns a `str` or a JSON document.

# %% [markdown]
# ## Ledger management
#
# Four topics that are about the ledger rather than about any one
# subject: each is a row on a reserved subject or a keyword on a
# transaction, nothing more.

# %% [markdown]
# ### Declaring an index

# %%
with L.transaction(by="human:dan") as t:
    t.add("db/pred/home", "db/index", "true")
rev = L.at()
print(rev["db/pred/home"])                  # {'db/index': 'true'}
print(rev["db/pred/officials"])   # {'db/cardinality': 'many'}
print(("db/pred/home", "db/index", "true") in rev)   # True
print(rev.select(("away",), home="G1"))     # [('G3',)]

# %% [markdown]
# An index is storage: the declaration is a row on the predicate's
# subject, beside `officials`' cardinality, and the store indexes
# every existing `home` row. Notice the query answers the same as
# before; an undeclared predicate is still a row, found by scan.

# %% [markdown]
# ### Revision naming
#
# A named revision is any subject's `rev` row, and `L.at` reads a
# digit-only string as a revision id.

# %%
with L.transaction(by="human:dan") as t:
    t["env/prod", "rev"] = str(rev2.id)
rev = L.at()
prod_rev = L.at(rev["env/prod", "rev"])       # L.at("2")
print(prod_rev.id, prod_rev.get("game/G1", "court"))   # 2 south

# %% [markdown]
# ### Predicate typing: `db/type`
#
# Checked at the write and on the strict reads.

# %%
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "score", {"home": 61, "away": 58})   # json
with L.transaction(by="human:dan") as t:
    t.add("db/pred/score", "db/type", "str")
    t.add("db/pred/date", "db/type", "str")
top_rev = L.at()

# %% [markdown]
# A predicate may declare the tag its objects take: `str`, `json`,
# or a class's dotted name (the values notebook). Notice the
# mismatching write is refused at commit and the top does not move.

# %%
try:
    with L.transaction(by="human:dan") as t:
        t.add("game/G2", "date", {"y": 2026, "m": 10})
except TypeError as e:
    print("TypeError:", e)               # json under a str pred
print(L.at().id == top_rev.id)           # True: nothing written

# %% [markdown]
# Rows written before the declaration are not re-checked at the
# write, but the strict read checks them. Notice `score`, stored as
# JSON before it was declared `str`, raises here.

# %%
rev = L.at()
try:
    rev["game/G1", "score"]
except TypeError as e:
    print("TypeError:", e)               # stored json, declared str

# %%
print(rev.all("game/G1", "score"))       # [{'home': 61, ...}]
print(rev["game/G1"]["score"])           # the record: loose too
print(rev["game/G1", "date"])            # a str: passes

# %% [markdown]
# The loose reads, `all`, `rev[s]` and `select`, return what is
# stored. A bare `int`, `float` or `bool` is refused by `add`
# whatever the declaration: a number is stored as its string.

# %%
try:
    with L.transaction(by="human:dan") as t:
        t.add("game/G1", "attendance", 1200)
except TypeError as e:
    print("TypeError:", e)               # a number is its string

# %%
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "attendance", "1200")

# %% [markdown]
# ### A real code repository
#
# Every value function runs in a git checkout, the ledger records
# which commit, and the notebook makes a tiny one of its own; no
# value function runs here, so one empty package is enough.

# %%
import subprocess, sys

demo_repo_path = (project_path.parent / "demo-game").resolve()
(demo_repo_path / "demo_game").mkdir(parents=True, exist_ok=True)
(demo_repo_path / "demo_game/__init__.py").write_text("")
git_cmd = ["git", "-c", "user.name=demo",
           "-c", "user.email=demo@example.com"]
for args in (["init", "-q"], ["add", "."],
             ["commit", "-q", "-m", "demo-game 0.1.0"]):
    subprocess.run(git_cmd + args, cwd=demo_repo_path, check=True)
sys.path.insert(0, str(demo_repo_path))
import demo_game                       # discovery sees it imported

# %% [markdown]
# ### Transaction locking: `bump` under `lock=`
#
# `bump` on `code/<repo>` reads the commit by git discovery over
# the modules this process imported.

# %%
with L.transaction(by="human:dan") as t:
    t.add("code/demo-game", "version", "0.1.0")  # the clock's start
with L.transaction(by="human:dan", lock=10, time=True,
                   why="T531 re-baseline") as t:
    new = bump(t, "code/demo-game")       # patch: 0.1.0 -> 0.1.1
    t.add(t.tx, "checked", "G1,G4,G5")
rev = t.rev
print(new, rev["code/demo-game"])
# 0.1.1 {'version': '0.1.1', 'commit': '<the demo commit>'}

# %% [markdown]
# `bump` reads the version through `t.base`, writes the next one,
# and on `code/<repo>` writes `commit` beside it, read from the
# checkout: the caller never writes `commit`. `lock=10` holds
# the write lock for the body, so nothing slips between the read
# and the write.

# %%
print(sorted(rev[rev.tx]))
# ['checked', 'db/by', 'db/time', 'why']
print(rev[rev.tx, "db/time"])            # UTC, since time=True

# %% [markdown]
# `t.tx` is a placeholder for `db/tx/<rev>`, rewritten at commit:
# provenance decided inside the body lands beside `by`, `time=True`
# and the keywords given up front.

# %% [markdown]
# A minor or major bump must be confirmed. Notice the bare call
# refuses and writes nothing.

# %%
try:
    with L.transaction(by="human:dan") as t:
        bump(t, "schema/tape", "minor")
except ValueError as e:
    print("ValueError:", e)              # minor needs confirm=

# %% [markdown]
# `code/dvc-dat` has no checkout in this environment. Notice the
# message names the repo.

# %%
try:
    with L.transaction(by="human:dan") as t:
        bump(t, "code/dvc-dat")
except ValueError as e:
    print("ValueError:", e)              # no checkout for code/dvc-dat

# %%
with L.transaction(by="human:dan") as t:
    print(bump(t, "schema/tape", "minor",
               confirm=lambda old, new: True))   # 0.1.0
with L.transaction(by="human:dan") as t:
    t.add("schema/tape", "version", "0.0.9")
print(L.at()["schema/tape", "version"])  # 0.0.9: add went back

# %% [markdown]
# `confirm(old, new)` must answer `True` (`just bump` asks for the
# word `yes`); a subject with no `version` starts from `0.0.0`.
# `add` can set a clock backwards; `bump` is the helper that only
# goes up.

# %%
with L.transaction(by="agent:release", lock=5) as t:
    v = t.base["code/demo-game", "version"]
    c = t.base["code/demo-game", "commit"]
    t.add("rel/demo-game", "pair", f"{v}+{c}")
print(L.at()["rel/demo-game", "pair"])    # 0.1.1+<commit>

# %% [markdown]
# A body that reads and then writes takes `lock=`. Notice that past
# the limit the body is interrupted and `pair` is unchanged.

# %%
try:
    with L.transaction(by="agent:release", lock=0.5) as t:
        t.add("rel/demo-game", "pair", "never")
        time.sleep(2)                     # past the limit
except LockTimeout as e:
    print("LockTimeout:", e)
print(L.at()["rel/demo-game", "pair"])    # 0.1.1+<commit>

# %%
rev = L.at()
when = rev.asserted("code/demo-game", "version", "0.1.0")
print(when)                               # [Rev(...)]: when it was set
print(when[0][when[0].tx, "db/by"])       # human:dan: by whom

# %% [markdown]
# The reverse lookup for a version: `asserted` names the revision,
# and its `db/tx/<rev>` rows say who, and when if stamped.
