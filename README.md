# DVC-DAT

Data artifact management with metadata and provenance for ML experimentation.

## Overview

A **dat** is a folder whose `_spec_.yaml` is a complete, argumentless recipe for
itself; `_result_.yaml` holds only what running it produced. `ns` is the one
namespace; `Dat.manager.run` is the one run.

```python
from dvc_dat import Dat

ns = Dat.ns   # the namespace; follows Dat.manager

# Importing reads no files; the first use finds .datconfig.yaml.
# A dotted name resolves through ns.mount names, then by import.
template = ns.load("catalog.experiment")

# Arguments fork a spec: they are written into the new dat's
# _spec_.yaml, and the run reads them back from there.
result = Dat.manager.run("catalog.experiment", epochs=200)

# Create a dat without running it, and open one.
dat = Dat.create("catalog.experiment", path="runs/exp1",
                 epochs=10)
dat = Dat.load("runs/exp1")
```

`Dat.manager.run(spec, **kw)` creates a dat and runs it; `Dat.create(spec, **kw)`
creates one and runs nothing; `dat.run` is the record a run leaves. Both take
keywords: they are merged into `dat.kwargs` and are the variables that fill `{…}`
in `dat.name`, `dat.preds` and the rest of the spec, over the spec's
`dat.defaults`. `dat.preds` are preds the dat carries onto the value it seals as.
A dat is run once, by the call that makes it; its recipe runs again as a new dat
with `Dat.manager.run(dat.get_spec(), x=1)`. A run saves nothing by itself: `dat.save()` inside it seals the
dat when the run returns, stamping its `dat.standing`; `dat.standing: rolling`
in a spec declares one that is saved at will. Nothing about the arguments is recorded in `_result_.yaml` — the
spec is the record.

See the [full documentation](doc/index.md) for details.

## Installation

```bash
pip install -e .
```

The base install needs pyyaml alone. The tables (`dt.from_dat`, `Cube`) need `pip install -e ".[tools]"` (pandas), Excel reports `".[excel]"`.

## Usage

```bash
# Dat.manager.run("catalog.experiment", epochs=200)
just run catalog.experiment epochs=200
# the same: bin/x is `exec just run "$@"`
x catalog.experiment epochs=200
# print that Dat.manager.run(...) call instead of making it
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

The Postgres cases (the `pg` half of the ledger suite, `tests/load/test_inproc.py`,
the load floor) run only when `DVC_DAT_TEST_PG` names a server; unset, they skip
and say how to enable them. There is no default address. They create and drop
databases and schemas on that server, so give them a disposable one:

```bash
docker run -d -p 5432:5432 \
  -e POSTGRES_HOST_AUTH_METHOD=trust postgres:16
export DVC_DAT_TEST_PG=postgresql://postgres@localhost:5432/postgres
uv run python -m pytest
```

Set and unreachable, they fail rather than skip. An address on port 5433 (in the
URL, a `port=` parameter, or `PGPORT` for a host that names none) stops the run
before collection: on the development laptop 5433 is the Cloud SQL proxy to the
production ledger. `DVC_DAT_TEST_PG_ALLOW_5433=1` lifts that for a disposable
server that really is on 5433. CI's `postgres` job sets the variable to its
Postgres 16 service. The rule lives in `tests/pg_server.py`.

## Demos

Runnable notebooks in [`doc/DAT Demos/`](https://github.com/oblinger/dvc-dat/tree/main/doc/DAT%20Demos), each paired
with a `py:percent` script (jupytext) and executed with its outputs kept; `just demo` regenerates and re-runs them:

- [`demo-walkthrough`](https://github.com/oblinger/dvc-dat/blob/main/doc/DAT%20Demos/demo-walkthrough.ipynb) — a small project end to end: a mounted
  folder of YAML templates, a `dat.base` chain, `Dat.manager.run()` and a keyword fork, loading a dat, the
  `merge_dicts` recipe, and the command-line main.
- [`demo-dats`](https://github.com/oblinger/dvc-dat/blob/main/doc/DAT%20Demos/demo-dats.ipynb) — dats, dependencies and versions: seal, hash, `dat.dependencies` two deep.
- [`demo-etl`](https://github.com/oblinger/dvc-dat/blob/main/doc/DAT%20Demos/demo-etl.ipynb) — an ETL chain over a game set (a binning per game, a cumulative binning built recursively, a podium) and what each change recomputes.
- The ledger's four notebooks, `doc/DAT Demos/ledger-*.py` (run by `tests/ledger/test_notebooks.py`):
  [`ledger-triples`](doc/DAT%20Demos/ledger-triples.ipynb), [`ledger-values`](doc/DAT%20Demos/ledger-values.ipynb),
  [`ledger-dats`](doc/DAT%20Demos/ledger-dats.ipynb), [`ledger-just`](doc/DAT%20Demos/ledger-just.ipynb).
  See [The ledger](doc/DAT%20Modules/ledger/DAT%20Ledger.md).
