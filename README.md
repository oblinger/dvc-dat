# DVC-DAT

Data artifact management with metadata and provenance for ML experimentation.

## Overview

A **dat** is a folder whose `_spec_.yaml` is a complete, argumentless recipe for
itself; `_result_.yaml` holds only what running it produced. `do` is the one
namespace and the one runner.

```python
from dvc_dat import Dat, do, load

# Importing reads no files; the first use finds .dataconfig.yaml.
# A dotted name resolves through the mount table, then by import.
template = do.load("catalog.experiment")

# Arguments fork a spec: they are written into the new dat's
# _spec_.yaml, and the run reads them back from there.
result = do("catalog.experiment", epochs=200)

# Create and open dats directly.
dat = Dat.create(spec="catalog.experiment", path="runs/exp1")
dat = load("runs/exp1")
```

Arguments never ride beside a spec at the call site. `do(dat)` re-runs a dat on
disk exactly as it is; `do(dat, x=1)` forks a new dat and leaves the original
untouched. Nothing about the arguments is recorded in `_result_.yaml` — the
spec is the record.

See the [full documentation](docs/index.md) for details.

## Installation

```bash
pip install -e .
```

Excel reports need the optional extra: `pip install -e ".[excel]"`.

## Usage

```bash
dat do hello_world
dat hello_again.salutation Maxim lucky_number=7
dat list
dat info
```

`dat` configures itself from the nearest `.dataconfig.yaml`. A copy of
`bin/dat` on your `PATH` is the same command from any directory with no
environment activated. See [the CLI reference](docs/cli.md).

## Testing

```bash
uv run python -m pytest
```

## Example Usage

A couple of included Python notebooks give a quick overview of what the
DVC-DAT module provides:

- [Dynamic function loading](https://github.com/oblinger/dvc-dat/blob/main/examples/do_examples.ipynb)
- [Dynamic object loading](https://github.com/oblinger/dvc-dat/blob/main/examples/dat_examples.ipynb)
