# DVC-DAT

Data artifact management with metadata and provenance tracking for ML experimentation.

## Overview

dvc_dat provides two integrated systems:

- **Do-System**: A namespace for loading Python objects by dotted name (e.g., `catalog.experiment`). Configure via `.dataconfig.yaml` mount commands.

- **DAT Storage**: Persistent data folders where each folder contains a `_spec_.yaml` file with metadata. Load and create DATs by path (e.g., `runs/experiment1`).

```python
from dvc_dat import Dat, do

# Load a template from the do-system
template = do.load("catalog.experiment")

# Create a DAT with that template
dat = Dat.create(spec="catalog.experiment", path="runs/exp1")

# Load an existing DAT
dat = Dat.load("runs/exp1")
```

See the [full documentation](docs/index.md) for details.

## Installation

```bash
pip install -e .
```

## Usage

```bash
cd tests; ./do hello_world
```

## Testing

```bash
python -m pytest
```

## Development

```bash
python -m black src
```

## Example Usage

A couple of included Python notebooks provide a quick overview of the capabilities provided by the DVC-DAT module:

- [Usage of dynamic function loading](https://github.com/oblinger/dvc-dat/blob/main/examples/do_examples.ipynb)
- [Usage of dynamic object loading](https://github.com/oblinger/dvc-dat/blob/main/examples/dat_examples.ipynb)

