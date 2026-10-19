# ledger.fold

The fold turns the rows on one `(subject, predicate)` into what they
hold, by the predicate's cardinality, and it is the one place that
rule lives. Under `one` (the default) the latest add wins, so `add` is
assignment; under `many` the held objects are the set added and not
since removed. Part of the [architecture](../../DAT%20Architecture.md).

## Public surface

- `fold(rows, card) -> [Held]`: `rows` are `(rev, ord, s, p, obj,
  added)` in `(rev, ord)` order; `card` is `"one"` or `"many"`.
- `Held(obj, rev, ord)`: a held object and the place of the add that
  made it held.

## Rules

- `one`: re-adding the held object changes nothing, its revision
  included; a remove of the held object leaves nothing (a tombstone); a
  remove of any other object changes nothing.
- `many`: each member at its earliest add not since removed, members in
  that order; re-adding a present member keeps its place; a remove then
  re-add moves it to the end.

## Invariants

- Pure: no I/O, no ledger; the same rows give the same answer on every
  backend.

## Left to other modules

Which cardinality a predicate has, and which rows to pass, are
[rev](rev.md)'s (`version`, `commit` and every `db/` predicate fixed at
`one`).
