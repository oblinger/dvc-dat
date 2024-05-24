import os

from dvc_dat import do, Dat


# Running the 3 stager with high debugging and other stuff.

sprint25 = {
    "main": {
        "base": "hello_3stager",
        "do": "sprint25.run_it",
    },
    "common": {
        "debug": 11
        }
    }


def run_it(dat: Dat):
    do("hello_mspipe.msproc_build_and_run", dat)
    result_file = os.path.join(dat.get_path(), "final_results.txt")
    os.system(f"less '{result_file}")


if __name__ == "__main__":
    do("hello_doubler")
