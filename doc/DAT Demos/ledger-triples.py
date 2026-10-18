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
# # Ledger: triples
#
# The ledger as a quad store and nothing else. Every fact is a row
# `(rev, subject, predicate, object)`, every write is one
# transaction, every read is a function of one revision. No `eval`
# and no value functions here: the running example is plain
# metadata about games (`game/G1`: teams, date, court, officials)
# and a few clock subjects (`code/sv-pipe`, `schema/tape`).
#
# Written to the ledger design of 2026-10-18 (SVP447 Ledger Module,
# API, Versions; F447 A37–A47). It runs once `ledger2` is rebuilt
# to that design (T534); until then it is the design, not a demo.
# Revision numbers in the comments count from 1, the first
# transaction on the project's ledger.

# %% [markdown]
# ## Setup
#
# Imports are what this notebook uses. `ledger_fn` and
# `ledger_class` belong to the values notebook.

# %%
import os, time
from pathlib import Path

from dvc_dat.ledger import Ledger, bump
from dvc_dat.ledger import LockTimeout

scratch_ledger_path = Path("scratch/triples-demo/ledger").resolve()
L = Ledger.create(scratch_ledger_path)         # an empty ledger

# %% [markdown]
# `Ledger.create(path)` is the one call that makes a ledger.
# `Ledger.open(path)` opens an existing one and never creates.

# %%
L = Ledger.open(scratch_ledger_path)           # reopened by path

# %% [markdown]
# ### A project's `.datconfig.yaml`
#
# In real code a project names its ledger once and every script in
# it says `Ledger.open()` with no argument. `Ledger.init(project)`
# is the one creating verb: it writes `.datconfig.yaml` with a
# `ledger:` line and makes the ledger it names, the way `git init`
# makes the directory and the config together.

# %%
project_path = Path("scratch/triples-demo/project").resolve()
Ledger.init(project_path)                 # .datconfig.yaml + ledger

print((project_path / ".datconfig.yaml").read_text())
# ledger: .dat/ledger

# %% [markdown]
# The one line is the whole config this notebook needs: `ledger:`,
# a path relative to the file's own folder. The same file carries a
# project's `mounts:` (the values and dats notebooks), and dvc-dat's
# own keys; it is the file the dat manager already reads. `open()`
# walks up from the working directory to the nearest `.datconfig.yaml`
# carrying `ledger:` and never creates anything.

# %%
os.chdir(project_path)
L = Ledger.open()                         # the project's ledger

# %% [markdown]
# A declaration is itself a row, on the predicate's own subject:
# `officials` is declared `many` before any game uses it.

# %%
with L.transaction(by="human:dan") as t:
    t.add("db/pred/officials", "db/cardinality", "many")   # rev 1

# %% [markdown]
# ## One transaction is one revision

# %%
with L.transaction(by="human:dan", time=True,
                   why="season opener") as t:
    t.add("game/G1", "home", "G4")
    t.add("game/G1", "away", "G5")
    t.add("game/G1", "date", "2026-10-11")
    t.add("game/G1", "court", "north")
r2 = t.rev
print(r2.id, r2.tx)                  # 2 db/tx/2
print(r2[r2.tx, "db/by"])            # human:dan
print(r2[r2.tx, "db/time"])          # 2026-10-18T15:52:07Z (UTC)
print(sorted(r2[r2.tx]))             # ['db/by', 'db/time', 'why']
print(r2[r2.tx]["why"])              # season opener

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
print(L.at().id == r2.id)            # True: nothing written
print(L.at()["game/G1", "court"])    # north

# %% [markdown]
# ## A second transaction, and the ledger as rows
#
# One more transaction: the court moves, and two officials are
# named. `t[s, p] = o` is an `add` (more under Bracket writes).

# %%
with L.transaction(by="human:dan") as t:
    t["game/G1", "court"] = "south"
    t.add("game/G1", "officials", "kim")
    t.add("game/G1", "officials", "ortiz")
r3 = t.rev

# %% [markdown]
# Every row so far, revision by revision. Notice the two game
# transactions stacked, a second `court` row after the first, and
# two `officials` rows side by side.

# %%
print(f"rev  {'subject':<18} {'predicate':<15} object")
prev = None
for n in range(1, r3.id + 1):
    r = L.at(n)
    for s, p, o in r.all(since=prev):     # rows asserted at n
        print(f"{n:>3}  {s:<18} {p:<15} {o}")
    prev = r
# rev  subject            predicate       object
#   1  db/pred/officials  db/cardinality  many
#   1  db/tx/1            db/by           human:dan
#   2  game/G1            home            G4
#   2  game/G1            away            G5
#   2  game/G1            date            2026-10-11
#   2  game/G1            court           north
#   2  db/tx/2            db/by           human:dan
#   2  db/tx/2            db/time         2026-10-18T15:52:07Z
#   2  db/tx/2            why             season opener
#   3  game/G1            court           south
#   3  game/G1            officials       kim
#   3  game/G1            officials       ortiz
#   3  db/tx/3            db/by           human:dan

# %%
rev = L.at()
print(rev["game/G1"])                # the record: the fold
# {'home': 'G4', 'away': 'G5', 'date': '2026-10-11',
#  'court': 'south', 'officials': ['kim', 'ortiz']}

# %% [markdown]
# Raw rows above, the fold below: one `court`, the later one, and
# `officials` as a list of both.

# %% [markdown]
# ## The fold: `add` as assignment and accumulation

# %%
print(r3["game/G1", "court"])          # south
print(r2["game/G1", "court"])          # north: r2 never changes
print(r3.all("game/G1", "officials"))  # ['kim', 'ortiz']
print(r2.all("game/G1", "officials"))  # []

# %% [markdown]
# `add` is assignment on a `one` predicate and accumulation on a
# `many` one. No retraction row was written for `north`: the
# predicate's cardinality, `one` by default, decides at read time
# that the latest `add` is the value, and `many` keeps every member.
# `r2` is a frozen view.

# %% [markdown]
# ## Reading at one, two and three positions
#
# A second game first, so the reads have two subjects.

# %%
with L.transaction(by="human:dan") as t:
    t.add("game/G2", "home", "G1")
    t.add("game/G2", "away", "G3")
    t.add("game/G2", "date", "2026-10-12")
    t.add("game/G2", "court", "north")
r4 = t.rev

# %%
rev = L.at()
print(rev["game/G2"])                # one position: the record
# {'home': 'G1', 'away': 'G3', 'date': '2026-10-12',
#  'court': 'north'}
print(rev["game/G1", "home"])        # G4: exactly one object
print(rev["game/G1", "home", "G4"])  # Rev(2): its earliest add
print(rev.get("game/G9", "home"))    # None: rev["game/G9"] raises

# %% [markdown]
# `[]` returns the positions the pattern leaves open: one position,
# the record; two, the one object of a `one` predicate; three, the
# revision of a held triple. Notice a superseded or retracted
# triple raises rather than answering with history.

# %%
try:
    rev["game/G1", "court", "north"]
except KeyError as e:
    print("KeyError:", e)            # superseded at r3: not held

# %% [markdown]
# Bracket reads take exact subjects. A glob is a `TypeError`, not
# an empty answer; globs live on `all` and `select`.

# %%
try:
    rev["game/*"]
except TypeError as e:
    print("TypeError:", e)

# %% [markdown]
# ## `get`, `in`, `asserted`

# %%
print(rev.get("game/G1", "score"))                # None
print(rev.get("game/G1", "score", default="tbd")) # tbd
print(("game/G1", "home", "G4") in rev)           # True
print(("game/G1", "court", "north") in rev)       # False
print(rev.asserted("game/G1", "court", "north"))  # [Rev(2)]
print(rev.asserted("game/G1", "court", "west"))   # []

# %% [markdown]
# `get` is `[]` answering `default` instead of raising on none.
# `in` is the no-raise membership test, by the same fold.
# `asserted` walks history: `north` is gone from the fold and still
# in the history.

# %% [markdown]
# ## `all` binds the open positions

# %%
print(sorted(rev.all("game/G1")))       # (predicate, object) pairs
# [('away', 'G5'), ('court', 'south'), ('date', '2026-10-11'),
#  ('home', 'G4'), ('officials', 'kim'), ('officials', 'ortiz')]
print(rev.all("game/G1", "home"))       # ['G4']: always a list
print(rev.all("game/G1", "home", "G4")) # [Rev(2)]
print([row for row in rev.all(since=r3)
       if not row[0].startswith("db/tx/")])
# game/G2's four rows: what (r3, r4] asserted
print(rev.get("game/G1", "court", since=r2))  # south
print(rev.get("game/G1", "home", since=r2))   # None: set at r2

# %% [markdown]
# `all` returns what the pattern leaves open, a list on either
# cardinality, ordered by revision; rows of one revision have no
# order, hence the `sorted`. `since=` restricts the rows considered
# to an interval: `rev.all(since=a)` is the delta from `a`.

# %% [markdown]
# ## Subjects as a table: `select`

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
print(rev.select(("home", "court"), where={"court": None},
                 since=r3))                  # [('G1', 'north')]

# %% [markdown]
# `since=` on the subject operations, in the Versions § 6 forms:
# `where={"court": None}` is *has a court row, any value*, and only
# `game/G2` asserted one in `(r3, r4]`; `game/G1`'s `south` is at
# r3 itself.

# %% [markdown]
# `select` has siblings, `refs`, `values`, `value` and `load`, and
# a `Ref` type: they hand back or instantiate values, and belong to
# the values notebook. At this level nothing is ever instantiated:
# every read here returns a `str` or a JSON document.

# %% [markdown]
# ## Declaring an index

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
# ## `many` as a set

# %%
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "officials", "lee")
    t.add("game/G1", "officials", "kim")   # held already: no change
rev = L.at()
print(rev.all("game/G1", "officials"))     # ['kim', 'ortiz', 'lee']

# %% [markdown]
# The `officials` of r3, built on. A set: `kim`, added again while
# held, changes nothing. Notice below that `[]` refuses `officials`
# by its declaration, however many members it holds, and names
# `all`.

# %%
try:
    rev["game/G1", "officials"]
except TypeError as e:
    print("TypeError:", e)                 # many: use all

# %%
with L.transaction(by="human:dan") as t:
    t.remove("game/G1", "officials", "kim")
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "officials", "kim")
    t.add("game/G1", "officials", "ortiz")  # present: keeps place
rev = L.at()
print(rev.all("game/G1", "officials"))   # ['ortiz', 'lee', 'kim']
print(rev["game/G1", "officials", "kim"])     # Rev(8)
print(rev["game/G1", "officials", "ortiz"])   # Rev(3)
print(rev.asserted("game/G1", "officials", "kim"))
# [Rev(3), Rev(6), Rev(8)]

# %% [markdown]
# Order is assertion order by each member's earliest add not since
# removed: re-adding a present member (`kim` at 6, `ortiz` at 8)
# keeps its place; remove then re-add moves `kim` to the end. The
# three-position read answers with that earliest surviving add;
# `asserted` lists every add, the removed one included.

# %% [markdown]
# The bracket `t[s, p] = o` writes `one` predicates only; a record
# write `t[s] = {...}` takes a list for a `many` key. Notice the
# refusal names the predicate's cardinality.

# %%
try:
    with L.transaction(by="human:dan") as t:
        t["game/G1", "officials"] = "park"
except TypeError as e:
    print("TypeError:", e)                 # t[s, p] = o: one only

# %% [markdown]
# ## The fold, revision by revision

# %%
for n in range(r2.id, L.at().id + 1):
    r = L.at(n)
    print(n, r.get("game/G1", "court"),
          r.all("game/G1", "officials"))
# 2 north []
# 3 south ['kim', 'ortiz']
# 4 south ['kim', 'ortiz']
# 5 south ['kim', 'ortiz']
# 6 south ['kim', 'ortiz', 'lee']
# 7 south ['ortiz', 'lee']
# 8 south ['ortiz', 'lee', 'kim']

# %% [markdown]
# Each `L.at(n)` folds every row at or before `n`; a revision is a
# view, not a copy. A named revision is any subject's `rev` row,
# and `L.at` reads a digit-only string as a revision id.

# %%
with L.transaction(by="human:dan") as t:
    t["env/prod", "rev"] = str(r3.id)
rev = L.at()
prod = L.at(rev["env/prod", "rev"])        # L.at("3")
print(prod.id, prod.get("game/G1", "court"))   # 3 south

# %% [markdown]
# ## Flipping cardinality

# %%
before = L.at()
with L.transaction(by="human:dan", why="courts are shared") as t:
    t.add("db/pred/court", "db/cardinality", "many")
flip = t.rev
print(before.all("game/G1", "court"))    # ['south']: one, latest
print(flip.all("game/G1", "court"))      # ['north', 'south']

# %% [markdown]
# A declaration is as-of: reads before `flip` fold `court` as
# `one`, reads from `flip` on fold every earlier `add` as a set
# member, superseded values included, since an assignment never
# wrote a retraction.

# %%
with L.transaction(by="human:dan") as t:
    t.add("db/pred/court", "db/cardinality", "one")
print(t.rev.get("game/G1", "court"))     # south: latest add wins

# %% [markdown]
# Flipping back makes the latest add win again from that revision.
# Notice `flip` itself still refuses the two-position read: it is
# frozen at a revision where `court` is `many`.

# %%
try:
    flip["game/G1", "court"]
except TypeError as e:
    print("TypeError:", e)

# %% [markdown]
# ## `db/type`
#
# Checked at the write and on the strict reads.

# %%
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "score", {"home": 61, "away": 58})   # json
with L.transaction(by="human:dan") as t:
    t.add("db/pred/score", "db/type", "str")
    t.add("db/pred/date", "db/type", "str")
top = L.at().id

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
print(L.at().id == top)                  # True: nothing written

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
# ## A clock: `bump` under `lock=`
#
# `bump` on `code/<repo>` reads the checkout from the environment
# provider. This notebook does not run inside an sv-pipe checkout,
# so it installs a stand-in; `Code`, `Env` and `set_env_provider`
# are part of the module interface for exactly this.

# %%
from dvc_dat.ledger import Code, Env, set_env_provider

ENV = Env({"sv-pipe": Code("0.2.3", "b48dca7c")},
          lock="sha256:5e1f", platform="darwin-arm64-py3.11")
set_env_provider(lambda module: ENV)

# %%
with L.transaction(by="human:dan") as t:
    t.add("code/sv-pipe", "version", "0.2.2")   # the clock's start
with L.transaction(by="human:dan", lock=10, time=True,
                   why="T531 re-baseline") as t:
    new = bump(t, "code/sv-pipe")         # patch: 0.2.2 -> 0.2.3
    t.add(t.tx, "checked", "G1,G4,G5")
rev = t.rev
print(new, rev["code/sv-pipe"])
# 0.2.3 {'version': '0.2.3', 'commit': 'b48dca7c'}

# %% [markdown]
# `bump` reads the version through `t.base`, writes the next one,
# and on `code/<repo>` writes `commit` beside it, read from the
# environment: the caller never writes `commit`. `lock=10` holds
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
with L.transaction(by="agent:svp", lock=5) as t:
    v = t.base["code/sv-pipe", "version"]
    c = t.base["code/sv-pipe", "commit"]
    t.add("rel/pipe", "pair", f"{v}+{c}")
print(L.at()["rel/pipe", "pair"])         # 0.2.3+b48dca7c

# %% [markdown]
# A body that reads and then writes takes `lock=`. Notice that past
# the limit the body is interrupted and `pair` is unchanged.

# %%
try:
    with L.transaction(by="agent:svp", lock=0.5) as t:
        t.add("rel/pipe", "pair", "never")
        time.sleep(2)                     # past the limit
except LockTimeout as e:
    print("LockTimeout:", e)
print(L.at()["rel/pipe", "pair"])         # 0.2.3+b48dca7c

# %%
rev = L.at()
when = rev.asserted("code/sv-pipe", "version", "0.2.2")
print(when)                               # [Rev(...)]: when it was set
print(when[0][when[0].tx, "db/by"])       # human:dan: by whom

# %% [markdown]
# The reverse lookup for a version: `asserted` names the revision,
# and its `db/tx/<rev>` rows say who, and when if stamped.

# %% [markdown]
# ## Bracket writes

# %%
with L.transaction(by="human:dan") as t:
    t["game/G2"] = {"home": "G1", "away": "G3", "court": "east"}
    t["game/G1", "date"] = "2026-10-10"
    del t["game/G1", "court"]
wrote = t.rev
print(wrote["game/G2"] == {"home": "G1", "away": "G3",
                           "court": "east"})   # True: no date
print(wrote["game/G1", "date"])                # 2026-10-10
print(wrote.get("game/G1", "court"))           # None: retracted

# %% [markdown]
# `t[s, p] = o` is an `add`. `t[s] = {...}` is closed world over
# the user rows: `game/G2`'s `date`, absent from the dict, was
# retracted. `del t[s, p]` retracts what the predicate holds.

# %%
with L.transaction(by="human:dan") as t:
    t["game/G2"] = t.base["game/G2"]
noop = t.rev
print([row for row in noop.all(since=wrote)
       if not row[0].startswith("db/tx/")])   # []: nothing moved

# %% [markdown]
# Writing a record back as it was writes no data row; only the
# transaction's own `db/tx/<rev>` rows are new. Notice a `db/` key
# in the dict that differs from the current row is refused:
# machinery is not written through the bracket.

# %%
try:
    with L.transaction(by="human:dan") as t:
        t["game/G2"] = {**t.base["game/G2"], "db/doc": "a game"}
except TypeError as e:
    print("TypeError:", e)               # db/doc differs

# %%
with L.transaction(by="human:dan") as t:
    del t["game/G2"]
print(t.rev.get("game/G2", "home"))      # None: every row retracted

# %% [markdown]
# `del t[s]` retracts the user rows: `game/G2` now holds nothing,
# so `rev["game/G2"]` would raise `KeyError`.
