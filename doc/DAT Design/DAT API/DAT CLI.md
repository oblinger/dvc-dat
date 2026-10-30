---
description: "`just run TARGET …` (`x TARGET …`) from a shell"
---
:>> [DAT](../../DAT%20Track/DAT.md) → [DAT Design](../DAT%20Design.md) → [DAT API](DAT%20API.md) → [DAT CLI](ha://p/DAT%20CLI) 
# DAT CLI
`just run TARGET …` — `x TARGET …`, by `bin/x` — is `Dat.manager.run(TARGET, …)` from a shell.

```bash
$ x mymodule.train.baseline              # run it
$ x mymodule.train.baseline lr=0.25      # fork it: lr into dat.kwargs
$ x mymodule.train.baseline 7 true --dry-run   # Dat.manager.run('…', 7, True)
$ x mymodule.train.baseline --set "notes=second try"
$ just mounts train                      # mounted names with `train` (x --list)
$ x --info                               # version, folders, config
$ x --version
$ x --help
```

Below `run` and `mounts`, `dvc_dat.just` carries the ledger verbs `values value history why set index bump`; `run` writes `.dat/targets.just` for `@command` targets ([cli.md](../../cli.md)).

## x CLI
Every line you can type: a word runs a target, a flag asks `x` about itself.

| x | |
| --- | --- |
| [x TARGET …](#^target) | Run it: call a function, fork a template, else print |
| [x TARGET --set K=V](#^set) | Update a spec key before the fork; repeat it |
| [x TARGET --json K=J](#^json) | The same, with the value as JSON; repeat it |
| [x TARGET --dry-run](#^dry-run) | Print the `Dat.manager.run(…)` call instead of making it |
| [x TARGET --usage](#^usage) | The target's own usage, else the general one |
| [just mounts PREFIX](#^list) | Mounted names starting with PREFIX; all without it (`x --list`) |
| [x --info](#^info) | Version, dat folders, artifact folder, config |
| [x --version](#^version) | The version |
| [x --help](#^help) | The usage; `x` alone prints it too |

**x TARGET**` [ARG …] [KEY=VALUE …]`
    Run — a plain call for a function, a fork for a template; anything else it loads to prints. Fixed words become `dat.args` and `KEY=VALUE` pairs update `dat.kwargs`, every value JSON, else the text exactly as typed (`n=12` an int, `start=2026-01-01` the string, `k='"12"'` the string 12); the return value prints. A word is a keyword iff it starts with `NAME=`; `--` ends keywords. ^target

**x TARGET --set**` DOTTED.KEY=VALUE`
    Update one spec key of a template before it forks; the value is JSON, else the text as typed. One pair per flag — repeat the flag for more: `--set a=1 --set b.c=2`. ^set

**x TARGET --json**` DOTTED.KEY=JSON`
    `--set` with the value parsed as JSON: `--json rules='[[2, "x.f"]]'` — the quotes are the shell's, and `x` sees one word, key `rules`, JSON `[[2, "x.f"]]`. Repeats, and mixes freely with `--set`. ^json

**x TARGET --dry-run**
    Print the `Dat.manager.run(…)` call this line would make, without making it — to check a fork before paying for the run. ^dry-run

**x TARGET --usage**
    `<first part of TARGET>.usage`, else the spec's `usage` key, else the general usage. ^usage

**just mounts**` [PREFIX]` · **x --list**` [PREFIX]`
    The mounted base names starting with `PREFIX`, all of them without one; plain imports and `value` mounts are not listed. ^list

**x --info**
    The version, dat folders, artifact folder, and config folder and file. ^info

**x --version**
    The version; needs no config. ^version

**x --help**
    The general usage; `x` with no arguments prints the same. Needs no config. ^help




# CLI Semantics

## No reserved words
A word in first position is always a `TARGET`; the four commands that are not a target are flags. A target named `list`, `info` or `version` runs like any other. `-h` is the same as `--help`.

## With a ledger: `just run <spec>`
In a project whose `.datconfig.yaml` has a `ledger:` line or `namespace: ledger` (a `ledgers:` section alone keeps the bare run), `just run` (and `x`) is `rev.run(TARGET, k=v …)` (DAT 1046), its names the ledger's `db/mount` rows (`mounts:` in the config). A dat spec (a mounted name such as `mymodule.specs.table12`, a spec file whose `dat:` names its run function, or a run function's name) runs as a dat: found if this spec, these kwargs and this code were run before, else made, run and sealed; it prints `ran` or `hit`, the dat's name and its preds (`ran  table/12  start=1 n=12 cells=144`), and `alias=NAME` names it (`path=` in the API). A ledger function (`@ledger_fn`, or a spec whose `main` names one) runs with the line's keys. Fixed words are refused there: keywords only. A mounted spec with `command: true`, or a mounted function marked `@command`, is also its own recipe, read off the mounted files: `just table12` runs `just run mymodule.specs.table12` ([DAT Ledger § Running](../../DAT%20Modules/ledger/DAT%20Ledger.md#Running)).

## Exit codes
`0` ran, `1` the run raised or the line was malformed, `2` the target does not load, `3` no `.datconfig.yaml` above (the `run` recipe); one line on stderr, `DAT_DEBUG=1` for the traceback.

## The `run` recipe
`just run` is the `run` recipe of `dvc_dat.just`, which the project's justfile imports; `x` (`bin/x`) is `exec just run "$@"`. It works from any directory with no environment active, execing the first of `$DAT_RUN`, the config's `run:`, `.venv/bin/python -m dvc_dat` beside it, `python3 -m dvc_dat`, with `DAT_CLI_CONFIG` set to the config it found (full reference: [cli.md](../../cli.md)).

# Changes

## 2.6 – 2.7

| Before | After |
| --- | --- |
| `--json DOTTED.KEY '<json>'` | `--json DOTTED.KEY=JSON`, one pair per flag, repeatable (2.6) |
| the words `list`, `info`, `version` | the flags `--list`, `--info`, `--version`; no reserved words (2.7) |
| `.dataconfig.yaml` | `.datconfig.yaml` (2.3) |
