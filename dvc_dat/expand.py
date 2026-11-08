"""Spec expansion: OmegaConf's `${…}` grammar, with `${unique:}` alone on the base install (doc/expand.md).

    ${batch}            a node of the spec (an absolute path from its root: ${dat.kwargs.game})
    ${ns:asset.pose}    ns.load("asset.pose"); a function is called, ${ns:a.f, 1, x} with those literals
    ${now:%Y}           the folder's moment, strftime; ${now:} is %y-%m-%d_%H-%M-%S
    ${unique:}          the counter: 1, 2, 3 as a whole path segment, "", _2, _3 inside one
    ${cwd:}             the working directory
    \\${                a literal ${

A string is *plain* (no `${`), *unique* (every `${` is exactly `${unique:}`) or *expand* (any other `${`, or the
escape `\\${`). A tree is the worst of its strings. Plain is returned as given and unique is filled by
`unique_text`, neither importing omegaconf; expand needs `dvc-dat[expand]`, and without omegaconf it is
`ImportError` before anything is written. With omegaconf the tree is one `OmegaConf.create(..., allow_objects)` and
`to_container(resolve=True)`, the four resolvers bound to the call's namespace, moment and count, and every
`${unique:}` filled by the same `unique_text` rule, so both tiers give the same strings. A brace without `$` is
plain text. This module imports neither `dvc_dat.core` nor `dvc_dat.do` (1519 R1).
"""

import contextvars
import inspect
import os
import re
from datetime import datetime, tzinfo
from typing import Any, Callable, Dict, Iterator, Optional, Tuple

PLAIN, UNIQUE, EXPAND = 0, 1, 2
UNIQUE_REF = "${unique:}"
NOW_FORMAT = "%y-%m-%d_%H-%M-%S"
_OPEN = re.compile(r"(\\*)\$\{")
#: The resolvers a `${unique:}` is rewritten to before OmegaConf sees it: which one is decided by where it sits.
_SEGMENT, _SUFFIX = "dat_unique_segment", "dat_unique_suffix"
_RESOLVERS = ("ns", "now", "unique", "cwd", _SEGMENT, _SUFFIX)
_INSTALL = "install dvc-dat[expand] (or dvc-dat[hydra]), or write the value literally"


class _Context:
    __slots__ = ("load", "now", "count")

    def __init__(self, load: Callable[[str], Any], now: datetime, count: int) -> None:
        self.load, self.now, self.count = load, now, count


_CTX: "contextvars.ContextVar[Optional[_Context]]" = contextvars.ContextVar("dvc_dat_expand", default=None)


# -- the scan ------------------------------------------------------------------

def _opens(text: str) -> Iterator[Tuple[int, int]]:
    """`(start, backslashes)` of each `${` in `text`: `start` the index of the `$`, `backslashes` how many
    backslashes stand right before it."""
    for m in _OPEN.finditer(text):
        yield m.end() - 2, len(m.group(1))


def scan_text(text: str) -> int:
    """`PLAIN`, `UNIQUE` or `EXPAND` (see the module doc)."""
    if "${" not in text:
        return PLAIN
    for start, slashes in _opens(text):
        if slashes or not text.startswith(UNIQUE_REF, start):
            return EXPAND
    return UNIQUE


def scan(tree: Any) -> int:
    """The worst `scan_text` over every string value of `tree` (keys are never read)."""
    worst = PLAIN
    for text in _strings(tree):
        worst = max(worst, scan_text(text))
        if worst == EXPAND:
            break
    return worst


def _strings(tree: Any) -> Iterator[str]:
    if isinstance(tree, str):
        yield tree
    elif isinstance(tree, dict):
        for v in tree.values():
            yield from _strings(v)
    elif isinstance(tree, (list, tuple)):
        for v in tree:
            yield from _strings(v)


def _map(tree: Any, fn: Callable[[str], Any]) -> Any:
    """A copy of `tree` with `fn` applied to every string value."""
    if isinstance(tree, str):
        return fn(tree)
    if isinstance(tree, dict):
        return {k: _map(v, fn) for k, v in tree.items()}
    if isinstance(tree, list):
        return [_map(v, fn) for v in tree]
    if isinstance(tree, tuple):
        return tuple(_map(v, fn) for v in tree)
    return tree


def _whole_segment(text: str, start: int, end: int) -> bool:
    """`text[start:end]` is a whole path segment (`events/${unique:}`)."""
    return (start == 0 or text[start - 1] == "/") and (end == len(text) or text[end] == "/")


def unique_count(count: int, whole_segment: bool) -> str:
    """What `${unique:}` fills at `count`: `str(count)` as a whole path segment, else `""` then `_2`, `_3`."""
    if whole_segment:
        return str(count)
    return "" if count == 1 else f"_{count}"


def unique_text(text: str, count: int) -> str:
    """`text` with every unescaped `${unique:}` filled at `count` (`unique_count`), nothing else read."""
    out, at = [], 0
    for start, slashes in _opens(text):
        if slashes % 2 or not text.startswith(UNIQUE_REF, start):
            continue
        end = start + len(UNIQUE_REF)
        out += [text[at:start], unique_count(count, _whole_segment(text, start, end))]
        at = end
    return "".join(out) + text[at:]


def has_unique(text: Any) -> bool:
    """`text` holds an unescaped `${unique:}`."""
    return isinstance(text, str) and any(
        not slashes % 2 and text.startswith(UNIQUE_REF, start) for start, slashes in _opens(text))


def _rewrite_unique(text: str) -> str:
    """Each unescaped `${unique:}` as the private resolver its place picks, so OmegaConf fills it by the
    whole-segment rule."""
    out, at = [], 0
    for start, slashes in _opens(text):
        if slashes % 2 or not text.startswith(UNIQUE_REF, start):
            continue
        end = start + len(UNIQUE_REF)
        out += [text[at:start], "${%s:}" % (_SEGMENT if _whole_segment(text, start, end) else _SUFFIX)]
        at = end
    return "".join(out) + text[at:]


# -- quoting --------------------------------------------------------------------

def _quote_text(text: str) -> str:
    if "${" not in text:
        return text
    try:
        import omegaconf  # noqa: F401
    except ImportError:
        raise ValueError(f"{text!r}: a call-site value is data, kept as given; on the base install it may hold no "
                         f"`${{` (its escape, `\\${{`, is the expand tier's); {_INSTALL}") from None
    return _OPEN.sub(lambda m: m.group(1) * 2 + "\\${", text)


def quote_spec(spec: Any) -> Any:
    """A copy of `spec` that the resolve hands back as it was: each `${` in a string escaped as `\\${`, the
    backslashes already before it doubled. A tree with no `${` is returned as given; one holding `${` needs
    omegaconf (on the base install a value is stored literally, and the escape is the expand tier's)."""
    return _map(spec, _quote_text)


# -- resolving ------------------------------------------------------------------

def _omegaconf(why: str = "") -> Any:
    try:
        from omegaconf import OmegaConf
    except ImportError:
        raise ImportError(f"expand_spec: {why or 'the spec holds a `${...}` reference other than ${unique:} and '}"
                          f"omegaconf is not installed; {_INSTALL}") from None
    return OmegaConf


def _context() -> _Context:
    ctx = _CTX.get()
    if ctx is None:
        raise RuntimeError("a dvc-dat resolver (ns, now, unique, cwd) runs only inside DAT's own resolve "
                           "(Dat.create, ns.expand); hand DAT the tree unresolved")
    return ctx


def _ns(name: Any, *args: Any) -> Any:
    obj = _context().load(str(name))
    if args:
        if not callable(obj):
            raise TypeError(f"${{ns:{name}, ...}}: {name!r} is {obj!r}, not callable")
        return obj(*args)
    return obj() if inspect.isroutine(obj) else obj


def _now(fmt: str = NOW_FORMAT) -> str:
    return _context().now.strftime(fmt)


def _unique(*args: Any) -> str:
    raise ValueError(f"${{unique:{','.join(map(str, args))}}}: ${{unique:}} takes no argument")


def _cwd() -> str:
    return os.getcwd()


def _register(OmegaConf: Any) -> None:
    """DAT's resolvers, registered again at every resolve (`replace=True`): Hydra registers its own `now`, a live
    clock, and DAT's must win whichever was imported last."""
    register = getattr(OmegaConf, "register_resolver", None) or OmegaConf.register_new_resolver  # 2.4's, else 2.3's
    for name, fn in (("ns", _ns), ("now", _now), ("unique", _unique), ("cwd", _cwd),
                     (_SEGMENT, lambda: unique_count(_context().count, True)),
                     (_SUFFIX, lambda: unique_count(_context().count, False))):
        register(name, fn, replace=True)


def resolve_spec(spec: Any, *, load: Callable[[str], Any], tz: Optional[tzinfo] = None,
                 now: Optional[datetime] = None, count: int = 1) -> Any:
    """`spec` with every string resolved (the module doc): returned as given when plain, filled by
    `unique_text` when unique, else through OmegaConf with `${ns:…}` loaded by `load`, the clock at `now` (default:
    this moment in `tz`) and `${unique:}` at `count`."""
    kind = scan(spec)
    if kind == PLAIN:
        return spec
    if kind == UNIQUE:
        return _map(spec, lambda text: unique_text(text, count))
    OmegaConf = _omegaconf()
    if not isinstance(spec, (dict, list)):
        return resolve_spec({"value": spec}, load=load, tz=tz, now=now, count=count)["value"]
    _register(OmegaConf)
    token = _CTX.set(_Context(load, now or datetime.now(tz), count))
    try:
        cfg = OmegaConf.create(_map(spec, _rewrite_unique), flags={"allow_objects": True})
        return OmegaConf.to_container(cfg, resolve=True)
    finally:
        _CTX.reset(token)


class Template:
    """A spec resolved again at each count without being parsed again (`DatManager._place` climbing a
    `${unique:}`): `name(key, count)` is the string at the top-level `key` at that count, `tree(count)` the
    whole spec."""

    def __init__(self, spec: Dict[str, Any], *, load: Callable[[str], Any], tz: Optional[tzinfo] = None,
                 now: Optional[datetime] = None) -> None:
        self._spec, self._load, self._tz, self._now = spec, load, tz, now or datetime.now(tz)
        self._cfg: Any = None
        if scan(spec) == EXPAND:
            self._oc = _omegaconf()
            self._cfg = self._oc.create(_map(spec, _rewrite_unique), flags={"allow_objects": True})

    def _resolved(self, count: int, get: Callable[[Any], Any]) -> Any:
        _register(self._oc)
        token = _CTX.set(_Context(self._load, self._now, count))
        try:
            return get(self._cfg)
        finally:
            _CTX.reset(token)

    def name(self, key: str, count: int) -> Any:
        if self._cfg is None:
            return resolve_spec(self._spec[key], load=self._load, now=self._now, count=count)
        return self._resolved(count, lambda cfg: cfg[key])

    def tree(self, count: int) -> Any:
        if self._cfg is None:
            return resolve_spec(self._spec, load=self._load, now=self._now, count=count)
        return self._resolved(count, lambda cfg: self._oc.to_container(cfg, resolve=True))


def expand_text(text: str, vars: Dict[str, Any], *, load: Callable[[str], Any], tz: Optional[tzinfo] = None,
                now: Optional[datetime] = None, count: int = 1) -> str:
    """The body of `Namespace.expand`: `text` resolved as the one string of a tree whose other top-level nodes are
    `vars` (each value data: quoted, never resolved), always a str."""
    if not isinstance(text, str):
        raise TypeError(f"expand takes a str, not {type(text).__name__}; a spec is expand_spec's")
    kind = scan_text(text)
    if kind != EXPAND:
        return unique_text(text, count) if kind == UNIQUE else text
    key = "_dat_expand_text_"
    tree = {**{k: quote_spec(v) for k, v in vars.items()}, key: text}
    value = resolve_spec(tree, load=load, tz=tz, now=now, count=count)[key]
    if not isinstance(value, (str, int, float)):
        raise TypeError(f"expand: {text!r} resolved to {type(value).__name__}, not a string or a number; expand "
                        "returns a str (the object a name refers to is ns.load(name); a spec value that is exactly "
                        "one reference is inlined by expand_spec)")
    return str(value)


#: A pre-changeover reference (`{YYYY}`, `{unique}`, `{a.b}`, `{a.b(1)}`) in a `dat.name`, not preceded by `$`.
_OLD_REFERENCE = re.compile(r"(?<![$\\{])\{([A-Za-z_][\w.]*(?:\(.*?\))?)\}")
_OLD_BUILTINS = {"YYYY": "${now:%Y}", "YY": "${now:%y}", "MM": "${now:%m}", "DD": "${now:%d}", "HH": "${now:%H}",
                 "mm": "${now:%M}", "SS": "${now:%S}", "now": "${now:}", "unique": "${unique:}", "cwd": "${cwd:}"}


def refuse_old_name(template: Any) -> None:
    """`ValueError` for a `dat.name` holding a reference in the `{…}` grammar retired in 3.0 (1519 decision 3),
    naming its new spelling; anything else passes."""
    if not isinstance(template, str):
        return
    m = _OLD_REFERENCE.search(template)
    if m is None:
        return
    name = m.group(1)
    new = _OLD_BUILTINS.get(name) or ("${ns:%s}" % name if "." in name else "${dat.kwargs.%s}" % name)
    raise ValueError(f"dat.name {template!r}: {{{name}}} is the `{{…}}` grammar retired in dvc-dat 3.0; write "
                     f"{new} (doc/expand.md)")


__all__ = ["scan", "scan_text", "PLAIN", "UNIQUE", "EXPAND", "unique_text", "unique_count", "has_unique",
           "quote_spec", "resolve_spec", "Template", "expand_text", "refuse_old_name", "UNIQUE_REF", "NOW_FORMAT"]
