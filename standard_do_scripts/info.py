from dvc_dat import Dat, do


def __main__(name: str = None):
    dat, do_value = None, None
    try:
        dat = Dat.load(name)
    except KeyError as e:
        print(f"ERROR: Could not find Dat named {name!r}.")
    try:
        do_value = do.load(name)
    except Exception as e:
        pass
    print()
    if not dat and not do_value:
        print(f"The name {name!r} is not a Dat name nor do value")
        return
    print(f" +----- DAT INFO FOR: {dat.get_path_name()!r}")
    if dat:
        print(f" |  path:  {dat.get_path()}")
        print(f" |  base:  {Dat.get(dat, 'dat.base', '')}")
        print(f" |  class: {Dat.get(dat, 'dat.class', '')}")
        print(f" |  do:    {Dat.get(dat, 'dat.do', '')}")
        print(f" |  ver:   {Dat.get(dat, 'dat.version', '')}")
        print(f" |  docs:  {Dat.get(dat, 'dat.docs', '')}")
    else:
        print(f" |  no Dat defined")
    if do_value:
        print(f" +----- DO VALUE")
        print(f" |  {do_value!r}")
    print(" +-----")



