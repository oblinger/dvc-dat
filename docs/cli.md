# Command Line

`dat` is the command line. It configures itself from the nearest
`.dataconfig.yaml` — walking up from the working directory — before it runs
anything that needs the namespace; `dat --version` and `dat --help` need no
config at all.

It comes two ways, and they are not the same. A copy of `bin/dat` (below)
execs the config's `run:` — your program's main, with its mounts. The `dat`
console script an environment installs is `dvc_dat.do:cli_main`: the
library's own command line, with no project mounts, and it never reads
`run:`.

The config's folder is the project's import root: it goes first on
`sys.path` when the config installs, so `mypkg.job.run` means the same
thing from every directory under the project, whether or not `mypkg` is
installed.

```
dat TARGET [ARG ...] [KEY=VALUE ...]      run TARGET
dat list [PREFIX]                         the mounted names
dat info                                  version, folder, config
dat version                               the version
dat --help                                the usage message
```

## Reserved words

| Command | Does |
|---------|------|
| `dat TARGET [ARG ...] [KEY=VALUE ...]` | `do(TARGET, *ARGS, **KWARGS)`. The return value prints on stdout when it is not `None`. |
| `dat list [PREFIX]` | Every mounted name whose name contains `PREFIX`, with what it loads to. The library mounts `dt` (`dvc_dat.dat_tools`) itself; `dat dt.list` is the same command. |
| `dat info` | The version, the dat folder, the config folder and the `.dataconfig.yaml` in force. `dat --info` is the same command. |
| `dat version` | The version. `dat --version` is the same command. |
| `dat` · `dat --help` · `dat -h` | The usage message. |

`list`, `info` and `version` are reserved words in the first position and
nowhere else; anything else in the first position is a `TARGET`. A target
that happens to be named `list` cannot be run from the shell — rename it.

## Arguments

`TARGET` is a dotted name resolved by `do.load` — the running program's
`do.mount(...)` names first, then the longest importable prefix. What happens next is the library's rule, not the
CLI's: a **callable** is called, a **template spec** is forked — the fixed
arguments become the new spec's `dat.args`, the `KEY=VALUE` pairs update its
`dat.kwargs` key by key — and the forked spec creates a dat, which runs.

Every fixed argument and every `KEY=VALUE` value is read as a **YAML scalar**:

```bash
# do("train", 7, True)
dat train 7 true

# do("train", epochs=7, lr=0.01)
dat train epochs=7 lr=0.01

# do("train", tags=["a", "b"], name="7")
dat train tags=[a,b] name='"7"'

# a bare word stays a string; an empty value is None
dat train note=hello
dat train note=
```

A word is a keyword argument when it starts with `NAME=` (a Python identifier
followed by `=`); anything else is a fixed argument. `--` ends the options, so
every word after it is a fixed argument even when it looks like one of them:

```bash
dat echo -- --not-an-option
```

The `TARGET` itself is never parsed as YAML.

## Options

| Option | Does |
|--------|------|
| `--set DOTTED.KEY=VALUE` | Set one spec key of a template before it forks; repeatable. The value is a YAML scalar. |
| `--json DOTTED.KEY '<json>'` | Set one spec key to a parsed JSON value. |
| `--dry-run` | Print the `do(...)` call this line would make, and any `--set` / `--json` updates, without making it. |
| `--usage` | Print `TARGET`'s own usage — a `<base>.usage` value, else the spec's `usage` key — else the general usage. |

`--set` / `--json` update a **template spec**; using them on a target that is
a plain function is an error.

```bash
dat my_letters --set "dat.title=Re-configured letterator"
dat my_letters --set dat.title=Quickie --set start=100 --set end=110
dat my_letters --json rules '[[2, "my_letters.triple_it"]]'
```

## Exit status

| Code | Meaning |
|------|---------|
| `0` | Ran. |
| `1` | The run raised, or the command line was malformed. |
| `2` | `TARGET` does not load. |
| `3` | (the bootstrap copy only) no `.dataconfig.yaml` above the working directory. |

A failed run prints one line on stderr and no traceback. Set `DAT_DEBUG=1` to
get the traceback instead.

## `bin/dat` — your project's `dat` from any directory

`bin/dat` is a POSIX `sh` script, checked into the repo and copied wherever it
is useful — `~/bin`, a project's root. It is `dat` from any directory, with no
environment activated and nothing assumed about the project's layout. With an
environment active, the console script of the same name comes first on
`PATH`; it runs the library's own command line with no project mounts and
never reads `run:`, so call the copy by its path to get your main:

1. Walk up from the working directory to the nearest `.dataconfig.yaml` (it
   stops at `/`; with none found it prints a message and exits `3`).
2. Pick the command — the first of:
   - `$DAT_RUN`,
   - the config's `run:` key,
   - `.venv/bin/python -m dvc_dat`, when `.venv` sits beside the config,
   - `python3 -m dvc_dat`.
3. `exec` that command with the arguments appended, working directory
   unchanged, and one variable set for it: `DAT_CLI_CONFIG`, the config
   file it found. A program's own main tests it to know it was launched
   by `dat`, and `cli_main()` reads the config from it, so the file is
   found once. Nothing else reads the variable.

A relative path in the command's first word is relative to the config's
folder.

```bash
# once
cp .../dvc-dat/bin/dat ~/bin/dat

# then, from anywhere in the project
cd any/deep/subfolder && dat train epochs=200
```

## `run:` in `.dataconfig.yaml`

```yaml
dat_folders: data

# the command a copy of bin/dat hands its arguments to
run: uv run dat
```

`run` is any command that ends up in `cli_main()`. For a project with no
mounts, the library's own command line will do: `uv run dat`, `conda run -n
ml dat`, `.venv/bin/python -m dvc_dat`. A project that mounts names points it at
its **own main** — `run: .venv/bin/python -m mypkg.main` — a module that
imports what it needs, makes its `do.mount(...)` calls and, when
`DAT_CLI_CONFIG` is set, ends with `sys.exit(dat.cli_main())`, so the shell
runs inside the program's own namespace and the same main is free to do
anything else when run by hand:

```python
if __name__ == "__main__":
    if os.environ.get("DAT_CLI_CONFIG"):   # launched by the dat bootstrap
        sys.exit(dat.cli_main())
    ...                                    # your own main
```

`cli_main(argv=None, *, config=None)` takes the config as a parameter
instead, for a program that runs the command line on a config it chose;
the environment variable is never the way to hand it one.
The library itself never reads the key — it is there so that one file
describes the whole project. `DataConfig.run` carries it, with a relative
first word made absolute.
