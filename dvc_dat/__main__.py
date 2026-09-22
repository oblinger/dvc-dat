#!/usr/bin/env python
import os
import sys

from dvc_dat import Dat, __version__, do, do_argv


def main():
    argv = list(sys.argv)
    if len(argv) == 2 and argv[1] == "--info":
        config = do.configure()
        print("\n# -- Dat Configuration Info -- ")
        print(f"# Dat version       : {__version__}")
        print(f"# Dat Data Folder   : {Dat.manager.sync_folder}")
        print(f"# .dataconfig folder: {config.cwd}")
        config_file = os.path.join(config.cwd, ".dataconfig.yaml")
        if os.path.exists(config_file):
            print(f"# .dataconfig.yaml  : {config_file}")
            with open(config_file) as f:
                print(f.read())
        else:
            print("# (no .dataconfig.yaml found)")
        print()
    else:
        return do_argv(argv)


if __name__ == "__main__":
    main()
