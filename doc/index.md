:>> [DAT](DAT.md) → [index](index.md) 
# DVC-DAT
The front page of the DVC-DAT docs: what it is, the documentation sections, and a first look at the ledger.

**Datomic for Python — an append-only artifact ledger for ML experiment tracking.**

Objects are versioned as triples, and every artifact carries its provenance: the sandboxed, git-tracked Python module that built it, the commit it ran at, and the inputs it read, so it can be rebuilt.

## Documentation sections

| Section | What it holds |
| --- | --- |
| **[Architecture](DAT%20Architecture.md)** | the dat and the ledger, how they meet, and what each piece is |
| **[Tutorials](tutorials.md)** | ten notebooks, run end to end with their outputs kept |
| **[How-to](how-to.md)** | one task per row, for a reader who knows the library |
| **[API reference](api/index.md)** | every public class and function, generated from the source |
| **[Code](https://github.com/oblinger/dvc-dat)** | the repository |

## A first look

A **ledger** keeps facts that are never overwritten, each true from one revision
on. Code joins it by a mount: a folder of a git repository, whose functions run
sandboxed. A call through the ledger is traced, sealed and remembered. What a
call builds is often a **dat**: a folder holding its files, the spec that is a
complete recipe for it, and its result.

```python
from dvc_dat.ledger import Ledger

L = Ledger("experiments", create=True)

# Mount a folder of a git repository; its functions run sandboxed.
with L.transaction(by="human:me") as t:
    t.ns.mount("mnt.exp", root="exp", repo="my-experiments")

# A call through the ledger is traced and sealed.
model = L.at().run("mnt.exp.train.fit", lr=1e-3, epochs=10)

# The same call again is answered from the ledger: nothing runs.
again = L.at().run("mnt.exp.train.fit", lr=1e-3, epochs=10)
assert again.subject == model.subject

# Pin the commit it ran at, so it can be re-executed;
# then rebuild it from its inputs and compare.
L.at().pin(model)
print(L.at().rerun(model).outcome)   # 'reproduced'

past = L.at(3)   # the ledger as it was at revision 3

# An artifact can be a dat: a folder the ledger stores.
print(*sorted(p.name for p in model.path.iterdir()))
```

```text
_result_.yaml _spec_.yaml metrics.json weights.pt
```

To install and run it on your own machine: [Installation](https://github.com/oblinger/dvc-dat#installation).
