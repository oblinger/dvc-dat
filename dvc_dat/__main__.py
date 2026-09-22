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
        print(f"# .dataconfig folder: {Dat.manager.config.cwd}")
        config = os.path.join(Dat.manager.config.cwd, ".dataconfig.yaml")
        if os.path.exists(config):
            print(f"# .dataconfig.yaml contents:")
            with open(config) as f:
                print(f.read())
        else:
            print("# (no .dataconfig.yaml found)")
        print()
    else:
        return do_argv(argv)


if __name__ == "__main__":
    main()
