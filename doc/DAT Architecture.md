# DAT Architecture

`dvc_dat` keeps two kinds of record. A **dat** is a folder that is its
own recipe: a spec, the files a run wrote, and a result, sealed under a
content hash. The **ledger** is the history around it: every fact a row
stamped with a revision, every read the state as of one revision, and
every value the ledger holds stored by its content. The dat half ships
today. The ledger described here was designed 2026-10-18 and is being
rebuilt to that design; until the rebuild lands, every ledger call on
this page is the design, not running code.

## Purpose

An ML project needs one answer to three questions about any result:
what it is, what made it, and whether it still holds. The dat answers the
first two for one folder: the spec says what to run, the result says what
came out and what it loaded. The ledger answers all three across a whole
project and through time: what every name meant at a given moment, which
code and which inputs produced a value, and whether those inputs have
moved since. When nothing has moved, the ledger hands back what was
already computed.

## Two halves: things and their history

```text
 the ledger: history                     the dat: a thing
 quads (rev, subject, pred, object)      _spec_.yaml
   │ read as of a revision                 │ run, in work/
   ▼                                       ▼
 value function ───── builds ──────────► folder + _result_
   │ eval seals                            │ Dat(work)
   ▼                                       ▼
 values, stored by content ◄───────── a dat is one of them
   ▲
 just recipes: one ledger call each
```

The two halves meet in one place: **a dat is a value**. A `Dat` is a
`Value` subclass that encodes as the manifest of its folder, so the
ledger stores, finds and depends on dats the way it does any other
value. From there the rest follows:

- **The dat constructor is a value function.** A function marked
  `@ledger_fn` takes a spec, builds the folder and returns `Dat(work)`;
  `eval` runs it once per question and seals the result.
- **An ETL pipeline is a set of value functions.** Each stage evaluates
  the stage below it and returns a dat; a change upstream re-derives
  only the stages whose trace moved.
- **The just layer is the human's verbs.** Each recipe is one ledger call
  under a name a person would type: `just bump`, `just eval`,
  `just why`, `just history`.

## The dat: a folder that is its own recipe

```text
data/runs/2026-10/exp1/
  _spec_.yaml     the recipe: complete, argumentless
  model.pt        what the run wrote: content
  _result_.yaml   what it produced: dat.sha256, standing,
                  dependencies (name -> hash of everything loaded)
  run/            the run sub-dat: host, time, git commit; not content
```

```python
from dvc_dat import Dat

do = Dat.do
do("catalog.experiment", epochs=200)  # fork the template, run it
exp_dat = Dat.load("runs/2026-10/exp1")
exp_dat.get_spec()["dat"]["kwargs"]   # {"epochs": 200}
```

Arguments never ride beside a spec: `do(template, **kwargs)` writes them
into a new spec, creates that dat, and runs it with no arguments, so
**the spec is the record**. The save that counts **seals** the dat:
`dat.sha256` is the hash of its content (the spec, minus its name, plus
the files and the result; `run/` is left out), and a sealed dat is never
rewritten. Two runs of one recipe on two machines hash the same when the
code is functional.

A dat's **standing** says how far it can be relied on: `rolling`,
`open`, `sealed`, or `referenceable` (sealed, by clean committed code,
from referenceable inputs). Every load inside a run goes through the
**manager** (`DatManager`, the world: its dat folders and its `do`
namespace), so a run's dependencies are captured, not declared.

An **artifact** is a file or folder saved by hash beside the dats, under
a name or under its URN `sha256:<hex>`. Dats and artifacts share one
namespace and one index. Detail: [Concepts](concepts.md),
[Spec Format](spec-format.md).

## The ledger: facts read as of a moment

### Every fact is a quad, every read a revision

```text
rev  subject     predicate   object
  1  game/G1     home        G4
  1  game/G1     court       north
  1  db/tx/1     db/by       human:dan
  2  game/G1     court       south
  2  game/G1     officials   kim
  2  game/G1     officials   ortiz
```

```python
from dvc_dat.ledger import Ledger

ledger = Ledger()                    # nearest .datconfig.yaml
with ledger.transaction(by="human:dan") as t:
    t["game/G1", "court"] = "south"
    t.add("game/G1", "officials", "kim")
rev = ledger.at()                    # the top, frozen
rev["game/G1", "court"]              # "south": exactly one
rev["game/G1"]                       # the record, a dict
ledger.at(1)["game/G1", "court"]     # "north", forever
rev.asserted("game/G1", "court")     # every change, with its rev
rev.rows()                           # the ledger as stored
```

One `with` block is one **revision**: every row it adds lands together
on exit, an exception writes nothing. Rows are never updated or deleted;
`remove` appends a remove row. A read is always made through a `Rev`, a
frozen view, so a long run reads one snapshot by construction.

**The fold** turns the rows at or before a revision into the state they
mean, by each predicate's **cardinality**: `one` (the default; the
latest `add` wins, so `add` is assignment) or `many` (the set of members
added and not since removed). Cardinality is itself a row,
`(db/pred/officials, db/cardinality, many)`, read as of the same
revision. Every read folds except `rows()` and `asserted`, which walk
history. `since=` restricts a read to the rows of an interval: what one
transaction wrote, or what moved between two releases.

### Values: stored by content, found by preds

```python
video_value = Video(read_mp4("G1.mp4"))  # a Value subclass
video_value.preds.update(game="G1", camera="wide")
with ledger.transaction(by="human:dan") as t:
    video_subject = t.add_value(video_value, alias="video/G1",
                                provenance="import:camera")
rev = ledger.at()
rev.load("video/G1")                     # through the alias
rev.values(kind=Video, game="G1")        # found by preds
```

A **value** is a large or complex object kept by its bytes. Its class
says how it becomes bytes and back (`encode`, `decode`); `add_value`
puts the bytes in the art store and **seals** a subject whose name is a
hash of the bytes, the preds and the trace, never typed by anyone. The
seal writes the subject's machinery rows (`db/value`, `db/kind`,
`db/provenance`, `db/preds`, `db/trace/*`) and one row per **pred**:
the string attributes a value is found by, set on `v.preds` by whoever
built it, named in advance by `@ledger_class(preds=…)` on the class.

**A sealed value never changes.** Its own rows are frozen (`Exists` on a
later write); any other row on its subject is annotation. A wrong pred
is fixed by sealing a corrected copy, and a new version is a new value.
An **alias** is a re-pointable row, `(video/G1, db/alias, <subject>)`,
so a readable name moves while the values it pointed at stay. A `Ref`
names a value at a revision without fetching a byte; `Ref.load()` is the
one act that does.

### Functions: global or sandboxed

```python
@ledger_fn
def cut(rev, *, game: str, version: str) -> Cut:
    home_str = rev[f"game/{game}", "home"]         # traced
    raw_video = rev.value(kind=Video, game=game)   # traced
    cut_value = Cut(cut_video(raw_video, home_str))
    cut_value.preds.update(game=game, version=version)
    return cut_value
```

A **value function** takes the revision first and keywords after, and
returns a `Value`. `@ledger_fn` marks it and changes nothing else: a
plain call still runs the body and returns an unsealed value, which is
how it is unit-tested. `rev.load_fn(name)` resolves a dotted name to an
`Fn` at that revision; calling the `Fn` is `eval`.

A **global** function is whatever the running process imports. The
ledger cannot control that code, so it records which code it was: the
repository's commit, found by git discovery over the module's folder
(`Env` and `set_env_provider` exist only as a test seam). `bump` moves
the clock subject `code/<repo>`, writing `version` and `commit`
together.

A **sandboxed** function lives under a **mount**, rows naming a dotted
prefix, its repo and its root:
`(db/mount/demo_game.etl, db/root, demo_game/etl)`. It runs in a worker
started `python -I` whose path holds only the standard library,
`site-packages` and the mounted roots. An import outside the mounts is
`UnmountedImport`, a read outside the mounts, the dats and its scratch
is `UntracedRead`, so an incomplete mount table is a crash rather than a
silently wider trace. Workers are kept warm, one per code identity.

### Evaluation remembers what it read

```python
rev = ledger.at()
cut_value = rev.eval("demo_game.game.cut", game="G1",
                     version="1.5.3")     # ran, sealed
again_value = ledger.at().eval("demo_game.game.cut", game="G1",
                               version="1.5.3")   # a hit
cut_value.trace
# {"fn": "db/fn/demo_game.game.cut/<hash>",
#  "code/demo-game": "0.1.0+<commit>",
#  "game/G1 home": "G4",
#  "q:{...kind Video, game G1}": "[ref:...Video:<hash>]",
#  "uv.lock": "sha256:...", "platform": "..."}
cut_value.matches(ledger.at())            # still holds?
```

`eval` keys a **memo** by `(fn, keys, trace)`. The `db/fn` and `db/keys`
rows say what was asked; the **trace** says what the world was: the code
that ran (one `fn` item), every row read by name, every value loaded
(named by its bytes, so identical inputs are the same input), every
query and the refs it answered, every nested eval, the lock file and the
platform. A lookup matches `(fn, keys)` exactly, then checks each
candidate's trace against the revision asked at; a hit is restored, a
miss runs and seals. A correction to `game/G1`'s teams therefore makes
the cut stale, and the next ask re-derives it. `memo=False` runs without
sealing; `memo="get"` looks up and never runs.

A hand seal (`add_value(deps=[…])`) has a **declared** trace, trusted
and not proven; an eval's is **recorded**, and its provenance,
`eval:sandbox` or `eval:base`, says so. A consumer that needs proof asks
for an `eval:` value.

### The ledger describes itself under `db/`

| subject | what it holds |
| --- | --- |
| `db` | `version`: the human name of a whole state, `db/format` |
| `db/tx/<rev>` | `db/by`, `db/time`, any keyword given the txn |
| `db/pred/<name>` | `db/cardinality`, `db/index`, `db/type`, `db/doc` |
| `db/fn/<name>/<hash>` | the code a dotted name resolved to |
| `db/mount/<prefix>` | `db/repo`, `db/root`, `db/salt` |
| `db/kind/<dotted>` | `db/moved`: a renamed class |

Every predicate the system writes or interprets is `db/…`; everything
bare is the user's. The ledger's configuration is ordinary rows written
by ordinary transactions, so declaring an index, a cardinality or a
mount has a revision and a history like any fact. A release is a bump of
`db`'s own `version`, and `ledger.at("3.2.0")` reads that moment.

## Storage

```text
 Ledger ──────► quads        one SQLite file; Postgres planned
        └─────► art store    bytes by sha256, write-once
                   ┊ designed: a shelf per cloud region,
                   ┊ and whereabouts(hash, region)
 DatManager ──► dat folders  data/
        └─────► artifacts    art/, by sha256, one _index_.json
```

- **The quads** live in one SQLite file: one table of
  `(rev, ord, subject, predicate, object, added)`, never updated, with
  indexes on `(subject, predicate, rev)` and `(predicate, object, rev)`.
  The object position is a tagged string (`str:`, `json:`, `ref:`), so a
  row reads without a schema. A Postgres backend is planned; the
  prefix-only `s=` globs are chosen to run as index range scans on both.
- **The art store** holds bytes by `sha256`, write-once: a file, a
  pickle, a parquet table, or a dat folder's files under its manifest.
  The same bytes are stored once however many subjects point at them.
  Today the ledger's store and the dat manager's `art/` are separate
  folders keyed the same way.
- **The mirror** is designed, not built: one durable shelf per cloud
  region beside the local store, and a `whereabouts(hash, region)` table
  saying where the bytes are now. Whereabouts is status, not history, so
  it sits outside the quads and takes no revision.

The project names its ledger in `.datconfig.yaml`, the file the dat
manager already reads: `ledger: .dat/ledger`, and optionally `mounts:`.
`Ledger()` walks up from the working directory to it and never creates
anything; `Ledger(path, create=True)` is the one explicit act that does.

## Concurrency: one writer, many moments

- **One writer at a time.** A transaction takes the backend's write lock
  only at commit; its revision is the next integer under that lock.
  `lock=<seconds>` holds the lock for the whole body when a read must not
  go stale before the write (`bump` under `lock=` cannot lose an update).
- **Revisions are dense and monotonic**, so a reader can never see half
  a transaction, and the same revision gives the same answer forever.
- **Reads are as-of.** Readers take no lock; a `Rev` is a snapshot.
- **Races are recorded, not hidden.** Two processes missing on one memo
  key both run and both seal: identical bytes and trace are one subject;
  different bytes are two entries, both kept, which is the evidence a
  nondeterminism check needs.
- **Not yet proven.** A stress test is on the roadmap: N writers and M
  readers on one SQLite file, then on Postgres, checking unique
  monotonic revisions, consistent as-of reads, and a cardinality cache
  that never goes stale. One database on one host is the supported
  shape; shared filesystems are out of scope.

## Designed, not yet built

- **The rebuild (T534), in progress.** `dvc_dat/ledger2` is a spike
  built to the 2026-10-17 surface; it is being rebuilt to the 2026-10-18
  design (the `db/` namespace, `add_value`, preds, aliases, `asserted`,
  `rows()`, the one constructor) to become `dvc_dat.ledger` in 5.0.0.
  The shipped `dvc_dat.ledger` is still the 4.0 ledger of
  [The ledger](ledger.md). The four `ledger-*` notebooks are the
  rebuild's acceptance tests and do not run until it lands.
- **The sandbox.** The spike evaluates in base mode only; mounts, the
  `python -I` worker, the import finder and the open hook are designed.
- **Q36, open:** where a function that builds a dat writes. Lean: it
  declares `work: Path`, the eval binds a fresh scratch folder, and the
  seal moves the folder into the art store.
- **Q37, open:** what the one `fn` trace item hashes. Lean: the modules
  actually loaded during the run, so a constructor that imports its
  stage by a spec key is pinned to the stage that ran.
- **The mirror** (`where`, `place` across clouds), the Postgres backend,
  the concurrency stress test, and the justfile the just notebook
  proposes.

## Where the detail lives

The ledger's design pages live in the project's design vault, not in
this repository; find them by name:

- **SVP447 Ledger Module**: every class, method and field, formally
- **SVP447 Eval**: functions, `eval`, the sandbox and the trace
- **SVP447 Versions**: clocks, releases, running at an old revision
- **SVP447 Values**: the value space, and § The worked example: a game
- **SVP447 - Ledger indices on dats, select with derive, and bump**: the
  decisions and the open questions (A46–A53, Q36, Q37)

The notebooks, in [`DAT Demos/`](DAT%20Demos/), written to that design:

- [`ledger-triples.py`](DAT%20Demos/ledger-triples.py): the quad store
  alone: transactions, the fold, every read, `db/type`, `lock=`
- [`ledger-values.py`](DAT%20Demos/ledger-values.py): values, preds,
  aliases, global and sandboxed functions, evaluation
- [`ledger-dats.py`](DAT%20Demos/ledger-dats.py): a dat as a value, the
  dat constructor, an ETL chain, releases
- [`ledger-just.py`](DAT%20Demos/ledger-just.py): the human's verbs,
  each one API call

The dat half: [Concepts](concepts.md), [Spec Format](spec-format.md),
[Mounts](mount-commands.md), [Command Line](cli.md),
[Overview](overview.md).
