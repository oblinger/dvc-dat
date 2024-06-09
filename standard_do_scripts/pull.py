#!/usr/bin/env python3
import os
import sys
root = os.path.dirname(os.path.dirname(__file__))
sys.path += [f"{root}/src", f"{root}/external"]

from dvc_dat import dat_config, Dat

DEBUG = 'prompt'  # False, True, 'prompt'


def main():
    print()
    os.chdir(dat_config.dat_folder)
    run(f"cd '{dat_config.dat_folder}'")
    run(f"git pull")
    run(f"dvc pull")
    print()


def run(cmd: str):
    if DEBUG == 'prompt':
        input(f" $ {cmd}   press [ENTER]")
    elif DEBUG:
        print(f" $ {cmd}")
    os.system(cmd)
    return 0


if __name__ == "__main__":
    main()
