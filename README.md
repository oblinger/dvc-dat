# dat
Data and code encapsulation for ML experimentation and productization.
- This package is designed to operate seemlessly with DVC and ML-FLOW based objects.
- It provides a dotted tree-style namespace for dynamically loaded Python code and Data.
- All data and functions are self-describing using JSON / YAML "manifest" files.
- Support for extensible project APIs are provided as well as recursive dict accessors based on declared metadata.


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

