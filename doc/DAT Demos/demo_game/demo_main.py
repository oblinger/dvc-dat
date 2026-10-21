"""The demo project's main: `just run` execs it (`run:` in .datconfig.yaml).

It mounts the ETL model module at `model`, so its `@command` functions are
recipes in `.dat/targets.just`, then hands the command line to `cli_main`.
"""
import sys

from dvc_dat import Dat

Dat.do.mount(module="demo_game.etl.model", at="model")

if __name__ == "__main__":
    sys.exit(Dat.cli_main())
