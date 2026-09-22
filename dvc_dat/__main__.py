"""`python -m dvc_dat`: the library's own `dat` command line, no project mounts."""
import sys

from dvc_dat import cli_main

if __name__ == "__main__":
    sys.exit(cli_main())
