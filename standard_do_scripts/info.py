import json

from dvc_dat import Dat, do


def __main__(name: str = None):
    dat, do_value = None, None
    try:
        dat = Dat.load(name)
    except KeyError as e:
        pass
    try:
        do_value = do.load(name)
    except KeyError as e:
        pass
    print()
    if not dat and not do_value:
        print(f"The name {name!r} is not a Dat name nor do value")
        return
    if dat:
        print(f" +----- DAT INFO FOR: {dat.get_path_name()!r}")
        print(f" |  path:  {dat.get_path()}")
        print(f" |  base:  {Dat.get(dat, 'dat.base', '')}")
        print(f" |  class: {Dat.get(dat, 'dat.class', '')}")
        print(f" |  do:    {Dat.get(dat, 'dat.do', '')}")
        print(f" |  ver:   {Dat.get(dat, 'dat.version', '')}")
        print(f" |  docs:  {Dat.get(dat, 'dat.docs', '')}")
    if do_value:
        print(f" +----- DO VALUE FOR: {name!r}")
        for line in json.dumps(do_value, indent=4).splitlines():
            print(f" |  {line}")
    print(" +-----")



