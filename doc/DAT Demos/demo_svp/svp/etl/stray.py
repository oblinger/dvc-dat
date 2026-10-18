"""`svp.etl.stray`: two functions the sandbox refuses."""
from pathlib import Path

from dvc_dat.ledger import ledger_fn


@ledger_fn
def borrow(rev, *, game: str) -> dict:
    from svp import shots      # in the repo, outside every mount
    return {"game": game, "kind": shots.Shots.__name__}


@ledger_fn
def snoop(rev, *, game: str) -> dict:
    hosts = Path("/etc/hosts").read_text()    # not a mount or a dat
    return {"game": game, "lines": len(hosts.splitlines())}
