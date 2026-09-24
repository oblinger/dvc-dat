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

See the [full documentation](docs/index.md) for details.

## Installation

```bash
pip install -e .
```

Excel reports need the optional extra: `pip install -e ".[excel]"`.

## Usage

```bash
# do("catalog.experiment", epochs=200)
dat catalog.experiment epochs=200
# print that do(...) call instead of making it
dat catalog.experiment epochs=200 --dry-run
dat --list catalog
dat --info
```

`dat` configures itself from the nearest `.datconfig.yaml`. A copy of
`bin/dat` on your `PATH` runs your project's `run:` main from any directory
with no environment activated. The environment's `dat` console script does
not read `run:`: it runs the library's own command line, with no project
mounts. See [the CLI reference](docs/cli.md).

## Testing

```bash
uv run python -m pytest
```

## Example

[`examples/walkthrough.ipynb`](https://github.com/oblinger/dvc-dat/blob/main/examples/walkthrough.ipynb)
builds a small project in a temp folder and runs it end to end: a mounted
folder of YAML templates, a `dat.base` chain, `do()` and a keyword fork,
loading a dat, the `merge_dicts` recipe, and the command-line main.
