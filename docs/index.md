# dvc_dat Documentation

**dvc_dat** is a lightweight framework for managing data artifacts with metadata and provenance tracking.

## Quick Start

```python
from dvc_dat import Dat, do

# Create a DAT with metadata
dat = Dat.create(
    path="experiments/exp1",
    spec={"name": "experiment 1", "params": {"lr": 0.01}}
)

# Load it later
dat = Dat.load("experiments/exp1")
print(dat.get_spec()["params"]["lr"])  # 0.01

# Load templates from mounted sources
template = do.load("catalog.experiment")
```

## Core Concepts

- **[Concepts](concepts.md)** - The two namespaces (do-system vs DAT paths) and how they work together
- **[Spec Format](spec-format.md)** - `_spec_.yaml` file format reference
- **[Mount Commands](mount-commands.md)** - Configuring the do-system namespace

## API Reference

- **[Overview](overview.md)** - API tables for Dat, DoManager, and dat_tools

## Examples

- **[Jupyter Notebooks](../examples/)** - Interactive examples
  - `do_examples.ipynb` - Do-system usage
  - `dat_examples.ipynb` - DAT creation and loading
  - `dat_tools_examples.ipynb` - Data tools and utilities
