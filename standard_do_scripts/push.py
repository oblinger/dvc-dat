import os

from dvc_dat import dat_config, Dat

DEBUG = 'prompt'  # False, True, 'prompt', or 'show'


def __main__():
    try:
        with open(os.path.join(dat_config.sync_folder, dat_config.DAT_ADDS_LIST), 'r') as f:
            paths = f.read().splitlines()
    except FileNotFoundError:
        paths = []
    if not paths:
        print("No files to push.\n")
        return
    errors = False
    print("\n----- FOLDERS TO DVC PUSH -----")
    for p in paths:
        if not os.path.exists(os.path.join(dat_config.sync_folder, p)):
            print(f"   {p}   ERROR: Folder does not exist.")
            errors = True
        elif not Dat.exists(p):
            print(f"   {p}   ERROR: Missing '_spec_.json' file.")
            errors = True
        else:
            print(f"   {p}")
        try:
            Dat.load(p)
        except Exception as e:
            print(f"      ERROR: Could not Dat.load(...): {e}")
            errors = True
    print("-------------------------------")
    if errors:
        t = dat_config.DAT_ADDS_LIST
        print(f"Aborted.  Please correct errors above (or edit {t!r}).\n")
        return
    msg = input("\nEnter commit message, or [RETURN] to abort: ")
    print()
    if not msg:
        print("Aborted.\n")
        return
    # paths = [os.path.join(dat_config.folder, p) for p in paths]

    os.chdir(dat_config.sync_folder)
    run(f"cd '{dat_config.sync_folder}'")
    if run(f"git pull") != 0:
        print("git pull failed.  Aborted.\n")
        return
    run(f"dvc add " + ' '.join([f"'{p}'" for p in paths]))
    run(f"git add " + ' '.join([f"'{p}.dvc'" for p in paths]))
    run(f"git add .gitignore")
    run(f"git commit -m '{msg}'")
    run(f"dvc push")
    run(f"git push")
    run(f"rm '{os.path.join(dat_config.sync_folder, dat_config.DAT_ADDS_LIST)}'")
    print()


def run(cmd: str):
    if DEBUG == 'prompt':
        input(f" $ {cmd}      press [ENTER]")
    elif DEBUG:
        print(f" $ {cmd}")
    if DEBUG != 'show':
        os.system(cmd)
    return 0
