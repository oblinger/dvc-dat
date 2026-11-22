# DVC-DAT

**Datomic for Python — an append-only artifact ledger for ML experiment tracking.**

Objects are versioned as triples, and every artifact carries its provenance: the sandboxed, git-tracked Python module that built it, the commit it ran at, and the inputs it read, so it can be rebuilt.

**[Architecture](https://oblinger.github.io/dvc-dat/DAT%20Architecture/)** · **[Tutorials](https://oblinger.github.io/dvc-dat/tutorials/)** · **[Documentation](https://oblinger.github.io/dvc-dat/)** · **[API reference](https://oblinger.github.io/dvc-dat/api/)** · **[Code](https://github.com/oblinger/dvc-dat)**

| See it work | In one notebook |
| --- | --- |
| [The ledger: triples](https://oblinger.github.io/dvc-dat/DAT%20Demos/ledger-triples/) | facts with revisions, read as they were at any point in time |
| [Rerunning](https://oblinger.github.io/dvc-dat/DAT%20Demos/demo-rerunning/) | today's code over past revisions, and a value rebuilt at its own commit |
| [API walkthrough](https://oblinger.github.io/dvc-dat/DAT%20Demos/api-walkthrough/) | dats, the namespace, values and the ledger on one sheet |
| [A project end to end](https://oblinger.github.io/dvc-dat/DAT%20Demos/demo-walkthrough/) | a small project set up, run, forked and reloaded |

## Overview

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

See the [full documentation](doc/index.md) for details.

## Installation

```bash
pip install -e .
```

The base install needs pyyaml alone; it stores a spec as given and expands `${unique:}`, and nothing else.

| Extra | Adds |
| --- | --- |
| `expand` | omegaconf: the whole `${…}` grammar in a spec (`${batch}`, `${ns:a.b}`, `${now:%Y}`; doc/expand.md) |
| `hydra` | hydra-core (brings `expand`): Hydra's override grammar on the command line (`+k=v`, `~k`, `a,b`, `-m`) |
| `tools` | pandas: the tables (`dt.from_dat`, `Cube`) |
| `excel` | xlsxwriter (brings `tools`): Excel reports |

`pip install -e ".[hydra]"` is the full DAT.

## Usage

```bash
# Dat.manager.run("catalog.experiment", epochs=200)
just run catalog.experiment epochs=200
# the same: bin/x is `exec just run "$@"`
x catalog.experiment epochs=200
# print the Dat.manager.run(...) call instead of making it,
# then the resolved spec
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
  See [The ledger](doc/api/ledger.md).
