#!/usr/bin/env python
"""The `dat` console script: one command line, one exit code."""
import sys

from dvc_dat import cli


def main(argv=None) -> int:
    """Run `dat`; the return value is the process exit status."""
    return cli(argv)


if __name__ == "__main__":
    sys.exit(main())
