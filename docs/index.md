# dvc_dat Documentation

**dvc_dat** manages data artifacts as folders that describe themselves. A dat
is a folder whose `_spec_.yaml` is a complete, argumentless recipe for itself;
`_result_.yaml` holds only what running it produced.

## Quick Start

```python
from dvc_dat import Dat, do

# Importing reads nothing; the first use below finds the nearest
# .dataconfig.yaml, walking up from the working directory.

# Create a dat with its own metadata
dat = Dat.create(
    path="experiments/exp1",
    spec={"dat": {"kind": "Dat"}, "params": {"lr": 0.01}},
)

# Open it later
dat = Dat.load("experiments/exp1")
print(dat.get_spec()["params"]["lr"])   # 0.01

# Fork a template and run the fork: the arguments go into the new
# dat's spec, and the run reads them back from there.
result = do("catalog.experiment", epochs=200)
```

## Core Concepts

- **[Concepts](concepts.md)** — the fork rule, the two kinds of name,
  configuration on first use, `dat.base`, the `{}` grammar, validation
- **[Spec Format](spec-format.md)** — `_spec_.yaml` / `_result_.yaml` reference
- **[Mounts](mount-commands.md)** — giving a name to something that is not an import
- **[Command Line](cli.md)** — the `dat` verbs, the bootstrap copy, exit codes

## API Reference

- **[Overview](overview.md)** — what `dvc_dat` exports, and every method

## Examples

- **[`examples/walkthrough.ipynb`](../examples/walkthrough.ipynb)** — one
  project, end to end: mounts, `dat.base`, `do()` and a fork, `Dat.load`,
  `merge_dicts`, the command-line main
