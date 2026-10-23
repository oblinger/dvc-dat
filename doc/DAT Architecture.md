:>> 
# DAT Architecture
`dvc_dat` keeps two kinds of record. A **dat** is a folder that is its
own recipe: a spec, the files a run wrote, and a result, sealed under a
content hash. The **ledger** is the history around it: every fact a row
stamped with a revision, every read the state as of one revision, and
every value stored by its content. The dat half is the package
`dvc_dat`; the ledger is `dvc_dat.ledger`. Each half has a module doc:

- [DAT Dat](DAT%20Modules/DAT%20Dat.md): `Dat`, `DatManager`,
  `DatContainer`, `Do`; specs, sealing, standing, the manager.
- [DAT Ledger](DAT%20Modules/ledger/DAT%20Ledger.md): `Ledger`, `Rev`,
  `Ref`, `Transaction`, `Value`, `Fn`; the fold, sealing and saving,
  the sandbox, evaluation and the dependencies.

![The dat and the ledger](DAT%20Architecture.svg) 

## Purpose

An ML project needs one answer to three questions about any result:
what it is, what made it, and whether it still holds. The dat answers the
first two for one folder: the spec says what to run, the result says what
came out and what it loaded. The ledger answers all three across a whole
project and through time: what every name meant at a given moment, which
code and which inputs produced a value, and whether those inputs have
moved since. When nothing has moved, the ledger hands back what was
already computed.

## How the halves connect

The two halves meet in one place: **a dat is a value**. The ledger's
`Dat` is a `Value` subclass that encodes as the manifest of its folder,
`{"files": {relpath: sha256}}`, so the ledger stores, finds and depends
on a folder the way it does any other value. It is its own class, not
the dat manager's `dvc_dat.Dat`: it hashes every file in the folder and
reads no `_spec_.yaml` beyond checking its `dat.kind` on load.

- **The dat constructor is a value function.** A function marked
  `@ledger_fn` declares `path: Path`; `run` binds a fresh folder under
  `$DAT_WORK`, the body writes the dat there and returns `Dat(path)`,
  the seal moves the files into the ledger's art store, and the call's
  `path=` names the result, its folder a view at the name.
- **A dat streams.** Its files are its parts, hashed in 1 MiB blocks and
  hardlinked into the art store (a streamed copy across filesystems), so
  a GB-scale folder seals and saves in memory bounded by its manifest.
- **An ETL pipeline is a set of value functions.** Each stage evaluates
  the stage below it and returns a dat; a change upstream re-derives
  only the stages whose dependencies moved.
- **The just layer is the human's verbs.** Each recipe is one ledger
  call under a name a person would type; a minimal justfile sits beside
  the notebooks ([`DAT Demos/justfile`](DAT%20Demos/justfile)).
- **Two stores, one keying.** The dat manager keeps dat folders and
  artifacts under its own `art/`, with one `_index_.json`; the ledger
  keeps `ledger.db` (or a Postgres schema) and its own `art/`. Both key
  bytes by sha256; they are separate folders.
- **One configuration file.** `.datconfig.yaml` configures the dat
  manager and, under `ledger:`, names the ledger; `Ledger()` finds it by
  walking up from the working directory and asserts its `mounts:` as
  ledger rows.

## Designed, not yet built

- **Sandbox stubs.** No idle retirement of workers; a nested eval
  under another mount runs in the same worker; a base-mode eval nested
  inside a worker is unsupported; repo files read under a mount are
  allowed, not recorded; no old commit is ever checked out.
- **The mirror**: one durable shelf per cloud region beside the local
  art store, and a `whereabouts(hash, region)` table saying where the
  bytes are now, outside the quads.
- **`platform`** naming the GPU, CUDA and torch; today it is
  `<sys.platform>-<machine>-py<X.Y>`.

## Where the detail lives

- [`DAT Modules/`](DAT%20Modules/): the two module docs above, and the
  per-file pages beside them ([`dat.md`](DAT%20Modules/dat.md), and one
  per file under [`ledger/`](DAT%20Modules/ledger/ledger.md)).
- The notebooks in [`DAT Demos/`](DAT%20Demos/):
  [`ledger-triples.py`](DAT%20Demos/ledger-triples.py) (the quad store
  alone), [`ledger-values.py`](DAT%20Demos/ledger-values.py) (values,
  functions, evaluation), [`ledger-dats.py`](DAT%20Demos/ledger-dats.py) 
  (a dat as a value, an ETL chain, releases),
  [`ledger-just.py`](DAT%20Demos/ledger-just.py) (the human's verbs).
- The dat half's guides: [Concepts](concepts.md),
  [Spec Format](spec-format.md), [Mounts](mount-commands.md),
  [Command Line](cli.md), [Overview](overview.md).
- The design pages live in the project's design vault, found by name:
  **SVP447 Ledger Module**, **SVP447 Eval**, **SVP447 Versions**,
  **SVP447 Values**.
