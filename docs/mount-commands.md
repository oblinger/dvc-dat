# Mount Commands

`mount_commands` in `.dataconfig.yaml` build the do-system namespace: what a
dotted name like `catalog.experiment` resolves to. `do.configure(...)` applies
them — onto the `do` object the process already holds, so a `from dvc_dat import
do` that ran earlier sees them.

A dotted name that matches no mount is still resolved: `do.load` imports the
longest importable prefix of the name and `getattr`s the rest, so
`os.path.join` and `mypkg.models.Trainer` work with nothing mounted at all.
Mounting is for the names that are *not* importable — YAML and JSON templates,
files outside the import path, literal values — and for giving an importable
thing a shorter name.

## Configuration Location

```yaml
# .dataconfig.yaml
local_prefix: data
mount_commands:
  - at: catalog
    folder: src/catalog
  - at: fixtures
    module: tests.fixtures
```

Paths are relative to the folder holding the config file.

## Mount Types

### folder

Mount a directory tree. Files become dotted paths.

```yaml
- at: catalog
  folder: src/catalog
```

Given:

```
src/catalog/
  experiment.yaml
  models/
    baseline.yaml
```

You get:

- `catalog.experiment` → loads `experiment.yaml`
- `catalog.models.baseline` → loads `models/baseline.yaml`

**Supported files:** `.yaml`, `.json`, `.py`

**Use for:** template directories, configuration trees, organized specs.

### module

Mount a Python module — by import name, by file path, or the module object
itself. Its attributes become names.

```yaml
- at: fixtures
  module: tests.fixtures
```

Given:

```python
# tests/fixtures/__init__.py
simple = {"name": "simple", "value": 42}
complex_data = {"items": [1, 2, 3]}
```

You get:

- `fixtures.simple` → `{"name": "simple", "value": 42}`
- `fixtures.complex_data` → `{"items": [1, 2, 3]}`

A module mounted with no attribute named resolves to its `__main__`.

**Use for:** a short name over a long import path; modules loaded from a file
path rather than the import system.

### file

Mount a single file at a name. `at:` is required — without it the entry is
registered under the empty name and cannot be reached.

```yaml
- at: helper
  file: scripts/helper.py
```

- `helper` → loads `scripts/helper.py`

YAML and JSON files load as data; Python files load as a module.

**Use for:** standalone scripts, individual config files.

### value

Mount a literal value.

```yaml
- at: constants
  value:
    pi: 3.14159
    e: 2.71828
```

You get:

- `constants.pi` → `3.14159`
- `constants.e` → `2.71828`

A string value that begins with `yaml` is parsed as YAML, which is how a spec
can be written inline in a `.py` file:

```python
__main__ = """yaml
dat:
  do: configurable_salutation
name: YAML Greeter
"""
```

**Use for:** constants, inline specs.

### add_do_folder

```yaml
- add_do_folder: scripts
```

Mounts every loadable under `scripts/` by **file name**, ignoring its
subdirectory, and makes that folder the fallback the resolver walks when a name
matches nothing else. Two files with the same base name in different
subfolders collide, and loading either one is an error.

**Use for:** a flat command folder where the file name is the command name.

## The `at:` Prefix

`at:` is the namespace prefix a mount lands under.

```yaml
- at: myprefix
  folder: some/path
```

Without `at:`, a `folder:` mount lands at the root namespace — its files are
reachable by their own relative paths.

## Choosing a Mount Type

| Your Need | Mount Type |
|-----------|------------|
| Directory of YAML/JSON templates | `folder` |
| A short name for a Python module | `module` |
| Single standalone script | `file` |
| Inline constants or an inline spec | `value` |
| A flat folder of commands | `add_do_folder` |
| An importable object | *nothing — `do.load` imports it* |

## Complete Example

```yaml
# .dataconfig.yaml
local_prefix: data

mount_commands:
  # Project templates
  - at: catalog
    folder: src/myproject/catalog

  # Test fixtures (Python module)
  - at: fixtures
    module: tests.fixtures

  # Utility scripts
  - at: scripts
    folder: src/scripts

  # Global constants
  - at: config
    value:
      debug: false
      version: "2.0.0"
```

Usage:

```python
from dvc_dat import do

do.configure()

# Load a template
spec = do.load("catalog.experiment")

# Get a fixture
fixture = do.load("fixtures.simple")

# Fork a script's spec and run it
do("scripts.process", input="data.csv")

# Access a constant
version = do.load("config.version")
```

## See Also

- [Core Concepts](concepts.md) — how mount commands fit in
- [Spec Format](spec-format.md) — what templates contain
