"""``python -I -m dvc_dat.ledger.worker``: the sandbox's warm server, one per environment, forking a child per
call (see ``sandbox``)."""

from dvc_dat.ledger.sandbox import worker_main

if __name__ == "__main__":
    worker_main()
