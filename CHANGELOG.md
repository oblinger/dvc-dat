# Changelog

Every user-visible change to `dvc_dat`, newest first.

## Versioning

[Semver](https://semver.org): a change to the public contract (`Dat.create` / `Dat.load` / `do`, the `_spec_.yaml` format, do-system resolution, the CLI) is **major**; a new capability that leaves every existing consumer working is **minor**; a fix is **patch**. `__version__` lives in `dvc_dat/__init__.py`.

## 2.0.0 — 2026-09-21

A dat's spec is now a complete, argumentless recipe for itself, and `do` is the
one runner and the one namespace. Breaking on every count below.

### The fork rule

- `do(template, *args, **kwargs)` no longer passes the arguments to the
  function. It updates the template's `dat` section — kwargs into `dat.kwargs`
  key by key, positional args **replacing** `dat.args` — writes that as the new
  dat's `_spec_.yaml`, and runs the new dat with no call-site arguments.
  1.x appended positional args and let keywords win over the spec's.
- `do(existing_dat)` re-runs a dat on disk as it is. `do(existing_dat, x=1)`
  forks a new dat from its spec and never rewrites the one on disk.
- Nothing about arguments is written to `_result_.yaml` any more; 1.x recorded
  `dat.args` and `dat.kwargs` there. The spec is the record.
- `_result_.yaml` holds what the function put in `dat.get_results()`, plus
  `dat.run_at` and `dat.run_time`.

### One `do`

- `Do` replaces `DoManager`, `SimpleMethodManager`, `DoProxy` and
  `create_do_manager`. `dvc_dat.do` is the one instance.
- `do.load` falls back to **static resolution**: the longest importable prefix
  of a dotted name is imported and the rest is `getattr`-ed, so an importable
  object needs no mount. Nothing found raises Python's own `ImportError` /
  `AttributeError` / `KeyError` unless `default=` is given.
- `do.name_of(obj)` returns the dotted name `do.load` takes back to it.
- **`import dvc_dat` no longer reads the filesystem.** `do.configure(source)`
  is explicit, and mounts onto the same `do` object, so a name imported before
  it keeps working. The `dat` CLI configures itself.
- `do.expand_spec` is renamed `do.resolve_base` (it resolves `dat.base`; the
  name now belongs to the `{}` expander). `do.merge_configs` is gone — the one
  merge is `merge_dicts`, in which an override of `0`, `""` or `false`
  overrides.
- `dat.base` accepts a **list**, merged left to right with later entries
  winning. `dat.base` is removed from a stored spec rather than set to `null`.

### The `{}` grammar

- `expand(text, vars=None)` and `expand_spec(spec, vars=None)` are public and
  exported. An undotted `{name}` is a built-in (`YYYY YY MM DD HH mm SS now cwd
  unique`) or a key of `vars`; a dotted `{a.b}` resolves through `do.load` at
  run time; `{{` is a literal brace; a string that is exactly one reference
  yields the referenced object.
- `Dat.get_spec()` returns the spec with every reference resolved, computed
  once per instance. `Dat.get_spec(raw=True)` is the file as written.
- A spec value beginning with `{` must be quoted in YAML or it arrives as a
  dict; `validate_spec` names that case.

### The `dat` command line

- One grammar, with verbs: `dat do TARGET [ARG ...] [KEY=VALUE ...]`, plus
  `dat list [PREFIX]`, `dat info`, `dat version` and `dat --help`. `dat TARGET
  ...` is still the shorthand for `dat do TARGET ...`.
- **Keyword arguments are `KEY=VALUE`**, not `--keyword value`. The 1.x
  `--keyword value` / `--flag` forms are gone; the only flags left are
  `--set`, `--sets`, `--json`, `--print`, `--usage`, `--help`, `--version`
  and `--info`.
- Every fixed argument and every `KEY=VALUE` value is read as a **YAML
  scalar**: `7` is an int, `true` a bool, `[1,2]` a list, `"x"` a string, and
  a bare word stays a string. `--` ends the options.
- **Exit codes**: `0` ran, `1` the run raised or the command line was
  malformed, `2` the target does not load. A failure prints one line on
  stderr and no traceback; `DAT_DEBUG=1` gives the traceback. `do_argv`
  returns the exit code, and `dat --version` / `dat --help` work with no
  config in reach.
- `dat list` and `dat info` are verbs now, so they no longer resolve through
  the namespace; a target of either name still runs as `dat do list` /
  `dat do info`.
- New reference page: `docs/cli.md`.

### `bin/X` — the bootstrap

- A POSIX `sh` script, checked in and copied wherever it is useful, that runs
  a dat from any directory with no environment activated: it walks up to the
  nearest `.dataconfig.yaml` (exit `3` with a message if there is none),
  picks an interpreter — `$DAT_PYTHON`, the config's `python:` key,
  `.venv/bin/python` beside the config, then `python3` on `PATH` — and
  `exec`s `<python> -m dvc_dat do "$@"` with the working directory unchanged.
- `.dataconfig.yaml` takes a **`python:`** key for that interpreter: a path to
  one, or a folder holding `bin/python`; a relative path resolves against the
  config's folder. `DataConfig.python` carries it, absolute. The library never
  reads it — only `X` does.

### Spec fields

- `dat.path` is renamed **`dat.name`**, and it stays in the stored spec (1.x
  popped it).
- The `dat` section is `kind`, `base`, `name`, `do`, `args`, `kwargs`,
  `target_exists`.

### Validation without pydantic

- `pydantic` is no longer a dependency. `DataConfig` is a dataclass and
  `DatSpec` / `DatSpecCore` / `Dat._SPEC_TYPE` are gone, so `dat.spec.dat.kind`
  no longer works — use `dat.get_spec()["dat"]["kind"]`.
- `Dat.validate_spec(cls, spec) -> spec` is a classmethod hook called by
  `create` and `load` on the class `dat.kind` names. A subclass overrides it;
  a schema library inside it is the consumer's choice and dependency.
- An unknown key in a `.dataconfig.yaml` now raises, naming the file, the key
  and the known keys. `remote_prefix`, `default_remote` and `dat:` are no
  longer config keys.

### Removed

`Dat.run` and its `_result_.yaml` keys (`start_time`, `success`,
`execution_time`, `end_time`, `run_metadata`) · `Dat.is_valid` · the `Dat.path`
property · `pull_if_missing` · `create_from_template` · the module-level
`load`/`_dynamic_load_dat_class` in `dat.py` · `DatMethod` · `MethodManager` ·
`dynamic_load_fn` · `load_dict` · `DAT_VERSION` · the `files_shallowly` mount.

### Renamed modules

`dvc_dat/dat.py` → `dvc_dat/core.py` (so `dvc_dat.dat` stops meaning a
submodule) and `dvc_dat/do_fn.py` → `dvc_dat/do.py`.

### Migrating from 1.x

| 1.x | 2.0 |
|-----|-----|
| `from dvc_dat.dat import Dat` | `from dvc_dat import Dat` |
| `Dat.manager.do` | `do` |
| `DoManager()` | `Do()` |
| `do.expand_spec(spec)` | `do.resolve_base(spec)` |
| `do.merge_configs(a, b)` | `merge_dicts(a, b)` |
| `dat.spec.dat.kind` | `dat.get_spec()["dat"]["kind"]` |
| `dat.path` (property) | `dat.get_path()` |
| spec key `dat.path` | spec key `dat.name` |
| `Dat.run()` | `do(dat)` |
| `do(dat, *args)` re-runs in place | `do(dat)` re-runs; with args it forks |
| `dat cmd ARG --keyword value` | `dat cmd ARG keyword=value` |
| args appended to `dat.args` | args **replace** `dat.args` |
| args/kwargs read from `_result_.yaml` | read from the forked `_spec_.yaml` |
| pydantic spec models | `Dat.validate_spec` override |
| config `remote_prefix` / `default_remote` / `dat:` | delete them |
| implicit config on import | `do.configure()` where you want it read |

Consumers pin the tag: `dvc_dat @ git+https://github.com/oblinger/dvc-dat@v2.0.0`.

## 1.2.0 — 2026-09-21

- Import on Python < 3.11 fixed: `Self` now comes from `typing_extensions` (was `typing`, so the package failed to import on 3.10 despite `requires-python >= 3.8`).

- Docs describe the code: `.dataconfig.yaml` key is `local_prefix` (the
  documented `sync_folder` was silently ignored); `file:` mounts need `at:`;
  `{cwd}` is the full path, `{unique}` is empty then `_2`, `_3`; `{now}`
  documented; `Dat.manager.exists`; `Dat.create` does not expand `dat.base`;
  the unimplemented `files_shallowly` mount and `--get` / `--USAGE` flags are
  no longer advertised.
- `dat --info` works again (it read a `DatManager.folder` that does not exist).
- `xlsxwriter` is an optional dependency: `pip install dvc_dat[excel]`.
- Semver rule in `docs/about.md`.
- CI: GitHub Actions runs `uv run python -m pytest` on push to `main` and on
  every pull request.
- Package is correct on a machine that is not the author's: the committed
  self-referencing `dvc_dat/dvc_dat` symlink is gone, `do_fn` is imported
  unconditionally (the `except ImportError` guard could only hide a real bug),
  and suite-generated dats under `tests/test_sync_folder/anonymous/` are
  gitignored.
- 451 committed test-suite artifacts removed.

## 1.1.0 — 2025-11-28

Consolidation of the `sv-update` line on top of the runnable-dat work.

- `dat.py` is standalone again: `config.py` and `utils.py` folded in.
- `DataConfig` with `mount_commands`; do-system init moved to `do_fn.py`.
- `Dat.create()` accepts a string or YAML spec; `resolve_dat_folder` interface.
- `target_exists` parameter skips re-execution when the target is present.
- `Dat.run()` routes through the do-system instead of `dynamic_load_fn`.
- Docs: `concepts.md`, `spec-format.md`, `mount-commands.md`.
- Examples consolidated onto test data; notebooks fixed; 73 tests green.
- Removed: `dat_io.py` stub, `_old_init_logic.py`.

## 1.0.x → sv-update (2025-01 … 2025-11, Juan Barajas)

Runnable dats.

- `Dat` is the base structure carrying its config; spec is public;
  `create`/`load` exposed on `Dat`; manager made private.
- Pydantic models validate the spec.
- Running a dat writes a results file with run metadata; results metadata
  loads back; a dat is not executed twice.
- `pull_if_missing` on load; settings unified into YAML with the dat spec.
- `just` interface; template creation decoupled from loading.

## 1.00.05 — 2024-06-20

First versioned release: `Dat` folders with `_spec_.yaml`, the do-system with
mount commands, dat caching, multiple dat folders, run duration and start
time recorded.
