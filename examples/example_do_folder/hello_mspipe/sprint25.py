import os
from dvc_dat import do, Dat

main = {
    "main": {
        "base": "hello_doubler",
        "do": "sprint25.run_it"},
    "common": {
        "debug": 11}}


def run_it(dat: Dat):
    do("hello_mspipe.mspipe_build_and_run", dat)
    result_file = os.path.join(dat.get_path(), "final_stage/final_results.txt")
    print()
    os.system(f"cat '{result_file}'")


if __name__ == "__main__":
    do("sprint25")
