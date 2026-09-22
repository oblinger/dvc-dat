#!/usr/bin/env python
"""The `dat` console script: one command line, one exit code."""
import sys

from dvc_dat import do_argv


def main(argv=None) -> int:
    """Run `dat`; the return value is the process exit status."""
    return do_argv(list(sys.argv if argv is None else argv))


if __name__ == "__main__":
    sys.exit(main())
