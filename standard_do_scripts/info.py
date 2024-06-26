from dvc_dat import Dat


def __main__(name: str = None):
    print("Hello, World!")
    try:
        dat = Dat.load(name)
    except Exception as e:
    print()
    print(f" +----- DAT INFO FOR: {dat.get_path_name()!r}")
    print(f" |  path:  {dat.get_path()}")
    print(f" |  base:  {Dat.get(dat, 'dat.base')}")
    print(f" |  class: {Dat.get(dat, 'dat.class')}")
    print(f" |  do:    {Dat.get(dat, 'dat.do')}")
    print(f" |  ver:   {Dat.get(dat, 'dat.version')}")
    print(f" |  docs:  {Dat.get(dat, 'dat.docs')}")

