# Changelog

Every user-visible change to `dvc_dat`, newest first.

## Versioning

[Semver](https://semver.org): a change to the public contract (`Dat.create/load/run`, the `_spec_.yaml` format, do-system resolution, the CLI) is **major**; a new capability that leaves every existing consumer working is **minor**; a fix is **patch**. `__version__` lives in `dvc_dat/__init__.py`.

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
