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
# transaction, every read is a function of one revision. No values
# and no `eval` here: the running example is plain metadata about
# games (`game/G1`: teams, date, court) and one clock subject,
# `code/sv-pipe`.
#
# Written to the ledger design of 2026-10-18 (SVP447 Ledger Module,
# API, Eval, Versions). It runs once `ledger2` is rebuilt to that
# design (T534); until then it is the design, not a demo.

# %%
import os, tempfile, time
from pathlib import Path

from dvc_dat.ledger import Ledger, ledger_fn, ledger_class, bump, attr
from dvc_dat.ledger import Ref, LockTimeout
from dvc_dat.ledger import Code, Env, set_env_provider

ledger_dir = Path(tempfile.mkdtemp(prefix="ledger-triples-"))
os.environ["DAT_LEDGER"] = str(ledger_dir)
L = Ledger.open()

ENV = Env({"sv-pipe": Code("0.2.3", "b48dca7c")},
          lock="sha256:5e1f", platform="darwin-arm64-py3.11")
set_env_provider(lambda module: ENV)

# %% [markdown]
# `Ledger.open()` reads `DAT_LEDGER`. The environment provider stands
# in for the sv-pipe checkout this notebook does not run inside;
# `bump` on `code/sv-pipe` reads the commit from it (the last
# section).

# %% [markdown]
# ## One transaction is one revision

# %%
with L.transaction(by="human:dan", why="season opener") as t:
    t.add("game/G1", "home", "G4")
    t.add("game/G1", "away", "G5")
    t.add("game/G1", "date", "2026-10-11")
    t.add("game/G1", "court", "north")
r1 = t.rev
print(r1.id, r1.tx)                  # 1 db/tx/1
print(r1[r1.tx, "db/by"])            # "human:dan"
print(r1[r1.tx])                     # {"db/by": ..., "why": ...}
print(Ref(r1, r1.tx).preds)          # {"why": "season opener"}

# %% [markdown]
# `by` is required, once per transaction. Every other keyword is a
# row on the transaction's own subject, `db/tx/<rev>`, and it stays
# bare: user vocabulary, so it shows in `Ref.preds`, while `db/by`
# does not.

# %%
try:
    with L.transaction(by="human:dan") as t:
        t.add("game/G1", "court", "east")
        raise RuntimeError("changed my mind")
except RuntimeError:
    pass
print(L.at().id == r1.id)            # True: nothing written
print(L.at()["game/G1", "court"])    # "north"

# %% [markdown]
# An exception in the body writes nothing. The rows of a body land
# together on exit or not at all.

# %% [markdown]
# ## `add` is assignment on a `one` predicate

# %%
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "court", "south")
r2 = t.rev
print(r2["game/G1", "court"])        # "south"
print(r1["game/G1", "court"])        # "north": r1 never changes

# %% [markdown]
# No retraction row was written for `north`. The predicate's
# cardinality, `one` by default, decides at read time that the
# latest `add` is the value. `r1` is a frozen view and still says
# `north`.

# %% [markdown]
# ## Bracket writes

# %%
with L.transaction(by="human:dan") as t:
    t["game/G2"] = {"home": "G1", "away": "G3",
                    "date": "2026-10-12", "court": "north"}
    t["game/G1", "date"] = "2026-10-10"
r3 = t.rev

with L.transaction(by="human:dan") as t:
    t["game/G2"] = {"home": "G1", "away": "G3", "court": "east"}
    del t["game/G1", "court"]
r4 = t.rev
print(r4["game/G2"])
# {"home": "G1", "away": "G3", "court": "east"}: no date
print(r4.get("game/G1", "court"))    # None: retracted

# %% [markdown]
# `t[s, p] = o` is an `add`. `t[s] = {...}` is closed world: the
# record equals the dict at the next revision, so `game/G2`'s
# `date`, absent from the dict, was retracted. `del t[s, p]`
# retracts what the predicate holds. Every row the brackets write is
# an ordinary `add` or `remove`.

# %%
with L.transaction(by="human:dan") as t:
    t["game/G2"] = t.base["game/G2"]
noop = t.rev
print([row for row in noop.all(since=r4)
       if not row[0].startswith("db/tx/")])   # []: nothing moved

# %% [markdown]
# Writing a record back as it was writes no data row: only the
# transaction's own `db/tx` rows are new.

# %% [markdown]
# ## Reading: `[]` at one, two and three positions

# %%
rev = L.at()
print(rev["game/G1"])                # the record, a dict
# {"home": "G4", "away": "G5", "date": "2026-10-10"}
print(rev["game/G1", "home"])        # "G4": exactly one object
print(rev["game/G1", "home", "G4"])  # Rev(1): its earliest add
try:
    rev["game/G2", "date", "2026-10-12"]
except KeyError as e:
    print("KeyError:", e)            # retracted: not held

# %% [markdown]
# `[]` returns the positions the pattern leaves open. One position:
# the subject's record. Two: the one object of a `one` predicate.
# Three: the revision of a held triple, and only a held one; a
# superseded or retracted triple raises.

# %%
for key in ["game/G9", "game/*"]:
    try:
        rev[key]
    except (KeyError, TypeError) as e:
        print(type(e).__name__, e)
# KeyError: no rows at all;  TypeError: a glob in a bracket

# %% [markdown]
# ## `get`, `in`, `asserted`

# %%
print(rev.get("game/G1", "court"))                # None
print(rev.get("game/G1", "court", default="tbd")) # "tbd"
print(("game/G1", "home", "G4") in rev)           # True
print(("game/G1", "court", "south") in rev)       # False
print(rev.asserted("game/G1", "court", "south"))  # [Rev(2)]
print(rev.asserted("game/G1", "court", "west"))   # []

# %% [markdown]
# `get` is `[]` that answers `default` instead of raising on none.
# `in` is the no-raise membership test, by the same fold. `asserted`
# is the one read that walks history: every revision that asserted
# the triple, held now or not. `south` is gone from the fold and
# still in the history.

# %% [markdown]
# ## `all` binds the open positions

# %%
print(rev.all()[:3])             # rows: (subject, predicate, object)
print(rev.all("game/G1"))        # (predicate, object) pairs
print(rev.all("game/G1", "home"))           # ["G4"]: always a list
print(rev.all("game/G1", "home", "G4"))     # [Rev(1)]
print(rev.all(since=r3))         # rows asserted in (r3, top]
print(rev.get("game/G1", "date", since=r2)) # "2026-10-10"
print(rev.get("game/G1", "home", since=r2)) # None: set at r1

# %% [markdown]
# `all` returns what the pattern leaves open, fixed per arity, on
# either cardinality a list. `since=` restricts the rows considered
# to an interval: `rev.all(since=a)` is the delta from `a`, and a
# `get` with `since=` sees only what the interval asserted.

# %% [markdown]
# ## Subjects as a table: `refs` and `select`

# %%
print(rev.refs(s="game/*"))      # [Ref(game/G1), Ref(game/G2)]
print(rev.refs(home="G1"))       # a bare keyword names a row
print(rev.select(("home", "away"), s="game/*"))
# [("G4", "G5"), ("G1", "G3")]
print([r.preds for r in rev.refs(s="game/*")])

# %% [markdown]
# The subject operations work on plain subjects too: a bare keyword
# means *has this row*, `s=` constrains the name (exact or a prefix
# glob), and `select` projects predicates into tuples. A plain
# subject's `Ref.preds` is its non-`db/` rows.

# %% [markdown]
# ## `many`: a set, in assertion order

# %%
with L.transaction(by="human:dan") as t:
    t.add("db/pred/referee", "db/cardinality", "many")
    t.add("db/pred/referee", "db/doc", "officials of a game")
    t.add("game/G1", "referee", "kim")
    t.add("game/G1", "referee", "ortiz")
    t.add("game/G1", "referee", "kim")     # held already: no change
rev = L.at()
print(rev.all("game/G1", "referee"))       # ["kim", "ortiz"]
print(rev["game/G1"]["referee"])           # the record: a list
try:
    rev["game/G1", "referee"]
except TypeError as e:
    print("TypeError:", e)                 # many: use all

# %% [markdown]
# A predicate is a subject, `db/pred/<p>`, and its cardinality is a
# row on it. On a `many` predicate the objects are a set:
# duplicates collapse. `[]` and `get` refuse a `many` predicate by
# its declaration, however many members it holds, and name `all`.

# %%
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "referee", "lee")
    t.remove("game/G1", "referee", "kim")
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "referee", "kim")
    t.add("game/G1", "referee", "ortiz")   # present: keeps its place
rev = L.at()
print(rev.all("game/G1", "referee"))       # ["ortiz", "lee", "kim"]
try:
    with L.transaction(by="human:dan") as t:
        t["game/G1", "referee"] = "park"
except TypeError as e:
    print("TypeError:", e)                 # t[s, p] = o: one only

# %% [markdown]
# Order is assertion order, by each member's earliest add not since
# removed: re-adding a present member keeps its place, remove then
# re-add moves it to the end. The bracket `t[s, p] = o` writes `one`
# predicates only; a record write `t[s] = {...}` takes a list for a
# `many` key.

# %% [markdown]
# ## The fold, revision by revision

# %%
for n in range(r1.id, L.at().id + 1):
    r = L.at(n)
    print(n, r.get("game/G1", "court"), r.get("game/G1", "date"),
          r.all("game/G1", "referee"))
# 1 north 2026-10-11 []
# 2 south 2026-10-11 []
# 3 south 2026-10-10 []
# 4 None  2026-10-10 []    ... and so on

# %% [markdown]
# Each `L.at(n)` folds every row at or before `n`. Nothing is
# overwritten; a revision is a view, not a copy.

# %% [markdown]
# ## Flipping a predicate's cardinality

# %%
before = L.at()
with L.transaction(by="human:dan", why="courts are shared") as t:
    t.add("db/pred/court", "db/cardinality", "many")
flip = t.rev
print(before.all("game/G2", "court"))    # ["east"]: one, latest wins
print(flip.all("game/G2", "court"))      # ["north", "east"]
print(flip.all("game/G1", "court"))      # ["north"]

# %% [markdown]
# A declaration is as-of. Reads before `flip` still fold `court` as
# `one`; reads from `flip` on fold every earlier `add` as a set
# member, superseded values included, since no retraction row was
# ever written for an assignment. `game/G1`'s `north` was replaced
# by `south`, never removed, and `south` was removed: as a set, only
# `north` is held.

# %%
with L.transaction(by="human:dan") as t:
    t.add("db/pred/court", "db/cardinality", "one")
print(t.rev.get("game/G2", "court"))     # "east": latest add wins
try:
    flip["game/G2", "court"]             # at flip, court is many
except TypeError as e:
    print("TypeError:", e)

# %% [markdown]
# ## `db/type`: checked at the write and on the strict reads

# %%
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "score", {"home": 61, "away": 58})   # json
with L.transaction(by="human:dan") as t:
    t.add("db/pred/score", "db/type", "str")
    t.add("db/pred/date", "db/type", "str")
top = L.at().id
try:
    with L.transaction(by="human:dan") as t:
        t.add("game/G2", "date", {"y": 2026, "m": 10})
except TypeError as e:
    print("TypeError:", e)               # json under a str pred
print(L.at().id == top)                  # True: nothing written

# %% [markdown]
# A predicate may declare the tag its objects take: `str`, `json`,
# or a `Value` class's dotted name (the values notebook). A write
# that mismatches is refused and the whole transaction writes
# nothing. Rows written before the declaration are not re-checked.

# %%
rev = L.at()
try:
    rev["game/G1", "score"]              # strict: checks the type
except TypeError as e:
    print("TypeError:", e)
print(rev.all("game/G1", "score"))       # loose: [{"home": 61, ...}]
print(rev["game/G1"]["score"])           # the record is loose too
print(rev["game/G1", "date"])            # a str: passes

# %% [markdown]
# The strict/loose split: `[]` and `get` compare the stored tag with
# the declaration and raise; `all`, `rev[s]` and `select` return
# what is stored. The `score` row predates its `str` declaration, so
# only the strict read objects.

# %%
try:
    with L.transaction(by="human:dan") as t:
        t.add("game/G1", "attendance", 1200)
except TypeError as e:
    print("TypeError:", e)               # a number is its string
with L.transaction(by="human:dan") as t:
    t.add("game/G1", "attendance", "1200")

# %% [markdown]
# A bare `int`, `float` or `bool` is refused by `add`: a number is
# stored as its string. A JSON document may hold numbers.

# %% [markdown]
# ## A clock: `bump` under `lock=`

# %%
with L.transaction(by="human:dan") as t:
    t["code/sv-pipe"] = {"version": "0.2.2", "commit": "7d742989"}
with L.transaction(by="human:dan", lock=10, time=True,
                   why="T531 re-baseline") as t:
    new = bump(t, "code/sv-pipe")         # patch: 0.2.2 -> 0.2.3
rev = t.rev
print(new, rev["code/sv-pipe"])
# 0.2.3 {"version": "0.2.3", "commit": "b48dca7c"}
print(rev[rev.tx, "db/time"])             # UTC, since time=True

# %% [markdown]
# `bump` reads the version through `t.base`, writes the next one,
# and on `code/<repo>` writes `commit` beside it, read from the
# environment; the caller never writes `commit`. `lock=10` holds the
# write lock for the body, so `t.base` stays the top until exit and
# no other writer can slip between the read and the write.

# %%
for subject, part in [("schema/tape", "minor"),
                      ("code/dvc-dat", "patch")]:
    try:
        with L.transaction(by="human:dan") as t:
            bump(t, subject, part)
    except ValueError as e:
        print("ValueError:", e)
with L.transaction(by="human:dan") as t:
    print(bump(t, "schema/tape", "minor",
               confirm=lambda old, new: True))   # 0.1.0

# %% [markdown]
# A minor or major bump must be confirmed (`confirm(old, new)`
# answering `True`; `just bump` asks for the word `yes`). A subject
# with no `version` starts from `0.0.0`. `code/dvc-dat` has no
# checkout in this environment, so `bump` refuses it and writes
# nothing.

# %%
with L.transaction(by="agent:svp", lock=5) as t:
    v = t.base["code/sv-pipe", "version"]
    c = t.base["code/sv-pipe", "commit"]
    t.add("rel/pipe", "pair", f"{v}+{c}")
print(L.at()["rel/pipe", "pair"])         # "0.2.3+b48dca7c"
try:
    with L.transaction(by="agent:svp", lock=0.5) as t:
        t.add("rel/pipe", "pair", "never")
        time.sleep(2)                     # past the limit
except LockTimeout as e:
    print("LockTimeout:", e)
print(L.at()["rel/pipe", "pair"])         # unchanged

# %% [markdown]
# A body that reads and then writes takes `lock=`. Past the limit
# the body is interrupted and nothing is written. Without `lock=`
# the body holds nothing, may be long, and makes no claim about what
# moved meanwhile.

# %%
rev = L.at()
when = rev.asserted("code/sv-pipe", "version", "0.2.2")
print(when)                               # [Rev(...)]: when it was set
print(when[0][when[0].tx, "db/by"])       # and by whom

# %% [markdown]
# The reverse lookup for a version: `asserted` names the revision,
# and that revision's `db/tx/<rev>` rows say who, and when if the
# transaction stamped `time=True`.
