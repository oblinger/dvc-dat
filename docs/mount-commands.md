# Mount Commands

Mount commands in `.dataconfig.yaml` define the do-system namespace—what dotted names like `catalog.experiment` resolve to.

## Configuration Location

```yaml
# .dataconfig.yaml
sync_folder: data
mount_commands:
  - at: catalog
    folder: src/catalog
  - at: fixtures
    module: tests.fixtures
```

## Mount Types

### folder

Mount a directory tree. Files become accessible by dotted path.

```yaml
- at: catalog
  folder: src/catalog
```

Given this structure:
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

**Use for:** Template directories, configuration trees, organized specs.

### module

Mount an already-imported Python module. Module attributes become accessible.

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

**Important:** The module must be imported before use. Typically done in your package's `__init__.py`:
```python
from tests import fixtures  # noqa: F401
```

**Use for:** Test fixtures, Python-defined configurations, dynamic data.

### file

Mount a single file.

```yaml
- file: scripts/helper.py
```

The file's basename (without extension) becomes the name:
- `helper` → loads `scripts/helper.py`

For YAML/JSON files, the content is loaded as a dict.
For Python files, the module is loaded.

**Use for:** Standalone scripts, individual config files.

### value

Mount a literal value directly.

```yaml
- at: constants
  value:
    pi: 3.14159
    e: 2.71828
```

You get:
- `constants.pi` → `3.14159`
- `constants.e` → `2.71828`

**Use for:** Simple constants, inline configuration.

### files_shallowly

Mount all files in a folder (non-recursive).

```yaml
- files_shallowly: scripts/
```

Given:
```
scripts/
  process.py
  analyze.py
  utils/        # Ignored (subfolder)
    helper.py
```

You get:
- `process` → loads `scripts/process.py`
- `analyze` → loads `scripts/analyze.py`

**Use for:** Flat directories of scripts.

## The `at:` Prefix

Most mount types support `at:` to add a namespace prefix:

```yaml
- at: myprefix
  folder: some/path
```

Without `at:`, names are mounted at the root namespace.

## Choosing a Mount Type

| Your Need | Mount Type |
|-----------|------------|
| Directory of YAML/JSON templates | `folder` |
| Python module with test fixtures | `module` |
| Single standalone script | `file` |
| Inline constants | `value` |
| Flat folder of scripts (no subfolders) | `files_shallowly` |

## Complete Example

```yaml
# .dataconfig.yaml
sync_folder: data

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
      version: "1.0.0"
```

Usage:
```python
from dvc_dat import do

# Load a template
spec = do.load("catalog.experiment")

# Get a fixture
fixture = do.load("fixtures.simple")

# Run a script
do("scripts.process", input="data.csv")

# Access a constant
version = do.load("config.version")
```

## See Also

- [Core Concepts](concepts.md) - How mount commands fit in
- [Spec Format](spec-format.md) - What templates contain
