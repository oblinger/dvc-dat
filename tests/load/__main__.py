import sys

from tests.load.harness import main

if __name__ == "__main__":     # spawn re-imports this as __mp_main__ on 3.14: no run there
    sys.exit(main())
