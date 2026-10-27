:>> [DAT](../DAT%20Track/DAT.md) → [Modules dat](ha://p/Modules%20dat) 
# dvc_dat: the dat manager
A dat is a folder whose `_spec_.yaml` is a complete, argumentless recipe
for itself and whose `_result_.yaml` holds what running it produced,
sealed under a content hash. A `DatManager` is a world of dats: the
folders it searches and writes, the artifact store beside them, and a
`do` namespace that names things and runs specs; every load inside a
run goes through it, so dependencies are captured rather than declared.
The code is `dvc_dat/core.py` (`Dat`, `DatContainer`, `DatManager`) and
`dvc_dat/do.py` (`Do`), exported as `from dvc_dat import Dat,
DatContainer, DatManager, Do`. Part of the
[architecture](../DAT%20Architecture.md); a `Dat` is also a ledger value,
`ledger.Dat` the same class ([DAT Ledger](ledger/DAT%20Ledger.md), DAT 1038).

## Public surface

`DatManager`:

- `DatManager(*, dat_folders, art_folder=None, index=None, do=None,
  verify=False)`: dat folders searched in order, the first written to;
  `dat_folders` not a non-empty list, or an artifact folder nested with
  a dat folder, is `TypeError`/`ValueError`. Reads nothing from disk.
- `DatManager.load_dat_config(start=None, *, do=None) -> DatManager`:
  from the nearest `.datconfig.yaml` walking up from `start`, then
  `.datconfig.override.yaml`, then `DAT_FOLDERS` (one folder, not split) / `DAT_ART_FOLDER`; an
  unknown key `ValueError`; `manager:` names a subclass to build.
- `create(spec=None, *, path=None) -> Dat`: merge `dat.base`,
  validate, place, expand every `{}` once, write `_spec_.yaml`; an
  existing folder follows `dat.target_exists` (`FileExistsError` by
  default); a bad spec `TypeError`.
- `load(name, *, cache_after_load=True, verify=None)`: a dat (as its
  `dat.kind` class) or an artifact (through its recorded type), by
  name or `sha256:` URN; missing `KeyError`/`FileNotFoundError`; a name
  held by both `ValueError`; a hash mismatch under `verify`
  `ValueError`.
- `load_path(name, *, verify=None) -> Path`, `exists(name) -> bool`,
  `reindex() -> int`.
- `save_artifact(source, *, type=None, name=None, link=False) -> str`:
  store a file or folder, return its URN; a name already a dat's, or an
  existing artifact name, `FileExistsError`.
- `load_artifact(name, *, verify=None)`: an artifact only; a dat's name
  `KeyError`.
- `standing(name) -> str | None`: `rolling`, `open`, `sealed`,
  `referenceable`, or `None` when nothing is stored.
- `recording(dat)` (context manager), `record_dependency(name,
  sha256=None)` (`RuntimeError` when nothing records), `roots(deps)`,
  `code_of(fn) -> {branch, commit, dirty} | None`; `dirty` skips paths
  the repo's `.gitattributes` marks `dat-noncode` (`CODE_PATHSPEC`).
- `run(target, *args, **kwargs)`: the one run, fixed (2.35). A
  callable is called; a template spec (or its name) is forked into a new
  dat that runs; a `Dat` runs in place, or forks with arguments. A dat's
  run (private `_execute`) calls `fn(dat, *args, **kwargs)` for
  `dat.do`, inside `recording(dat)`, in a fresh `run/` sub-dat with
  `run/work/` as cwd; a sealed dat `RuntimeError`; a non-callable
  `dat.do` `TypeError`; a `referenceable` demand unmet `RuntimeError`;
  each re-raised as `Exception("In <target>")`.
- `expand(text, vars=None)`, `expand_spec(spec, vars=None)`: the `{}`
  grammar through this manager's `do`; `expand_spec` first merges the
  spec over its `dat.base` chain.
- `do`: the manager's `Do`, its only other public attribute.

`Dat`:

- `Dat.manager` (class, assignable; built on first read from
  `load_dat_config()`), `Dat.do` (forwards to `Dat.manager.do`; not callable).
- `Dat.load(name_or_path, *, cache_after_load=True)`,
  `Dat.create(path=None, spec=None)`: in the default world; a
  `dat.kind` outside `cls` is `TypeError`.
- `get_spec()`, `get_results()`, `get_path()`, `get_path_name()`,
  `run` (the `run/` sub-dat or `None`), `manager`.
- `save()`: stamp `dat.sha256` and `dat.standing`; the first save that
  counts seals; inside its own run a checkpoint (`open`) with the seal
  at return; a sealed dat `RuntimeError`.
- `verify() -> bool`, `delete(*, must_exist=True)`, `copy(new_path, *,
  run=True)`, `move(new_path)`.
- `validate_spec(spec)` (classmethod, a subclass's hook),
  `get(source, keys, default)`, `set(source, keys, value)`,
  `cli_main(argv=None, *, config=None) -> int`, `standing`,
  `save_artifact`, `load_artifact` (the default world's).

`DatContainer(Dat)`: `get_dat_paths()` and `get_dats()`, the dats in
its folder, lazily, a child's `run/` skipped.

`Do` (a namespace, not callable):
`load(dotted, *, default, kind)`, `name_of(obj)`,
`keys()`, `mount(*, folder, file, module, value, at, relative_to)`
(`ValueError` when a mounted name would shadow an importable one).

Module functions: `merge_dicts`, `expand`, `expand_spec`.

## Invariants

- The spec on disk is a record: every `{}` is expanded once at create,
  except `dat.name`, which keeps the path template (never the path it
  expanded to), and call-site arguments go into a new spec.
- A sealed (or referenceable) dat is never rewritten: `save` and
  `run` refuse it.
- `dat.sha256` hashes the folder without `run/`; a run is not content.
- Standing is the least of the inputs', capped at `sealed` by dirty
  code or code outside a checkout.
- Dats and artifacts share one namespace and one index.

## Left to other modules

The ledger (history, values, `run`) is
[`dvc_dat.ledger`](ledger/DAT%20Ledger.md);
the command line is `dvc_dat.do.cli_main`, reached by `just run`
(`dvc_dat.just`) and `bin/x`
([Command Line](../cli.md)); tabulating dats into DataFrames and Excel
is `dvc_dat/dat_tools.py`; the spec format is
[Spec Format](../spec-format.md).
