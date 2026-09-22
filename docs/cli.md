# Command Line

`dat` is the console script. It configures itself from the nearest
`.dataconfig.yaml` — walking up from the working directory — before it runs
anything that needs the namespace; `dat --version` and `dat --help` need no
config at all.

The config's folder is the project's import root: `dat` puts it first on
`sys.path` before resolving anything, so `mypkg.job.run` means the same
thing from every directory under the project, whether or not `mypkg` is
installed. (The API path never touches `sys.path`; the program that
imported `dvc_dat` owns it.)

```
dat do TARGET [ARG ...] [KEY=VALUE ...]   run TARGET
dat TARGET [ARG ...] [KEY=VALUE ...]      the same, shorthand
dat list [PREFIX]                         the mounted names
dat info                                  version, folder, config
dat version                               the version
dat --help                                the usage message
```

## Verbs

| Command | Does |
|---------|------|
| `dat do TARGET [ARG ...] [KEY=VALUE ...]` | `do(TARGET, *ARGS, **KWARGS)`. The return value prints on stdout when it is not `None`. |
| `dat TARGET ...` | The same, for any `TARGET` that is not one of the verbs below. |
| `dat list [PREFIX]` | Every mounted name whose name contains `PREFIX`, with what it loads to. |
| `dat info` | The version, the sync folder, the config folder and the `.dataconfig.yaml` in force. `dat --info` is the same command. |
| `dat version` | The version. `dat --version` is the same command. |
| `dat` · `dat --help` · `dat -h` | The usage message. |

A verb name is only a verb in the first position: `dat do list` runs a target
named `list`, and `dat do info NAME` runs one named `info`.

## Arguments

`TARGET` is a dotted name resolved by `do.load` — the mount table first, then
the longest importable prefix. What happens next is the library's rule, not the
CLI's: a **callable** is called, a **template spec** is forked — the fixed
arguments become the new spec's `dat.args`, the `KEY=VALUE` pairs update its
`dat.kwargs` key by key — and the forked spec creates a dat, which runs.

Every fixed argument and every `KEY=VALUE` value is read as a **YAML scalar**:

```bash
# do("train", 7, True)
dat do train 7 true

# do("train", epochs=7, lr=0.01)
dat do train epochs=7 lr=0.01

# do("train", tags=["a", "b"], name="7")
dat do train tags=[a,b] name='"7"'

# a bare word stays a string; an empty value is None
dat do train note=hello
dat do train note=
```

A word is a keyword argument when it starts with `NAME=` (a Python identifier
followed by `=`); anything else is a fixed argument. `--` ends the options, so
every word after it is a fixed argument even when it looks like one of them:

```bash
dat do echo -- --not-an-option
```

The `TARGET` itself is never parsed as YAML.

## Options

| Option | Does |
|--------|------|
| `--set DOTTED.KEY VALUE` | Set one spec key of a template before it forks. The value is a string. |
| `--sets DOTTED.KEY1=VALUE1,DOTTED.KEY2=VALUE2,...` | Set several at once. |
| `--json DOTTED.KEY '<json>'` | Set one spec key to a parsed JSON value. |
| `--print` | Print the `do(...)` call instead of making it. |
| `--usage` | Print `TARGET`'s own usage — a `<base>.usage` value, else the spec's `usage` key — else the general usage. |

`--set` / `--sets` / `--json` update a **template spec**; using them on a target
that is a plain function is an error.

```bash
dat my_letters --set dat.title "Re-configured letterator"
dat my_letters --sets dat.title=Quickie,start=100,end=110
dat my_letters --json rules '[[2, "my_letters.triple_it"]]'
```

## Exit status

| Code | Meaning |
|------|---------|
| `0` | Ran. |
| `1` | The run raised, or the command line was malformed. |
| `2` | `TARGET` does not load. |
| `3` | (`X` only) no `.dataconfig.yaml` above the working directory. |

A failed run prints one line on stderr and no traceback. Set `DAT_DEBUG=1` to
get the traceback instead.

## `X` — running a dat without activating an environment

`bin/X` is a POSIX `sh` script, checked into the repo and copied wherever it is
useful. `X TARGET ...` is `dat do TARGET ...`, from any directory, with no
environment activated and nothing assumed about the project's layout:

1. Walk up from the working directory to the nearest `.dataconfig.yaml` (it
   stops at `/`; with none found it prints a message and exits `3`).
2. Pick the interpreter — the first of:
   - `$DAT_PYTHON`,
   - the config's `python:` key,
   - `.venv/bin/python` beside the config,
   - `python3` on `PATH`.
3. `exec <python> -m dvc_dat do "$@"`, with the working directory unchanged.

A value that names a folder means the venv holding it, so `python: myenv` and
`python: myenv/bin/python` are the same interpreter. A relative value resolves
against the config's folder.

```bash
# once
cp .../dvc-dat/bin/X ~/bin/X

# then, from anywhere in the project
cd any/deep/subfolder && X train epochs=200
```

## `python:` in `.dataconfig.yaml`

```yaml
local_prefix: data

# the interpreter X runs: a path, or a folder holding bin/python
python: .venv
```

`python` is the interpreter `X` runs: a path to one, or a folder holding
`bin/python`. A relative path resolves against the config's folder. The library
itself never reads the key — it is there so that one file describes the whole
project. `DataConfig.python` carries it, absolute.
