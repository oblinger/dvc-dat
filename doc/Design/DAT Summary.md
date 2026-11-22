---
description: "what dvc-dat is, in its descriptive overview, and what each part of it means in the code"
---
:>>
# DAT Summary
What dvc-dat is, in its descriptive overview, and what each part stands for in the code.

## Descriptive overview

**Datomic for Python — a functional DB for ML experiment tracking.**
- Git-versioned, sandboxed Python execution with reproducible provenance
- Content-addressed blob store of serialized objects and folder trees
- Triples-based, append-only, incrementally updated JSON structures:
  a compact, timeless view of large, ever-changing configurations

Used to represent large Python computation graphs with fully reproducible provenance.

|                        |                                                                   |
| ---------------------- | ----------------------------------------------------------------- |
| **HISTORY**            | incremental and infinite                                          |
| Append-only            | a write adds facts under a new revision; nothing is overwritten   |
| Full-history           | every revision stays readable, back to the first                  |
| Point-in-time          | a revision is a frozen view; reads against it never change        |
| Incremental            | a repeated call is a hit; a change recomputes only its dependents |
| Retractable            | ending a fact is itself a fact, with when and why                 |
|                        |                                                                   |
| **STORAGE**            | serialization of folders and blobs                                |
| Serialized             | any Python value or JSON, sealed by a codec and read back whole   |
| Folder-tree            | a dat, a folder that is its own recipe, stored as one value       |
| Content-<br>addressed  | bytes stored once by sha256, write-once, shared by every value    |
| Lazy-loaded            | bytes are fetched on load; a machine holds only what it reads     |
|                        |                                                                   |
| **PROVENANCE**         | code and inputs                                                   |
| Git-versioned          | functions from a mounted git repository, at a known commit        |
| Sandboxed              | each call runs in a fresh process holding only the mounted code   |
| Dependency-<br>tracked | each result records its function, commit and every value read     |
| Reproducible           | a pinned result re-executes from its inputs; the hashes compare   |
|                        |                                                                   |
| **USE**                | ML experiment tracking                                            |
| Queryable              | runs, models and metrics are values, queried by their predicates  |
| Retroactive            | today's code runs over any past revision, or a sweep of them      |
| Shared                 | one Postgres ledger serves every machine; a folder serves one     |

It heads the [README](../../README.md) and the [front page](../index.md). A change to it is made here first, then copied to both.

## What each part means

| Phrase | What it stands for | Where in the code |
| --- | --- | --- |
| Datomic for Python | the model: facts that are never overwritten, each true from one revision on, readable at any past revision; values addressed by content, like Datomic's database of immutable facts | `dvc_dat/ledger/rev.py` (a revision and its reads), `dvc_dat/ledger/store.py` |
| a functional DB | a stored result is a function of its code and inputs: the same call at the same commit over the same values is a hit, not a second run | `dvc_dat/ledger/fn.py`, `dvc_dat/ledger/trace.py` |
| Git-versioned … reproducible provenance | each sealed value names the function that made it, the commit of the code it ran at, and the values it read; the commit is tagged and pushed so it stays reachable, so the value can be rerun from its inputs at its own commit | `dvc_dat/ledger/code.py`, `dvc_dat/ledger/pin.py`, `dvc_dat/ledger/trace.py` |
| sandboxed Python execution | a function runs in a fresh process forked for the one call, loaded from a checkout of the mounted tree; nothing it loads or changes outlives the call. The code it runs is named by a mount: a module path in a git repository, resolved at the revision's commit | `dvc_dat/ledger/sandbox.py`, `dvc_dat/ledger/fn.py`, `dvc_dat/ledger/namespace.py` |
| Content-addressed blob store | bytes held once by hash and shared by every value that holds them | `dvc_dat/ledger/value.py` |
| serialized objects and folder trees | what it records: any Python value sealed by a codec, and a dat (a folder whose spec is a complete recipe for itself) | `dvc_dat/dat.py`, `dvc_dat/ledger/value.py` |
| Triples-based | every object is a set of facts (subject, predicate, object), each added at a revision and never edited, so any object reads as it was at any revision | `dvc_dat/ledger/rev.py`, `dvc_dat/ledger/txn.py` |
| append-only | a write adds rows under a new revision; a retraction is a row saying a fact stopped being true; no row is edited | `dvc_dat/ledger/txn.py` |
| Postgres-backed (not in the overview) | the ledger's facts live in one quad table in Postgres, shared by every machine; a local folder serves the same interface on one machine | `dvc_dat/ledger/pgstore.py`, `dvc_dat/ledger/backends.py` |
| ML experiment tracking | the use it was built for: runs, their inputs, their metrics, and every derived result kept, compared and rerun | the [tutorials](../tutorials.md) |

## Other phrasings considered

- "Data artifact management with metadata and provenance for ML experimentation" (the README's earlier line): accurate, but names no mechanism and could describe many tools.
- Leading with "ML experiment tracking" first: places it beside experiment trackers, which record runs but do not rerun them; the Datomic comparison says what is different first.
- "Datomic for Python — an append-only artifact ledger for ML experiment tracking.", with the second line "Objects are versioned as triples, and every artifact carries its provenance: the sandboxed, git-tracked Python module that built it, the commit it ran at, and the inputs it read, so it can be rebuilt." It named what the provenance holds (module, commit, inputs) and why it matters (rebuilding); the overview keeps both and adds the storage.
- "Provides triples-based versioned objects and artifact provenance built from sandboxed, git-tracked Python modules." (a draft before it): "provenance built from" left implicit what the provenance holds. "Postgres-backed" left the line too: it is a backend, not the idea.
