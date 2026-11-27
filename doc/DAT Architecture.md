---
description: "the two halves, the dat and the ledger, and where they meet"
---
:>> [DAT](DAT.md) → [DAT Architecture](DAT%20Architecture.md) 
# DVC-DAT Architecture
`dvc_dat` has two halves: the dat, a folder that is its own recipe, and the ledger, an append-only database of its history.

The **dat** half (the package `dvc_dat`) keeps
folders that are their own recipe: a spec, the files a run wrote, and a
result, sealed under a content hash. The **ledger** half
(`dvc_dat.ledger`) keeps the history around them: an append-only
database where every fact is a row stamped with a revision, every read
sees the state as of one revision, and every value is stored by its
content. Each half has one module page, its design first and its
reference, generated from the docstrings, below:

- [DAT Dat](api/core.md): `Dat`, `DatManager`,
  `DatContainer`, `Namespace`; specs, sealing, standing, the manager.
- [DAT Ledger](api/ledger.md): `Ledger`, `Rev`,
  `Ref`, `Transaction`, `Value`, `Fn`; the fold, sealing and saving,
  the sandbox, evaluation and the dependencies.

![The dat and the ledger](DAT%20Architecture.svg) 

What each piece is (square boxes are classes; rounded ones are not):

- **Dat** — a folder that is its own recipe: spec, files, result.
- **DatManager** — finds dat folders, runs them, loads them by name.
- **Ledger** — an append-only database of facts, one revision each.
- **Rev** — a frozen view of the ledger at one time point.
- **Ref** — a pointer to a value, not yet loaded.
- **Value** — a serialized Python object, stored by its content hash.
- **Value function** — a sandboxed, versioned Python function
  (`@dat.fn`); a call is evaluated once and remembered.
- **Just recipes** — the human's verbs, one ledger call each.
- **ArtStore** — the bytes of every value, by sha256, written once.
- **A dat is a value** — the ledger stores a dat folder as a `Value`
  whose encoding is its manifest, `{relpath: sha256}`.

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
  `@dat.fn` declares `path: Path`; `run` binds a fresh folder under
  `$DAT_WORK`, the body writes the dat there and returns `Dat(path)`,
  the seal moves the files into the ledger's art store, and the call's
  `path=` names the result, its folder a view at the name.
- **A dat streams.** Its files are its parts, hashed in 1 MiB blocks and
  cloned copy-on-write into the art store (a streamed copy where the
  filesystem cannot clone; never a hardlink), so
  a GB-scale folder seals and saves in memory bounded by its manifest.
- **An ETL pipeline is a set of value functions.** Each stage runs
  the stage below it and returns a dat; a change upstream re-derives
  only the stages whose dependencies moved.
- **The just layer is the human's verbs.** Each recipe is one ledger
  call under a name a person would type, shipped in `dvc_dat.just`
  beside `run` ([Command Line](cli.md) § The ledger verbs).
- **Two stores, one keying.** The dat manager keeps dat folders and
  artifacts under its own `art/`, with one `_index_.json`; the ledger
  keeps `ledger.db` (or a Postgres schema) and its own `art/`. Both key
  bytes by sha256; they are separate folders.
- **One configuration file.** `.datconfig.yaml` configures the dat
  manager and, under `root:`, names the root ledger, whose registry
  lists every other ledger (`ledgers.games`); without it the
  root is a SQLite folder under the first dat folder, made on first
  use. `Ledger()` and `L` find the active one by walking up from the
  working directory (`DAT_LEDGER`, else the file's `default:`) and
  assert its `mounts:` as ledger rows. `namespace: ledger` makes the
  project's names the ledger's `db/mount` rows. There is no override
  file.

## Designed, not yet built

- **The mirror**: one durable shelf per cloud region beside the local
  art store, and a `whereabouts(hash, region)` table saying where the
  bytes are now, outside the quads.
- **`platform`** naming the GPU, CUDA and torch; today it is
  `<sys.platform>-<machine>-py<X.Y>`.

## Where the detail lives

- `api/`: the module pages above, and the reference pages of
  `dvc_dat.just` and `dvc_dat.dat_tools`.
- The notebooks in `DAT Demos/`:
  [`ledger-triples.py`](DAT%20Demos/ledger-triples.ipynb) (the quad store
  alone), [`ledger-values.py`](DAT%20Demos/ledger-values.ipynb) (values,
  functions, evaluation), [`ledger-dats.py`](DAT%20Demos/ledger-dats.ipynb) 
  (a dat as a value, an ETL chain, releases),
  [`ledger-just.py`](DAT%20Demos/ledger-just.ipynb) (the human's verbs).
- The dat half's guides: [Concepts](concepts.md),
  [Spec Format](spec-format.md), [Mounts](mount-commands.md),
  [Command Line](cli.md).
- The design choices and the reason for each: [DAT Design Notes](Design/DAT%20Design%20Notes.md).
