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
    Do, do, cli_main,
    expand, expand_spec, merge_dicts,
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
| `cli_main` | The `dat` command line for a program's own main |
| `expand` / `expand_spec` | The `{}` grammar |
| `merge_dicts` | The zipper merge `dat.base` uses |

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
| `do.configure(SOURCE) -> DataConfig` | Install a chosen config; first use does this for you |
| `do.config` | The `DataConfig` in force, or `None` |
| `do.mount(at=, folder=/file=/module=/value=)` | Add one name to the namespace; your program calls it |
| `do.keys()` | Every mounted base name |

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
| `.get_spec() -> dict` | The spec — every `{}` was expanded once, at create |
| `.get_results() -> dict` | The mutable results tree |
| `.get_path() -> str` | The dat's absolute path |
| `.get_path_name() -> str` | Its name, relative to the dat folder |
| `.save()` | Write the results to `_result_.yaml` |
| `.delete()` | Remove the folder |
| `.copy(NAME)` / `.move(NAME)` | Copy or move the dat |

`DatContainer` adds `.get_dat_paths() -> [str]` and `.get_dats() -> [Dat]`.

NAME is an absolute path, a path under the config folder, a mounted dat name,
or a path under one of the dat folders.

## Dict trees

| Method | Description |
|--------|-------------|
| `Dat.get(Dat/dict, "a.b.c", [default])` | Get by dotted name or key list |
| `Dat.set(dict, "a.b.c", value)` | Set, creating levels as needed |

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

`dvc_dat.dat_tools` is mounted as `dt`, and `dt.list` is `dat list`.

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
dat TARGET [ARG ...] [KEY=VALUE ...]
dat list [PREFIX]
dat info
dat version

dat TARGET --set DOTTED.KEY=VALUE [--set ...]
dat TARGET --json DOTTED.KEY '<json>'
dat TARGET --dry-run
dat TARGET --usage
```

`dat` configures itself from the nearest `.dataconfig.yaml`. A target that
is a template spec is forked: the fixed arguments become its `dat.args`,
the `KEY=VALUE` pairs update its `dat.kwargs`, and `--set` / `--json` update
any spec key. Every argument value is a YAML scalar. `list`, `info` and
`version` are reserved words. The exit code is `0` ran, `1` failed, `2` the
target does not load.

A copy of `bin/dat` on your `PATH` runs your project's `run:` main from any
directory. The environment's `dat` console script does not read `run:`: it
runs the library's own command line, with no project mounts. See **[Command Line](cli.md)** for every
reserved word, flag and exit code, the bootstrap and the `run:` config key.

## `.dataconfig.yaml`

Like git, dvc-dat walks up from the working directory looking for
`.dataconfig.yaml`. An empty file is a complete config.

```yaml
dat_folders: data            # or a list: the first is written, all are read
run: .venv/bin/python -m mypkg.main   # what a copy of bin/dat execs
```

Those are the only keys; anything else is an error that names the file and the
key. The config's folder is the import root. The namespace is whatever the
running program imported; `run:` names your program's main, which mounts what
it mounts and ends with `sys.exit(dat.cli_main())`. See **[Mounts](mount-commands.md)**.
