# DVC-DAT API Reference

A dat is a folder whose `_spec_.yaml` is a complete, argumentless recipe for
itself. `do` is the one namespace and the one runner.

## Quick Links

- **[Core Concepts](concepts.md)** — the fork rule, the two kinds of name
- **[Spec Format](spec-format.md)** — `_spec_.yaml` / `_result_.yaml` reference
- **[Mount Commands](mount-commands.md)** — configuring the do-system

## What the package exports

```python
from dvc_dat import (
    Dat, DatContainer, DatManager, DataConfig,
    Do, do, do_argv, load, expand, expand_spec,
)
```

| Name | What it is |
|------|------------|
| `Dat` | A dat folder: its spec, its results, its path |
| `DatContainer` | A dat whose folder holds other dats |
| `DatManager` | Creates, finds and loads dats; reached as `Dat.manager` |
| `DataConfig` | The `.dataconfig.yaml` values |
| `Do` | The do class — one instance, `do` |
| `do` | The singleton: namespace, runner, configuration |
| `do_argv` | The `dat` command line; returns the exit code |
| `load` | `Dat.load` — open a dat by path or name |
| `expand` / `expand_spec` | The `{}` grammar |

## Running and loading — `do`

```python
do(TARGET, *args, **kwargs)
```

| `TARGET` | What happens |
|----------|--------------|
| a **callable** | called as `TARGET(*args, **kwargs)` |
| a **spec** (dict) | forked with the arguments, created, run |
| a **Dat**, no arguments | re-run in place |
| a **Dat**, with arguments | forked into a new dat; the original is untouched |
| a **string** | `do.load`-ed first, then one of the above |

The run itself is `fn(dat, *spec.dat.args, **spec.dat.kwargs)`, where `fn` is
what `dat.do` names. `dat.run_at` and `dat.run_time` land in the results.

| Method | Description |
|--------|-------------|
| `do.load(NAME, default=, kind=)` | The object a dotted name names |
| `do.name_of(OBJ) -> str` | The name `load` takes back to `OBJ` |
| `do.configure(SOURCE) -> DataConfig` | Read a config, build the manager, mount |
| `do.config` | The `DataConfig` in force, or `None` |
| `do.mount(at=, folder=/file=/module=/value=)` | Add one name to the namespace |
| `do.mount_all(COMMANDS, relative_to=)` | Apply a config's mount table |
| `do.add_do_folder(PATH)` | Mount a folder by file name |
| `do.get_base(BASE)` | The object mounted at a base name |
| `do.keys()` | Every mounted base name |
| `do.resolve_base(SPEC)` | Merge a spec over its `dat.base` chain |
| `do.fork_spec(SPEC, ARGS, KWARGS)` | The fork rule, as a function |
| `do.dat_from_template(SPEC, path=)` | `(dat, skip_execution)` |

`do.load` checks mounts first, then imports the longest importable prefix of
the name and `getattr`s the rest. With nothing found it raises what Python
raises — `ImportError`, `AttributeError` or `KeyError` — unless `default=` is
given.

## Dat folders

| Method | Description |
|--------|-------------|
| `Dat.create(path=, spec=) -> Dat` | Create a dat from a path template and spec |
| `Dat.load(NAME) -> Dat` | Load a dat by name or path |
| `Dat.validate_spec(SPEC) -> SPEC` | Classmethod hook, run on create and load |
| `Dat.manager.exists(NAME) -> bool` | True iff the named dat exists |
| `.get_spec() -> dict` | The spec with every `{}` reference resolved |
| `.get_spec(raw=True) -> dict` | The spec as the file was written |
| `.spec` | `get_spec()` |
| `.get_results() -> dict` | The mutable results tree |
| `.get_path() -> str` | The dat's absolute path |
| `.get_path_name() -> str` | Its name, relative to the sync folder |
| `.get_path_tail() -> str` | The last path segment |
| `.save()` | Write the results to `_result_.yaml` |
| `.delete()` | Remove the folder |
| `.copy(NAME)` / `.move(NAME)` | Copy or move the dat |

`DatContainer` adds `.get_dat_paths() -> [str]` and `.get_dats() -> [Dat]`.

NAME is an absolute path, a path under the config folder, a mounted dat name,
or a path under one of the sync folders.

## Dict trees

| Method | Description |
|--------|-------------|
| `Dat.get(Dat/dict, "a.b.c", [default])` | Get by dotted name or key list |
| `Dat.set(dict, "a.b.c", value)` | Set, creating levels as needed |
| `Dat.gets(Dat/dict, *NAMES) -> [value]` | Several at once |
| `Dat.sets(dict, *"a.b=value")` | Several assignments at once |

```python
x = {}
Dat.set(x, "a.b.c", 1)
Dat.get(x, "a.b.c")      # 1
```

## References

| Function | Description |
|----------|-------------|
| `expand(TEXT, vars=None)` | Resolve the `{}` references in one string |
| `expand_spec(SPEC, vars=None)` | Resolve them throughout a spec tree |

See [Spec Format](spec-format.md) for the grammar and the YAML quoting rule.

## dat_tools — DataFrames and Excel

| Function | Description |
|----------|-------------|
| `dt.from_dat([Dat, ...], [point_fn, ...]) -> DF` | Apply point_fns to dats |
| `dt.to_excel(DF, ...)` | Write a DataFrame to Excel |
| `dt.dat_report(spec, ...) -> DF` | Build an Excel report from dats |
| `Cube(points=, dats=, point_fns=)` | A data cube over dats |
| `dt.list([prefix])` | List the do names with a prefix |

`to_excel` needs the `excel` extra: `pip install dvc_dat[excel]`.

## Command line

```
dat do TARGET [ARG ...] [KEY=VALUE ...]
dat TARGET [ARG ...] [KEY=VALUE ...]
dat list [PREFIX]
dat info
dat version

dat do TARGET --set DOTTED.KEY VALUE
dat do TARGET --sets DOTTED.KEY1=VALUE1,DOTTED.KEY2=VALUE2
dat do TARGET --json DOTTED.KEY '<json>'
dat do TARGET --print
dat do TARGET --usage
```

`dat` configures itself from the nearest `.dataconfig.yaml`. A target that
is a template spec is forked: the fixed arguments become its `dat.args`,
the `KEY=VALUE` pairs update its `dat.kwargs`, and `--set` / `--sets` /
`--json` update any spec key. Every argument value is a YAML scalar. The
exit code is `0` ran, `1` failed, `2` the target does not load.

`bin/X` runs a target from any directory without activating an
environment. See **[Command Line](cli.md)** for every verb, flag and exit
code, the `X` bootstrap and the `python:` config key.

## `.dataconfig.yaml`

Like git, dvc-dat walks up from the working directory looking for
`.dataconfig.yaml`.

```yaml
local_prefix: data
extra_local_prefixes: []
python: .venv
mount_commands:
  - at: catalog
    folder: src/catalog
  - at: fixtures
    module: tests.fixtures
  - at: constants
    value: {debug: false}
```

Those are the only keys; anything else is an error that names the file and the
key. See **[Mount Commands](mount-commands.md)** for the mount types.
