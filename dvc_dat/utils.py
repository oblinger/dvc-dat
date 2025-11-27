import importlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

import yaml

PathLike = Union[str, Path]


def merge_dicts(
    *dicts: Dict,
    inplace: bool = False,
) -> Dict:
    """Recursively merge N dicts, with each dict having priority over the previous one.

    Parameters
    ----------
    inplace : bool
        If True, the merging operations will be done in place. Copies will be created
        otherwise.

    Returns
    -------
    Dict
        Final merged dict.

    """
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


def dynamic_load_fn(fn_string: str) -> Callable:
    """Dynamically load the function `fn_string`. It must be specified as 'module.fn'."""
    try:
        fn_mod_str, fn_str = fn_string.rsplit(".", maxsplit=1)
    except Exception:
        raise ValueError("Function must be specified as: my_module.my_fn")
    module = importlib.import_module(fn_mod_str)
    try:
        fn: Callable = getattr(module, fn_str)
    except Exception:
        raise AttributeError(f"Function {fn_str} not found in module {module}.")
    return fn


def load_dict(conf_path: Optional[PathLike]) -> Optional[Dict[str, Any]]:
    """Load either a json or yaml file into a dict.

    Parameters
    ----------
    conf_path : Optional[PathLike]
        Path to the config file.

    Returns
    -------
    Optional[Dict[str, Any]]
        The read config, or None if the file doesn't exist.

    """
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
