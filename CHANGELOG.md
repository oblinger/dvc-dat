# Changelog

Every user-visible change to `dvc_dat`, newest first.

## Versioning

[Semver](https://semver.org): a change to the public contract (`Dat.create/load/run`, the `_spec_.yaml` format, do-system resolution, the CLI) is **major**; a new capability that leaves every existing consumer working is **minor**; a fix is **patch**. `__version__` lives in `dvc_dat/__init__.py`.

## Unreleased

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
