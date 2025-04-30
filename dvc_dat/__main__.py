#!/usr/bin/env python
import os
import sys
from dvc_dat import do_argv, Dat, DAT_VERSION


def main():
    argv = list(sys.argv)
    if len(argv) == 2 and argv[1] == "--info":
        print("\n# -- Dat Configuration Info -- ")
        print(f"# Dat version      : {DAT_VERSION}")
        print(f"# Dat Data Folder  : {Dat.manager.sync_folder}")
        print(f"# .datconfig folder: {Dat.manager.folder}")
        print(f"# .datconfig.json contents:")
        config = os.path.join(Dat.manager.folder, ".datconfig.json")
        if not os.path.exists(config):
            config = os.path.join(Dat.manager.folder, ".datconfig.yaml")
        os.system(f"cat '{config}'")
        print()
    else:
        return do_argv(argv)


if __name__ == "__main__":
    main()
