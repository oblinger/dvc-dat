# DAT Architecture

`dvc_dat` keeps two kinds of record. A **dat** is a folder that is its
own recipe: a spec, the files a run wrote, and a result, sealed under a
content hash. The **ledger** is the history around it: every fact a row
stamped with a revision, every read the state as of one revision, and
every value the ledger holds stored by its content. The dat half ships
as `dvc_dat`. The ledger below is the 2026-10-18 design as built in
`dvc_dat.ledger2` (branch `ledger2`); the shipped `dvc_dat.ledger` is
still the 4.0 ledger of [The ledger](ledger.md), and `ledger2` becomes
`dvc_dat.ledger` in 5.0.0. Each component has a page under
[`DAT Modules/`](DAT%20Modules/); the table in [Components](#components)
links them.

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

The two halves meet in one place: **a dat is a value**. The ledger's
`Dat` is a `Value` subclass that encodes as the manifest of its folder,
`{"files": {relpath: sha256}}`, so the ledger stores, finds and depends
on a folder the way it does any other value. It is its own class, not
the dat manager's `dvc_dat.Dat`: it hashes every file in the folder
(`__pycache__` skipped) and reads no `_spec_.yaml`. From there:

- **The dat constructor is a value function.** A function marked
  `@ledger_fn` declares `work: Path`; `eval` binds a fresh folder, the
  body writes the dat there and returns `Dat(work)`, and the seal moves
  the files into the art store and points `Dat.path` at the stored copy.
- **An ETL pipeline is a set of value functions.** Each stage evaluates
  the stage below it and returns a dat; a change upstream re-derives
  only the stages whose trace moved.
- **The just layer is the human's verbs.** Each recipe is one ledger call
  under a name a person would type. A minimal justfile sits beside the
  notebooks ([`DAT Demos/justfile`](DAT%20Demos/justfile)): `values`,
  `value`, `history`, `why`, `annotate`, `alias`, `index`, `bump`,
  `eval`, `run`.

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
[Spec Format](spec-format.md), [the dat module](DAT%20Modules/dat.md).

## The ledger: facts read as of a moment

### Every fact is a quad, every read a revision

```text
rev  subject     predicate   object
  1  game/G1     home        G4
  1  game/G1     court       north
  1  db          db/format   dvc-dat-ledger2/1
  1  db/tx/1     db/by       human:dan
  2  game/G1     court       south
  2  game/G1     officials   kim
  2  game/G1     officials   ortiz
  2  db/tx/2     db/by       human:dan
```

```python
from dvc_dat.ledger2 import Ledger

ledger = Ledger()                    # DAT_LEDGER, else the
                                     #   nearest .datconfig.yaml
with ledger.transaction(by="human:dan") as t:
    t["game/G1", "court"] = "south"
    t.add("game/G1", "officials", "kim")
rev = ledger.at()                    # the top, frozen
rev["game/G1", "court"]              # "south": exactly one
rev["game/G1"]                       # the record, a dict
ledger.at(1)["game/G1", "court"]     # "north", forever
rev.asserted("game/G1", "court")     # [(Rev, obj, added)]
rev.rows()                           # the ledger as stored
```

One `with` block is one **revision**: every row it adds lands together
on exit, in body order, followed by its own `db/tx/<rev>` rows (`db/by`,
`db/time` when `time=True`, and any keyword given `transaction()`),
which a body that wrote nothing still writes. A ledger's first
transaction also writes `(db, db/format, dvc-dat-ledger2/1)`. An
exception in the body writes nothing, and a verb used outside the block
is `RuntimeError`. Rows are never updated or deleted; `remove` appends a
remove row. A read is always made through a `Rev`, a frozen view, so a
long run reads one snapshot by construction.

**The fold** turns the rows at or before a revision into the state they
mean, by each predicate's **cardinality**: `one` (the default; the
latest `add` wins, so `add` is assignment) or `many` (the set of members
added and not since removed). Cardinality is itself a row,
`(db/pred/officials, db/cardinality, many)`, read as of the same
revision; every `db/` predicate and the clocks `version` and `commit`
are fixed at `one`. Every read folds except `rows()` and `asserted`,
which walk history. `since=` restricts a read to the rows of an
interval: what one transaction wrote, or what moved between two
releases.

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
says how it becomes bytes and back (`encode`, `decode`), and
`@ledger_class(preds=…)` on the class names the **preds** its values may
carry: the string attributes a value is found by, set on `v.preds` by
whoever built it. `add_value` **seals** the value into a subject whose
name is a 64-hex hash of the trace, the preds and the `db/value` text
(the class and the bytes' hash), never typed by anyone. The seal happens
on `add_value`'s line: `preds` becomes read-only and `sealed`, `subject`
and `trace` are set; `rev` is set at commit, when the bytes go to the
art store just before the rows. A refusal at commit or an exception in
the body unseals every value the transaction froze and removes the bytes
it stored. The rows are the subject's machinery (`db/value`, `db/kind`,
`db/provenance`, `db/preds`, one `db/trace/<item>` per trace item) and
one row per pred, one per member for a `many` pred.

**A sealed value never changes.** Its own rows are frozen: a later
`add` or `remove` on one is `Exists`, raised at commit. Any other row on
its subject is annotation. A wrong pred is fixed by sealing a corrected
copy, and a new version is a new value. An **alias** is a re-pointable
row, `(video/G1, db/alias, <subject>)`, so a readable name moves while
the values it pointed at stay; an alias names a subject holding a
`db/value`, and a subject holding its own `db/value` cannot be an alias.
A `Ref` names a value at a revision without fetching a byte;
`Ref.load()` is the one act that does.

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
returns a `Value`; its return annotation is required (`TypeError` at
decoration), and an annotation that is not a `Value` subclass wraps the
result in `Pickled`. `@ledger_fn` marks it and changes nothing else: a
plain call still runs the body and returns an unsealed value with an
empty trace, which is how it is unit-tested. `rev.load_fn(name)`
resolves a dotted name to an `Fn` at that revision; calling the `Fn` is
`eval`, and `rev.eval(name, **keys)` is the one-liner.

A **global** (base-mode) function is whatever the running process
imports. The ledger cannot bound that code, so it records which code it
was: the `fn` item hashes the function module's static import closure
within its checkout, and the `code/<repo>` item names that checkout's
commit. The checkout is found by git discovery over the folders of the
imported modules, skipping the standard library, `site-packages` and the
dvc-dat checkout itself; a checkout is named by its `pyproject.toml`
`[project].name`. `Env`, `Code` and `set_env_provider` exist only as a
test seam. `bump` moves the clock subject `code/<repo>`, writing
`version` and `commit` together.

A **sandboxed** function lives under a **mount**, rows naming a dotted
prefix, its repo and its root:
`(db/mount/demo_game.etl, db/root, demo_game/etl)` with `db/repo`
beside it. It runs in a worker started `python -I`, whose path holds the
standard library and `site-packages`; a finder first on `sys.meta_path`
serves the mounted prefixes from their roots. An import that would
resolve inside a mounted repo's checkout but under no mount is
`UnmountedImport`; a read outside the mounts, the art store, the
worker's scratch, the interpreter's folders and the dvc-dat package is
`UntracedRead`; a write outside the scratch and the art store is
`ConfinedWrite`. An incomplete mount table is therefore a crash rather
than a silently wider trace. There is one worker per mount, kept warm,
and the mounted modules are purged before each top-level call so every
run loads, and records, what it uses.

### Evaluation remembers what it read

```python
rev = ledger.at()
cut_value = rev.eval("demo_game.game.cut", game="G1",
                     version="1.5.3")     # ran, sealed
again_value = ledger.at().eval("demo_game.game.cut", game="G1",
                               version="1.5.3")   # a hit
cut_value.trace                           # base mode:
# {"fn": "db/fn/demo_game.game.cut/<hash16>",
#  "code/demo-game": "0.1.0+<commit8>",
#  "game/G1 home": "G4",
#  "q:{\"game\":\"G1\",\"kind\":\"demo_game.game.Video\"}":
#      "[\"ref:demo_game.game.Video:<hash>\"]",
#  "ref:demo_game.game.Video:<hash>":
#      "ref:demo_game.game.Video:<hash>",
#  "uv.lock": "sha256:...", "platform": "darwin-arm64-py3.12"}
cut_value.matches(ledger.at())            # still holds?
```

`eval` looks up a **memo** entry: every entry at the top whose `db/fn`
(the dotted name) and `db/keys` (the bound keys, defaults included, as
canonical JSON) match exactly, newest seal first, each candidate's trace
checked against the revision asked at. A hit is restored; a miss runs,
records the trace and seals in a transaction `by="eval:<name>"`, under
a subject hashing fn, keys, trace, preds and the `db/value` text. A miss
runs only when the function's checkout is clean and its HEAD is the
rev's `code/<repo>` commit (or the rev has no such row); otherwise
`NotEvaluated`. The **trace** says what the world was:

- `fn`: the `db/fn/<name>/<hash>` subject of the code that ran. Base
  mode hashes the static import closure; a sandbox run hashes the static
  closure plus every mounted module loaded during the run, at the rev's
  commit, and the mount rows.
- `code/<repo>`: base mode only, the function's own repo,
  `<version>+<commit8>` (`+<commit8>` before any `code/<repo>` row);
  it holds on the commit alone.
- every row read by name (`<subject> <predicate>`), every alias read
  through (`<name> db/alias`), every value loaded (named by its bytes,
  so identical inputs are the same input), every query (`q:{…}` → the
  sorted refs it answered), every other read (`q:{"__call__": …}`),
  every nested eval (`eval:<name>{keys}`), `uv.lock`, `platform`, and
  in the sandbox the mount's `salt` when set.

A correction to `game/G1`'s teams therefore makes the cut stale, and the
next ask re-derives it. `matches` and `diff` consult the memo and never
run anything. `memo=False` runs without sealing; `memo="get"` looks up
and never runs.

A hand seal (`add_value(deps=[…])`) has a **declared** trace, trusted
and not proven: its items are the deps given, plus `code/<repo>` for
every repo discovery reports, `uv.lock` and `platform`. An eval's is
**recorded**, and its provenance, `eval:sandbox` or `eval:base`, says
so; `add_value` refuses a provenance beginning `eval:`. A consumer that
needs proof asks for an `eval:` value.

### The ledger describes itself under `db/`

| subject | what it holds |
| --- | --- |
| `db` | `version`: the human name of a whole state; `db/format` |
| `db/tx/<rev>` | `db/by`, `db/time`, any keyword given the txn |
| `db/pred/<name>` | `db/cardinality`, `db/index`, `db/type`, `db/doc` |
| `db/fn/<name>/<hash>` | `db/name`, `db/module`, `db/sha`, `db/modules`, `db/mounts`, `db/mode`, `db/returns` |
| `db/mount/<prefix>` | `db/repo`, `db/root`, `db/salt` |
| `db/kind/<dotted>` | `db/moved`: a renamed class |

Every predicate the system writes or interprets is `db/…`; everything
bare is the user's. The ledger's configuration is ordinary rows written
by ordinary transactions, so declaring an index, a cardinality or a
mount has a revision and a history like any fact; a
`(db/pred/<p>, db/index, true)` row builds a partial SQL index on `<p>`
in the transaction that commits it. A release is a bump of `db`'s own
`version`, and `ledger.at("3.2.0")` reads that moment.

## Storage

```text
 Ledger folder ─► ledger.db   SQLite: one quads table
              └─► art/        sha256/<2>/<hex>: bytes, write-once
                              dats/<16>: a Dat materialised
                   ┊ designed: a shelf per cloud region,
                   ┊ and whereabouts(hash, region)
 DatManager ────► dat folders data/
              └─► artifacts   art/, by sha256, one _index_.json
```

- **The quads** live in one SQLite file: one table of
  `(rev, ord, subject, predicate, object, added)`, keyed by
  `(rev, ord)`, never updated, with indexes on `(subject, predicate,
  rev)` and `(predicate, object, rev)`. The object position is a tagged
  string (`str:`, `json:`, or `ref:<class>:<hash>[:<subject>]`), so a
  row reads without a schema; a bare number is refused (a number is its
  string). A Postgres backend is planned; the prefix-only `s=` globs are
  chosen to run as index range scans on both.
- **The art store** holds bytes by `sha256`, write-once: a pickle, a
  parquet table, or a dat folder's files plus its manifest. The same
  bytes are stored once however many subjects point at them. The
  ledger's store and the dat manager's `art/` are separate folders keyed
  the same way.
- **The mirror** is designed, not built: one durable shelf per cloud
  region beside the local store, and a `whereabouts(hash, region)` table
  saying where the bytes are now. Whereabouts is status, not history, so
  it sits outside the quads and takes no revision.

A ledger is a folder. `Ledger(path)` opens it and refuses a missing one;
`Ledger()` takes `DAT_LEDGER` when set, else walks up from the working
directory to the nearest `.datconfig.yaml` carrying a `ledger:` key (the
file the dat manager already reads) and asserts its `mounts:` as
`db/mount/*` rows, `by="config:<path>"`, when they differ from the
ledger's. Nothing is created without `create=True`:
`Ledger(path, create=True)` makes an empty ledger, and
`Ledger(create=True)` makes a project in the working directory
(`ledger: .dat/ledger` in its `.datconfig.yaml`).

## Concurrency: one writer, many moments

- **One writer at a time.** A transaction takes SQLite's write lock
  only at commit; its revision is `MAX(rev) + 1` under that lock.
  `lock=<seconds>` holds the lock for the whole body when a read must
  not go stale before the write (`bump` under `lock=` cannot lose an
  update); past the limit the body is interrupted, `LockTimeout`,
  nothing written.
- **Revisions are dense and monotonic**, so a reader can never see half
  a transaction, and the same revision gives the same answer forever.
- **Reads are as-of.** Readers take no lock; a `Rev` is a snapshot.
- **Races are recorded, not hidden.** Two processes missing on one memo
  key both run and both seal: identical bytes and trace are one subject
  (the second seal is dropped at commit and writes no revision);
  different bytes are two entries, both kept, which is the evidence a
  nondeterminism check needs.
- **Not yet proven.** A stress test is on the roadmap: N writers and M
  readers on one SQLite file, then on Postgres, checking unique
  monotonic revisions, consistent as-of reads, and a cardinality cache
  that never goes stale. One database on one host is the supported
  shape; shared filesystems are out of scope.

## Components

| component | what it owns |
| --- | --- |
| [`ledger`](DAT%20Modules/ledger2/ledger.md) | `Ledger`: finding, opening, creating; `at`, `transaction` |
| [`rev`](DAT%20Modules/ledger2/rev.md) | `Rev`: every read; `Ref`, `Row` |
| [`txn`](DAT%20Modules/ledger2/txn.md) | `Transaction`: writes, seals, the commit's checks; `attr` |
| [`value`](DAT%20Modules/ledger2/value.md) | `Value`, `Pickled`, `Table`, `Dat`, `ledger_class` |
| [`fn`](DAT%20Modules/ledger2/fn.md) | `ledger_fn`, `Fn`, `load_fn`, `eval`, the memo lookup |
| [`trace`](DAT%20Modules/ledger2/trace.md) | trace item names; whether an item still holds |
| [`env`](DAT%20Modules/ledger2/env.md) | discovery: repos, commits, `uv.lock`, platform |
| [`sandbox`](DAT%20Modules/ledger2/sandbox.md) | mounts, the worker, the finder, the open hook |
| [`worker`](DAT%20Modules/ledger2/worker.md) | the worker's `-m` entry point |
| [`store`](DAT%20Modules/ledger2/store.md) | SQLite quads and the art store |
| [`fold`](DAT%20Modules/ledger2/fold.md) | rows to held objects, by cardinality |
| [`codec`](DAT%20Modules/ledger2/codec.md) | tagged row objects, hashes |
| [`helpers`](DAT%20Modules/ledger2/helpers.md) | `bump` |
| [`errors`](DAT%20Modules/ledger2/errors.md) | the exceptions |
| [`dat`](DAT%20Modules/dat.md) | `Dat`, `DatManager`, `DatContainer`, `Do` |

## Designed, not yet built

- **Promotion.** `dvc_dat.ledger2` is the T534 rebuild, awaiting
  verification; it becomes `dvc_dat.ledger` in 5.0.0. The four
  `ledger-*` notebooks are its acceptance tests and run against it
  (`tests/ledger2/test_l2_notebooks.py`).
- **Sandbox stubs.** No network refusal; no idle retirement of workers;
  reads also allowed in the interpreter's folders and the dvc-dat
  package, writes in the whole scratch and the art store; a nested eval
  under another mount runs in the same worker; a base-mode eval nested
  inside a worker is unsupported; repo files read under a mount are
  allowed, not recorded; no old commit is ever checked out.
- **Q36, open, built as its lean:** a function that builds a dat
  declares `work: Path`, the eval binds a fresh folder, and the seal
  moves the files into the art store.
- **Q37, open, built as its lean:** the `fn` item hashes the static
  closure plus the modules loaded during the run (sandbox), the static
  closure alone (base).
- **The mirror** (`where`, `place` across clouds), the Postgres backend,
  the concurrency stress test, and `platform` naming the GPU, CUDA and
  torch (today `<sys.platform>-<machine>-py<X.Y>`).

## Where the detail lives

The ledger's design pages live in the project's design vault, not in
this repository; find them by name:

- **SVP447 Ledger Module**: every class, method and field, formally
- **SVP447 Eval**: functions, `eval`, the sandbox and the trace
- **SVP447 Versions**: clocks, releases, running at an old revision
- **SVP447 Values**: the value space, and § The worked example: a game
- **SVP447 - Ledger indices on dats, select with derive, and bump**: the
  decisions and the open questions (A9–A62, Q36, Q37)

The code, module by module: [`DAT Modules/`](DAT%20Modules/).

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
