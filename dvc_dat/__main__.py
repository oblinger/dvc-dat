#!/usr/bin/env python
import os
import sys
from dvc_dat import do_argv, dat_config, DAT_VERSION


def main():
    argv = list(sys.argv)
    if len(argv) == 2 and argv[1] == "--info":
        print("\n# -- Dat Configuration Info -- ")
        print(f"# Dat version      : {DAT_VERSION}")
        print(f"# Dat Data Folder  : {dat_config.sync_folder}")
        print(f"# .datconfig folder: {dat_config.folder}")
        print(f"# .datconfig.json contents:")
        os.system(f"cat '{dat_config.folder}/.datconfig.json'")
        print()
    else:
        return do_argv(argv)


if __name__ == "__main__":
    main()
