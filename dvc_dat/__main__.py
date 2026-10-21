"""`python -m dvc_dat`: the library's own command line (what `just run` execs by default), no project mounts."""
import sys

from dvc_dat.do import cli_main

if __name__ == "__main__":
    sys.exit(cli_main())
