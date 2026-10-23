:>> [DAT](DAT.md) → [DAT index](ha://p/DAT%20index) 
# dvc_dat Documentation
The front page of the dvc_dat docs: what the package does, and where to read next.

**dvc_dat** manages data artifacts as folders that describe themselves. A dat
is a folder whose `_spec_.yaml` is a complete, argumentless recipe for itself;
`_result_.yaml` holds what running it produced, written once when `dat.save()` seals it.

## Quick Start

```python
from dvc_dat import Dat

do = Dat.do   # the shortcut; follows Dat.manager

# Importing reads nothing; the first use below finds the nearest
# .datconfig.yaml, walking up from the working directory.

# Create a dat with its own metadata
dat = Dat.create(
    path="experiments/exp1",
    spec={"params": {"lr": 0.01}},
)

# Open it later
dat = Dat.load("experiments/exp1")
print(dat.get_spec()["params"]["lr"])   # 0.01

# Fork a template and run the fork: the arguments go into the new
# dat's spec, and the run reads them back from there.
result = do("catalog.experiment", epochs=200)
```

## Core Concepts

- **[Architecture](DAT%20Architecture.md)** — the dat and the ledger, and
  how they meet; a module doc for each:
  [DAT Dat](DAT%20Modules/DAT%20Dat.md),
  [DAT Ledger](DAT%20Modules/ledger/DAT%20Ledger.md) 
- **[Concepts](concepts.md)** — the fork rule, the two kinds of name,
  configuration on first use, `dat.base`, the `{}` grammar, validation
- **[Spec Format](spec-format.md)** — `_spec_.yaml` / `_result_.yaml` reference
- **[Mounts](mount-commands.md)** — giving a name to something that is not an import
- **[Command Line](cli.md)** — `just run` (`x`), `dvc_dat.just`, exit codes

## API Reference

- **[Overview](overview.md)** — what `dvc_dat` exports, and every method

## Demos

Notebooks in [`DAT Demos/`](https://github.com/oblinger/dvc-dat/tree/main/doc/DAT%20Demos), each paired with a `py:percent` script and executed with its
outputs kept (`just demo` re-syncs and re-runs them; the tests run every one):

- **[`demo-walkthrough`](DAT%20Demos/demo-walkthrough.ipynb)** — one project, end to end: mounts,
  `dat.base`, `do()` and a fork, `Dat.load`, `merge_dicts`, the command-line main
- **[`demo-dats`](DAT%20Demos/demo-dats.ipynb)** — dats, dependencies and versions
- **[`demo-etl`](DAT%20Demos/demo-etl.ipynb)** — an ETL chain over a game set, and what each change to it recomputes
- **[`ledger-triples`](DAT%20Demos/ledger-triples.ipynb)** — the ledger as a quad store: transactions, reads as of a revision
- **[`ledger-values`](DAT%20Demos/ledger-values.ipynb)** — values, preds, ledger functions, `run`, the sandbox
- **[`ledger-dats`](DAT%20Demos/ledger-dats.ipynb)** — a dat as a value
- **[`ledger-just`](DAT%20Demos/ledger-just.ipynb)** — the human's verbs, one ledger call per recipe

The ledger: [The ledger](DAT%20Modules/ledger/DAT%20Ledger.md).
