:>> [DAT](DAT%20Track/DAT.md) → [DAT doc cli](ha://p/DAT%20doc%20cli) 
# Command Line
The command line, `just run` and `x`: where it finds its config, and every subcommand.

```
x TARGET [ARG ...] [KEY=VALUE ...]      run TARGET (just run)
just mounts [PREFIX]                    the mounted names (x --list)
x --info                                version, folders, config
x --version                             the version
x --help                                the usage message
```

`just run TARGET` is the one way to run (F447 Q40): the `run` recipe of
`dvc_dat.just`, which every project's justfile imports. `x TARGET` is the
same command, two lines of `sh` in `bin/x`: `exec just run "$@"`. There is
no `dat` command any more.

The recipe configures the command line from the nearest `.datconfig.yaml` —
walking up from the working directory — before it runs anything that needs
the namespace; `x --version` and `x --help` need no namespace. It execs the
config's `run:` (your program's main, with its mounts), else the library's
own command line, `python -m dvc_dat`, with no project mounts.

The config's folder is the project's import root: it goes first on
`sys.path` (and on `PYTHONPATH` for the command it execs), so `mypkg.job.run`
means the same thing from every directory under the project, whether or not
`mypkg` is installed.

## Commands

| Command | Does |
|---------|------|
| `x TARGET [ARG ...] [KEY=VALUE ...]` | `do(TARGET, *ARGS, **KWARGS)`. The return value prints on stdout when it is not `None`. |
| `just mounts [PREFIX]` · `x --list [PREFIX]` | Every mounted name that starts with `PREFIX`, with what it loads to. The library mounts `dt` (`dvc_dat.dat_tools`) itself; `x dt.list` is the same command. |
| `x --info` | The version, the dat and artifact folders, the config folder and the `.datconfig.yaml` in force. |
| `x --version` | The version. |
| `x` · `x --help` · `x -h` | The usage message. |

A word in the first position is always a `TARGET`; the commands that ask
the command line about itself are flags. There are no reserved words, so a
target named `list` runs like any other.

## Arguments

`TARGET` is a dotted name resolved by `do.load` — the running program's
`do.mount(...)` names first, then the longest importable prefix. What happens next is the library's rule, not the
CLI's: a **callable** is called, a **template spec** is forked — the fixed
arguments become the new spec's `dat.args`, the `KEY=VALUE` pairs update its
`dat.kwargs` key by key — and the forked spec creates a dat, which runs.

Every fixed argument and every `KEY=VALUE` value is read as **JSON, else the text exactly as typed** — the one `k=v` grammar of every dat command line (`dvc_dat.do.arg_value`):

```bash
# do("train", 7, True)
x train 7 true

# do("train", epochs=7, lr=0.01)
x train epochs=7 lr=0.01

# do("train", tags=["a", "b"], cfg={"a": 1}, name="7", seed=None)
x train 'tags=["a","b"]' 'cfg={"a":1}' name='"7"' seed=null

# not JSON, so the string as typed: a bare word, a date, an empty value
x train note=hello start=2026-01-01 note=
```

A word is a keyword argument when it starts with `NAME=` (a Python identifier
followed by `=`); anything else is a fixed argument. `--` ends the options, so
every word after it is a fixed argument even when it looks like one of them:

```bash
x echo -- --not-an-option
```

The `TARGET` itself is never parsed.

## Options

| Option | Does |
|--------|------|
| `--set DOTTED.KEY=VALUE` | Set one spec key of a template before it forks; repeat the flag for more. The value is JSON, else the text as typed. |
| `--json DOTTED.KEY=JSON` | The same, with the value parsed as JSON; repeatable, and mixes freely with `--set`. |
| `--dry-run` | Print the `do(...)` call this line would make, and any `--set` / `--json` updates, without making it. |
| `--usage` | Print `TARGET`'s own usage — a `<base>.usage` value, else the spec's `usage` key — else the general usage. |

`--set` / `--json` update a **template spec**; using them on a target that is
a plain function is an error.

```bash
x my_letters --set "dat.title=Re-configured letterator"
x my_letters --set dat.title=Quickie --set start=100 --set end=110
x my_letters --json rules='[[2, "my_letters.triple_it"]]'
```

## With a ledger: `run` evaluates

When the config has a `ledger:` line, `x TARGET KEY=VALUE ...` runs
through the ledger (F447 Q40): `rev.run` of the ledger function TARGET
names, found if computed before from the same inputs by the same code,
else run and sealed. It prints `hit` or `ran`, the value (its name, else
a hash prefix) and its preds. Without a `ledger:` line it is the bare run
above and records nothing.

| TARGET | The function and its keys |
|--------|---------------------------|
| a spec file, `.yaml` / `.json` | `main` names it; the other keys are its keys |
| a mounted name | the `@ledger_fn` it loads to, or a spec with `main` |
| a dotted name | the `@ledger_fn` itself |

```bash
x demo_game.game.cut game=G1 version=1.5.3   # ran, then hit
x model-G1.yaml epochs=9                     # the line's key wins
x model-G1.yaml alias=model/prod             # names the result
```

`alias=NAME` is the run's `path=`: it names the result, and a `Dat`'s
folder is built there. `--set` / `--json` update a spec's keys. A target
that is not a ledger function, and a positional argument, are refused.
`DAT_LEDGER` overrides the config's ledger, as for `Ledger()`.

## Commands: `@command` and `.dat/targets.just`

A function marked `@command` also runs as `just NAME`:

```python
from dvc_dat.just import command

@command(args="game=…", help="train the model on one game's tracks")
@ledger_fn
def train(rev, *, game: str, path: Path) -> StageDat: ...
```

`args` (at most 24 characters) and `help` (one or two lines of at most
56) are what `just --list` prints; over budget is `ValueError` at import.
A mounted spec is a command by its `command:` key, `true` or
`{args: ..., help: ...}`. A justfile opts in with one line:

```
import 'dvc_dat.just'
import? '.dat/targets.just'
```

`run` then writes `.dat/targets.just` beside the config: one recipe per
mounted command (a mounted function, or a command defined in a mounted
module, named by its function), each `just run TARGET "$@"`, in group
`run`. It is rewritten when older than the config, the justfile or a
mounted source, and `run` says on stderr what it wrote and skipped. A name
the justfile already has is skipped: the hand recipe wins. Anything not
marked stays `just run TARGET`.

## Exit status

| Code | Meaning |
|------|---------|
| `0` | Ran. |
| `1` | The run raised, or the command line was malformed. |
| `2` | `TARGET` does not load. |
| `3` | No `.datconfig.yaml` above the working directory. |

A failed run prints one line on stderr and no traceback. Set `DAT_DEBUG=1` to
get the traceback instead.

## `dvc_dat.just` — `run` and `mounts` in every project

dvc-dat ships `dvc_dat.just` inside the package (`dvc_dat/dvc_dat.just`).
A project links it beside its justfile once and imports it:

```bash
# once, at the project root
uv run python -c 'import dvc_dat, pathlib; print(
  pathlib.Path(dvc_dat.__file__).with_name("dvc_dat.just"))' |
  xargs -I{} ln -s {} dvc_dat.just
```

```
# the project's justfile
import 'dvc_dat.just'
```

`just` finds the justfile walking up from any folder, so `just run` and `x`
work from every directory of the project with no environment activated.
Copy `bin/x` onto your `PATH` for the short form. The `run` recipe:

1. Walks up from the working directory to the nearest `.datconfig.yaml` (it
   stops at `/`; with none found it prints a message and exits `3`).
2. Picks the command — the first of:
   - `$DAT_RUN`,
   - the config's `run:` key,
   - `.venv/bin/python -m dvc_dat`, when `.venv` sits beside the config,
   - `python3 -m dvc_dat`.
3. `exec`s that command with the arguments appended, working directory
   unchanged, and two variables set for it: `DAT_CLI_CONFIG`, the config
   file it found, and `DAT_JUSTFILE`, the justfile (for
   `.dat/targets.just`). A program's own main tests `DAT_CLI_CONFIG` to
   know it was launched by `just run`, and `cli_main()` reads the config
   from it, so the file is found once.

A relative path in the command's first word is relative to the config's
folder.

```bash
# from anywhere in the project
cd any/deep/subfolder && x train epochs=200
```

## `run:` in `.datconfig.yaml`

```yaml
dat_folders: data

# the command `just run` hands its arguments to
run: uv run python -m dvc_dat
```

`run` is any command that ends up in `cli_main()`. For a project with no
mounts, the library's own command line will do: `uv run python -m
dvc_dat`, `.venv/bin/python -m dvc_dat`. A project that mounts names points
it at its **own main** — `run: .venv/bin/python -m mypkg.main` — a module
that imports what it needs, makes its `do.mount(...)` calls and, when
`DAT_CLI_CONFIG` is set, ends with `sys.exit(Dat.cli_main())`, so the shell
runs inside the program's own namespace and the same main is free to do
anything else when run by hand:

```python
if __name__ == "__main__":
    if os.environ.get("DAT_CLI_CONFIG"):   # launched by `just run`
        sys.exit(Dat.cli_main())
    ...                                    # your own main
```

`Dat.cli_main(argv=None, *, config=None)` takes the config as a parameter
instead — a folder or a config file — for a program that runs the command
line on a config it chose: it does
`Dat.manager = DatManager.load_dat_config(config, do=Dat.do)`, keeping
the program's mounts. The environment variable is never the way to hand it
one. The library itself never reads the `run` key — it is there so that one
file describes the whole project.
