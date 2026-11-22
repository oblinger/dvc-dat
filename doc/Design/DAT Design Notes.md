---
description: "The main design choices behind dvc-dat, and the reason for each."
---
:>> 
# DAT Design Notes
The main design choices behind dvc-dat, and the reason for each.

| Choice | Why |
| --- | --- |
| **A dat is a self-describing folder** | A folder holding its own recipe (`_spec_.yaml`) and its result (`_result_.yaml`) can be copied, inspected and re-run with ordinary tools, and it never depends on a database being up to say what it is or how it was made. |
| **An append-only ledger of triples** | Every fact is a (subject, predicate, object) row written under a new revision and never overwritten. Small, uniform rows make any structure, however large or often changed, cheap to update incrementally, and keeping every revision means history is never lost: ending a fact is itself a fact, recorded with when and why. |
| **Revisions are point-in-time views** | A read names a revision, and a revision never changes. A result computed against it stays explainable later, and two readers at the same revision always see the same thing. |
| **Content-addressed, write-once bytes** | A value's bytes are stored once under their sha256. Identical bytes are shared by every value that holds them, a copy between stores is checked by its hash alone, and nothing that has been written can change under a reader. Bytes are fetched lazily, so a machine holds only what it reads. |
| **Git-versioned, sandboxed functions** | A function is loaded from a mounted git repository at a known commit and run in a fresh process that sees only the mounted code. What produced a result is then a commit, not whatever happened to be imported in the caller's process. |
| **Recorded dependencies** | Each result records its function, its commit, its arguments and every value it read. The record is the provenance: it answers where a value came from, and it decides what a change makes stale. |
| **Memoised calls** | A call whose function, code and inputs match a recorded result is a hit and returns that result; only a change recomputes, and only its dependents. Re-running a whole experiment costs what changed, not what exists. |
| **One namespace** | Dats, ledger values, functions and mounted code are all reached by one dotted name (`do.load("catalog.experiment")`), configured once by `.datconfig.yaml`. Code says what it needs by name and never by where it is stored. |

How the parts fit together is on [DVC-DAT Architecture](../DAT%20Architecture.md); what each part means in one line is on [DAT Summary](DAT%20Summary.md).
