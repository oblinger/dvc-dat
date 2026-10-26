"""The demo project's main: `just run` execs it (`run:` in .datconfig.yaml).

Launched from the project's folder, it hands the command line to `cli_main`.
Its names are the ledger's (`mounts:` in .datconfig.yaml, DAT 1046), so the
`@command` functions under the mount are read off the files, nothing mounted
here.
"""
import sys

from dvc_dat import Dat

if __name__ == "__main__":
    sys.exit(Dat.cli_main())
