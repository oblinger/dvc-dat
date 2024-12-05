import os

from dvc_dat import dat_config, Dat


DEBUG = True   # False, True, 'prompt'


def __main__():
    print()
    os.chdir(dat_config.sync_folder)
    run(f"cd '{dat_config.sync_folder}'")
    status = run(f"git pull")
    status = status or run(f"dvc pull")
    if status != 0:
        print("\n\nWARNING:\nWARNING:  Local Dat files out of date.\nWARNING:\n")
    print()
    return status


def run(cmd: str):
    if DEBUG == 'prompt':
        input(f" $ {cmd}   press [ENTER]")
    elif DEBUG:
        print(f" $ {cmd}")
    return os.system(cmd)
