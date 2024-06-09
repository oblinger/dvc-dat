#!/usr/bin/env python3
import os
import sys
root = os.path.dirname(os.path.dirname(__file__))
sys.path += [f"{root}/src", f"{root}/external"]

from dvc_dat import dat_config, Dat

DEBUG = True


def main():
    adds_file = os.path.join(dat_config.dat_folder, dat_config.DAT_ADDS_LIST)
    paths = []
    for arg in sys.argv[1:]:
        arg = os.path.join(os.getcwd(), arg)
        p = Dat.load(arg).get_path_name()
        paths.append(p)
    with open(adds_file, 'a') as f:
        lines = '\n'.join(paths)
        f.write(lines + ('\n' if lines else ''))
    if DEBUG:
        print(f"\nDAT ADDS:   ({adds_file})")
        os.system(f"cat '{adds_file}'")


if __name__ == "__main__":
    main()
