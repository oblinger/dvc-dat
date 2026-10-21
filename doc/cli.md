# Command Line

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

```
x TARGET [ARG ...] [KEY=VALUE ...]      run TARGET (just run)
just mounts [PREFIX]                    the mounted names (x --list)
x --info                                version, folders, config
x --version                             the version
x --help                                the usage message
```

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

Every fixed argument and every `KEY=VALUE` value is read as a **YAML scalar**:

```bash
# do("train", 7, True)
x train 7 true

# do("train", epochs=7, lr=0.01)
x train epochs=7 lr=0.01

# do("train", tags=["a", "b"], name="7")
x train tags=[a,b] name='"7"'

# a bare word stays a string; an empty value is None
x train note=hello
x train note=
```

A word is a keyword argument when it starts with `NAME=` (a Python identifier
followed by `=`); anything else is a fixed argument. `--` ends the options, so
every word after it is a fixed argument even when it looks like one of them:

```bash
x echo -- --not-an-option
```

The `TARGET` itself is never parsed as YAML.

## Options

| Option | Does |
|--------|------|
| `--set DOTTED.KEY=VALUE` | Set one spec key of a template before it forks; repeat the flag for more. The value is a YAML scalar. |
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
   unchanged, and one variable set for it: `DAT_CLI_CONFIG`, the config
   file it found. A program's own main tests it to know it was launched
   by `just run`, and `cli_main()` reads the config from it, so the file
   is found once. Nothing else reads the variable.

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
