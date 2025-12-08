# Spec File Format

Every DAT folder contains a `_spec_.yaml` (or `_spec_.json`) file that describes its contents and configuration.

## Minimal Spec

```yaml
dat:
  kind: Dat
```

The only required field is `dat.kind`, which specifies the Python class.

## Complete dat.* Fields

```yaml
dat:
  kind: Dat                              # Required: class name
  base: "catalog.base_template"          # Inherit from another spec
  name: "runs/{YYYY}-{MM}/{unique}"      # Path template (if no path provided)
  do: "scripts.run_experiment"           # Function to execute
  args: [1, 2, 3]                        # Positional args for do function
  kwargs: {verbose: true}                # Keyword args for do function
  target_exists: error                   # Collision behavior (see below)
```

### Field Descriptions

| Field | Description |
|-------|-------------|
| `kind` | Python class name. Usually `Dat` or a subclass. |
| `base` | Dotted name of a spec to inherit from. Recursively expanded. |
| `name` | Path template used when `Dat.create()` has no `path` argument. |
| `do` | Dotted name of a function to execute when the DAT runs. |
| `args` | List of positional arguments passed to the `do` function. |
| `kwargs` | Dict of keyword arguments passed to the `do` function. |
| `target_exists` | What to do if the path already exists. |

### target_exists Options

| Value | Behavior |
|-------|----------|
| `error` | Raise an exception (default) |
| `use` | Return the existing DAT without recreating |
| `overwrite` | Delete existing folder and recreate |
| `increment` | Auto-increment path to make it unique |

## Custom Fields

Any keys outside `dat:` are preserved as custom data:

```yaml
dat:
  kind: Dat
name: "My Experiment"
description: "Testing the baseline model"
parameters:
  learning_rate: 0.01
  epochs: 100
  batch_size: 32
```

Access custom fields via `dat.get_spec()`:

```python
dat = Dat.load("runs/my_experiment")
print(dat.get_spec()["parameters"]["learning_rate"])  # 0.01
```

## Path Template Variables

When `dat.name` or `Dat.create(path=...)` contains template variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `{YYYY}` | 4-digit year | 2025 |
| `{YY}` | 2-digit year | 25 |
| `{MM}` | Month (01-12) | 01 |
| `{DD}` | Day (01-31) | 15 |
| `{HH}` | Hour (00-23) | 14 |
| `{mm}` | Minute (00-59) | 30 |
| `{SS}` | Second (00-59) | 45 |
| `{cwd}` | Current working directory name | myproject |
| `{unique}` | Auto-incrementing number | 1, 2, 3... |

**Example:**
```yaml
dat:
  kind: Dat
  name: "runs/{YYYY}-{MM}-{DD}/exp_{unique}"
```
Creates paths like `runs/2025-01-15/exp_1`, `runs/2025-01-15/exp_2`, etc.

## Spec Expansion (dat.base)

When a spec has `dat.base`, the referenced spec is loaded and merged:

**Base spec** (`catalog/base.yaml`):
```yaml
dat:
  kind: Dat
defaults:
  optimizer: adam
  epochs: 100
```

**Child spec** (`catalog/experiment.yaml`):
```yaml
dat:
  kind: Dat
  base: catalog.base
defaults:
  epochs: 200  # Override
custom_param: true  # Add new field
```

**Expanded result:**
```yaml
dat:
  kind: Dat
  base: null  # Cleared after expansion
defaults:
  optimizer: adam  # From base
  epochs: 200      # Overridden
custom_param: true # Added
```

Expansion is recursive: if the base also has a `dat.base`, it's expanded first.

## Result File

After execution, DATs may have a `_result_.yaml` file containing output:

```yaml
status: completed
output:
  accuracy: 0.95
  loss: 0.05
completed_at: "2025-01-15T14:30:45"
```

## See Also

- [Core Concepts](concepts.md) - How DATs fit into the system
- [Mount Commands](mount-commands.md) - Configuring template locations
