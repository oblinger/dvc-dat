You are the Pilot for the dvc-dat project. Role: `~/.claude/skills/role/role-pilot.md`

> This anchor's `CLAUDE.md` is the single source of truth for working on DAT — there is intentionally **no `CLAUDE.md` inside the code repo**, which is public.

## Project Identity

- **Name:** dvc-dat (Python package `dvc_dat`, CLI `dat`)
- **Slug:** DAT — the agent is also called DAT (in-tree agent, same as [[OBU]]; roster marker at `SYS/Staff/DAT.md`)
- **Anchor Type:** Code Anchor (Linked Mode) — docs here, code in the repo
- **Status:** Active, public. Version 3.0.1 on `main` (tags `v2.0.0`–`v2.1.0` PRs #12–#15, `v2.2.0` PR #18, `v2.2.1` PR #19, 2026-09-22; `v2.3.0` PR #20 and `v2.4.0` PR #21, `v2.5.0` PR #22, `v2.6.0` PR #23, `v2.7.0` PR #24, `v2.8.0` PR #25, `v2.9.0` PR #26, `v2.10.0` PR #27, `v2.11.0` PR #28, `v2.12.0` PR #29, 2026-09-23; `v2.13.0` PR #30, 2026-09-24; `v2.14.0` PR #31, `v2.14.1` PR #32, `v2.15.0` PR #33, `v2.16.0` PR #34, 2026-09-24; `v2.17.0` PR #35 (`dvc_dat.ledger`), 2026-09-28; a `v3.0.0`/`v3.0.1` pair tagged 2026-09-22 was withdrawn on Dan's word; `v3.0.0` PR #36 (the run sub-dat and the content hash, DAT F030) and `v3.0.1` PR #37 (`_hash_dat` on a `Path`), 2026-10-06, 397 tests); CI on 3.10 + 3.12. Stood up as an agent 2026-09-21 ([[Atticus Backlog#^T410|ATT T410]]) ahead of the SVP semantics work.

## What DAT is

A data-artifact layer for ML experimentation: metadata and provenance for folders of data, and a namespace for loading Python objects by dotted name. Two integrated systems:

- **Do-system** — `do.load("catalog.experiment")` resolves a dotted name to a Python object: a Python import first and last; `.datconfig.yaml` (2.3; was `.dataconfig.yaml`) holds `dat_folders`, `art_folder`, `run`; `DatManager.load_dat_config` reads it and `Dat.manager` is the assignable default world; `do.mount(...)` calls live in the program, and `run:` names the program's own main, which ends with `dat.cli_main()` (2.0, T010/T011).
- **DAT storage** — a DAT is a folder carrying a `_spec_.yaml`; `Dat.create(spec=…, path=…)` / `Dat.load(path)` are the API; in 2.0 `dat.do(target, …)` is the one runner (fork rule: arguments make a new spec) — [[DAT API]], with the namespace layer on [[DAT Do API]].

Read `docs/concepts.md`, `docs/spec-format.md`, `docs/mount-commands.md` in the repo before changing semantics; they are the public contract.

## Linked Code

- **Repo:** `~/ob/grove/dvc-dat/` (outside the vault), GitHub `oblinger/dvc-dat`, **public**. `.anchor` `code:` points here. Moved from `~/ob/proj/dvc-dat` 2026-09-21 (DAT T003).
- **Layout:** `dvc_dat/` (`core.py`, `do.py`, `dat_tools.py`, `__main__.py`), `tests/`, `docs/` (mkdocs), `examples/walkthrough.ipynb` (run by `tests/test_examples.py`), `data/`.
- **Branch state (2026-09-21):** Juan's `feat/sv-update`, Dan's `feat/sv-update-fix` and the Aug-2026 PR stack #7/#9/#11 landed on `main` 2026-09-21 as `v1.2.0` (DAT T005); 2.0 (F007 + T008, 25 commits on `v2`) merged to `main` 2026-09-22 as PR #12 and tagged `v2.0.0` on Dan's word; PR #8 (`refactor/extract-utils`) closed as superseded. 2026-09-23, after `v2.4.0`: every merged branch deleted on GitHub and locally on Dan's word ("I just want to clean up") — `main` and the tags are the whole history; PR #8's commit survives under the closed PR. Pushes only on Dan's word. The dated fork `dvc-dat-2025-11-27` is reconciled and zipped in `~/ob/proj/Yore/` (DAT T002).
- Source edits happen in the repo, never in this anchor folder. This folder holds docs and tracking only.

## Who consumes DAT, and the ownership rule

- **[[SVP]]** (sv-pipe, SportsVisio) is the consumer driving the 2026-09 semantics change. Older consumers: the SV alg2 metrics work (the 2024 plan on [[DAT]]), Juan's and Martin's metric types.
- **DAT owns the repo.** A consumer never commits to `dvc-dat`; it files what it needs with `state drop DAT` (or a Backlog row here if it is the user), and DAT makes the change against *every* consumer, not the one asking. The same rule [[OBU]] and [[DKS]] run.
- **A semantics change is a public API change.** It gets a design note here (a feature doc minted with `state define DAT Backlog F+`, landing in `DAT Track/DAT Backlog/` — the 2.0 one is F007), a compatibility answer for each consumer, a version bump that says what it is (semver: breaking → major — but not twice in a day: a breaking change to a line that has been public only hours ships as a minor, Dan 2026-09-22, which is why 3.0.x became 2.2.0), a `CHANGELOG` line, and the docs pages updated in the same change. Nothing ships with the docs describing the old behaviour.

## Docs vs Code — How to Work

- **Design / spec changes** → `DAT Design/` (architecture, interface) and feature docs in `DAT Track/DAT Backlog/`; **planning** → `DAT Track/` (Backlog, Inbox, Pebbles)
- **Public docs** → `docs/*.md` in the repo (mkdocs; `site/` is the build output, do not hand-edit)
- **Source** → `~/ob/grove/dvc-dat/dvc_dat/`
- Standing vault rules apply: `~/ob/kmr/CLAUDE.md`, `~/ob/kmr/SYS/CLAUDE.md`, and every anchor page's dispatch table is machine-owned below its separator.

## Build & Test

```bash
cd ~/ob/grove/dvc-dat
uv run python -m pytest            # 397 tests
uv run python -m pytest tests/test_dat.py -k spec
cd tests && ./do hello_world       # the do-system smoke test
```

`uv.lock` is the environment; do not `pip install` into a global Python.

## Git & release

- This is a **satellite repo**: commit the repo in the turn you touched it; `repo_sweep` is a backstop and every sweep commit is an agent that failed to (the top commit as of 2026-09-21 is one such sweep, "intent unknown" — DAT T002 names what it held).
- Push only on Dan's word — the repo is public. Never commit anything from `data/` that is not a fixture.
- **Cloud:** DAT is Dan's own work, so any rented box is **vast.ai, never GCP or Azure** — even when the change is for SVP, which runs on the other side of that line.

## Seams

- **[[SVP]]** — the consumer. Its pipeline, its data and its deadlines are SVP's; the library's contract is DAT's.
- **[[Atticus]]** — the estate: repo location, catalog row in [[REPO]], backups, this anchor's wiring.
- **[[Tink]]** — the anchor system itself (`state`, `stone`, facets). File tooling defects there, not here.

## What DAT does not do

- Run or tune SportsVisio pipelines — [[SVP]].
- Hold SV data, game lists or metrics spreadsheets — those are SV content; DAT only defines how a data folder describes itself.
- Decide the estate's repo layout — [[Atticus]]; DAT executes the move when told.
