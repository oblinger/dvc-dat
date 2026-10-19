# ledger.helpers

A clock is a subject whose `version` only goes up, and `bump` is the
helper that moves one inside a transaction. On `code/<repo>` it also
pins the commit, read from that repo's checkout, so a version always
names exact code. A value's version is not a clock: it is a pred, and a
new version is a new seal with the alias re-pointed. Part of the
[architecture](../../DAT%20Architecture.md).

## Public surface

- `bump(t, subject, part="patch", *, confirm=None) -> str`: reads
  `version` through `t.base` (`0.0.0` when absent), adds the next by
  `part`, returns it.
  - A subject holding a `db/alias` row is `TypeError` naming the alias.
  - `part` not `patch`/`minor`/`major`, or a current version not
    `MAJOR.MINOR.PATCH`, is `ValueError`.
  - `minor` and `major` need `confirm(old, new)` to return `True`;
    without `confirm=`, or on another answer, `ValueError`.
  - On `code/<repo>` it also adds `commit`: no checkout for the repo in
    the environment, or a dirty one, is `ValueError`.
  - Nothing is written on any refusal.

`attr` lives in [txn](txn.md).

## Invariants

- `bump` writes only through `t.add`, so its rows are ordinary rows in
  the transaction's revision; two bumps of one subject in one body both
  read `t.base` and write the same version.
- Run it under `lock=` when the update must not be lost to a
  concurrent writer.

## Left to other modules

The checkout and its commit come from [env](env.md); the rows are
written by [txn](txn.md).
