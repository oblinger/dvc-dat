:>> [DAT](DAT.md) → [how-to-ledger](how-to-ledger.md) 
# How to use a ledger
At the end you will have a ledger of your own holding values and a dat, their bytes pushed to a values store and pulled back on a second machine, a value read as of an older revision, and a memo policy chosen.

Needs: `dvc_dat` installed (in a checkout of this repository, `uv sync`), `git`, and an empty folder to work in. Every command below runs in that folder and printed what is shown under it. What a ledger is, a project's history of facts with every value stored by its content, is [DAT Ledger](api/ledger.md); the four ledger notebooks under [Tutorials](tutorials.md) teach it at length.

## 1. Create the ledger and give it a values store
A folder ledger is a SQLite file, `ledger.db`, beside its cache of bytes, `art/`. Nothing is made on disk without `create=True`. The row `(db, db/values, <uri>)` names where the ledger's bytes live beyond this machine; here a local folder, `bucket/`, stands in for a cloud bucket.

```python
# s1_create.py
from pathlib import Path

from dvc_dat.ledger import Ledger

bucket = Path("bucket").resolve()
bucket.mkdir()
L = Ledger("team", create=True)
with L.transaction(by="human:me") as t:
    t.add("db", "db/values", bucket.as_uri())
print("ledger:", sorted(p.name for p in Path("team").iterdir()))
print("values at:", L.values.endswith("/bucket"))
print("revision:", L.at().id)
```

```bash
python s1_create.py
```

```text
ledger: ['ledger.db', 'ledger.db-shm', 'ledger.db-wal']
values at: True
revision: 1
```

Each `with L.transaction(...)` block becomes exactly one revision when it closes, or nothing if it raises. A cloud store is a backend you register (`register_values`, [Backends](api/ledger.md#backends)); a ledger shared by a team is a Postgres location instead of a folder, and nothing else on this page changes.

## 2. Declare a value class and seal two values
A value is an object stored by its content. Its class says how it becomes bytes (`encode`) and back (`decode`), and `@ledger_class(preds=...)` names the predicates, the searchable facts, its values may carry. The class lives in a module so a later `load` can import it:

```python
# scores.py
"""scores: one game's score sheet, a ledger value."""
import json

from dvc_dat.ledger import Value, ledger_class


@ledger_class(preds=("game", "season"))
class Score(Value):
    """A game's points by team, stored as canonical JSON."""

    def __init__(self, points: dict):
        self.points = points

    def encode(self, out) -> None:
        out.write(json.dumps(self.points, sort_keys=True).encode())

    @classmethod
    def decode(cls, src, store) -> "Score":
        return cls(json.loads(src.read()))
```

`v.seal(t, name=...)` fixes the value's identity, writes its rows into the transaction, and names it. Because the ledger has a values store, the seal also pushes the bytes there before the commit:

```python
# s2_seal.py
from pathlib import Path

from dvc_dat.ledger import Ledger
from scores import Score

L = Ledger("team")
g1 = Score({"home": 64, "away": 58})
g1.preds.update(game="G1", season="2026")
g2 = Score({"home": 71, "away": 73})
g2.preds.update(game="G2", season="2026")
with L.transaction(by="human:me") as t:
    g1.seal(t, name="score/G1")
    g2.seal(t, name="score/G2")
print("sealed:", repr(g1), repr(g2))
print("subject:", g1.subject[:12], "...")
blobs = sorted(Path("bucket").rglob("*"))
print("pushed:", len([b for b in blobs if b.is_file()]), "blobs")
print("revision:", L.at().id)
```

```bash
python s2_seal.py
```

```text
sealed: <Score score/G1> <Score score/G2>
subject: b22e44cf974f ...
pushed: 2 blobs
revision: 2
```

The subject is a hash of the value's bytes, preds and dependencies, so the same content sealed again is the same subject. Once sealed, a value never changes: its preds are read-only and a later `add` on one of them is refused (`Exists`).

## 3. Read values by name and by predicate
`L.at()` is a frozen view of the ledger at its newest revision. `load` takes a name or a subject; `values` returns every value whose preds match, and `value` exactly one:

```python
# s3_read.py
from dvc_dat.ledger import Ledger, Multiple
from scores import Score

rev = Ledger("team").at()
print("by name:", rev.load("score/G1").points)
print("by preds:", rev.values(season="2026"))
print("one:", repr(rev.value(game="G2")))
try:
    rev.value(kind=Score)
except Multiple as e:
    print("Multiple:", e)
```

```bash
python s3_read.py
```

```text
by name: {'away': 58, 'home': 64}
by preds: [<Score score/G1>, <Score score/G2>]
one: <Score score/G2>
Multiple: kind=scores.Score matches 2: score/G1, score/G2
```

`value` refuses rather than pick one when several match. From a shell the same reads are `just values season=2026` and `just value game=G2` ([The ledger verbs](cli.md#the-ledger-verbs)).

## 4. Seal a dat
A dat is a folder with a `_spec_.yaml`, and on the ledger it is a value like any other: each file goes to the store by its hash, and the dat's bytes are the manifest naming them. Loading it rebuilds the folder in the cache:

```python
# s4_dat.py
from pathlib import Path

from dvc_dat import Dat
from dvc_dat.ledger import Ledger

folder = Path("box-scores")
folder.mkdir()
(folder / "_spec_.yaml").write_text("game: G1\nperiod: 4\n")
(folder / "G1.csv").write_text("team,points\nhome,64\naway,58\n")

L = Ledger("team")
d = Dat(folder)
with L.transaction(by="human:me") as t:
    d.seal(t, name="box/G1")
print("sealed:", repr(d))
back = L.at().load("box/G1")
print("files:", sorted(p.name for p in back.path.iterdir()))
print("own folder:", back.path.resolve() != folder.resolve())
files = [b for b in Path("bucket").rglob("*") if b.is_file()]
print("pushed:", len(files), "blobs")
```

```bash
python s4_dat.py
```

```text
sealed: <Dat box/G1>
files: ['G1.csv', '_spec_.yaml']
own folder: True
pushed: 5 blobs
```

The three new blobs are the two files and the manifest. A dat whose spec names a `dat.kind` subclass carries that class's preds; [DAT Dat](api/core.md) and the [ledger: dats](DAT%20Demos/ledger-dats.ipynb) notebook cover it.

## 5. Pull the bytes on another machine
Every reader of a ledger shares its rows and its values store; each machine keeps its own cache. A read takes the bytes from the cache and, on a miss, pulls them from the values store, checked against their hash. Here a copy of the rows with an empty cache stands in for the second machine:

```python
# s5_pull.py
import sqlite3
from pathlib import Path

from dvc_dat.ledger import Ledger

# the second machine: the ledger's rows, none of its bytes
other = Path("other-machine/team")
other.mkdir(parents=True)
src = sqlite3.connect("team/ledger.db")
dst = sqlite3.connect(other / "ledger.db")
src.backup(dst)
src.close()
dst.close()


def cached(folder):
    blobs = (folder / "art" / "sha256").rglob("*")
    return len([p for p in blobs if p.is_file()])


L2 = Ledger(other)
print("before:", cached(other), "files in its cache")
print("score/G1:", L2.at().load("score/G1").points)
box = L2.at().load("box/G1")
print("box/G1:", sorted(p.name for p in box.path.iterdir()))
print("after:", cached(other), "files in its cache")
```

```bash
python s5_pull.py
```

```text
before: 0 files in its cache
score/G1: {'away': 58, 'home': 64}
box/G1: ['G1.csv', '_spec_.yaml']
after: 4 files in its cache
```

Only what was read came over: `score/G1`'s blob and the dat's three, not `score/G2`. Nothing is pushed by hand: the seal pushed, and the read pulled.

## 6. Correct a value and read the old one
A value never changes, so a correction is a new value with the name re-pointed at it. Every read is bounded by a revision, so `L.at(n)` still answers as it did at `n`:

```python
# s6_revision.py
from dvc_dat.ledger import Ledger
from scores import Score

L = Ledger("team")
before = L.at().id
fixed = Score({"home": 66, "away": 58})
fixed.preds.update(game="G1", season="2026")
with L.transaction(by="human:me", why="two points missed") as t:
    fixed.seal(t, name="score/G1")
print("now:", L.at().load("score/G1").points)
print("as of", before, ":", L.at(before).load("score/G1").points)
for row in L.at().history("score/G1", "db/alias"):
    print("alias at", row.rev, "->", row.object[:12], "...")
```

```bash
python s6_revision.py
```

```text
now: {'away': 58, 'home': 66}
as of 3 : {'away': 58, 'home': 64}
alias at Rev(2) -> b22e44cf974f ...
alias at Rev(4) -> b47900313cdc ...
```

A name is an alias row; the one written latest wins. `just history score/G1` prints the same rows with who wrote each revision.

## 7. Memoize a function and choose a memo policy
A ledger function is a Python function the ledger knows by name: it takes the revision first, and its result is sealed as a value, so the same call is answered from the ledger next time. The ledger ties the function to the commit that holds it, so it lives in a git checkout, here `margin/`:

```python
# margin/margin.py
"""margin: a ledger function over a score."""
from dvc_dat import dat


@dat.fn
def margin(rev, *, game: str) -> int:
    """Home points minus away points for one game."""
    points = rev.load(f"score/{game}").points
    return points["home"] - points["away"]
```

```bash
cd margin && git init -q && git add . && cd ..
git -C margin -c user.name=me -c user.email=me@example.com \
  commit -qm margin
```

Every run records the platform it ran on. The **memo policy**, the row `(db, db/memo-policy, <name>)`, decides at each lookup how much of that record must agree for a stored result to answer: `platform` (the default) compares the operating system, machine and Python version; `card` adds the GPU model and driver, so a result computed on one card does not answer on another. Changing the policy is a new row; nothing stored is rewritten. A policy of your own is a function of the record, registered by name:

```python
# s7_memo.py
import json
import sys

from dvc_dat.ledger import Ledger, register_policy

sys.path.insert(0, "margin")  # the checkout holding margin.py
L = Ledger("team")
first = L.at().run("margin.margin", game="G1")
top = L.at().id
again = L.at().run("margin.margin", game="G1")
print("margin:", first.obj, " hit:", again.subject == first.subject,
      " nothing written:", L.at().id == top)
record = json.loads(first.dependencies["platform/record"])
print("recorded:", ", ".join(sorted(record)))
print("policy:", L.at()["db", "db/memo-policy"])

with L.transaction(by="human:me") as t:
    t.add("db", "db/memo-policy", "card")
third = L.at().run("margin.margin", game="G1")
print("policy:", L.at()["db", "db/memo-policy"],
      " hit:", third.subject == first.subject)


def by_cuda(r):
    return f"{r['platform']}|{r['card']}|{r['cuda']}"


register_policy("cuda", by_cuda)
with L.transaction(by="human:me") as t:
    t.add("db", "db/memo-policy", "cuda")
fourth = L.at().run("margin.margin", game="G1")
print("policy:", L.at()["db", "db/memo-policy"],
      " hit:", fourth.subject == first.subject)
```

```bash
python s7_memo.py
```

```text
margin: 8  hit: True  nothing written: True
recorded: card, cpu, cuda, driver, machine, os, platform, python, torch
policy: platform
policy: card  hit: True
policy: cuda  hit: True
```

The three hits are on the machine that computed the result, whose record agrees under every policy. The row stores only the policy's name, so every process that looks up under a policy of its own registers it first; one that does not is refused:

```python
# s8_unregistered.py
import sys
import textwrap

from dvc_dat.ledger import Ledger, LedgerError

sys.path.insert(0, "margin")
L = Ledger("team")
try:
    L.at().run("margin.margin", game="G2")
except LedgerError as e:
    print(textwrap.fill(f"LedgerError: {e}", 60,
                        break_on_hyphens=False))
```

```bash
python s8_unregistered.py
```

```text
LedgerError: the ledger's memo policy is 'cuda' (db
db/memo-policy), which no code in this process registered
(built-in: card, platform; register_policy)
```

The rules behind each step: [Revisions and transactions](api/ledger.md#revisions-and-transactions), [Storage](api/ledger.md#storage), [Backends](api/ledger.md#backends), [Memoization and the platform](api/ledger.md#memoization-and-the-platform).
