---
description: "`dat TARGET …` from a shell, and the bootstrap copy"
---
:>> [DAT](../../DAT%20Track/DAT.md) → [DAT Design](../DAT%20Design.md) → [DAT API](DAT%20API.md) → [DAT CLI](ha://p/DAT%20CLI) 
# DAT CLI
`dat TARGET …` is `Dat.do(TARGET, …)` from a shell.

```bash
$ dat mymodule.train.baseline            # run it
$ dat mymodule.train.baseline lr=0.25    # fork it: lr into dat.kwargs
$ dat mymodule.train.baseline 7 true --dry-run   # do('…', 7, True)
$ dat mymodule.train.baseline --set "notes=second try"
$ dat --list train                       # mounted names with `train`
$ dat --info                             # version, folders, config
$ dat --version
$ dat --help
```

## dat CLI
Every line you can type: a word runs a target, a flag asks `dat` about itself.

| dat | |
| --- | --- |
| [dat TARGET …](#^target) | Run it: call a function, fork a template, else print |
| [dat TARGET --set K=V](#^set) | Update a spec key before the fork; repeat it |
| [dat TARGET --json K=J](#^json) | The same, with the value as JSON; repeat it |
| [dat TARGET --dry-run](#^dry-run) | Print the `Dat.do(…)` call instead of making it |
| [dat TARGET --usage](#^usage) | The target's own usage, else the general one |
| [dat --list PREFIX](#^list) | Mounted names starting with PREFIX; all without it |
| [dat --info](#^info) | Version, dat folders, artifact folder, config |
| [dat --version](#^version) | The version |
| [dat --help](#^help) | The usage; `dat` alone prints it too |

**dat TARGET**` [ARG …] [KEY=VALUE …]`
    Run — a plain call for a function, a fork for a template; anything else it loads to prints. Fixed words become `dat.args` and `KEY=VALUE` pairs update `dat.kwargs`, every value a YAML scalar; the return value prints. A word is a keyword iff it starts with `NAME=`; `--` ends keywords. ^target

**dat TARGET --set**` DOTTED.KEY=VALUE`
    Update one spec key of a template before it forks; the value is a YAML scalar. One pair per flag — repeat the flag for more: `--set a=1 --set b.c=2`. ^set

**dat TARGET --json**` DOTTED.KEY=JSON`
    `--set` with the value parsed as JSON: `--json rules='[[2, "x.f"]]'` — the quotes are the shell's, and `dat` sees one word, key `rules`, JSON `[[2, "x.f"]]`. Repeats, and mixes freely with `--set`. ^json

**dat TARGET --dry-run**
    Print the `Dat.do(…)` call this line would make, without making it — to check a fork before paying for the run. ^dry-run

**dat TARGET --usage**
    `<first part of TARGET>.usage`, else the spec's `usage` key, else the general usage. ^usage

**dat --list**` [PREFIX]`
    The mounted base names starting with `PREFIX`, all of them without one; plain imports and `value` mounts are not listed. ^list

**dat --info**
    The version, dat folders, artifact folder, and config folder and file. ^info

**dat --version**
    The version; needs no config. ^version

**dat --help**
    The general usage; `dat` with no arguments prints the same. Needs no config. ^help




# CLI Semantics

## No reserved words
A word in first position is always a `TARGET`; the four commands that are not a target are flags. A target named `list`, `info` or `version` runs like any other. `-h` is the same as `--help`.

## With a ledger: `just run <spec>`
In a project whose `.datconfig.yaml` has a `ledger:` line, `just run` (and `x`) is `rev.run(TARGET, k=v …)` (DAT 1046), its names the ledger's `db/mount` rows (`mounts:` in the config). A dat spec (a mounted name such as `mymodule.specs.table12`, a spec file whose `dat:` names its run function, or a run function's name) runs as a dat: found if this spec, these kwargs and this code were run before, else made, run and sealed; it prints `ran` or `hit`, the dat's name and its preds (`ran  table/12  start=1 n=12 cells=144`), and `alias=NAME` names it (`path=` in the API). A ledger function (`@ledger_fn`, or a spec whose `main` names one) runs with the line's keys. Fixed words are refused there: keywords only. A mounted spec with `command: true`, or a mounted function marked `@command`, is also its own recipe, read off the mounted files: `just table12` runs `just run mymodule.specs.table12` ([DAT Ledger § Running](../../DAT%20Modules/ledger/DAT%20Ledger.md#Running)).

## Exit codes
`0` ran, `1` the run raised or the line was malformed, `2` the target does not load, `3` (`bin/dat` only) no `.datconfig.yaml` above; one line on stderr, `DAT_DEBUG=1` for the traceback.

## The console script and the bootstrap
The console script `dat` builds its world from the nearest `.datconfig.yaml` (`DatManager.load_dat_config`) and never reads `run:`. A copy of `bin/dat` on `PATH` works from any directory with no environment active, execing the first of `$DAT_RUN`, the config's `run:`, `.venv/bin/python -m dvc_dat` beside it, `python3 -m dvc_dat` (full reference: the repo's `docs/cli.md`).

# Changes

## 2.6 – 2.7

| Before | After |
| --- | --- |
| `--json DOTTED.KEY '<json>'` | `--json DOTTED.KEY=JSON`, one pair per flag, repeatable (2.6) |
| `dat list`, `dat info`, `dat version` | `dat --list`, `dat --info`, `dat --version`; no reserved words (2.7) |
| `.dataconfig.yaml` | `.datconfig.yaml` (2.3) |
