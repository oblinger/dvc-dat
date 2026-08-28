"""Generic dict-address and file-loading helpers.

Nothing in this module knows about dats: these are recursive-dict plumbing
(`merge_dicts`, the `dotted_*` family) and format-agnostic file loading
(`load_dict`).  `dat.py` builds its spec handling on top of them, and
`Dat.get`/`set`/`gets`/`sets` remain as thin wrappers there.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union, cast

import yaml

if TYPE_CHECKING:
    from .dat import Dat, SpecDict

_NO_ARG = object()


def merge_dicts(
    *dicts: Dict,
    inplace: bool = False,
) -> Dict:
    """Recursively merge N dicts, with each dict having priority over the previous one."""
    if len(dicts) == 1:
        return dicts[0]

    dict_1 = dicts[0]
    if not inplace:
        dict_1 = deepcopy(dict_1)

    dict_2 = dicts[1]
    for k, v in dict_2.items():
        if isinstance(v, dict):
            dict_1[k] = merge_dicts(dict_1.get(k, {}), v)
        else:
            dict_1[k] = v
    return merge_dicts(dict_1, *dicts[2:])


def load_dict(conf_path: Optional[Union[str, Path]]) -> Optional[Dict[str, Any]]:
    """Load either a json or yaml file into a dict."""
    if conf_path is None:
        return None

    conf = None
    conf_path = Path(conf_path)
    if not conf_path.exists():
        return conf
    try:
        with conf_path.open("r") as f:
            if ".json" in conf_path.suffixes:
                conf = json.load(f)
            if ".yaml" in conf_path.suffixes or ".yml" in conf_path.suffixes:
                conf = yaml.safe_load(f)
    except Exception:
        return None
    return conf


def _as_dict(source: Union[Dat, dict]) -> dict:
    # Duck-typed rather than isinstance(source, Dat) so this module never
    # imports dat.py at runtime (dat.py imports us; the reverse would cycle).
    # The isinstance(source, type) guard keeps a *class* (whose get_spec is an
    # unbound function) flowing through untouched, as isinstance(source, Dat) did.
    spec_getter = getattr(source, "get_spec", None)
    if callable(spec_getter) and not isinstance(source, type):
        return cast(dict, spec_getter())
    return cast(dict, source)


def dotted_get(
    source: Union[Dat, dict],
    keys: Union[str, List[str]],
    default_value: Any = _NO_ARG,
):
    """Utility method to get value from a recursive dict tree or return None."""
    d = _as_dict(source)
    if isinstance(keys, str):
        keys = keys.split(".")
    for k in keys:
        if d is None:
            result = None
            break
        elif not isinstance(d, dict):
            raise ValueError(f"GET: Expected dict value for {k!r} not {d!r}")
        else:
            d = d.get(k)
    else:
        result = d
    if result is not None:
        return result
    elif default_value is _NO_ARG:
        raise KeyError(f"GET: Key {keys} not found in {source!r}")
    else:
        return default_value


def dotted_gets(source: Union[Dat, SpecDict], *dotted_keys):
    assert source is not None, "gets method requires a non None dict"
    source_ = _as_dict(source)
    results = []
    for dotted_key in dotted_keys:
        keys = dotted_key.split(".")
        results.append(dotted_get(source_, keys))
    return results


def dotted_set(source: SpecDict, keys, value):
    """Utility method into a recursive dict tree."""
    assert source is not None, "set method requires a non None dict"
    assert len(keys) > 0, "set method requires at least one key"
    if isinstance(keys, str):
        keys = keys.split(".")
    for k in keys[:-1]:
        if not isinstance(source, dict):
            raise Exception(f"Expected dict value for {k!r} not {source!r}")
        sub = source.get(k)
        if sub is None:
            sub = source[k] = {}
        source = sub
    source[keys[-1]] = value


def dotted_sets(source: dict, *assignments):
    """Utility method that applies multiple dotted assignments into a
    recursive dict tree.

    Each assignment is of the form:   key.sub_key...=value
    - spaces are trimmed from ends and around '='
    - values are parsed as an int, as a float, else as a string.
    """
    assert source is not None, "set method requires a non None dict"
    for assignment in assignments:
        prefix, suffix = assignment.split("=")
        keys, suffix = prefix.strip().split("."), suffix.strip()
        try:
            value = int(suffix)
        except ValueError:
            try:
                value = float(suffix)
            except ValueError:
                value = suffix
        dotted_set(source, keys, value)
