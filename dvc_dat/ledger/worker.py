"""``python -I -m dvc_dat.ledger.worker``: the sandbox worker's entry point (see ``sandbox``)."""

from dvc_dat.ledger.sandbox import worker_main

if __name__ == "__main__":
    worker_main()
