#!/usr/bin/env python3

"""
The 'do' module provides a way to dynamically load and execute python code.


API
    do(do_spec, *args, **kwargs) -> Any    # loads, caches, and executes a do-fn
    load(dotted_name) -> Any               # loads, caches, and returns a python object
    do_argv(sys.argv) -> None              # Executes a do command from the command line


.datconfig
    The do module search CWD and all its parent folders for the '.datconfig' file.
    If it is found, it expects a JSON object with a 'do_folder' key that indicates
    the path (relative to the .datconfig file itself) of the "do folder"
"""

import os
import sys
import copy
import json
import yaml
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Type, Union, Any, Dict, Callable

from dat.inst import Inst

# The loadable "do" fns, scripts, configs, and methods are in the do_folder
_DAT_FILE = ".datconfig"
_INST_FOLDER_KEY = "inst_data_folder"
_DO_FOLDER_KEY = "do_folder"
_DO_EXTENSIONS = [".json", ".yaml", ".py"]
_DO_ERROR_FLAG = tuple("multiple loadable modules have this same name")
_DO_NULL = tuple("arg not specified")

_MAIN_BASE = "main.base"
_MAIN_DO = "main.do"              # the main fn to execute
_MAIN_ARGS = "main.args"          # prefix args for the main.do method
_MAIN_KWARGS = "main.kwargs"      # default kwargs for the main.do method

Spec = Dict[str, Any]


class DoManager(object):
    """Manages the loading and execution of 'do' methods.

    The 'do' method is a configurable dynamically loadable function call.  API:

    do(do_spec, *args, **kwargs) -> Any   # loads, caches, and executes a do-fn
    do.load(dotted_name) -> Any           # loads, caches, and returns a python object
    do.define_module(base, path)          # specifies the full path of the python module
    do.define_fn(base, name, fn)          # specifies a fn to be used in a do call
    """
    do_index: Dict[str, Union[str, ModuleType]]   # path to module or module itself
    do_fns: Dict[str, Dict[str, Callable]]        # externally defined fns

    def __init__(self, *, do_folder):
        self.do_index = {}
        self.do_fns = {}
        self.do_folder = do_folder

    def __call__(self, do_spec: Union[Spec, str], *args, **kwargs) -> Any:
        """Loads and executes a 'do-method'.

        A "do function" or "do method" is a configurable dynamically loadable function
        call. Each 'do' accepts a multi-level configuration dict as its first
        argument followed by any number of additional fixed and keyword arguments.

        If "do_spec" is a:
        - STRING: then 'do.load' is used to get the value to use in its place
        - DICT: then its 'main.do' sub-key specifies the function to execute
          If it is a string then, get_loadable is used to get fn to execute
          Otherwise it is directly called.
        - CALLABLE: then it is directly called with the specified args and kwargs

        The function found is called with the spec dict found as its first
        argument, then specified args and kwargs after that.
        """
        obj = self.load(do_spec) if isinstance(do_spec, str) else do_spec
        if callable(obj):
            result = obj(*args, **kwargs)
            return result
        try:
            obj = self.expand_spec(obj, context=do_spec)
            fn_spec = Inst.get(obj, _MAIN_DO)
        except IOError:
            raise Exception(F"The loadable {do_spec!r} is not a callable or config")
        if isinstance(fn_spec, str):
            fn_spec = self.load(fn_spec)
        if not callable(fn_spec):
            raise Exception(F"'{_MAIN_DO}' in {do_spec!r} of type {type(fn_spec)} "
                            + "is not callable")
        result = fn_spec(obj, *args, **kwargs)
        return result

    def define_module(self, base: str, path: str, *, allow_redefine=False):
        """Specifies the full path of the python module to load for a given base name"""
        if not allow_redefine and base in self.do_index:
            raise Exception(F"Base {base!r} is already defined")
        self.do_index[base] = path

    def define_fn(self, base: str, name: str, fn: Callable):
        """Specifies a fn to be used in a do call."""
        if base not in self.do_fns:
            self.do_fns[base] = {}
        self.do_fns[base][name] = fn

    def merge_configs(self, base, override):
        """Recursively merges the 'override' dict trees over 'base' tree of dicts."""
        if isinstance(override, dict) and isinstance(base, dict):
            merge = dict(base)
            for k, v in override.items():
                merge[k] = self.merge_configs(merge.get(k), v)
            # if BASE in base:
            #     merge[BASE] = base[BASE]
            return merge
        elif override:
            return override
        else:
            return base

    def expand_spec(self, spec: Union[Spec | str], context: str = None) -> Spec:
        """Expands a spec by recursively loading and expanding its 'main.base' spec,
        and then merging its keys as an override to the expanded base."""
        if isinstance(spec, str):
            spec = self.load(spec, context=context)
            spec = copy.deepcopy(spec)
        if base := Inst.get(spec, _MAIN_BASE):
            sub_spec = self.expand_spec(base, context=context)
            return self.merge_configs(sub_spec, spec)
        else:
            return spec

    def load(self, dotted_name: str, *, default: Any = _DO_NULL, kind: Type = None,
             context=None) -> Any:
        """Uses 'dotted_name' do find a "loadable" python object, and then dynamically
        load this object from within the loadables folder.

        - If NAME contains a dot ("."), then the first part is called the
          FILENAME, and the second part is called the PART-NAME. If there is
          no dot, then "NAME" is used twice for both FILENAME and PART-NAME.

        - If FILENAME.* is found multiple times in the loadable's folder, then
          an error is generated indicating the ambiguity in loading this name.

        - If FILENAME.json or FILENAME.yaml is found, then it is loaded, and its
          parsed contents are returned.  (PART-NAME is ignored)


        """
        self.do_index = index = self.do_index or _build_loadables_index()
        # _DO_INDEX = index = _build_loadables_index()
        #  <<<<<<< remove in order to start using cached index (once debugging is done)
        ctx = "" if context is None else F" {context}"
        values = dotted_name.split(".")
        if len(values) < 2:
            values = [dotted_name, dotted_name]
        prefix, suffix = values[0], values[1]
        # if "." in dotted_name:
        #     prefix, suffix = dotted_name.split(".", 1)
        # else:
        #     prefix, suffix = dotted_name, dotted_name
        if prefix in self.do_fns and suffix in self.do_fns[prefix]:
            return self.do_fns[prefix][suffix]
        if prefix not in index:
            if default is _DO_NULL:
                raise Exception(F"Loadable module {prefix!r} does not exist{ctx}")
            else:
                return default
        elif isinstance(path := index[prefix], str):
            index[path] = obj = _load_file(os.path.splitext(path)[0])
        elif path == _DO_ERROR_FLAG:
            raise Exception(F"Loadable {prefix!r} is defined multiple times.{ctx}")
        else:
            obj = path[0]   # loaded object is stored in ele 0 of the tuple

        if isinstance(obj, ModuleType):
            if hasattr(obj, suffix):
                result = getattr(obj, suffix)
            else:
                raise Exception(
                    F"Loadable '{prefix}.py' does not define {suffix!r}{ctx}")
        elif "." not in dotted_name:
            result = obj
        elif isinstance(obj, dict):
            result = Inst.gets(obj, suffix)[0]
        else:
            raise Exception(F"Illegal value {obj!r} for {dotted_name}{ctx}")

        if len(values) > 2:
            result = Inst.get(result, values[2:])
        if result is None and default is not _DO_NULL:
            return default
        if result is None:
            raise Exception(F"Required loadable {dotted_name!r} is missing")
        if kind and not isinstance(result, kind):
            raise Exception(F"Expected loadable {dotted_name!r} of type {kind} " +
                            F"but found {result!r}")
        return result


def _load_file(path_base: str) -> Union[ModuleType, Spec]:
    if os.path.exists(name := F"{path_base}.json"):
        with open(name, 'r') as f:
            try:
                return json.load(f)
            except Exception as e:
                raise Exception(F"While parsing {name}, {e}")
    elif os.path.exists(name := F"{path_base}.yaml"):
        with open(name, 'r') as f:
            return yaml.safe_load(f)
    else:
        return _load_module(path_base)


def _load_module(path_base: str) -> ModuleType:
    assert isinstance(path_base, object)
    f = F"{path_base}.py"
    if not os.path.exists(f):
        raise Exception(F"Missing module file: {f} ...")
    spec = importlib.util.spec_from_file_location("module_name", f)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_loadables_index() -> Dict:
    global _DO_EXTENSIONS
    result = {}
    for path in Path(dat_config.do_folder).rglob('*'):
        base, ext = os.path.splitext(os.path.basename(path))
        if not path.is_file() or ext not in _DO_EXTENSIONS or \
                base == '__init__':
            continue
        elif base in result:
            print("WARNING: loadable at" +
                  F"{result[base]} conflicts with {path}")
            result[base] = _DO_ERROR_FLAG
        else:
            result[base] = str(path)
    return result


USAGE = """
SYNOPSIS
    do CMD_NAME FIXED_ARGS ... KEYWORD_ARG ...
    do KEY_WORD_ARGS  ...  CMD_NAME FIXED_ARGS ...

    do --usage
    do --get DOTTED.KEY
    do --set DOTTED.KEY=VALUE
    do --sets "DOTTED.KEY1=VALUE1, DOTTED.KEY2=VALUE2"

DESCRIPTION
    Executes the do command named by CMD_NAME.
    
    --usage     Prints the command-specific usage info if it exists
    
    --USAGE     Prints this usage message
    
    --print     Prints the python do call with args, but does not call it.
    
    --get DOTTED.NAME
                Expands the config for a command and returns an arg from it
    
    --set DOTTED.NAME=VALUE
    --sets DOTTED.NAME1=VALUE1,DOTTED.NAME2=VALUE2,...
                Expands the config for a command and updates the indicated
                config parameters before invoking the indicated command

NOTES
    Per standard UNIX 'getopt' parameter parsing two dashes ("--")
    can be used to terminate keyword arguments and cause all remaining 
    arguments to be treated as fixed parameters even when those parameters
    begin with "-" in a way that could be confused as additional keywords

    Unlike most UNIX parameters each single dash ("-") keywords cannot
    be concatenated.  So "do -a -b foo" cannot be shorted to "do -ab foo"
    
    All keyword arguments can be either flags or keywords with arguments, 
    thus "--" must be added in some cases to avoid treating a fixed arg
    as the value associated with a keyword flag.
    

EXAMPLES

    do --show balls,hoops viz
"""


def do_argv(argv):
    """
    --usage will Look up "CMD_NAME.usage" to see if usage was specified, else it
    looks at the "usage" key in config for usage, else print default usage
    """
    overrides, args, kwargs = _parse_argv(argv[1:])
    # print(F"DO  args={args!r}   kwargs={kwargs!r}")
    if "usage" in kwargs or (not args and not kwargs):
        print(USAGE)
        return
    elif len(args) == 0 and "usage" not in kwargs:
        print("Error: No do-command specified.")
        return
    cmd = do.load(args[0])
    spec = do.expand_spec(cmd) if hasattr(cmd, "__getitem__") else {}
    spec = do.merge_configs(spec, overrides)
    # for keys, value in overrides:
    #     Inst.set(spec, keys, value)
    if "usage" in kwargs:
        try:
            usage = do.load(args[0].split(".")[0] + ".usage")
        except IOError:
            usage = spec.get("usage") or USAGE
        print(usage)
        return
    elif "print" in kwargs:
        del kwargs["print"]
        args = [repr(a) for a in args]
        kwargs = [F"{k}={repr(v)}" for k, v in kwargs.items()]
        print(F"  do({', '.join(args + kwargs)})")
        return
    elif spec:
        args_ = Inst.get(spec, _MAIN_ARGS) or []
        kwargs_ = Inst.get(spec, _MAIN_KWARGS) or {}
        kwargs_.update(kwargs)
        result = do(spec, *args_ + args[1:], **kwargs_)
    elif not callable(cmd):
        print(cmd)
        return
    elif overrides:
        print("Error: Cannot specify --set or --sets on a do w/o a config")
        return
    else:
        result = do(*args, **kwargs)
    if result is not None:
        print(result)


def _parse_argv(argv):
    overrides, args, kwargs, i, argv = {}, [], {}, 0, argv + ["--end-of-args"]
    while i < len(argv) - 1:
        arg = argv[i]
        flag = _get_flag(arg)
        if arg == "--":
            args += argv[i+1:-1]
            break
        elif arg == "--json":
            try:
                Inst.set(overrides, argv[i+1], json.loads(argv[i+2]))
                # overrides.append((argv[i+1], json.loads(argv[i+2])))
            except json.decoder.JSONDecodeError:
                print(F"Illegal JSON: {argv[i+2]}")
            i += 2
        elif arg == '--set':
            Inst.set(overrides, argv[i+1], argv[i+2])
            # overrides.append((argv[i+1], argv[i+2]))
            i += 2
        elif arg == "--sets":
            Inst.sets(overrides, *argv[i+1].split(","))
            # overrides += [part.strip().split("=") for part in argv[i+1].split(",")]
            # assignments += map(str.strip, argv[i+1].split(','))
            i += 1
        elif not flag:
            args.append(arg)
        elif _get_flag(argv[i + 1]):
            kwargs[flag] = True
        else:
            kwargs[flag] = argv[i + 1]
            i += 1
        i += 1
    return overrides, args, kwargs


def _get_flag(arg):
    if not all(c.isalnum() or c == '-' for c in arg):
        return None
    elif arg == "--":
        return arg
    elif arg.startswith("--"):
        return arg[2:].replace("-", "_")
    elif arg.startswith("-") and len(arg) == 2:
        return arg[1]
    else:
        return None


class DatConfig(object):
    config: Dict[str, Any]
    do_folder: str
    inst_folder: str

    def _lookup_path(self, folder_path, key, default):
        if key in self.config:
            path = os.path.join(folder_path, self.config[key])
        else:
            path = os.path.join(os.getcwd(), default)
        os.makedirs(path, exist_ok=True)
        return path

    def __init__(self):
        self.config = {}
        folder = os.getcwd()
        while True:
            if os.path.exists(config := os.path.join(folder, _DAT_FILE)):
                with open(config, 'r') as f:
                    self.config = json.load(f)
                    break
            if folder == '/':
                folder = os.getcwd()
                break
            folder = os.path.dirname(folder)
        self.do_folder = self._lookup_path(folder, _DO_FOLDER_KEY, "do")
        self.inst_folder = self._lookup_path(folder, _INST_FOLDER_KEY, "inst_data")
        # print(F"# DO_FLDR = {self.do_folder}\n# INST_DATA = {self.inst_folder}")


dat_config = DatConfig()
do = DoManager(do_folder=dat_config.do_folder)


if __name__ == '__main__':
    # do_argv([None, "cmdln_example", "--show-spec"])
    # do_argv([None, "my_letters", "--set", "main.title", "Re-configured letterator",
    # "--json", "rules", '[[2, "my_letters.triple_it"]]'])
    # do_argv([None, "my_letters", "--sets", "main.title=QuickChart,start=100,end=110"])
    do_argv(sys.argv)
