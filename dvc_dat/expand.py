"""Spec expansion: the `{}` grammar (doc/expand.md), with no Dat layer.

`expand` fills one string, `expand_spec` every string value of a spec tree, `quote_spec` escapes a tree so that
`expand_spec` hands it back as it was, and `spec_variables` gives a spec's expansion variables. This module imports
neither `dvc_dat.core` nor `dvc_dat.do`, so the ledger's namespace (`ns.expand`) uses it without loading the Dat
layer (1519 R1).
"""

import ast
import inspect
import os
import re
from datetime import datetime, tzinfo
from typing import Any, Callable, Dict, List, Optional, Tuple


_REFERENCE = re.compile(r"\{\{|\}\}|\{([^{}]*)\}|[{}]")
_WHOLE_VALUE = re.compile(r"^\{([^{}]+)\}$")
_BUILTIN_NAMES = ("YYYY", "YY", "MM", "DD", "HH", "mm", "SS", "now", "cwd", "unique")


def _builtins(now: Optional[datetime] = None, tz: Optional[tzinfo] = None) -> Dict[str, str]:
    """The built-in expansion variables at one moment, `now` (default: this moment) in the zone `tz`
    (`None`: the machine's local zone, a namespace with no ledger; a ledger namespace passes its ledger's)."""
    if now is None:
        now = datetime.now(tz)
    elif tz is not None:
        now = now.astimezone(tz)
    return {
        "now": now.strftime("%y-%m-%d_%H-%M-%S"),
        "YYYY": now.strftime("%Y"),
        "YY": now.strftime("%Y")[2:],
        "MM": now.strftime("%m"),
        "DD": now.strftime("%d"),
        "HH": now.strftime("%H"),
        "mm": now.strftime("%M"),
        "SS": now.strftime("%S"),
        "unique": "",
        "cwd": os.getcwd(),
    }


_CALL = re.compile(r"^([A-Za-z_][\w.]*)\s*\((.*)\)$", re.DOTALL)


def _literal_args(text: str, reference: str) -> Tuple[List[Any], Dict[str, Any]]:
    """The arguments of `{fn(...)}`: Python literals only, positional then
    keyword; no names, no expressions, no `*` or `**`."""
    try:
        call = ast.parse(f"_({text})", mode="eval").body
    except SyntaxError:
        raise ValueError(f"expand: {{{reference}}}: the arguments do not parse") from None
    assert isinstance(call, ast.Call)
    try:
        if any(isinstance(a, ast.Starred) for a in call.args) or any(
                k.arg is None for k in call.keywords):
            raise ValueError
        args = [ast.literal_eval(a) for a in call.args]
        kwargs = {k.arg: ast.literal_eval(k.value) for k in call.keywords}
    except ValueError:
        raise ValueError(f"expand: {{{reference}}}: arguments are Python literals only -- "
                         "numbers, strings, True/False/None, and lists, tuples or "
                         "dicts of them") from None
    return args, kwargs


def _resolve_name(name: str, vars: Dict[str, Any], resolver: Callable[[str], Any]) -> Any:
    """What one `{}` reference expands to.  A dotted name that resolves to a
    function or method is called with no arguments; `{a.b(1, k=2)}` calls
    whatever `a.b` resolves to with those literals.  A class, or any other
    callable object, is returned as it is unless called with parentheses."""
    name = name.strip()
    if not name:
        raise ValueError("expand: empty reference '{}'")
    if (call := _CALL.match(name)):
        target = call.group(1)
        if "." not in target:
            raise ValueError(f"expand: {{{name}}}: only a dotted name can be called")
        fn = _lookup_name(target, vars, resolver)
        if not callable(fn):
            raise TypeError(f"expand: {{{name}}}: {target!r} is {fn!r}, not callable")
        args, kwargs = _literal_args(call.group(2), name)
        return fn(*args, **kwargs)
    value = _lookup_name(name, vars, resolver)
    if "." in name and inspect.isroutine(value):
        return value()
    return value


def _lookup_name(name: str, vars: Dict[str, Any], resolver: Callable[[str], Any]) -> Any:
    if "." in name:
        return resolver(name)
    if name in vars:
        return vars[name]
    given = sorted(k for k in vars if k not in _BUILTIN_NAMES)
    raise KeyError(
        f"expand: unknown name {{{name}}}; an undotted name is an expansion variable, a built-in "
        f"{sorted(_BUILTIN_NAMES)} or a keyword given to the call ({', '.join(given) or 'none given'}); "
        "a dotted name resolves through the namespace"
    )


def _whole_segment(text: str, start: int, end: int) -> bool:
    """The reference at `text[start:end]` is a whole path segment (`events/{unique}`)."""
    return (start == 0 or text[start - 1] == "/") and (end == len(text) or text[end] == "/")


def _has_unique(text: str) -> bool:
    """`text` holds the reference `{unique}` (not the literal `{{unique}}`)."""
    return any((m.group(1) or "").strip() == "unique" for m in _REFERENCE.finditer(text))


def expand(text: str, vars: Dict[str, Any], *, resolver: Callable[[str], Any],
           tz: Optional[tzinfo] = None, count: Optional[int] = None) -> str:
    """The body of `Namespace.expand` (see it): `text` with its `{}` references filled, a str.

    `vars` are the call's keywords, over the built-ins at one moment in `tz`; dotted names go to
    `resolver`.  `count` (a ledger namespace's counter) gives `{unique}` its value: a whole path
    segment `str(count)`, a suffix `""` then `_2`, `_3`, ...; a keyword `unique=` wins over it.
    """
    if not isinstance(text, str):
        raise TypeError(f"expand takes a str, not {type(text).__name__}; a spec is expand_spec's")
    return _fill(text, {**_builtins(None, tz), **vars}, resolver,
                 None if "unique" in vars else count)


def _fill(text: str, names: Dict[str, Any], resolver: Callable[[str], Any],
          count: Optional[int] = None) -> str:
    def replace(match: "re.Match") -> str:
        token = match.group(0)
        if token == "{{":
            return "{"
        if token == "}}":
            return "}"
        if token in ("{", "}"):
            raise ValueError(
                f"expand: {text!r}: a lone {token!r} -- references do not nest (a reference holds no "
                "'{' or '}'; build a name chosen by a variable first), and a literal brace is '{{' or '}}'")
        name = match.group(1)
        if count is not None and name.strip() == "unique":
            if _whole_segment(text, match.start(), match.end()):
                return str(count)
            return "" if count == 1 else f"_{count}"
        value = _resolve_name(name, names, resolver)
        if not isinstance(value, (str, int, float)):
            raise TypeError(
                f"expand: {{{name}}} must be a string or a number, got {type(value).__name__}; "
                "expand returns a str (the object a name refers to is ns.load(name); a spec "
                "value that is exactly one reference is inlined by expand_spec)")
        return str(value)

    return _REFERENCE.sub(replace, text)


def quote_spec(spec: Any) -> Any:
    """The body of `Namespace.quote_spec`: a copy of `spec` that `expand_spec` turns back into
    `spec`, every brace in a string doubled."""
    if isinstance(spec, dict):
        return {k: quote_spec(v) for k, v in spec.items()}
    if isinstance(spec, list):
        return [quote_spec(v) for v in spec]
    if isinstance(spec, str):
        return spec.replace("{", "{{").replace("}", "}}")
    return spec


def expand_spec(spec: Any, vars: Dict[str, Any], *, resolver: Callable[[str], Any],
                tz: Optional[tzinfo] = None) -> Any:
    """The body of `Namespace.expand_spec`: a copy of `spec` with every string value expanded (keys are
    left alone), the built-ins taken at one moment.  A string value that is exactly one reference is
    replaced by what it names, any object (`cfg: "{svp.defaults}"` inlines the dict)."""
    names = {**_builtins(None, tz), **vars}

    def walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, str):
            if (whole := _WHOLE_VALUE.match(value)):
                return _resolve_name(whole.group(1), names, resolver)
            return _fill(value, names, resolver)
        return value

    return walk(spec)


def spec_variables(spec: Dict[str, Any], *, resolver: Callable[[str], Any], tz: Optional[tzinfo] = None,
                   now: Optional[datetime] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """`(spec, variables)`: the expansion variables of a spec (SVP 1508), `dat.defaults` overridden by
    `dat.kwargs`, each value as the run receives it (both maps expanded once here, the built-ins at
    `now`), and a copy of `spec` whose two maps hold those values quoted, so the spec's own expansion
    hands them back unchanged and evaluates no reference in them twice.  A `dat.defaults` or
    `dat.kwargs` that is not a mapping with str keys is `TypeError`."""
    dat = spec.get("dat") if isinstance(spec, dict) else None
    if not isinstance(dat, dict):
        return spec, {}
    names = _builtins(now, tz)
    variables: Dict[str, Any] = {}
    out = None
    for key in ("defaults", "kwargs"):
        given = dat.get(key)
        if given is None:
            continue
        if not isinstance(given, dict) or not all(isinstance(k, str) for k in given):
            raise TypeError(f"dat.{key} is a mapping of names to values, not {given!r}")
        values = expand_spec(given, names, resolver=resolver, tz=tz)
        variables.update(values)
        if out is None:
            out = dict(spec)
            out["dat"] = dict(dat)
        out["dat"][key] = quote_spec(values)
    return (out if out is not None else spec), variables
