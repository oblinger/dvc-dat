# Changelog

Every user-visible change to `dvc_dat`, newest first.

## Versioning

[Semver](https://semver.org). A major marks a different DAT and is cut only by the owner, never by an agent: 1.x is the original DAT, 2.x is DAT with the ledger. A minor is a notable capability, one per run of related changes and cut by a release PR, not per feature PR. Everything else is a patch. `__version__` lives in `dvc_dat/__init__.py`.

## 2.30.0 — 2026-10-26

- **One `rev.run` for a ledger function and a dat; `rev.resolve` names through the ledger's mounts (DAT 1046).** A dat run is a ledger-function call. `rev.run(target, /, *, seal, clean, path, **kwargs)` takes a ledger function's dotted name (the kwargs its keys), a spec dict, or a dotted name of a spec (a mounted `.yaml`/`.json`, a literal dict in a mounted module, an imported dict) or of a dat's run function (the spec `{dat: {do: <name>}}`), the kwargs merged into `dat.kwargs`. A dat's memo key is the spec with `dat.base` merged, `dat.kind` set, every `{}` expanded once through the ledger's namespace and `dat.name` removed; its run function is an `Fn` of the new `kind` `"dat"`, called with that key through the one `Fn.__call__` (lookup, miss, seal, place) and the one worker loop (`run_here`, whose dat branch creates the dat in the work folder and runs it). `Fn.kind` is read off the function: `"ledger"` for a `@ledger_fn`, `"dat"` for an undecorated one, which runs only through a spec (a direct call is `TypeError`). `rev.resolve(name)` is what a dotted name denotes at the revision: the `db/mount` rows longest prefix first; a mounted data file a dict, a mounted function its `Fn` (read off the file, never imported here), a mounted literal its value; a name under no mount imported, a `@ledger_fn` its `Fn`. In a project whose `.datconfig.yaml` names a ledger, `Dat.manager.do` is a `LedgerDo` (exported from `dvc_dat.ledger`): the `Do` interface answered from the ledger's mounts at the head, `mount` refused (`TypeError`), so a ledger project names things once, in `db/mount` rows (`mounts:` in the config); a project with no `ledger:` key keeps the plain `Do`. A plain `Dat.do` of a mounted run function in a ledger project runs it in the calling process, imported through the mounts, nothing memoised. `just run` in a ledger project is `rev.run` for every target, and `.dat/targets.just` reads `@command` functions and `command:` specs off the mounted files. Memo entries are unchanged. **Removed, no alias:** `rev.dat_run` (into `rev.run`), `rev.load_fn` (into `rev.resolve`), `sandbox.run_dat_sandboxed`, `sandbox.load_mounted_run`, `sandbox.run_dat_here`, the worker's `dat_run` op, `rundat._RunName`, `rundat.run_fn`, `rundat.question_of` (the memo key is `rundat.memo_key`). The ledger notebooks read `rev.resolve`; ledger-just mounts `demo_game.etl` on the ledger instead of `Dat.do.mount` in its main, so `train` runs sandboxed.
## 2.29.1 — 2026-10-26

- **Discovery no longer reports a deleted checkout when a live one shares its name (DAT 1023).** `env.discover()` skips module folders and checkouts that no longer exist; before, a deleted checkout's modules lingering in `sys.modules`, with its toplevel cached, could win the name (a notebook re-run resolved the previous run's deleted scratch checkout, `commit=None`). Of two existing checkouts with one name, the one the most recently imported module was loaded from wins, not the one whose path sorts last.

## 2.29.0 — 2026-10-26

- **`rev.do` is now `rev.dat_run`, and a mounted dat run function runs in the sandbox worker (DAT 1045).** `rev.dat_run(target, **kwargs)` is the run function executed for a dat through the ledger, parallel to `rev.run` for a `@ledger_fn`; `rev.do` is gone, with no alias. A run function under a `db/mount` now runs as a mounted ledger function does: imported in a forked `python -I` child from the mounted tree (never in the calling process), its body confined to the mounts, the dats and its work folder, its `code` item the modules it loaded, provenance `eval:sandbox`. It no longer records `code/<repo>`, so a commit that changes no file the run loaded leaves the next call a hit, and the in-process import no longer has to be the mounted file. The child builds its dat world from the caller's dat folders, art folder and index; names mounted with `Dat.do.mount` are resolved before the spec is shipped. An installed (unmounted) run function still runs in the calling process, recording `code/<repo>`.

## 2.28.0 — 2026-10-25

- **A dat is a ledger value: `dvc_dat.Dat` and `dvc_dat.ledger.Dat` are one class, and `rev.do(spec)` runs a dat through the ledger (DAT 1038).** `Dat` now subclasses `Value` and carries the folder codec (the manifest encoding, the art-store parts, `decode`, `sealed_at_path`, `kind_ok`, `spec_kind`) that the ledger's separate `Dat` held; that class is removed, and `dvc_dat.ledger.Dat` is `dvc_dat.Dat`. A dat made by `Dat.create`/`Dat.do` seals with no subclass once saved (`dat.seal(t, name="table/12")`; an open dat is `ValueError` naming `dat.save()`), loads back with `get_spec()`, `get_results()` and its files, and is found by `values(kind=Dat)`: its `db/value` kind is its `dat.kind`, and its preds default to the spec's scalar `dat.kwargs` and the results' scalar top-level entries (`@ledger_class(preds=...)` adds names). `Dat(path)` is the dat already in a folder. `rev.do(target, **kwargs)` is `Dat.do` memoised: the question is the expanded spec without `dat.name`, the code the run function's module (`db/fn` its dotted name, `db/returns` the dat's class), a hit the sealed dat at its name, a miss created, run and sealed; a `@ledger_fn` target is `TypeError`. In a ledger project `just run specs.table12` is `rev.do` and prints `ran`/`hit`; a spec with `command: true` mounted from a folder is `just table12`. The q-dats and q-cli sheets drop `TableDat` and `table_dat.py` for `table12_dat.seal(t)` and `L.at().do("specs.table12")`.

## 2.27.0 — 2026-10-25

- **The version clock is per package at `db/repo/<repo>/<package>`, the commit per repo at `db/repo/<repo>` (DAT 1044).** Every subject the ledger writes itself lives under `db/`, and now the code clocks do too. A clean seal reads `db/repo/<repo>/<package> version` for the package whose `__version__` the run's code declared (the new read-only `Code.package`: the mount prefix for mounted code, the top-level package for installed code, `None` when the version came from a commit or the hash): absent or lower, it adds the version; equal, nothing; higher, a warning naming that subject. It adds `db/repo/<repo> commit` whenever the clean run's commit differs from the row, so the commit follows the latest clean run of any package in the repo. Two versioned packages in one checkout keep two clocks and no longer warn about each other. `clean=True` and `NotClean` read and name `db/repo/<repo>`. A warning raised while sealing in the sandboxed worker now reaches the caller as a `warnings.warn`, not only the worker's stderr. `SourceBump` gains `package`, the dotted root whose `__version__` it edited. The dependency item keeps its label `code/<repo>` and its 8-hex commit. **Removed, no alias:** the `code/<repo>` subject; nothing writes or reads it, and `bump` refuses `db/repo/` subjects instead, naming both new subjects. The sheets read the new subjects (q-cli and ledger-just `just history db/repo/<repo>/<package>`; ledger-dats, demo-etl, q-dats, q-triples, ledger-triples); q-values drops its shared-clock warning and prints both packages' clocks.

## 2.26.0 — 2026-10-25

- **`bump_source` edits the source `__version__`; a clean seal moves the `code/<repo>` clock (DAT 1043).** A code version lives in its source: the new `bump_source(module, part="patch", *, confirm=None) -> SourceBump`, exported from `dvc_dat.ledger` with `SourceBump(module, old, new, path, repo)`, rewrites the one `__version__ = "X.Y.Z"` line innermost on the module's dotted path (the module's file, then each enclosing package's `__init__.py`; a mount root declaring its own wins), `minor`/`major` behind `confirm`, and never commits or touches a ledger. The `code/<repo>` `version` and `commit` rows are now the version runs were exposed to: a seal involving a function (a run's memo entry, a hand seal with an `Fn` dep) whose `Code.version` is plain `MAJOR.MINOR.PATCH` adds both when the row is absent or lower, writes nothing when equal, and warns when the row is higher. A declared version counts only from a clean checkout: with modified tracked files `Code.version` is `<commit 8>+dirty` (mounted and installed), so a dirty run never moves the clock. **Removed, no alias:** `bump`'s `code/` form; `bump(t, "code/<repo>")` is `TypeError` naming `just bump <module>`. The `just bump` recipe takes a module (`just bump mymodule` prints the edit and a `git commit` hint), `db` (the release) or a slashed clock subject; the `code` shorthand is gone. The demo packages (`demo_game`, `demo_game.etl`, `comfort`, the sheets' `mymodule`) declare `__version__ = "0.1.0"`; demo-etl, ledger-dats, q-dats and q-cli Setup drop their clock-starting bumps and print the clock the first run wrote; q-cli Releasing and ledger-just show `just bump`, a commit, a run and `just history code/<repo>`; ledger-dats shows the dirty rule; ledger-triples' refusal cell is the new `TypeError`; q-triples runs a function to write the clock; q-values notes the shared-clock warning for its two packages in one checkout.

## 2.25.0 — 2026-10-25

- **`t.previous_rev` under `lock=` replaces `t.base`; the read-then-write helpers refuse an unlocked body (DAT 1039).** A transaction has a revision's read operators through `t.previous_rev`, bound to the previous revision: the top as it stands while the write lock holds. It exists only under `lock=`, since an unlocked transaction has no well-defined previous revision; unlocked, reading it raises the new `Unlocked(LedgerError, RuntimeError)`, exported from `dvc_dat.ledger`. `bump`, the record write `t[s] = {...}`, `del t[s, p]` and `del t[s]` read through it, so unlocked they raise `Unlocked` and write nothing. `t[s, p] = o`, `t.add`, `t.remove` and `v.seal(t)` need no lock (declarations and seal checks read a snapshot taken at open). **Removed, no alias:** `Transaction.base`. Every demo transaction that bumps, writes a record or deletes takes `lock=10` (demo-etl, ledger-dats, ledger-just and its `ledger_recipes.py` bump recipe, ledger-triples, ledger-values, q-just, q-triples); ledger-triples and q-triples teach the lock: a body reads a record through `t.previous_rev`, adds an official and writes it back, the unlocked read is refused with `Unlocked`, and `t[s, p] = o` and `t.add` run unlocked.

## 2.24.0 — 2026-10-25

- **The snapshot owns identity; a fn is a name inside its `Code` (DAT 1037).** `Code` gets `hash` and `subject`: its `encode()` is the identity, the canonical `{"modules": relpath -> sha256, "mounts": <mounts hash or null>}`, `hash` its sha256 and `subject` `db/code/<16 hex>`, the same 16 hex the memo key carried as `db/fn/<name>/<16 hex>` (equal whenever the module set is the same: a sandboxed run's, and installed code whose package sits at its checkout's root). `version`, `commit`, `lock`, `sandboxed` and `mounts` describe it and are not hashed; the `#hash8` version fallback is `#` + 8 hex of `code.hash`. **Removed, no alias:** `Fn.subject` and `Fn.sha`; a function has `name` and `code`. **Memo layout:** an entry keeps `db/fn` (the dotted name), `db/keys`, `db/value`, `db/deps/*`, plus `db/returns` (moved from the fn item); the code item is `db/code/<16 hex>` with `db/modules` and `db/mounts`, written once and shared by every function and result in that snapshot (the `db/name`, `db/module`, `db/sha` rows are gone). **Dependencies:** `code: db/code/<16 hex>` and `fn: <dotted name>` replace `fn: db/fn/<name>/<16 hex>`; `code/<repo>` is unchanged; `matches` re-hashes the `code` item for the function `fn` names. An `Fn` dep of a hand seal writes both rows; a seal record holds `{"fn", "code", "rows"}`. Entries saved before 2.24 name `db/fn/…` and miss once. Print forms unchanged. q-values prints `dependencies["code"]` and `dependencies["fn"]`; ledger-values, ledger-dats, q-dats and demo-etl read the `code` item.

## 2.23.0 — 2026-10-24

- **`fn.code`: a fn says its code's version and whether it is boxed (DAT 1037).** Every `Fn` carries `code`, a `Code(Value)` computed at `load_fn` (not written to the ledger): named `<unit>@<version>`, the unit the mount prefix for mounted code (`plane`) or the top-level package for installed code (`geometry`); read-only `sandboxed`, `version`, `modules`, `mounts`, `commit`, `lock` (the blob id of the checkout's `uv.lock`). The version is read as a module attribute after import: mounted, the root package's `__version__` (imported in a forked worker child), else the last commit touching the loaded files (8 hex, `+dirty`), else `#` + 8 hex of `fn.sha`; installed, `__version__`, else the distribution's version, else the checkout's commit (`+dirty`), else `#sha8`. `str(fn)` is `plane.measure.length@2.7.1`, `repr(fn)` `<Fn plane.measure.length@2.7.1>`, `repr(fn.code)` `<Code plane@2.7.1>`. **Removed:** `Fn.mode` and the `db/mode` row (the `db/mounts` row, `none` or the mounts hash, already says it). **Renamed:** the environment test seam `dvc_dat.ledger.Code` (one repo's checkout) is `Checkout`, freeing `Code`. `fn.sha`, `fn.subject`, memo keys and dependencies are unchanged. q-values prints both fns and their code; ledger-values, ledger-dats and demo-etl drop `mode`.

## 2.22.1 — 2026-10-24

- **print forms: `<Type label>` repr, bare label str, `#hash8` for unnamed (DAT 1036).** The label is the name at the head, else `#` + the hash's first 8 hex (was the bare 8 hex). A saved value reprs `<Video video/G1>` / `<Video #2db69ce1>`; one sealed locally `<Clip sealed #2db69ce1>` (was `<Clip sealed, saved nowhere>`); a draft `<Clip draft>` (was `<Clip unsealed>`; a draft `Value.Blob` was `Value.Blob(obj)`). A `Ref` reprs `<Ref video/G1>` / `<Ref #2db69ce1>`, an unresolved one included (was the bare name, or `ref:cls:hash8`). A `Fn` reprs `<Fn clips.clip @bab09325>`, `@` + the first 8 hex of the hash ending its `db/fn/<name>/<hash>` subject. `str` is the bare label (`video/G1`, `#2db69ce1`, `clips.clip`; a draft has none and prints its repr). `display_name` and `Ref.name` return the new label; `bump`'s alias refusal names `#hash8`. Demos re-executed; the ledger-just recipes print `#hash8` too.

## 2.22.0 — 2026-10-24

- **`seal=` replaces `memo=` on a run (DAT 1028).** `Fn.__call__(*, seal=…, clean, path, kwargs, **keys)` and `Rev.run(name, *, seal=…, clean, **keys)`: the value of `seal` is where the result goes. `"get"`: the saved result or `None`, never runs (was `memo="get"`). `False`: run, keep nothing, the trace on the result (was `memo=False`). `True`: run and seal locally, off the ledger (new). A `Ledger`, by default the one the function was loaded from: the memo hit, else run and save the memo entry in a transaction of its own (was `memo=True`). An open `Transaction`: the same, saved into it atomically with whatever else it writes (new). Another ledger or any other value is `ValueError`. `memo` is no longer a control option, with no alias: a call passing `memo=` binds it as a key. `kwargs=` still carries a key named `seal`.
- **`v.seal(x)` takes the same `x`.** `v.seal()` is `v.seal(True)`; `v.seal(t, name=…)` and `v.seal(L)` save; `v.seal(False)` and `v.seal("get")` are `TypeError`.
- **A draft keeps its provenance.** Every run attaches its trace (fn, keys, `code/<repo>`, platform, every read) to its result at every level, and the seal record of a `seal=True` result carries it. Saving a draft or a locally sealed result later writes the full memo entry (`db/fn`, `db/keys`, `db/deps/*`), so the next identical call hits; before, a hand seal of a `memo=False` result recorded only code and platform and was no memo entry. A late save of an unsandboxed result checks the code: not run dirty, and the checkout clean at the trace's commit, else `NotEvaluated`. A hand-built value seals as before.
- `do.py`'s `just run` asks `fn(seal="get", …)` first. Demos (q-values, ledger-values, ledger-just) and the Ledger page use `seal=`; q-values keeps its draft with `.seal(t, name=…)` instead of re-running.

## 2.21.0 — 2026-10-23

- **`Value.dependencies` replaces `Value.trace` (T035).** The mapping of what producing a value read is `v.dependencies`, its type `Value.Dependencies`, and its rows `db/deps/<item>` (were `db/trace/<item>`). "Trace" stays the verb: a recording `Rev` traces reads into the dependencies; `UntracedRead` and `dvc_dat.ledger.trace` keep their names. No alias for the old names.
- **The unsandboxed mode is named `unsandboxed` (T034).** `Fn.mode`, the `db/mode` row and provenance read `unsandboxed` / `eval:unsandboxed` (were `base` / `eval:base`).
- **The `code/<repo>` dependency item is the commit alone (T034):** `<commit8>`, was `<version>+<commit8>`; the version stays readable from the `code/<repo>` rows at the revision. `code_token(env_commit)` takes the commit only.
- Entries sealed before 2.21 carry `db/trace/` rows and old tokens, so a lookup no longer finds them: they recompute once.

## 2.20.0 — 2026-10-22

- **`Rev.run` is the ledger's evaluation verb, matching `just run`.** `rev.run(name, /, *, memo=True, clean=False, **keys)` is `rev.eval` renamed, same behaviour and signature: the API form of `just run NAME KEY=VALUE`. `rev.eval` remains a deprecated alias that warns (`DeprecationWarning`) and forwards; it goes at the next major. Docs, demos and tests use `run`. Stored names are unchanged: trace items stay `eval:<name>{keys}` and provenance `eval:base` / `eval:sandbox`, so every sealed entry still hits.

## 2.19.1 — 2026-10-21

- **With a `ledger:` line, `just run` runs through the ledger** (F447 Q40 (A)). `x TARGET k=v …` is `rev.eval` of the ledger function TARGET names: a dotted function, a mounted name, or a spec file (`.yaml`/`.json`) whose `main` names it, the line's keys over the file's (`--set`/`--json` update a spec's). Found if computed before from the same inputs by the same code, else run and sealed; it prints `hit` or `ran`, the value and its preds. `alias=NAME` names the result (`path=`). A target that is not a ledger function is refused, positional arguments too; without a `ledger:` line nothing changes. `.datconfig.yaml` accepts the ledger's keys `ledger:` and `mounts:` (a ledger project's config was refused by `DatManager.load_dat_config`).
- **`@command` and `.dat/targets.just`** (A64, A65, A67). `from dvc_dat.just import command`; `@command(args="k=…", help="…")` marks a function a command (a spec by `command: true` or `command: {args, help}`), `args` at most 24 characters and `help` one or two lines of at most 56, else `ValueError` at import. A justfile holding `import? '.dat/targets.just'` gets one recipe per mounted command, written beside `.datconfig.yaml` by `run` when the file is older than the config, the justfile or a mounted source; `just NAME k=v` is `just run TARGET k=v`, listed by `just --list` in group `run` with its args and help. A name the justfile already has is skipped and said so on stderr. The `run` recipe now also exports `DAT_JUSTFILE`. The sandbox's warm server preloads `dvc_dat.just`, so a mounted module may carry `@command`.
- **ledger-just runs through `just run`.** The demo justfile drops its `eval` and `run` recipes and is imported by the demo project's justfile beside `dvc_dat.just`; `just run demo_game.game.cut …`, `just run model-G1.yaml alias=model/prod` (its `main` now `demo_game.etl.model.train`) and `just train game=G1` (a hit) replace them. `demo_game.etl.model.train` carries `@command`; `demo_game/demo_main.py` mounts it.

## 2.19.0 — 2026-10-21

- **`just run` is the one way to run; `x` is its sugar; `dat` is gone** (F447 Q40, A69). `dvc_dat/dvc_dat.just` (shipped in the package) holds the recipes `run` (the old `bin/dat` bootstrap: the `.datconfig.yaml` walk, `$DAT_RUN` / `run:` / `.venv` / `python3`, `DAT_CLI_CONFIG`, the config folder on `PYTHONPATH`, exit 3 with no config) and `mounts` (`--list`); a project's justfile imports it. `bin/x` is `exec just run "$@"`. `bin/dat` and the `dat` console script are removed; `python -m dvc_dat` remains the library's own command line. Error lines start `run:`.
- **A sandboxed lookup compares the modules' bytes as they are now** (Q39). A lookup no longer re-hashes mounted modules at the rev's `code/<repo>` commit, so editing a loaded module, committed or not, recomputes with no `bump`. `demo-etl`'s "Changing one stage's code" drops its `bump`: binning 0, cumulative 0, podium 1.
- **A value has one name; `path=` gives it** (F447 Q36, A70). `Value.name` is the value's one alias, relative to the data folder (`<art store>/dats`), not part of its hash: `Value(name=...)` (and `Pickled(obj, name=...)`, `Table`, `Dat`) names it at its save, assigning `v.name` on a saved value moves it. Naming retracts the value's other names and moves the name off any value it named. A value prints as its name, else a hash prefix (superseding A25's shortest alias). `eval`'s `path=` is a control option, never hashed: relative, the result's name, a `Dat`'s folder rebuilt there as a view (hardlinks into the store), and a hit asked for under a new name takes it; absolute, the folder is made there and nothing is named. A function that builds a folder declares `path: Path` (replacing `work`); with no `path=`, its `Dat` result is named by that parameter's default as a path template expanded with the keys, else `anonymous/Dat{unique}`. The sandbox's messages say "path folder".
- **`kwargs=` and exactly four control options** (Q41). `memo=`, `clean=`, `path=`, `kwargs=` are the control options of `Fn.__call__` and `rev.eval`; `f(kwargs={...})` passes the whole key set, so a function may declare a key named like a control option; inline keys beside `kwargs=` are `TypeError`.
- **A dat's spec stores its path template, never the path it expanded to** (Q36). `DatManager.create` keeps `dat.name` as given (`path`, else the spec's own; a constant path is its own template); the folder is the dat's name (`get_path_name()`).
- **A sandboxed entry is keyed on exactly the modules it loaded.** Its `fn` item holds every module the run loaded, third-party ones included: a mounted module (with the static import closure) by the bytes of its file as read, a module of an installed distribution as `dist:<name>` → `<version>:<sha256 of its RECORD>`, any other (the standard library, an editable source) as `py:<path>` → the file's sha256. A lookup re-hashes exactly those, so one changed byte in a loaded module is a different value and an edit to a module the run never loaded moves nothing. The whole-`uv.lock` trace item is gone from every trace (base, sandbox, hand seal), and `Env` has no `lock` (`Env(code, platform, mounts=None)`).
- **A fresh process per sandboxed call.** One warm `python -I` server per environment, holding only the ledger's machinery (no mounted module, no CUDA), forks a child for each call; nothing a body loaded or changed outlives it. This replaces the warm per-mount worker and its per-call purge of mounted modules.
- **A sandboxed miss runs at HEAD, clean or dirty** (F447 Q39 (A)). `clean=True` on `Fn.__call__` and `rev.eval` asks for a clean checkout at the commit the rev's `code/<repo>` row names, in either mode, checked before the lookup, else `NotClean`, a new `NotEvaluated` subclass. Base mode keeps its gate: a miss needs a clean checkout. `clean` is reserved and never a key.

## 2.18.1 — 2026-10-21

- **A sandboxed body's first traced read works in a fresh worker.** With dvc-dat installed editable, a body whose first read was `rev.all` (or any read that first imports `dvc_dat.ledger.trace`) failed with `ModuleNotFoundError`: the read guard refused the import system's listing of the editable source folder. The worker now imports `trace` before the guard goes up.
- **`demo-etl` is the ETL chain on the ledger.** A dataset per game, a game set as rows, a binning per game, a cumulative binning built recursively, and a podium; each section changes one thing (a game added, a game replaced, a game's data, one stage's code) and counts what ran. The hand-made gamey/trial/metrics kinds it replaces (`demo_kinds/etl.py`) are removed.

## 2.18.0 — 2026-10-21

- **Renumbered: 3.0.0 through 6.3.0 were all the ledger build-out of 2.x.** Those releases were cut as four majors in two weeks while one refactor reshaped the ledger; none made DAT a different thing. Their tags are renamed below and point at the same commits; no history was rewritten. Each commit's own `__version__` and changelog text still say the old number. A lock that pins an old tag with its commit (`rev=v6.3.0#<sha>`) still installs, because the installer fetches by commit. The changelog sections 5.1.0, 5.2.0 and 6.0.0 were never tagged.

| Published tag | Now |
|---|---|
| v3.0.0 | v2.18.0-rc.1 |
| v3.0.1 | v2.18.0-rc.2 |
| v4.0.0 | v2.18.0-rc.3 |
| v5.0.0 | v2.18.0-rc.4 |
| v6.1.0 | v2.18.0-rc.5 |
| v6.2.0 | v2.18.0-rc.6 |
| v6.2.1 | v2.18.0-rc.7 |
| v6.3.0 | v2.18.0-rc.8 |

- **The ledger demo follows 2.18's API.** `doc/DAT Demos/ledger-just.py` runs first, then lists, then updates, with one sentence per verb, and seals values with `v.seal(t)`.
- **Docs match the code.** `load_artifact`, `DAT_FOLDERS`, the spec-format's dependency keys, and the ledger module pages were corrected against the source; version-history notes left the module pages and docstrings.

## 2.18.0-rc.8 (published as 6.3.0) — 2026-10-20

- **A seal persists.** Every `v.seal()`, kept or not, writes a seal
  record, `sealed/<entry>.json` in the kept folder (`$DAT_KEPT`, else
  `~/.cache/dvc-dat/kept`): hash, kind, time, a `Dat`'s folder
  (`path`), deps (`ref:` texts with subject, hash and name), provenance,
  preds, environment, `kept`, size. Until 6.2 the seal lived on the
  object, so only the sealing process could save it (sv-pipe kept its
  own `<root>/.sealed/<name>.json` to bridge that; it can go).
- **`Dat.sealed_at_path(path, *, name=None)`** reopens the last seal of
  a folder in any later process; `v.seal(t)` on it saves exactly as
  the sealing process would have (same subject; `SealBroken` on a
  changed byte unless kept; the kept bytes when kept). `name=` is the
  alias it will be saved under: a value sealed with it as a dep before
  it is saved binds the dep through that name at its own save (refused
  until the name holds those bytes), as a `Ref` by that name would.
- **`keep=True` clones.** A kept part is a copy-on-write clone where the
  filesystem can (macOS APFS `clonefile`, Linux reflink `FICLONE`),
  else a streaming copy as before; never a hardlink. A clone costs no
  disk and an in-place edit of the source never reaches it, so
  `keep=True` is free on the laptop: measured, a 1 GiB file kept on
  APFS by clone, free space unchanged within noise, the kept bytes
  unchanged after the source is edited in place
  (`tests/ledger/test_seal_record.py`). `place(..., clone_ok=True)`
  and `store.clone(src, dest)` are the mechanism.
- **`just sealed`** lists every seal never saved, kept or not (`kept`
  marks the kept ones); `purge` drops records, then blobs no record
  names (older than an hour, as before). A save drops its record at
  commit; a new unkept seal of a folder replaces that folder's unkept
  records. `Kept.put` is now `Kept.seal(record, data=None, parts=())`;
  `Kept.for_path(path)` is the latest record of a folder.
- **The loaded-value cache rechecks a `Dat`'s folder.** `Ref.load`
  hands back a cached `Dat` only while its folder is still there and
  the same directory (device and inode); a folder moved or replaced
  since is loaded afresh.

## 2.18.0-rc.7 (published as 6.2.1) — 2026-10-20

- **A repo marks what is not code.** The dirty flag of `dat.code`
  (`_code_of`) and of the ledger's discovered `Code` reads `git status`
  over `CODE_PATHSPEC` — the whole tree less every path the repo's
  `.gitattributes` gives the `dat-noncode` attribute. With `doc/**
  dat-noncode`, an edit under `doc/` leaves the checkout clean, so a
  tool that rewrites docs no longer caps a run at `sealed` or refuses a
  `referenceable` demand; an edit to code still reads dirty. A repo with
  no such attribute reads as before (sv-pipe T560).

## 2.18.0-rc.6 (published as 6.2.0) — 2026-10-20

- **A `Dat` streams.** `Value._parts()` yields `(sha256, source)`, the
  source a `Path` or a zero-arg opener; a `Dat` hashes each file in
  1 MiB blocks and caches the per-file hashes (keyed by size, mtime,
  inode), so no file is held in memory whole. `ArtStore.put_path(source,
  h)` hardlinks a part on the same filesystem, else streams a checked
  copy to a temp name and renames; `get_to(h, dest)` places one back the
  same way; `exists(h)`; `put(bytes)` stays for small values. A save
  stores one value and one part at a time, checking only the encoding
  (the manifest) for determinism; `v.seal(keep=True)` streams the parts
  into the kept cache as copies (an in-place write to the source cannot
  reach them), and the save hardlinks the kept blobs into the art
  store. Measured: a 2 GB three-file folder seals with `keep=True` and
  saves to a SQLite ledger with 3.8 MB of RSS growth
  (`tests/ledger/test_stream.py`, `DAT_SLOW=1`). The files of a saved
  or loaded `Dat` share inodes with the store: seal a new folder, never
  edit one in place (sv-pipe T543 § 3.1).
- **`decode(data, store, *, name=None)`.** `Ref.load` passes the alias
  it was made by to a `decode` that accepts `name=`; a `Dat` loaded by
  a name materialises under `art/dats/<name>/` (replaced when the alias
  now names other content), by its subject under `art/dats/<16 hex>/`.
- **`Dat.kind_ok(kind)`**, a classmethod: the load's `_spec_` kind
  check asks it (default: the class's dotted or bare name), so a
  subclass can accept another library's `dat.kind`.
- **`DAT_WORK`** names where an eval's `work` folders are made (default
  `~/.cache/dvc-dat/work`), so a GB-scale result is built on the
  filesystem it is saved to.
- **Every transaction is stamped `db/time`.** `time=` is gone: passing
  it is `TypeError` naming the change. Callers drop the keyword
  (sv-pipe: `svp/dat/gamesets.py`, `svp/just.py`,
  `scripts/gameset_migrate.py`, `tests/test_ledger.py`).
- **A `code/<repo>` commit row no longer gates a base eval** (sv-pipe
  T543 Q7 (C)). The row pins what the version means; a clean checkout
  at any commit evaluates, its trace token is `<row version>+<the
  environment's commit8>`, and the hit test compares the environment's
  commit, as it did with no row, so an entry holds at the commit it ran
  at. Fix in `code_token`: a hand seal at a later commit recorded the
  row's commit (false provenance). A sandboxed eval keeps the gate (its
  `fn` hashes modules at the row's commit).

## 2.18.0-rc.5 (published as 6.1.0) — 2026-10-20

- **`v.seal()` seals without a ledger; `v.seal(t)` saves it later.**
  With no target the seal freezes the preds and records the bytes'
  hash, deps, provenance, environment and time (`sealed_at`), writing
  nothing; `subject` stays `None`. A later `v.seal(t)` or `v.seal(L)`
  saves that state (the trace carries the seal's environment, a
  `db/sealed-at` row the time) and refuses with `SealBroken` when the
  bytes changed. `v.seal(keep=True)` copies the bytes into the kept
  cache (`$DAT_KEPT`, else `~/.cache/dvc-dat/kept`), so the source may
  change; `just sealed` lists what is kept and never saved, `just
  sealed purge [older=14d]` drops it (T543 Q4 (D)).
- `sealed` now means identity fixed; "in the ledger" is `subject is not
  None`. Every check that meant the latter reads `subject`.

## 6.0.0 (never tagged; within 2.18.0-rc) — 2026-10-20

- **`v.seal(t)` replaces `t.add_value(v)`; `t.add_value` is gone.**
  Same arguments (`deps`, `alias`, `provenance`), same subject, same
  refusals. `v.seal(L)` given a ledger opens and commits a one-value
  transaction of its own (`by=` names the writer; default the
  provenance, else `seal`); `v.seal(t)` joins a transaction already
  open. Breaking: every `add_value` caller moves (Dan 2026-10-20,
  sv-pipe T543 Q4).

## 5.2.0 (never tagged; within 2.18.0-rc) — 2026-10-19

- **`Ledger.close()`; a `Ledger` is a context manager.** Closes every
  reader connection the handle opened, in every thread (`Store.close()`
  on both stores); a later read reopens. Postgres handles no longer hold
  their connections until process exit.
- **Fix: `lock=` on Postgres.** The alarm interrupting a read in the
  body left that thread's reader connection mid-statement, so every
  later read failed ("another command is already in progress") and
  load workers died; the interrupted connection is now dropped. The
  base revision is read before the body's clock starts, and a failure
  there releases the lock.
- **Load numbers for Postgres and a floor (R0017).** The load harness
  takes a Postgres DSN; `tests/load/test_threshold.py` (`DAT_LOAD=1`)
  fails on any invariant failure or 4-process tx/s under half the
  recorded value; numbers in `doc/DAT Modules/ledger/store.md`
  § Measured.

## 5.1.0 (never tagged; within 2.18.0-rc) — 2026-10-19

- **A Postgres store behind the same ledger API (T542).** `Ledger(dsn)`,
  `DAT_LEDGER` or `.datconfig.yaml` `ledger:` naming
  `postgresql://…?art=<folder>` opens a ledger whose quads live in
  Postgres (one per schema; `options=-csearch_path%3D<schema>`) and whose
  art store stays the folder `art` names. Same rows, fold and tests as
  SQLite. Needs `pip install 'dvc_dat[pg]'` (psycopg 3). Differences:
  Postgres text cannot hold NUL, so a row carrying `\x00` is refused.
  The store interface is named (`Store`, `Writer`); the SQLite one is
  `SqliteStore`.

## 2.18.0-rc.4 (published as 5.0.0) — 2026-10-18

- **The ledger rebuilt to the value-space design (T534/T539); the 4.0 ledger
  is removed** (`Ledger.open`, `assign`, `last`, `objects`, `SqliteLedger`,
  the shelf and its artifact types). One constructor, `Ledger(path=None, *,
  create=False)`: a path, or the nearest `.datconfig.yaml` `ledger:` key, and
  nothing is made without `create=True`. Every fact is a quad
  `(rev, subject, predicate, object)`; `L.transaction(by=…)` writes one
  revision, `L.at(…)` returns a `Rev` every read goes through (`[]`, `get`,
  `all`, `asserted`, `rows`, `values`/`value`/`refs`/`select`). Values
  (`Value`, `Pickled`, `Table`, `Dat`, `@ledger_class(preds=…)`) are stored by
  content via `t.add_value`, named by alias, read back by `Ref(rev, name)`.
  Functions are `@ledger_fn`, resolved at a rev by `load_fn`; `rev.eval(name,
  **keys)` answers from the memo or runs and seals (`memo=False` runs
  regardless, `memo="get"` only looks). A function under a
  `db/mount/<prefix>` runs sandboxed in a worker, its reads traced and its
  writes confined; `bump` versions clocks. A new ledger's
  `db/format` is `dvc-dat-ledger/1`. Docs: `doc/DAT Architecture.md`,
  `doc/DAT Modules/ledger/`, the four `doc/DAT Demos/ledger-*` notebooks.
- **Python 3.11 is the floor; 3.8–3.10 dropped.** `requires-python = ">=3.11"`;
  CI runs 3.11 and 3.14 (Dan, 2026-10-17).
- The docs live in `doc/` (was `docs/`), the demo notebooks in `doc/DAT Demos/`
  (was `examples/`), each a jupytext pair; a `justfile` (`test`, `demo`, `docs`).

## 2.18.0-rc.3 (published as 4.0.0) — 2026-10-16

- **Ledger: a transaction is stamped with a UTC timestamp, not a day.** The
  row is `tx/<rev> time`, ISO 8601 to the microsecond; `Ledger.time(rev)`
  returns an aware UTC `datetime`. `Ledger.date(rev)` and the `tx/<rev> date`
  row are gone (major: a public accessor removed). A ledger written by 3.x
  keeps its `date` rows and `time(rev)` reads them as that day at 00:00 UTC.
  Dan, reading SVP's ledger demo: a day threw away when a write happened for
  nothing.

## 2.18.0-rc.2 (published as 3.0.1) — 2026-10-06

- Fix: `_hash_dat` given a `pathlib.Path` hashed `run/` in (the top-level
  check compared a `Path` with `os.walk`'s `str`) and returned a wrong hash
  with no error; found by SVP's first verify on a real box. `verify()` and
  the saves always passed a `str` and were right.

## 2.18.0-rc.1 (published as 3.0.0) — 2026-10-06

**A dat is its functional content; the run that made it is a sub-dat
inside it, outside the hash** (Dan, 2026-10-06, DAT F030 / SVP F358: "the
spec is the logical recipe; the run is procedural by nature"). A major:
`_result_.yaml` loses the run's keys.

- **`run/`**, a sub-dat every `execute` makes fresh inside the dat: its
  results hold `dat.run_at`, `dat.run_time`, `dat.host`, `dat.pid`,
  `dat.code` and `dat.content` (the `dat.sha256` the run sealed); its
  `work/` is the run's scratch and the working directory while the code
  runs. `dat.run` is the sub-dat, `None` for a dat filled by hand. A rolling
  dat's `run/` is replaced each time it runs. A run has no hash of its own
  and reads `dat.standing: sealed` once finished.
- **`dat.sha256` is the content hash**: `run/` left out, and `dat.name`
  left out of `_spec_.yaml`, which is hashed as its sorted-key dump. Two
  runs of one recipe hash the same when the code is functional, wherever and
  whenever they ran; a dat that differs from its twin wrote something
  undeclared. `dat.hash: functional` in `_result_.yaml` marks the rule; a
  file written before 3.0 carries no mark and keeps hashing by the 2.x rule,
  so every existing dat still verifies and the index holds.
- **`_result_.yaml` no longer holds `dat.run_at`, `dat.run_time` or
  `dat.code`** — read them from `dat.run.get_results()`. The seal still caps
  standing at `sealed` on dirty or uncheckouted code, read from the run.
- `Dat.copy(name, run=False)` copies the content only. A `DatContainer`
  does not list its dats' runs. `verify()` is unmoved by a rename or by
  anything under `run/`.

## 2.17.0 — 2026-09-28

**`dvc_dat.ledger`: the ledger beside the dat** (Dan with Juan, 2026-09-28:
a dat is space, the ledger is time). The generic core of SVP's `svp.ledger`,
under the names ruled on SVP T195. New subpackage; nothing existing changes.

- One append-only table of events `(added, rev, subject, predicate, object)`,
  one rev per transaction, the transaction's `by` and `date` as rows on
  `tx/<rev>`; every read a function of a rev.
- `Ledger`: `add`, `remove`, `transaction(by=)`, `rev()`,
  `query(s, p, o, rev=as-of, tx=one transaction)`; derived `assign` (was
  `set`), `held`, `history`, `last`, `objects`, `subjects(p, o)`, `get_spec`,
  `set_spec`, `exists`, `date`; `save`/`load`/`ref` for artifacts;
  `Ledger.open(profile)` from a `ledger.profile.yaml` or `DAT_LEDGER`;
  static `encode`/`decode`.
- Typed values by prefix (`str:` `json:` `blob:` `dat:` `art:<type>:` `node:`);
  `Ref` as plain data; artifact types `json`, `file`, `ckpt`, `video`, and any
  `Artifact` subclass with a `token`.
- SQLite backend (`SqliteLedger`, over the shared `SqlLedger` base) with a
  write-once content-addressed shelf and the `whereabouts` table; other
  backends by dotted class name in the profile.
- `docs/ledger.md`; `examples/ledger_walkthrough.ipynb`, run by the tests.

## 2.16.0 — 2026-09-24

**`{…}` references call functions** (Dan, SVP T161 Q2, from the Juan call:
a `meta` module — commit, branch, version, time — straight from templates).

- `{mod.fn}` whose dotted name resolves to a function or method is called
  with no arguments, and its value is what expands. A mounted function
  counts; a class or a callable object does not, so a proxy like SVP's
  `asset` still answers `{asset.ocr}` with its string.
- `{mod.fn(1, "x", key=2)}` calls it with Python literals only.
- Changed: `expand("{os.path.join}")` used to return the function; it now
  calls it. A reference that should stay an object needs to be a class or a
  value.

## 2.15.0 — 2026-09-24

**Artifact verbs by their own names** (Dan, T023 Q4). Breaking for a line
public only hours, so a minor.

- **`Dat.save_artifact(source, *, type=None, name=None, link=False)`** and
  **`Dat.load_artifact(name_or_urn)`** forward to the default world, beside
  `Dat.load`, `Dat.create` and `Dat.standing`: the manager can stay out of
  sight. `Dat.load` stays typed to dats; `dat.save()` still seals a dat.
- The manager's **`save` is now `save_artifact`**, with `type` and `name`
  keyword-only; **`load_artifact`** is new, and refuses a dat's name.
  `m.load` still takes either.

## 2.14.1 — 2026-09-24

- **The index is JSON**, `_index_.json`: every save reads and rewrites it,
  and at 15 000 keys YAML took 1.5 s a save where JSON takes 0.01 s. A
  2.14.0 `_index_.yaml` is not read; `m.reindex()` builds the new one.

## 2.14.0 — 2026-09-24

**The store: one index, `dat.standing`, type at save** (Dan, T023 and F026
Q1). Breaking for a line public only hours, so a minor.

- **`dat.standing`** replaces `dat.rolling`, `dat.referenceable`,
  `Dat.status` and `Dat.Status`: one key, `rolling | open | sealed |
  referenceable`, stamped by every save. A seal earns the least of its
  inputs (rolling counts as sealed), capped at sealed by dirty code. In a
  spec it is a demand: `rolling`, or `referenceable`, which replaces
  **`execute(dat, referenceable=True)`** (gone). `Dat.standing(name)` /
  `m.standing(name)` reads it from the files, `None` when absent. Files
  written before 2.14 read by the 2.13 rule.
- **`save(source, type=None, name=None, *, link=False)`**: `type` is a class
  or callable recorded as its dotted name, or that name as a string;
  `load` resolves it through `do.load` and calls it with the path.
  **`register_artifact` is gone** — mount a factory that cannot be
  imported and name it. The name is any relative path and carries no type;
  with none the artifact answers to its URN only. `save` returns the URN.
  The 2.13 call `save(path, "art:…")` is a `TypeError` saying so.
- **Dedupe**: stored bytes saved under a new name get that name as a second
  key, copying nothing; an equal hash with a different size is refused.
- **One index**, `_index_.yaml` in the artifact folder (`index:` config key,
  `DatManager(index=)`), keyed by every artifact name and every `sha256:`
  URN, dats included; locked and written by rename; `m.reindex()` rebuilds
  it. `load`, `load_path`, `exists`, `standing` take a name or a URN.
- **One namespace**: a dat name and an artifact name never coincide; a
  name both hold on disk is `ValueError`. The `art:<kind>/` rule is gone;
  `art:` names written before still load, the prefix stripped, and a
  dependency on one counts as an artifact.
- A world with the default config now writes `art/_index_.yaml` beside
  `data/` on its first save; ignore it where `data/` is ignored.

## 2.13.0 — 2026-09-24

**Provenance v2** (Dan, SVP F155 Q1 and Q4, reconciled with T021). Breaking
for a line public only hours, so a minor.

- **Every save stamps `dat.sha256`** again; the save that counts seals. A save
  inside the dat's own run is a checkpoint written to disk, and the seal comes
  when the run returns; a save outside seals at once with `$MANUAL`.
- **`dat.rolling: true`** (spec): saved at will, runs again, never frozen.
- **`dat.referenceable`**, stamped at the seal: not rolling, clean committed
  code (runs only), every dependency referenceable. A rolling or
  unreferenceable input makes the run unreferenceable; an open one keeps it
  open. **`execute(dat, referenceable=True)`** makes each an error at the load
  and refuses dirty code.
- **`Dat.status(name)` / `m.status(name)`** → `Dat.Status.ABSENT | OPEN |
  SEALED | ROLLING`, from the files, nothing built. `dat.sealed` is gone.
- **The verifying load**: `load(name, verify=True)`, `load_path(..., verify=)`,
  `DatManager(verify=True)`, `verify:` in `.datconfig.yaml` — re-hash, and
  `ValueError` naming both hashes on a mismatch.
- **Public**: `m.roots(deps)`, `DatManager.code_of(fn)`, `Do.resolve(spec)`
  (was `_resolve_base`); `m.save(..., link=True)` hard-links the payload.
- A sealed file is one with `dat.run_time` or `$MANUAL` and no `unsealed`
  entry; without `dat.referenceable` it is not referenceable.

## 2.12.0 — 2026-09-23

**The seal** (Dan, 2026-09-23, T021 Q1; T022). Breaking for a line public
only hours, so a minor.

- **A run saves nothing.** `execute` records `run_at`, `run_time`, `code` and
  `dependencies` in the dat's results and leaves them in memory.
- **`dat.save()` seals the dat, once.** It writes `_result_.yaml` and stamps
  `dat.sha256`; a second `save()` is `RuntimeError`, and so is running a
  sealed dat (`do(dat)` with no arguments). A `save()` inside the dat's own
  run seals when the run returns, with the whole record. `dat.sealed` says
  which.
- **`create` writes no `_result_.yaml`**; a created dat is unsealed.
- **`$MANUAL`**: a dat sealed anywhere but inside its own run gets the
  dependency `$MANUAL: manual` — made or finished by hand, its dependencies
  incomplete.
- **`unsealed`**: loading a dat not yet sealed records it under that value,
  and the loading dat can then never be sealed: its `save()` writes the
  results with no hash and may be repeated.
- **Roots only**: at the seal, a dependency that another entry already lists
  among its own dependencies is dropped.
- A dat saved before 2.9 is unsealed (no longer hashed on load).
- `tests/do` put the repo ahead of any installed `dvc_dat`.

## 2.11.0 — 2026-09-23

From Dan's 2026-09-23 call with Juan. Additive.

- **`DatManager.load_path(name) -> Path`**: a dat's folder or an artifact's
  payload, with nothing built — no factory runs — for heavy objects and for
  tools that read the file themselves. Recorded on the running dat like `load`.
- **`manager:` in `.datconfig.yaml`**: the dotted `DatManager` subclass that
  `load_dat_config` builds, and so the default world's class. The subclass's
  `CONFIG_KEYS` are extra keys the file may carry, handed to its constructor;
  any other unknown key is still an error.

## 2.10.0 — 2026-09-23

**Named list entries merge by name** (Dan, 2026-09-23, ruled on SVP T150 Q1
after measuring ALG2's configs: every variant appends a stage, edits fields
inside one, or replaces the list). In `merge_dicts`, and so in `dat.base`,
two lists whose entries are all mappings with a `name` merge by name: a later
entry merges into its namesake, a new name appends in order, and
`{name: X, remove: true}` deletes X. Any other list is still replaced whole.
A spec that relied on a named list being replaced whole now merges; name
every entry it keeps, or remove the rest.

## 2.9.0 — 2026-09-23

**Every dat has a content hash** (Dan, 2026-09-23: "I don't think anything
should have a null content hash"). Additive for callers; every
`_result_.yaml` written from now on carries `dat.sha256`.

- **`dat.sha256`**, stamped by every `save()` — so by `create` and by every
  run: the sha256 over every file in the folder, `_result_.yaml` included,
  that file counted as its sorted-key dump with `dat.sha256` set to
  `excluded`.
- **`dat.verify() -> bool`**: the folder still hashes to its `dat.sha256`.
- **`dat.dependencies` entries for dats are hashes, never `null`**; a nested
  run is recorded by its final hash. A dat saved before 2.9 is hashed on load.
- `create` now writes `_result_.yaml` (holding the hash) for every dat.

## 2.8.0 — 2026-09-23

**The package exports four classes** (Dan, 2026-09-23: "everything truly is
contained inside of DAT, but if you want that shortcut you can easily do
it"). Breaking for every `from dvc_dat import do` and kin; shipped as a
minor per the rule above 2.2.0.

- `from dvc_dat import Dat, DatContainer, DatManager, Do` — and `__version__`
  — is the whole surface.
- **`Dat.do`** is the default world's runner and namespace. It returns the
  forwarder to `Dat.manager.do`, so `do = Dat.do` binds a shortcut that keeps
  following a later reassignment of `Dat.manager`.
- **`Dat.merge_dicts`** (beside `Dat.get` / `Dat.set`) and **`Dat.cli_main`**.
- `expand` / `expand_spec` are `Dat.manager.expand` / `expand_spec`.

| Gone | Instead |
| --- | --- |
| `from dvc_dat import do` / `dvc_dat.do(...)` | `do = Dat.do` / `Dat.do(...)` |
| `dvc_dat.cli_main()` | `Dat.cli_main()` |
| `dvc_dat.merge_dicts` | `Dat.merge_dicts` |
| `dvc_dat.expand`, `expand_spec` | `Dat.manager.expand`, `expand_spec` |

## 2.7.0 — 2026-09-23

**A word runs a dat; a flag asks `dat` about itself** (Dan, 2026-09-23).
Breaking for a command line using the bare verbs; shipped as a minor per the
rule above 2.2.0.

- `dat --list [PREFIX]`, `dat --info`, `dat --version`, `dat --help` are the
  commands that do not run a target. The bare `dat list`, `dat info` and
  `dat version` are gone.
- No reserved words: a first word is always a `TARGET`, so a target named
  `list`, `info` or `version` now runs from the shell.

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
