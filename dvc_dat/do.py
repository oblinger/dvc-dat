"""The namespace: `ns` maps dotted names to Python objects.

    ns.load("pkg.mod.fn")         # the object a dotted name imports to
    ns.name_of(obj)               # the dotted name that loads back to obj
    ns.mount(folder=..., at=...)  # add names to the namespace, in code
    ns.mounts()                   # the mount table: {prefix: location}
    ns.expand("runs/${now:%Y}/${ns:a.b}/${k}", k=v)   # a template filled through these names, a str

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
import itertools
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

# =============================================================================
# Overrides: `KEY=VALUE` on base, Hydra's override grammar with dvc-dat[hydra] (1519 R5)
# =============================================================================

#: An override's key: a name, or a dotted path into the spec (`dat.base`, `model.width`).
_OVERRIDE_KEY = re.compile(r"[A-Za-z_][\w-]*(?:\.[A-Za-z_][\w-]*)*")
#: A word Hydra's grammar alone reads: a `+` (add), `++` (add or change) or `~` (delete) before a key.
_HYDRA_PREFIX = re.compile(r"(\+\+|\+|~)[A-Za-z_]")
_SWEEP_FUNCTIONS = ("range(", "choice(", "glob(", "interval(")
MULTIRUN = ("-m", "--multirun")


class Override:
    """One override of a command line: `op` is `set` (`key=v`: add or change), `add` (`+key=v`: the key must be
    new), `force` (`++key=v`) or `delete` (`~key`); `path` the keys from the spec's root (an undotted key is
    `dat.kwargs.<key>`); `value` the spec text or value (`delete`: unused)."""

    __slots__ = ("op", "key", "path", "value")

    def __init__(self, op: str, key: str, value: Any = None) -> None:
        self.op, self.key, self.value = op, key, value
        self.path = key.split(".") if "." in key else ["dat", "kwargs", key]

    @property
    def bare(self) -> bool:
        """An undotted `key=v`: what a callable or a ledger function takes as a keyword."""
        return self.op == "set" and "." not in self.key

    def __repr__(self) -> str:
        sign = {"set": "", "add": "+", "force": "++", "delete": "~"}[self.op]
        return f"{sign}{self.key}" + ("" if self.op == "delete" else f"={self.value!r}")


def _top_level_comma(text: str) -> bool:
    """A `,` outside brackets, braces, parentheses and quotes: Hydra's choice (`a,b`). A JSON list or mapping
    (`[1,2]`, `{"a":1,"b":2}`), today's line, keeps its commas inside."""
    depth, quote = 0, None
    for ch in text:
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth -= 1
        elif ch == "," and depth == 0:
            return True
    return False


def needs_hydra(word: str, multirun: bool = False) -> bool:
    """Whether a word is Hydra's override grammar beyond today's `KEY=VALUE` (1519 decision 7): `-m`, or a `+`, `++`
    or `~` before a key; under `-m` also a value that is a choice (`a,b`) or a sweep function (`range(1,3)`). Without
    `-m` a comma is text, as it always was (`modules=a,b`): Hydra itself runs a sweep only under `-m`."""
    if word in MULTIRUN or _HYDRA_PREFIX.match(word):
        return True
    key, eq, value = word.partition("=")
    return multirun and bool(eq) and _OVERRIDE_KEY.fullmatch(key) is not None and (
        _top_level_comma(value) or value.startswith(_SWEEP_FUNCTIONS))


def _hydra_parser(word: str) -> Any:
    try:
        from hydra.core.override_parser.overrides_parser import OverridesParser
    except ImportError:
        raise ValueError(f"{word!r} needs Hydra's override grammar; install dvc-dat[hydra]") from None
    return OverridesParser.create()


def _hydra_points(words: List[str], multirun: bool) -> List[List[Override]]:
    """The points a line in Hydra's grammar names: the product of its choices and sweeps, in Hydra's order (the
    first override varies slowest, as `BasicSweeper` does); each point a list of overrides."""
    from hydra.core.override_parser.types import OverrideType

    parsed = _hydra_parser(words[0]).parse_overrides(words)
    axes: List[List[Override]] = []
    for o in parsed:
        key = o.key_or_group
        if o.package is not None:
            raise ValueError(f"{o.input_line!r}: a package (`@`) is Hydra's config groups; a DAT override names a key")
        if o.type == OverrideType.DEL:
            axes.append([Override("delete", key)])
            continue
        op = {OverrideType.CHANGE: "set", OverrideType.ADD: "add", OverrideType.FORCE_ADD: "force"}[o.type]
        if o.is_sweep_override() and not multirun:          # `a,b` without -m: the text as typed, today's line
            axes.append([Override(op, key, arg_value(o.input_line.partition("=")[2]))])
        elif o.is_sweep_override():
            axes.append([Override(op, key, v) for v in o.sweep_iterator()])
        else:
            axes.append([Override(op, key, o.value())])
    return [list(point) for point in itertools.product(*axes)] if axes else [[]]


def parse_overrides(words: List[str], multirun: bool = False) -> List[List[Override]]:
    """The points of a line's override words: one point of `KEY=VALUE` overrides (`arg_value`, today's grammar) when
    no word needs Hydra's grammar; else the whole set through Hydra's `OverridesParser`, under `-m` each choice and
    sweep a point (without it, the text as typed), and without dvc-dat[hydra] `ValueError` naming the word and the
    extra."""
    hydra_word = next((w for w in words if needs_hydra(w, multirun)), None)
    if multirun and hydra_word is None:
        hydra_word = "-m"
    if hydra_word is not None:
        _hydra_parser(hydra_word)
        return _hydra_points(words, multirun) if words else [[]]
    point = []
    for word in words:
        key, _, value = word.partition("=")
        point.append(Override("set", key, arg_value(value)))
    return [point]


def apply_overrides(spec: Spec, point: List[Override]) -> Spec:
    """A copy of `spec` with one point's overrides applied in order: `set` writes the value (missing levels made),
    `add` refuses a key already there, `force` writes it either way, `delete` removes a key that is there. A value
    is spec text: `${…}` in it resolves at create."""
    out = copy.deepcopy(spec)
    for o in point:
        *parents, last = o.path
        node: Any = out
        for i, k in enumerate(parents):
            if not isinstance(node, dict):
                raise ValueError(f"{o!r}: {'.'.join(o.path[:i])} is not a mapping")
            if node.get(k) is None:
                if o.op == "delete":
                    raise ValueError(f"{o!r}: no key {o.key!r} to delete")
                node[k] = {}
            node = node[k]
        if not isinstance(node, dict):
            raise ValueError(f"{o!r}: {'.'.join(parents)} is not a mapping")
        if o.op == "delete":
            if last not in node:
                raise ValueError(f"{o!r}: no key {o.key!r} to delete")
            del node[last]
        elif o.op == "add" and last in node:
            raise ValueError(f"{o!r}: {o.key!r} is already set; ++{o.key}=... changes it")
        else:
            node[last] = copy.deepcopy(o.value)
    return out


USAGE = """
SYNOPSIS
    x TARGET [ARG ...] [OVERRIDE ...] [-m]      run TARGET
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

    `x TARGET ...` calls Dat.manager.run.  A TARGET that is a template spec
    gets the OVERRIDEs applied to it: KEY=VALUE sets a key, an undotted KEY
    being dat.kwargs.KEY and a dotted one a path from the spec's root
    (dat.title=T); the fixed ARGs become its dat.args; the spec creates a
    dat, and that dat runs.  A TARGET that is a callable is called with the
    ARGs and the undotted KEY=VALUE pairs.  The return value prints on
    stdout when it is not None.

    With `namespace: ledger` in the config, `x TARGET KEY=VALUE ...` is
    rev.run(TARGET, ...): found if computed before from the same inputs by
    the same code, else run and sealed; it prints `hit` or `ran` and the
    value, and alias=NAME names it.  TARGET is a dotted name through the
    ledger's mounts or a spec file: a ledger function (its keys the
    KEY=VALUE pairs), a dat spec or a dat's run function (the overrides
    applied to the spec), or a spec whose `main` names a ledger function
    (the line's keys over the file's).

    A function marked @command (dvc_dat.just), or a spec with `command:`,
    also runs as `just NAME` once the justfile has
    `import? '.dat/targets.just'`; `run` rewrites that file when stale.

    Every ARG and every KEY=VALUE value is JSON, else the text as typed: 7 is
    an int, true is a bool, null is None, [1,2] is a list, '"7"' is the string
    7, and 2026-01-01 or a bare word is that string.  An override's value is
    spec text: ${ns:asset.ocr} resolves when the dat is created.  Use -- to
    end the options and pass anything after it as a fixed argument.

HYDRA'S GRAMMAR (dvc-dat[hydra])
    +KEY=VALUE                  add a key that is not there
    ++KEY=VALUE                 add or change it
    ~KEY                        delete it
    KEY=a,b  KEY=range(1,3)     a sweep under -m, one dat per point (else text)
    -m, --multirun              run every point of the sweeps, in order
                The first word in this grammar sends the whole line through
                Hydra's override parser (its value grammar: 'a b' quoted,
                [a,b] a list, {x:1} a dict); without the extra it is refused
                by name

OPTIONS
    --dry-run   Print the call (each point's) instead of making it; for a
                spec, then the spec it would create, merged and resolved, as
                YAML
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
    x my_letters dat.title=Quickie
    x cfg.run.graded -m game=G1,G4 +horizon=3000
    just mounts hello
"""

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
        words, args, flags = _parse_argv(argv)
        points = parse_overrides(words, multirun="multirun" in flags)
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
            return _cmd_eval(ledger, args, points, flags)
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
    if not isinstance(cmd, dict):
        if any(not o.bare for point in points for o in point):
            return _fail(f"a dotted key, +, ++ or ~ edits a template spec; {target!r} is {type(cmd).__name__}")
        if not callable(cmd):
            print(cmd)
            return 0
    for point in points:
        if "dry-run" in flags:
            if isinstance(cmd, dict):
                print(f"Dat.manager.run({target!r}{''.join(f', {a!r}' for a in fixed)})"
                      + (f"  with the spec updated by {point!r}" if point else ""))
                try:
                    _print_spec(ns, Namespace._fork_spec(apply_overrides(ns._merge_bases(cmd), point), fixed))
                except Exception as e:
                    if os.environ.get("DAT_DEBUG"):
                        raise
                    return _fail(f"cannot resolve {target!r}: {_message(e)}")
            else:
                shown = [repr(target)] + [repr(a) for a in fixed] + [f"{o.key}={o.value!r}" for o in point]
                print(f"Dat.manager.run({', '.join(shown)})")
            continue
        try:
            if isinstance(cmd, dict):
                result = Dat.manager.run(apply_overrides(ns._merge_bases(cmd), point), *fixed)
            else:
                result = Dat.manager.run(target, *fixed, **{o.key: o.value for o in point})
        except Exception as e:
            if os.environ.get("DAT_DEBUG"):
                raise
            return _fail(_message(e))
        if result is not None:
            print(result)
    return 0


class _SpecDumper(yaml.SafeDumper):
    """`--dry-run`'s YAML: a value YAML has no tag for (an object a `${ns:…}` reference inlined) is shown by its repr."""


_SpecDumper.add_multi_representer(object, lambda dumper, obj: dumper.represent_str(repr(obj)))


def _print_spec(namespace: Namespace, spec: Dict[str, Any]) -> None:
    """`--dry-run`'s second part (SVP 1138 Q1 (A)): the spec this line would create, merged over its `dat.base`
    chain and resolved (`namespace.expand_spec`), as YAML; keys in the spec's order."""
    print(yaml.dump(namespace.expand_spec(spec), Dumper=_SpecDumper, sort_keys=False,
                    default_flow_style=False, allow_unicode=True), end="")


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


def _cmd_eval(ledger: Any, args: List[str], points: List[List[Override]], flags: set) -> int:
    """`x TARGET k=v ...` with a ledger: `rev.run(TARGET, **keys)`, found if computed before, else run and sealed
    (DAT 1046); each sweep point (`-m`) is one `rev.run`.

    TARGET is what `rev.run` takes: a dotted name through the ledger's mounts (a ledger function, its keys the
    `k=v` pairs; a spec, or a dat's run function, the overrides applied to the spec, an undotted key being
    `dat.kwargs.<key>`), or a spec file (`.yaml`/`.json`). A spec whose `main` names a ledger function is that
    function, its other keys the keys, the line's over the file's. `alias=NAME` names the result (`path=`).
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
    except Exception as e:
        if os.environ.get("DAT_DEBUG"):
            raise
        return _fail(f"cannot load {target!r}: {_message(e)}", code=2)
    main = spec is not None and isinstance(spec.get("main"), str)
    if spec is not None and not main and not isinstance(spec.get("dat"), dict):
        return _fail(f"{target}: a spec run through the ledger is a dat spec (`dat:` naming its run "
                     "function in `dat.do`) or names a ledger function in `main`")
    for point in points:
        alias = next((o.value for o in point if o.bare and o.key == "alias"), None)
        point = [o for o in point if not (o.bare and o.key == "alias")]
        run_target: Any = target
        keys: Dict[str, Any] = {}
        if main:
            run_target = spec["main"]
            keys = {k: v for k, v in spec.items() if k not in ("main", "command")}
        if spec is None or main:
            if any(not o.bare for o in point):
                return _fail(f"a dotted key, +, ++ or ~ edits a dat spec; {target!r} takes keywords (KEY=VALUE)")
            keys.update({o.key: o.value for o in point})
        elif point or is_file:
            run_target = apply_overrides(spec, point)
        if "dry-run" in flags:
            shown = ([repr(run_target) if not isinstance(run_target, dict) else repr(target)]
                     + [f"{k}={v!r}" for k, v in keys.items()])
            print(f"rev.run({', '.join(shown)})" + (f"  with the spec updated by {point!r}" if point and not keys
                                                     and isinstance(run_target, dict) else "")
                  + (f", then named {alias!r}" if alias else ""))
            if spec is not None and not main:
                try:
                    _print_spec(rev.ns, run_target if isinstance(run_target, dict) else spec)
                except Exception as e:
                    if os.environ.get("DAT_DEBUG"):
                        raise
                    return _fail(f"cannot resolve {target!r}: {_message(e)}")
            continue
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


def _parse_argv(argv: List[str]) -> Tuple[List[str], List[str], set]:
    """Split `x TARGET` arguments into override words, positionals and flags.

    An override word is `KEY=VALUE` (`KEY` a name, or a dotted path into the spec) or one in Hydra's grammar
    (`+k=v`, `++k=v`, `~k`; `parse_overrides` reads them). Positionals come back as written (the first is the
    target name); `--` ends the options. A malformed line raises `ValueError`.
    """
    words: List[str] = []
    args: List[str] = []
    flags: set = set()
    for i, arg in enumerate(argv):
        if arg == "--":
            args += argv[i + 1:]
            break
        elif arg in ("--set", "--json"):
            raise ValueError(f"{arg} was removed in dvc-dat 3.0: write KEY=VALUE, a dotted KEY a path into the spec "
                             "(dat.title=Quickie)")
        elif arg in ("--dry-run", "--usage"):
            flags.add(arg[2:])
        elif arg in MULTIRUN:
            flags.add("multirun")
        elif not args and not arg.startswith("-") and not _HYDRA_PREFIX.match(arg):
            args.append(arg)                # the first word is the TARGET, never parsed (cli.md)
        elif _HYDRA_PREFIX.match(arg) or _OVERRIDE_KEY.fullmatch(arg.partition("=")[0]) and "=" in arg:
            words.append(arg)
        elif arg.startswith("-") and arg != "-" and isinstance(arg_value(arg), str):
            raise ValueError(f"unknown option {arg!r}; keyword arguments are written KEY=VALUE")
        else:
            args.append(arg)
    return words, args, flags


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
