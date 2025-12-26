# Core Concepts

dvc_dat provides two integrated systems for managing data and code:

1. **Do-System** - A namespace for loading Python objects by dotted name
2. **DAT Storage** - Persistent data folders with `_spec_.yaml` metadata

## Two Namespaces

### Dotted Names (Do-System)

Used for referencing source code: templates, functions, configurations.

```python
from dvc_dat import do

# Load a template spec
spec = do.load("catalog.experiment")

# Execute a function
result = do("scripts.process_data", input_file="data.csv")
```

- Names like `catalog.experiment` or `fixtures.simple`
- Resolved through mount commands in `.dataconfig.yaml`
- Points to Python modules, YAML/JSON files, or folders

### Slash Paths (DAT Storage)

Used for data storage locations in the filesystem.

```python
from dvc_dat import Dat

# Load a persisted DAT
dat = Dat.load("runs/2025-01/experiment1")

# Create a new DAT
dat = Dat.create(path="runs/2025-01/experiment2", spec={"name": "exp2"})
```

- Paths like `runs/experiment1` or `upstream/kegg/compounds`
- Relative to `sync_folder` (from `.dataconfig.yaml`) or absolute
- Each DAT is a folder containing `_spec_.yaml`

## The Two Managers

### DoManager

Manages the do-system namespace. Configured via `mount_commands` in `.dataconfig.yaml`.

**Responsibilities:**
- Load Python objects by dotted name
- Mount folders, modules, and files into the namespace
- Expand specs (resolve `dat.base` inheritance)

### DatManager

Manages DAT creation, loading, and persistence.

**Responsibilities:**
- Create DAT folders with `_spec_.yaml`
- Load DATs from filesystem paths
- Resolve path templates (`{YYYY}`, `{unique}`, etc.)
- Coordinate with DoManager for spec resolution

**Relationship:** DatManager uses DoManager internally. When you call `Dat.create(spec="catalog.template")`, DatManager asks DoManager to load and expand the spec.

## Lifecycle: Template to Persisted DAT

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Source Code    │     │    DoManager    │     │   DatManager    │
│  (templates)    │────▶│  (namespace)    │────▶│  (persistence)  │
└─────────────────┘     └─────────────────┘     └─────────────────┘
       │                        │                       │
  catalog/                 do.load()              Dat.create()
  experiment.yaml          expands spec          writes folder
```

**Step by step:**

1. **Define a template** in your source tree:
   ```yaml
   # src/catalog/experiment.yaml
   dat:
     kind: Dat
     name: "runs/{YYYY}-{MM}/{unique}"
   experiment_type: baseline
   ```

2. **Mount it** via `.dataconfig.yaml`:
   ```yaml
   mount_commands:
     - at: catalog
       folder: src/catalog
   ```

3. **Create a DAT** from the template:
   ```python
   dat = Dat.create(spec="catalog.experiment")
   # Creates: data/runs/2025-01/Dat_1/_spec_.yaml
   ```

4. **Load it later**:
   ```python
   dat = Dat.load("runs/2025-01/Dat_1")
   print(dat.get_spec()["experiment_type"])  # "baseline"
   ```

## Configuration: .dataconfig.yaml

```yaml
sync_folder: data              # Where DATs are stored
mount_commands:                # Do-system namespace
  - at: catalog
    folder: src/catalog
  - at: fixtures
    module: tests.fixtures
```

See [Mount Commands](mount-commands.md) for all mount types.

## See Also

- [Spec Format](spec-format.md) - `_spec_.yaml` reference
- [Mount Commands](mount-commands.md) - Configuring the do-system
- [Overview](overview.md) - API reference
