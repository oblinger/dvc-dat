"""The namespace: `ns` maps dotted names to Python objects.

    ns.load("pkg.mod.fn")         # the object a dotted name imports to
    ns.name_of(obj)               # the dotted name that loads back to obj
    ns.mount(folder=..., at=...)  # add names to the namespace, in code
    ns.mounts()                   # the mount table: {prefix: location}
    ns.expand("runs/{YYYY}/{a.b}", k=v)  # a template filled through these names, a str

Running is the manager's: `Dat.manager.run(target, *args, **kwargs)` runs a
dat, a template spec or a plain callable, loading names through this namespace.
`ns` (`Dat.ns`) is the process's default namespace: it forwards to `Dat.manager.ns`,
whichever manager that is.  `DatManager(dat_folders=[...])` is another world
with an `ns` of its own.  A dotted name is a mounted name, else exactly what
`import` means in this environment, `getattr` below that.  Mounts are
`ns.mount(...)` calls in the program; `.datconfig.yaml` holds none.  Importing
never reads the filesystem; the first use builds `Dat.manager` from the
nearest `.datconfig.yaml`.

In a project whose `.datconfig.yaml` says `namespace: ledger`, `Dat.manager.ns` is a
`LedgerNamespace` (`dvc_dat.ledger.namespace`, DAT 1046, 1051): the same interface, its
names the ledger's `db/mount` rows, and `mount` refused.
"""

import copy
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

from .core import DAT_CONFIG_FILE, Dat, DatManager
from .namespace import Namespace

Spec = Dict[str, Any]


class _DefaultNamespace:
    """`dvc_dat.do.ns` (`Dat.ns`): forwards every call and attribute to `Dat.manager.ns`, so it
    always acts on the default world, whichever manager that is."""

    __slots__ = ()

    @staticmethod
    def _current() -> Optional[Namespace]:
        """The default world's `Namespace` if one is built yet, else None (reads no config)."""
        from . import core
        return core._default_manager.ns if core._default_manager is not None else None

    def __getattr__(self, name: str) -> Any:
        return getattr(Dat.manager.ns, name)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(f"Dat.ns forwards to Dat.manager.ns; set {name!r} there")

    def __repr__(self) -> str:
        return f"<Dat.ns -> {self._current()!r}>"


# The process's default namespace: `Dat.manager.ns`, whichever manager that is.
ns = _DefaultNamespace()


# =============================================================================
# Command line
# =============================================================================

USAGE = """
SYNOPSIS
    x TARGET [ARG ...] [KEY=VALUE ...]          run TARGET
    x --list [PREFIX]                           the mounted names
    x --info                                    version, folders, config
    x --version                                 the version
    x --help                                    this message

DESCRIPTION
    `x` is `just run` (the recipe in dvc_dat.just; `just mounts` is
    `x --list`).  It configures itself from the nearest .datconfig.yaml
    before it runs anything that needs the namespace.  A word in first
    position is always a TARGET; the commands that ask about the command
    line itself are flags.

    `x TARGET ...` calls Dat.manager.run(TARGET, *ARGS, **KWARGS).  A TARGET that is a
    template spec is forked: the fixed ARGs become its dat.args and the
    KEY=VALUE pairs update its dat.kwargs, key by key; the forked spec creates
    a dat, and that dat runs.  A TARGET that is a callable is simply called.
    The return value prints on stdout when it is not None.

    With `namespace: ledger` in the config, `x TARGET KEY=VALUE ...` is
    rev.run(TARGET, KEY=VALUE, ...): found if computed before from the same
    inputs by the same code, else run and sealed; it prints `hit` or `ran`
    and the value, and alias=NAME names it.  TARGET is a dotted name
    through the ledger's mounts or a spec file: a ledger function (its
    keys the KEY=VALUE pairs), a dat spec or a dat's run function (the
    pairs update its dat.kwargs), or a spec whose `main` names a ledger
    function (the line's keys over the file's).

    A function marked @command (dvc_dat.just), or a spec with `command:`,
    also runs as `just NAME` once the justfile has
    `import? '.dat/targets.just'`; `run` rewrites that file when stale.

    Every ARG and every KEY=VALUE value is JSON, else the text as typed: 7 is
    an int, true is a bool, null is None, [1,2] is a list, '"7"' is the string
    7, and 2026-01-01 or a bare word is that string.  A KEY=VALUE pair is recognised by a leading NAME= ; use -- to end
    the options and pass anything after it as a fixed argument.

OPTIONS
    --set DOTTED.KEY=VALUE      VALUE JSON, else the text as typed
    --json DOTTED.KEY=JSON      JSON a JSON value
                Update one spec key of a template before it forks; each
                repeats, one KEY=VALUE per flag

    --dry-run   Print the python Dat.manager.run() call instead of making it
    --usage     Print TARGET's own usage (a <base>.usage value, or the spec's
                usage key), else this message

EXIT STATUS
    0   ran
    1   the run failed, or the command line was malformed
    2   TARGET does not load

    A failure prints one line on stderr and no traceback; set DAT_DEBUG=1
    for the traceback.

EXAMPLES
    x hello_world
    x hello_again.salutation Maxim emphasis=true lucky_number=7
    x my_letters --set dat.title=Quickie --set start=100 --set end=110
    just mounts hello
"""

_KWARG = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=")


ENV_CLI_CONFIG = "DAT_CLI_CONFIG"     # set by `just run`, read here and nowhere else
ENV_JUSTFILE = "DAT_JUSTFILE"         # set by `just run`: the justfile, for `.dat/targets.just`


def cli_main(argv: Optional[List[str]] = None, *,
             config: Union[None, str, Path] = None) -> int:
    """The command line (`just run`, `x`), for a program's own main.

    A program that mounts names -- or simply wants the command line to run
    inside its own imports -- names its main in `.datconfig.yaml`'s `run:` and,
    when `DAT_CLI_CONFIG` is set, ends with `sys.exit(dat.cli_main())`.  The
    `run` recipe of `dvc_dat.just` sets that one variable -- the config file it
    found -- for the program it launches, so the main knows it was launched by
    `just run` and the config is read once; nothing else reads the variable.  `argv` defaults to
    `sys.argv`; `config` (a folder or a config file) replaces the default world,
    `Dat.manager = DatManager.load_dat_config(config, ns=Dat.ns)`, keeping
    its mounts; with neither, first use discovers one.  The return value is the
    exit status.
    """
    if config is None:
        config = os.environ.get(ENV_CLI_CONFIG) or None
        if config and not Path(config).is_file():
            raise ValueError(f"{ENV_CLI_CONFIG}={config}: no such config file")
    if config is not None:
        Dat.manager = DatManager.load_dat_config(config, ns=ns)
    argv = list(sys.argv if argv is None else argv)
    justfile = os.environ.get(ENV_JUSTFILE)
    if config is not None and justfile and argv[1:2] not in (["--version"], ["--help"], ["-h"]):
        from .just import refresh
        cfg = Path(config)
        try:
            refresh(ns, cfg.parent if cfg.is_file() else cfg, Path(justfile))
        except Exception as e:
            print(f"run: targets: {_message(e)}", file=sys.stderr)
    return _do_argv(argv, config)


def _do_argv(argv: List[str], config: Union[None, str, Path] = None) -> int:
    """Run one command line (argv[0] is the program); returns the exit code."""
    args = list(argv[1:])
    if not args or args[0] in ("-h", "--help"):
        print(USAGE)
        return 0
    command, rest = args[0], args[1:]
    if command == "--version":
        from . import __version__
        print(__version__)
        return 0
    elif command == "--info":
        return _cmd_info(rest)
    elif command == "--list":
        return _cmd_list(rest)
    return _cmd_do(args, config)


def _cmd_do(argv: List[str], config: Union[None, str, Path] = None) -> int:
    """`x TARGET ...` -- every line whose first word is not a flag."""
    try:
        overrides, args, kwargs, flags = _parse_argv(argv)
    except ValueError as e:
        return _fail(str(e))
    if not args:
        if "usage" in flags:
            print(USAGE)
            return 0
        return _fail("no TARGET given; `x --help` for usage")
    if "usage" not in flags:
        try:
            ledger = _ledger_of(config, namespace=True)
        except Exception as e:
            return _fail(_message(e))
        if ledger is not None:
            return _cmd_eval(ledger, args, kwargs, overrides, flags)
    target, fixed = args[0], [arg_value(a) for a in args[1:]]
    try:
        cmd = ns.load(target)
    except Exception as e:                  # a mounted file that does not parse included: one line, 2
        if os.environ.get("DAT_DEBUG"):
            raise
        return _fail(f"cannot load {target!r}: {_message(e)}", code=2)
    if "usage" in flags:
        usage = ns.load(target.split(".")[0] + ".usage", default=None)
        if usage is None and isinstance(cmd, dict):
            usage = cmd.get("usage")
        print(usage or USAGE)
        return 0
    elif "dry-run" in flags:
        shown = ([repr(target)] + [repr(a) for a in fixed]
                 + [f"{k}={v!r}" for k, v in kwargs.items()])
        print(f"Dat.manager.run({', '.join(shown)})")
        if overrides:
            print(f"  with the spec updated by --set/--json: {dict(overrides)!r}")
        return 0
    try:
        if isinstance(cmd, dict):
            spec = _apply_sets(ns._merge_bases(cmd), overrides)
            result = Dat.manager.run(spec, *fixed, **kwargs)
        elif overrides:
            return _fail(f"--set/--json need a template spec; "
                         f"{target!r} is {type(cmd).__name__}")
        elif not callable(cmd):
            print(cmd)
            return 0
        else:
            result = Dat.manager.run(target, *fixed, **kwargs)
    except Exception as e:
        if os.environ.get("DAT_DEBUG"):
            raise
        return _fail(_message(e))
    if result is not None:
        print(result)
    return 0


def _config_file(config: Union[None, str, Path]) -> Optional[Path]:
    """The `.datconfig.yaml` in force: `config` (a file or its folder), else the manager's."""
    if config is None:
        folder = getattr(Dat.manager, "_config_dir", None)
        config = os.path.join(folder, DAT_CONFIG_FILE) if folder else None
    if config is None:
        return None
    path = Path(config)
    path = path if path.suffix in (".yaml", ".yml") else path / DAT_CONFIG_FILE
    return path if path.is_file() else None


def _ledger_of(config: Union[None, str, Path], *, namespace: bool = False) -> Any:
    """The config's active ledger (`DAT_LEDGER`, else its `default:`), else None when it names none; with
    `namespace`, None too unless the project's names are the ledger's (`namespace: ledger`, the one switch)."""
    path = _config_file(config)
    if path is None:
        return None
    from .core import _ledger_namespace
    from .ledger.ledger import DEFAULT_KEY, ENV, Ledger, _resolve, _values
    values = _values(path)
    if namespace and not _ledger_namespace(path, values):
        return None
    if not os.environ.get(ENV) and values.get(DEFAULT_KEY) is None:
        return None
    return Ledger._opened(*_resolve(path, values, os.environ.get(ENV)))


RESERVED_RUN_KEYS = ("alias",)                # control options on a ledger run, never a key


def _cmd_eval(ledger: Any, args: List[str], kwargs: Dict[str, Any], overrides: List[Tuple[str, Any]],
              flags: set) -> int:
    """`x TARGET k=v ...` with a ledger: `rev.run(TARGET, **kwargs)`, found if computed before, else run
    and sealed (DAT 1046).

    TARGET is what `rev.run` takes: a dotted name through the ledger's mounts (a ledger function, a
    spec, or a dat's run function, its keys updating the spec's `dat.kwargs`), or a spec file
    (`.yaml`/`.json`).  A spec whose `main` names a ledger function is that function, its other keys
    the keys, the line's over the file's.  `--set` / `--json` update a spec's keys.  `alias=NAME`
    names the result (`path=`).
    """
    target, fixed = args[0], args[1:]
    if fixed:
        return _fail(f"a run through the ledger takes keywords only (KEY=VALUE); got {fixed!r}")
    rev = ledger.at()
    spec: Any = None
    is_file = os.path.isfile(target) and target.endswith((".yaml", ".yml", ".json"))
    try:
        if is_file:
            with open(target) as f:
                spec = json.load(f) if target.endswith(".json") else yaml.safe_load(f)
            if not isinstance(spec, dict):
                return _fail(f"{target}: a spec is a mapping, not {type(spec).__name__}")
        else:
            obj = rev.ns.load(target)
            if isinstance(obj, dict):
                spec = obj
            elif overrides:
                return _fail(f"--set/--json need a spec; {target!r} is {type(obj).__name__}")
    except Exception as e:
        if os.environ.get("DAT_DEBUG"):
            raise
        return _fail(f"cannot load {target!r}: {_message(e)}", code=2)
    run_target: Any = target
    keys: Dict[str, Any] = {}
    if spec is not None:
        spec = _apply_sets(spec, overrides)
        if isinstance(spec.get("main"), str):
            run_target = spec["main"]
            keys = {k: v for k, v in spec.items() if k not in ("main", "command")}
        elif isinstance(spec.get("dat"), dict):
            run_target = spec if (is_file or overrides) else target
        else:
            return _fail(f"{target}: a spec run through the ledger is a dat spec (`dat:` naming its run "
                         "function in `dat.do`) or names a ledger function in `main`")
    keys.update(kwargs)
    alias = keys.pop("alias", None)
    if "dry-run" in flags:
        shown = [repr(run_target)] + [f"{k}={v!r}" for k, v in keys.items()]
        print(f"rev.run({', '.join(shown)})" + (f", then named {alias!r}" if alias else ""))
        return 0
    try:
        hit = rev.run(run_target, seal="get", path=alias, **keys)
        value = hit or rev.run(run_target, path=alias, **keys)
    except Exception as e:
        if os.environ.get("DAT_DEBUG"):
            raise
        return _fail(_message(e))
    preds = " ".join(f"{p}={json.dumps(o) if isinstance(o, (dict, list)) else o}"
                     for p, o in value.preds.items())
    print(f"{'hit' if hit else 'ran'}  {value}" + (f"  {preds}" if preds else ""))
    return 0


def _cmd_list(argv: List[str]) -> int:
    """`x --list [PREFIX]` (`just mounts`) -- the mounted names."""
    if len(argv) > 1:
        return _fail("--list takes at most one PREFIX")
    from .dat_tools import cmd_list
    cmd_list(argv[0] if argv else "")
    return 0


def _cmd_info(argv: List[str]) -> int:
    """`x --info` -- the version, the folders and the config in force."""
    if argv:
        return _fail("--info takes no arguments")
    from . import __version__
    manager = Dat.manager
    config_dir = manager._config_dir
    print("\n# -- Dat Configuration Info -- ")
    print(f"# Dat version       : {__version__}")
    print(f"# Dat folder        : {manager._dat_folders[0]}")
    print(f"# Artifact folder   : {manager._art_folder or '(none)'}")
    print(f"# .datconfig folder : {config_dir}")
    config_file = os.path.join(config_dir, DAT_CONFIG_FILE) if config_dir else None
    if config_file and os.path.exists(config_file):
        print(f"# .datconfig.yaml   : {config_file}")
        with open(config_file) as f:
            print(f.read())
    else:
        print("# (no .datconfig.yaml found)")
    print()
    return 0


def _parse_argv(argv: List[str]) -> Tuple[List[Tuple[str, Any]], List[str], Dict[str, Any], set]:
    """Split `x TARGET` arguments into spec overrides, positionals, kwargs and flags.

    The overrides are the `--set` / `--json` `(DOTTED.KEY, value)` pairs in order, each setting
    one key (`_apply_sets`).  Positionals come back as written (the first is the target name); every
    KEY=VALUE value is `arg_value` (JSON, else the text).  A malformed line raises `ValueError`.
    """
    overrides: List[Tuple[str, Any]] = []
    shape: Spec = {}                    # the keys the line sets, so a key under a scalar it set is refused
    args: List[str] = []
    kwargs: Dict[str, Any] = {}
    flags: set = set()
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--":
            args += argv[i + 1:]
            break
        elif arg in ("--set", "--json"):
            (pair,) = _operands(argv, i, 1)
            key, eq, value = pair.partition("=")
            if not eq or not key:
                raise ValueError(f"{arg} needs DOTTED.KEY=VALUE, got {pair!r}")
            if arg == "--json":
                try:
                    value = json.loads(value)
                except json.JSONDecodeError as e:
                    raise ValueError(f"--json {key}: illegal JSON: {e}")
            else:
                value = arg_value(value)
            Dat.set(shape, key, copy.deepcopy(value))
            overrides.append((key, value))
            i += 1
        elif arg in ("--dry-run", "--usage"):
            flags.add(arg[2:])
        elif not args and not arg.startswith("-"):
            args.append(arg)                # the first word is the TARGET, never parsed (cli.md)
        elif (match := _KWARG.match(arg)):
            kwargs[match.group(1)] = arg_value(arg[match.end():])
        elif arg.startswith("-") and arg != "-" and isinstance(arg_value(arg), str):
            raise ValueError(f"unknown option {arg!r}; "
                             f"keyword arguments are written KEY=VALUE")
        else:
            args.append(arg)
        i += 1
    return overrides, args, kwargs, flags


def _apply_sets(spec: Spec, overrides: List[Tuple[str, Any]]) -> Spec:
    """A copy of `spec` with each `--set` / `--json` pair applied in order: the value replaces what the
    dotted key held (a dict or a named list too, never merged into it); missing levels are made."""
    out = copy.deepcopy(spec)
    for key, value in overrides:
        Dat.set(out, key, copy.deepcopy(value))
    return out


def _operands(argv: List[str], i: int, count: int) -> List[str]:
    """The `count` words after the option at `argv[i]`."""
    operands = argv[i + 1:i + 1 + count]
    if len(operands) < count:
        raise ValueError(f"{argv[i]} needs {count} value(s)")
    return operands


def arg_value(text: str) -> Any:
    """One command-line value: JSON, else the text exactly as typed (DAT 1041).

    The one `k=v` grammar of every dat command line (`x`, `just run`, `--set`, the
    ledger recipes): `12` an int, `1.5` a float, `true` a bool, `null` None, `[1,2]`
    a list, `{"a":1}` a dict, `"12"` the string 12; `2026-01-01`, `foo` and `NaN`
    are not JSON, so each is that string.
    """
    if text != text.strip():
        return text                     # JSON would drop the padding: not the text as typed
    try:
        return json.loads(text, parse_constant=_not_json, parse_float=_finite)
    except (ValueError, RecursionError):
        return text


def _finite(text: str) -> float:
    """A JSON number too big for a float (`1e999`) is not `inf`: the text stays as typed."""
    x = float(text)
    if math.isinf(x):
        raise ValueError(text)
    return x


def _not_json(name: str) -> Any:
    """`NaN` / `Infinity` / `-Infinity` are Python's extensions, not JSON."""
    raise ValueError(name)


def _message(error: BaseException) -> str:
    """One line naming an exception and the exceptions it was raised from."""
    parts: List[str] = []
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        text = str(error) or type(error).__name__
        if text not in parts:
            parts.append(text)
        error = error.__cause__
    return ": ".join(parts)


def _fail(text: str, code: int = 1) -> int:
    """Print a one-line error on stderr and return the exit code."""
    text = " ".join(line.strip() for line in text.splitlines() if line.strip())   # a YAML error spans lines
    print(f"run: {text}", file=sys.stderr)
    return code
