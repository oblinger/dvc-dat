"""``python -I -m dvc_dat.ledger.worker``: the fence's warm server, one per environment, forking a child per
call (see ``fence``)."""

from dvc_dat.ledger.fence import worker_main

if __name__ == "__main__":
    worker_main()
