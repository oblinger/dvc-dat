import os
from dvc_dat import do, Dat

__main__ = {
    "dat": {
        "base": "hello_mspipe/hello_doubler",
        "path": "sprint25",       # Use fixed folder during debugging
        "path_overwrite": True,
        "do": "sprint25.run_it"},
    "common": {
        "debug": 11}}


def run_it(dat: Dat):
    do("hello_mspipe.mspipe_build_and_run", dat)
    print()
    result_file = os.path.join(dat.get_path(), "final_stage/final_results.txt")
    os.system(f"cat '{result_file}'")


if __name__ == "__main__":
    do("sprint25")
