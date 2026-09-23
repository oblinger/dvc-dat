# Changelog

Every user-visible change to `dvc_dat`, newest first.

## Versioning

[Semver](https://semver.org): a change to the public contract (`Dat.create` / `Dat.load` / `do`, the `_spec_.yaml` format, do-system resolution, the CLI) is **major**; a new capability that leaves every existing consumer working is **minor**; a fix is **patch**. `__version__` lives in `dvc_dat/__init__.py`.

## 2.6.0 — 2026-09-23

**`--json` reads like `--set`** (Dan, 2026-09-23). Breaking for a command line
that used the two-word form; shipped as a minor per the rule above 2.2.0.

- `--json DOTTED.KEY=JSON`, one pair per flag, repeatable, mixing freely with
  `--set` — was `--json DOTTED.KEY '<json>'`. A missing `=` is an error
  naming the form. Migration: `--json rules '[[2, 3]]'` → `--json rules='[[2, 3]]'` (the quotes are the shell's; the word `dat` sees is `rules=[[2, 3]]`).

## 2.5.0 — 2026-09-23

**The artifact folder sits beside the dat folders, never inside them** (Dan,
2026-09-23: with 2.4's default `art/` inside `data/`, a dat named `art/...`
and an artifact name collide). Breaking for a 2.4 caller that relied on the
default; shipped as a minor per the rule above 2.2.0.

- **Nesting is refused**: an `art_folder` inside a dat folder, or a dat
  folder inside it, is `ValueError`, from the constructor and from
  `load_dat_config`.
- **`load_dat_config` defaults `art_folder` to `art/` beside the config file**,
  a sibling of `data/` (was `art/` under the first dat folder).
- **`DatManager(dat_folders=[...])` with no `art_folder` holds no artifacts**:
  `save` and `art:` loads raise `RuntimeError` naming the missing folder.
  `dat info` prints `(none)`.

## 2.4.0 — 2026-09-23

**Artifacts and dependencies by capture, in DAT itself** (DAT F018; was SVP's
F152). Additive: every 2.3 caller keeps working.

- **`DatManager.save(source, "art:<kind>/<rest>") -> "sha256:<hex>"`** copies
  a file or folder into the artifact folder, write-once, with a
  `_art_.yaml` sidecar (`kind`, `name`, `payload`, `sha256`, `saved_at`).
- **`DatManager.load("art:<kind>/<rest>")`** returns the artifact through the
  factory **`register_artifact(kind, factory)`** named — `factory(path)`, a
  class or a lambda — or a `Path` when none is registered. `exists` answers
  for `art:` names too.
- **`dat.dependencies`** in `_result_.yaml`: `execute` runs inside
  **`recording(dat)`**, so every `load` (and `save`) a run makes is recorded,
  name to hash (`null` for a dat without `dat.sha256`); `{}` when it loaded
  nothing. Nested runs record their own; the outer records the inner dat
  once. **`record_dependency(name, sha256=None)`** adds an entry by hand.
- **`DatManager(..., art_folder=None)`**; `.datconfig.yaml` gains
  `art_folder:` (default `art/` under the first dat folder) and the
  environment `DAT_ART_FOLDER`. `dat info` prints it.

## 2.3.0 — 2026-09-22

**The run and the class belong to the manager** (SVP's handoff, 2026-09-22).
Breaking for a caller of `DatManager.create` / `load`, and for code that
compares `dat.kind` to a bare name; shipped as a minor per the rule above
2.2.0.

- **`DatManager.execute(dat)`** is the run: `do(...)` calls it, and so does
  every `do(...)` a running function makes, so a `DatManager` subclass that
  overrides it wraps every run. It replaces the private `Do._run_dat`.
- **A run records its code**: `dat.code: {branch, commit, dirty}` in
  `_result_.yaml`, from the git checkout holding the source of the function
  `dat.do` names; nothing outside a checkout.
- **`dat.kind` is a dotted `module.qualname`** (`dvc_dat.core.Dat`,
  `mylab.runs.Run`), written by `create` and imported by `load`. An
  unimportable kind is `ImportError` and a non-`Dat` is `TypeError`; neither
  downgrades to `Dat`. A bare name on disk is still read the old way.
- **`manager.create(spec=None, *, path=None)`** and
  **`manager.load(name_or_path, *, cache_after_load=True)`** take no class;
  the spec decides. `load`'s ignored `cwd` is gone, from `Dat.load` too.
- **`Cls.load(name) -> Cls`** raises `TypeError` unless the dat is a `Cls`
  (was `ValueError` on a kind mismatch); **`Cls.create`** gives a spec with no
  kind `Cls`, and refuses a kind outside `Cls` before writing anything.
- `repr(dat)` is `<ClassName: name>`, not the spec's kind.

**One object: the manager** (Dan, 2026-09-22/23, DAT T017). A `DatManager`
owns its folders **and** its namespace, and it is the only thing a program
configures. 2.0 had inverted it — the `do` singleton held a `DataConfig`,
`configure()` built `Dat.manager`, and the storage code reached for the
global `do` — so a second `Do()` had mounts of its own but `Dat.create` of a
spec whose base was mounted only there failed.

- **`DatManager(*, dat_folders, do=None)`**: keyword-only, `dat_folders` a
  required list (a string is `TypeError`), searched in order by name, the
  first written to; nothing is read from disk. `do` is its only public
  attribute. Every manager carries a `Do` bound to it — its mounts, its
  `load`, its runner — and everything the manager does (a dotted spec,
  `dat.base`, `{}` expansion, path resolution) goes through it. `do=`
  adopts an existing namespace with its mounts. `dt` is mounted in every
  world.
- **`DatManager.load_dat_config(start=None, *, do=None)`**: a new manager from
  the `.datconfig.yaml` found walking up from `start` (a config file names
  itself); the file's folder goes first on `sys.path`.
- **`Dat.manager`** is a plain class attribute: filled on first read by
  `load_dat_config()`, replaced by assignment, shared by every subclass.
  Adopting the default `do` (`DatManager(..., do=dvc_dat.do)`) makes the new
  manager the default and keeps every mount.
- **`dvc_dat.do`** forwards to `Dat.manager.do`, whichever manager that is.
  A bare `Do()` mounts and loads; running in it before a manager adopts it
  is `RuntimeError`.
- **`DatManager.expand` / `expand_spec`**: dotted names through that
  manager's `do`; the module functions resolve through the default world.
- A dat remembers the manager that loaded it (`dat.manager`):
  `get_path_name`, `delete`, `copy`, `move` and `DatContainer.get_dats`
  work in a second world.

Removed, each with its replacement:

| Gone | Instead |
| --- | --- |
| `.dataconfig.yaml`, `.dataconfig.override.yaml` | `.datconfig.yaml`, `.datconfig.override.yaml` — rename the file |
| `DataConfig`, `DataConfig.new(cwd=X)` | `DatManager.load_dat_config(X)` |
| `DatManager(config)` | `DatManager(dat_folders=[...])` |
| `do.configure(X)` | `Dat.manager = DatManager.load_dat_config(X, do=dvc_dat.do)` |
| `do.config`, `manager.config`, `config.cwd` | none; `sys.path[0]` is the config folder |
| `manager.dat_folder`, `manager.dat_folders` | private; name dats, not folders |
| `DAT_CWD` | none; `load_dat_config(start)` |
| `load` of a path relative to the config folder | an absolute path, or a name under a dat folder |
| `cli_main(config=DataConfig)` | `cli_main(config=folder_or_file)` |

## 2.2.1 — 2026-09-22

- `Dat(spec)` raises a `TypeError` that names the two ways to get a dat:
  `Dat.create(spec=...)` makes one on disk, `Dat.load(path)` reads one. The
  constructor stays `(path, spec)` and writes nothing (Dan, 2026-09-22).

## 2.2.0 — 2026-09-22

Breaking, as a minor: 2.x was public for a few hours with one consumer, so the
API it settled on ships as 2.2 rather than a new major (Dan, 2026-09-22).
Tags `v3.0.0` and `v3.0.1`, briefly published the same day, are withdrawn;
this release is their content.

Breaking: public names removed or made private. Nothing is kept as an alias.

- **Removed** `Do.add_do_folder` and the do-folder fallback in `do.load`. A
  dotted name is a mounted name, else a plain Python import.
- **Removed** from `dvc_dat`'s exports: `do_argv` (now the private
  `dvc_dat.do._do_argv`) and the `load` alias of `Dat.load`.
- **Removed** `Dat.spec` (use `get_spec()`), `Dat.gets` / `Dat.sets` and the
  module functions `dotted_gets` / `dotted_sets`, and `Dat.get_path_tail` /
  `DatManager.get_path_tail`.
- **Made private** (leading underscore): `Do.fork_spec`,
  `Do.dat_from_template`, `Do.resolve_base`, `Do.get_base`,
  `Do.resolve_dat_folder`, the `Do` attributes `base_locations`,
  `base_objects` and `registered_values` (`do.config` stays public);
  `DatManager.prepare_dat_path`, `resolve_path`, `get_path_name` and
  `dat_cache` (`Dat.get_path_name()` stays public); `core.dotted_get` /
  `dotted_set`; `DataConfig.field_names` / `env_names`; `DataState`.
- **Built-in mounts** are `dt` (`dvc_dat.dat_tools`) and `dt.list`; the
  `dat_tools` and `dat_tools.list` mounts are gone, so `dat list` shows `dt`
  alone.
- The `dat` console script is `dvc_dat.do:cli_main`; `dvc_dat.__main__.main`
  is gone and `python -m dvc_dat` calls `cli_main()` directly. The docs now
  say plainly that the console script runs the library's own command line
  with no project mounts and never reads `run:`; only a copy of `bin/dat`
  execs `run:`.
- **Fix:** the mount clash check compares real paths, component by
  component. A package folder mounted at its own name through a symlink is
  no longer refused, and a sibling sharing a string prefix (`/x/configs2`
  beside a mounted `/x/configs`) no longer slips past.
- **Fix:** the documented variation recipe. A created dat's spec carries the
  folder it landed in as `dat.name`, so the 2.1 recipe raised
  `FileExistsError`; it is now
  `Dat.create(spec=merge_dicts(d.get_spec(), {"dat": {"target_exists": "increment"}, ...}))`,
  and a test runs the recipe from `docs/concepts.md` and
  `docs/spec-format.md` verbatim.
- **Examples:** one notebook, `examples/walkthrough.ipynb`, replaces the
  three 1.x notebooks; `standard_do_scripts/` and the 1.x example fixtures
  are gone; `tests/test_examples.py` runs the notebook.

### Migrating from 2.0 and 2.1

| 2.x | 3.0 |
|-----|-----|
| `do.add_do_folder(path)` | `do.mount(folder=path, at=...)` |
| `from dvc_dat import do_argv; do_argv(argv)` | `cli_main(argv)` |
| `from dvc_dat import load; load(name)` | `Dat.load(name)` |
| `dat.spec` | `dat.get_spec()` |
| `Dat.gets(src, "a.b", "c")` | `[Dat.get(src, "a.b"), Dat.get(src, "c")]` |
| `Dat.sets(src, "a.b=1")` | `Dat.set(src, "a.b", 1)` |
| `dotted_gets` / `dotted_sets` | `Dat.get` / `Dat.set`, one key each |
| `dat.get_path_tail()` | `os.path.basename(dat.get_path())` |
| `Dat.manager.get_path_tail(p)` | `os.path.basename(p)` |
| `do.resolve_base(spec)` | `Dat.create(spec=spec)` merges `dat.base` |
| `do.fork_spec` / `do.dat_from_template` | `do(template, *args, **kwargs)` |
| `do.get_base(name)` | `do.load(name)` |
| `do.resolve_dat_folder(name)` | `Dat.load(name).get_path()` |
| `do.base_locations` | `do.keys()` for the names |
| `do.base_objects` / `do.registered_values` | `do.load(name)` |
| `Dat.manager.prepare_dat_path` | `Dat.create(path=..., spec=...)` |
| `Dat.manager.resolve_path(name)` | `Dat.load(name).get_path()` |
| `Dat.manager.get_path_name(p)` | `Dat.load(p).get_path_name()` |
| `Dat.manager.dat_cache` | none: the cache is internal |
| `core.dotted_get` / `dotted_set` | `Dat.get` / `Dat.set` |
| `DataConfig.field_names()` | `[f.name for f in dataclasses.fields(DataConfig)]` |
| `DataConfig.env_names()` | `DAT_FOLDERS`, `DAT_RUN`, `DAT_CWD` |
| `DataState` | none: internal to `DatContainer` |
| `do.load("dat_tools.X")` / `dat_tools.list` | `dt.X` / `dt.list` |
| `dvc_dat.__main__:main` | `dvc_dat.do:cli_main` |

### Fixes found by the docs audit

- A value mount answers to the dotted paths inside it, as
  `docs/mount-commands.md` promised: after
  `do.mount(value={"pi": 3.14159}, at="constants")`, `do.load("constants.pi")`
  is `3.14159`. Before, only the exact mounted name resolved.
- `dat list PREFIX` matches names that start with `PREFIX`; it matched any
  name containing it.
- `Dat.load`'s not-found error names the config folder it searched, not the
  process's working directory.
- Docs: `spec-format.md` no longer contradicts itself on function-valued
  references; "sync folder" is gone from the docstrings.

## 2.1.0 — 2026-09-22

- **`do.mount` refuses a name that is also importable.** When a top-level
  name a mount would add (`at`'s first part, or each top-level entry of a
  folder mounted with no `at`) is a module or package Python can import from
  elsewhere, `mount` raises `ValueError` naming it. In 2.0 the mount silently
  shadowed the installed module inside `do.load`. A module mounted at its own
  name, or a package's own folder, is not a clash. A program that relied on
  shadowing must pick another `at`.
- A created dat's spec never changes, and there is no `fork` method: the
  recipe is `Dat.create(spec=merge_dicts(d.get_spec(), overrides))`,
  documented in `docs/concepts.md` (the overrides must carry
  `{"dat": {"target_exists": "increment"}}`; see 2.2.0).

## 2.0.2 — 2026-09-22

- `merge_dicts(*dicts)` is exported: the zipper merge `dat.base` uses, for a
  caller hydrating a spec by hand (`do.load` it, merge, `Dat.create`). Nested
  mappings merge key by key, later dicts win, and a list is replaced whole.

## 2.0.1 — 2026-09-22

- A folder mount answers to the dotted paths `docs/mount-commands.md` § folder
  promises: `at` prefixes the folder and a nested file answers to its path
  (`catalog.models.baseline`). In 2.0.0 the index held both but lookup tried
  only the first dotted part, so `at=` on a folder mount and every nested file
  were unreachable. A dat folder inside a mounted folder answers to
  `<path>._spec_`.

## 2.0.0 — 2026-09-21

- `do` configures itself on first use: `import dvc_dat` still reads no
  filesystem, but the first `do(...)`, `do.load(...)`, `Dat.load`,
  `Dat.create` or `Dat.manager` access discovers the nearest
  `.dataconfig.yaml` and installs it. `do.configure(source)` remains, for a
  config chosen by hand.
- **`.dataconfig.yaml` has two keys** — `dat_folders` (a folder, or a list:
  the first is where new dats are created, all are searched by name; replaces
  `local_prefix` + `extra_local_prefixes`) and `run` (the command a copy of
  `bin/dat` execs; replaces `python:`). `DAT_FOLDERS` and `DAT_RUN` in the
  environment override them. `Dat.manager.dat_folder` /
  `.dat_folders` replace `sync_folder` / `sync_folders`.
- **A spec on disk is a record.** `Dat.create` expands every `{}` once, with
  the same `now` and `unique` the folder got, and writes the result: `dat.name`
  is the folder the dat landed in, `{now}` is the moment it was made. Nothing
  is expanded on read; `get_spec(raw=)` is gone. A reference inside a longer
  string must be a string or a number; a whole-value reference is inlined as
  data, and a reference to a function or class is a `TypeError` at create.
  A fork from a `Dat` lands beside it (`target_exists: increment`), and
  `increment` on a name with no `{unique}` counts up `_2`, `_3` instead of
  looping.
- **`mount_commands` is gone from `.dataconfig.yaml`**; a file that still has
  it is an unknown-key error. The namespace is whatever the running program
  imported: `do.mount(...)` calls live in your own code, and for the shell
  `run:` names your program's main, which ends with `sys.exit(dat.cli_main())`
  when `DAT_CLI_CONFIG` is set (`cli_main(argv=None, *, config=None)` is new and
  exported; the bootstrap sets `DAT_CLI_CONFIG` -- the config file it found -- for the program
  it launches). `do.mount_all` is removed. With no mounts a
  dotted name is a Python name and nothing else; an empty `.dataconfig.yaml`
  is a complete config.
- The config's folder is the project's import root: it goes first on
  `sys.path` when the config installs, so the project's own modules resolve
  from any working directory, installed or not.

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
- References are expanded once, at create (see above); `Dat.get_spec()` is
  the file.
- A spec value beginning with `{` must be quoted in YAML or it arrives as a
  dict; `validate_spec` names that case.

### The `dat` command line

- One grammar: `dat TARGET [ARG ...] [KEY=VALUE ...]`, plus the reserved
  words `dat list [PREFIX]`, `dat info`, `dat version` and `dat --help`.
  There is no `do` verb.
- **Keyword arguments are `KEY=VALUE`**, not `--keyword value`. The 1.x
  `--keyword value` / `--flag` forms are gone; the only flags left are
  `--set DOTTED.KEY=VALUE` (repeatable; `--sets` is gone), `--json`,
  `--dry-run`, `--usage`, `--help`, `--version` and `--info`.
- Every fixed argument and every `KEY=VALUE` value is read as a **YAML
  scalar**: `7` is an int, `true` a bool, `[1,2]` a list, `"x"` a string, and
  a bare word stays a string. `--` ends the options.
- **Exit codes**: `0` ran, `1` the run raised or the command line was
  malformed, `2` the target does not load. A failure prints one line on
  stderr and no traceback; `DAT_DEBUG=1` gives the traceback. `do_argv`
  returns the exit code, and `dat --version` / `dat --help` work with no
  config in reach.
- `dat list`, `dat info` and `dat version` are reserved words, so they no
  longer resolve through the namespace; a target with one of those names is
  not reachable from the shell.
- New reference page: `docs/cli.md`.

### `bin/dat` — the bootstrap

- A POSIX `sh` script, checked in and copied wherever it is useful, that is
  the `dat` command from any directory with no environment activated: it
  walks up to the nearest `.dataconfig.yaml` (exit `3` with a message if there
  is none), picks a command — `$DAT_RUN`, the config's `run:` key,
  `.venv/bin/python -m dvc_dat` beside the config, then `python3 -m dvc_dat`
  — and `exec`s it with the arguments appended and the working directory
  unchanged. With an environment active the console script of the same name
  shadows the copy and does the same thing.
- `.dataconfig.yaml` takes a **`run:`** key for that command (`uv run dat`,
  `conda run -n ml dat`); a relative path in its first word resolves against
  the config's folder. `DataConfig.run` carries it. The library never reads
  it — only the bootstrap does.

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
| config `local_prefix` + `extra_local_prefixes` | `dat_folders: [first, ...]` |
| config `python:` | `run: .venv/bin/python -m dvc_dat` (or `uv run dat`) |
| `dat do TARGET` | `dat TARGET` |
| `--set KEY VALUE` · `--sets a=1,b=2` | `--set KEY=VALUE`, repeated |
| `get_spec(raw=True)` | `get_spec()` — the file holds the expanded values |
| `Dat.manager.sync_folder` | `Dat.manager.dat_folder` |
| implicit config on import | first use reads it; `do.configure()` for a chosen one |
| config `mount_commands:` | `do.mount(...)` calls in your program; `run: python -m mypkg.main` for the shell |
| `do.mount_all(cmds, relative_to)` | the `do.mount(...)` calls themselves |
| `bin/X TARGET` | `bin/dat TARGET` — the same word as the console script |

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
