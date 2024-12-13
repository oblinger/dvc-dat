import os

from dvc_dat import Dat

DEBUG = True


def __main__(*add_paths):
    adds_file = os.path.join(Dat.manager.sync_folder, Dat.manager.DAT_ADDS_LIST)
    paths = []
    for arg in add_paths:
        arg = os.path.join(os.getcwd(), arg)
        p = Dat.manager.load(arg).get_path_name()
        paths.append(p)
    with open(adds_file, 'a') as f:
        lines = '\n'.join(paths)
        f.write(lines + ('\n' if lines else ''))
    if DEBUG:
        print(f"\nDAT ADDS:   ({adds_file})")
        os.system(f"cat '{adds_file}'")
