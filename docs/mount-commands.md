# Mounts

A dotted name is a Python name: `do.load` imports the longest importable
prefix and `getattr`s the rest, so `os.path.join` and `mypkg.models.Trainer`
work with nothing mounted at all. A **mount** is for the names that are *not*
imports — a folder of YAML templates, a file outside the import path, a
literal value — and for giving an importable thing a shorter name.

Mounts are made in code, by `do.mount(...)`, by your own program — the
namespace is whatever the running program imported. For the shell, your
program's main does the mounting and hands the command line to `dat.cli_main()`,
and `.dataconfig.yaml` names that main as `run:`:

```yaml
# .dataconfig.yaml
dat_folders: data
run: .venv/bin/python -m mypkg.main
```

```python
# mypkg/main.py
import os
import sys
from pathlib import Path
import dvc_dat as dat

ROOT = Path(__file__).parent.parent

dat.do.mount(folder=str(ROOT / "catalog"), at="catalog")
dat.do.mount(module="tests.fixtures", at="fixtures")

if __name__ == "__main__":
    if os.environ.get("DAT_CLI"):      # launched by the dat bootstrap
        sys.exit(dat.cli_main())
```

The mounts land on the one `do` object the process holds, so a
`from dvc_dat import do` that ran earlier sees them. A notebook gets the same
namespace by importing `mypkg.main`; the config's folder is first on
`sys.path`, so that import works from any directory. With no `run:` the
bootstrap runs the library's own main, and a dotted name is a Python name and
nothing else.

## Mount forms

`do.mount(*, folder | file | module | value, at="", relative_to=".")` —
exactly one source. `at` is the name it answers to; omitted, the mount lands
at the namespace root. A relative `folder` or `file` resolves against
`relative_to`, which defaults to the working directory — build paths from
`__file__` instead, as above, so they mean the same thing from anywhere.

### folder

Mount a directory tree. Files become dotted paths.

```python
do.mount(folder=str(ROOT / "catalog"), at="catalog")
```

Given:

```
catalog/
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

```python
do.mount(module="tests.fixtures", at="fixtures")
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

A module mounted by import name resolves through `sys.modules`, so it is the
same module object the rest of the program holds: this form is an alias, and
costs nothing. A module mounted by file path is loaded outside the import
system and can never be the one your program imported.

**Use for:** a short name over a long import path.

### file

Mount a single file at a name. `at` is required — without it the entry is
registered under the empty name and cannot be reached.

```python
do.mount(file=str(ROOT / "scripts" / "helper.py"), at="helper")
```

- `helper` → loads `scripts/helper.py`

YAML and JSON files load as data; Python files load as a module.

**Use for:** standalone scripts, individual config files.

### value

Mount a literal value.

```python
do.mount(value={"pi": 3.14159, "e": 2.71828}, at="constants")
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

```python
do.add_do_folder(str(ROOT / "scripts"))
```

Mounts every loadable under `scripts/` by **file name**, ignoring its
subdirectory, and makes that folder the fallback the resolver walks when a
name matches nothing else. Two files with the same base name in different
subfolders collide, and loading either one is an error.

**Use for:** a flat command folder where the file name is the command name.

## Choosing a form

| Your need | Form |
|-----------|------|
| Directory of YAML/JSON templates | `folder` |
| A short name for a Python module | `module` |
| Single standalone script | `file` |
| Inline constants or an inline spec | `value` |
| A flat folder of commands | `add_do_folder` |
| An importable object | *nothing — `do.load` imports it* |

A mounted name shadows the static resolution, so an alias that collides with
an installed package wins — which is the one way a mount can make a Python
name mean something else.

## Complete example

```yaml
# .dataconfig.yaml
dat_folders: data
run: .venv/bin/python -m myproject.main
```

```python
# src/myproject/main.py
import os
import sys
from pathlib import Path
import dvc_dat as dat

SRC = Path(__file__).parent.parent

dat.do.mount(folder=str(SRC / "myproject" / "catalog"), at="catalog")
dat.do.mount(module="tests.fixtures", at="fixtures")
dat.do.mount(folder=str(SRC / "scripts"), at="scripts")
dat.do.mount(value={"debug": False, "version": "2.0.0"}, at="config")

if __name__ == "__main__":
    if os.environ.get("DAT_CLI"):      # launched by the dat bootstrap
        sys.exit(dat.cli_main())
```

Usage, from a program that has imported `myproject.main`:

```python
from dvc_dat import do

# Load a template; the config installs itself on first use
spec = do.load("catalog.experiment")

# Get a fixture
fixture = do.load("fixtures.simple")

# Fork a script's spec and run it
do("scripts.process", input="data.csv")

# Access a constant
version = do.load("config.version")
```

## See Also

- [Core Concepts](concepts.md) — how `run:` and the import root fit in
- [Spec Format](spec-format.md) — what templates contain
