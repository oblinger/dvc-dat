# DVC-DAT

Data artifact management with metadata and provenance for ML experimentation.

## Overview

A **dat** is a folder whose `_spec_.yaml` is a complete, argumentless recipe for
itself; `_result_.yaml` holds only what running it produced. `do` is the one
namespace and the one runner.

```python
from dvc_dat import Dat

do = Dat.do   # the shortcut; follows Dat.manager

# Importing reads no files; the first use finds .datconfig.yaml.
# A dotted name resolves through do.mount names, then by import.
template = do.load("catalog.experiment")

# Arguments fork a spec: they are written into the new dat's
# _spec_.yaml, and the run reads them back from there.
result = do("catalog.experiment", epochs=200)

# Create and open dats directly.
dat = Dat.create(spec="catalog.experiment", path="runs/exp1")
dat = Dat.load("runs/exp1")
```

Arguments never ride beside a spec at the call site. `do(dat, x=1)` forks a
new dat and leaves the original untouched; `do(dat)` re-runs a dat that is not
yet sealed. A run saves nothing by itself: `dat.save()` inside it seals the
dat when the run returns, stamping its `dat.standing`; `dat.standing: rolling`
in a spec declares one that is saved at will. Nothing about the arguments is recorded in `_result_.yaml` — the
spec is the record.

See the [full documentation](doc/index.md) for details.

## Installation

```bash
pip install -e .
```

Excel reports need the optional extra: `pip install -e ".[excel]"`.

## Usage

```bash
# do("catalog.experiment", epochs=200)
just run catalog.experiment epochs=200
# the same: bin/x is `exec just run "$@"`
x catalog.experiment epochs=200
# print that do(...) call instead of making it
x catalog.experiment epochs=200 --dry-run
just mounts catalog
x --info
```

`just run` is the one way to run: the `run` recipe of `dvc_dat.just`, which
a project's justfile imports. It configures itself from the nearest
`.datconfig.yaml` and runs your project's `run:` main from any directory
with no environment activated. See [the CLI reference](doc/cli.md).

## Testing

```bash
uv run python -m pytest
```

## Demos

Runnable notebooks in [`doc/DAT Demos/`](https://github.com/oblinger/dvc-dat/tree/main/doc/DAT%20Demos), each paired
with a `py:percent` script (jupytext) and executed with its outputs kept; `just demo` re-syncs and re-runs them:

- [`demo-walkthrough`](https://github.com/oblinger/dvc-dat/blob/main/doc/DAT%20Demos/demo-walkthrough.ipynb) — a small project end to end: a mounted
  folder of YAML templates, a `dat.base` chain, `do()` and a keyword fork, loading a dat, the
  `merge_dicts` recipe, and the command-line main.
- [`demo-dats`](https://github.com/oblinger/dvc-dat/blob/main/doc/DAT%20Demos/demo-dats.ipynb) — dats, dependencies and versions: seal, hash, `dat.dependencies` two deep.
- [`demo-etl`](https://github.com/oblinger/dvc-dat/blob/main/doc/DAT%20Demos/demo-etl.ipynb) — an ETL chain over a game set (a binning per game, a cumulative binning built recursively, a podium) and what each change recomputes.
- The ledger's four notebooks, `doc/DAT Demos/ledger-*.py` (run by `tests/ledger/test_notebooks.py`):
  [`ledger-triples`](doc/DAT%20Demos/ledger-triples.ipynb), [`ledger-values`](doc/DAT%20Demos/ledger-values.ipynb),
  [`ledger-dats`](doc/DAT%20Demos/ledger-dats.ipynb), [`ledger-just`](doc/DAT%20Demos/ledger-just.ipynb).
  See [The ledger](doc/DAT%20Modules/ledger/DAT%20Ledger.md).
