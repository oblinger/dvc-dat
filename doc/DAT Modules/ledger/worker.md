# ledger.worker

The sandbox's warm server is started as
`python -I -m dvc_dat.ledger.worker`, and this module is that entry
point: it calls [`sandbox.worker_main()`](sandbox.md) and nothing
else. Keeping it a separate module lets `-m` name the server without
importing the parent side first. Part of the [architecture](../../DAT%20Architecture.md).

## Public surface

None: run as `__main__` only.

## Invariants

- The server's stdin carries requests and a duplicate of its original
  stdout carries replies; each forked child replies over a pipe of its
  own, which the server relays; anything the function prints goes to
  stderr, so the protocol cannot be corrupted by output.

## Left to other modules

Everything: the loop, the finder, the open hook and the seal are in
[sandbox](sandbox.md).
