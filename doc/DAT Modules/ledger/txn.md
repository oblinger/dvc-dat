# ledger.txn

A transaction is the write set of one `with L.transaction(...)`, and it
becomes exactly one revision on exit. `add` and `remove` append rows
and read nothing; `v.seal(t)` seals a `Value` into an immutable
subject in this transaction (`Value.seal`, [value](value.md)); the bracket (`t[s, p] = o`, `t[s] = {…}`, `del`) is a
read-then-write helper over `add`/`remove` through `t.base`. Whatever
must see the transaction's own rows is checked at commit, inside the
write lock, against the state the new revision would have: the rows are
inserted, read back through the open write transaction, and rolled back
on a refusal. Part of the [architecture](../../DAT%20Architecture.md).

## Public surface

`Transaction` (made by `Ledger.transaction`):

- Constructor checks: `by` a non-empty `str`; `lock` a positive number
  of seconds or `None`; `time` a `bool`; each extra keyword a `str` or
  JSON document, never `db/…`, never a bare scalar; else `TypeError`.
- `tx: str`: a placeholder subject, rewritten to `db/tx/<rev>` at
  commit wherever it appears as a subject or a `str` object.
- `base: Rev`: the top when the block was entered; under `lock=` the
  top until exit. `RuntimeError` before entry.
- `rev: Rev`: the revision written; `RuntimeError` before commit.
- `with … as t`: entered once (`RuntimeError` on a second entry). With
  `lock=`, the write lock is taken on entry and the body is interrupted
  past the limit (`LockTimeout`, nothing written).
- `add(s, p, o) -> None`: one row. `o` is a `str`, a JSON `dict`/`list`,
  or a `Ref` to a sealed value; a `Value` is `TypeError` naming
  `seal`; a bare number, bool or `None` `TypeError`;
  `p == "db/value"` `TypeError`; a `db/alias` object not a `str`
  `TypeError`. Outside the block `RuntimeError`.
- `remove(s, p, o) -> None`: one remove row: out of the set on a
  `many` predicate, the tombstone on a `one` predicate when `o` is the
  held object.
- `v.seal(t, *, deps=(), alias=None, provenance=None) -> str`
  (`Value.seal`; `t.add_value` is gone, 6.0.0): seal `v` in this
  transaction and return its subject (64 hex). Refused on the line:
  not a `Value` or already sealed (`TypeError`, `ValueError`); a
  provenance beginning `eval:` (`ValueError`); a pred name the kind did
  not declare (`Undeclared`); a list under a `one` pred not typed
  `json`, or a pred value not `str`/`int`/`float`/`bool`/`Value`/`Ref`
  (`TypeError`); an unsealed `Value` as a typed pred or a dep
  (`ValueError`); a dep whose hash is not what the ledger holds for its
  subject (`ValueError`); a dep that is not a `Value`, `Ref` or `Fn`
  (`TypeError`).
- `t[s, p] = o`: `add` on a `one` predicate; a `many` predicate or a
  `db/` predicate `TypeError`.
- `t[s] = {…}`: makes the subject's user rows equal to the dict at the
  next revision (closed world over non-`db/` rows); a `db/` key that
  differs from the current row `TypeError`; `t[s] = t.base[s]` writes
  nothing.
- `del t[s, p]`, `del t[s]`: retract what `p` holds, or every user
  predicate; `db/` rows survive; a `db/` predicate `TypeError`.
- Brackets take exact subjects; a glob is `TypeError`.

Module functions: `attr(obj, path)` walks a dotted path over mappings,
sequences (integer steps) and attributes, `KeyError` at the first
missing step, `TypeError` for an empty path. `code_token(rev, repo,
env_commit)` is the `code/<repo>` trace value: `<version>+<commit8>`
from the rows, else `+<env commit8>`. `FORMAT` is
`"dvc-dat-ledger/1"`; `SEAL_PREDICATES` the seal's own predicates.

## The seal

- The subject hashes, as canonical JSON, the trace, the preds (a `many`
  list sorted) and the `db/value` text `ref:<class>:<hash>`; an eval's
  seal ([fn](fn.md)) adds the dotted name and the keys.
- The trace of a hand seal is declared: one `ref:<class>:<hash>` item
  per `Value`/`Ref` dep, a `<name> db/alias` item for a dep loaded or
  named through an alias, the `fn` item for an `Fn` dep (its
  `db/fn/<name>/<hash>` rows are written if absent), then
  `code/<repo>` for every repo discovery reports, `uv.lock` and
  `platform`.
- On the seal's line: `preds` becomes a `FrozenPreds`, `sealed`,
  `subject` and `trace` are set. At commit: `rev` is set, `preds`
  becomes the subject's non-`db/` rows as loaded (a typed pred a
  `Ref`), and `_after_seal` runs (a `Dat` moves to its stored folder).
- Rows written once per subject: `db/value`, `db/kind` (dotted class),
  `db/provenance` (default `seal`), `db/preds` (the kind's declared
  names, JSON), `db/trace/<item>` per item, one row per pred (per
  member for `many`); with `alias`, `(alias, db/alias, subject)`.
- A subject already sealed at `base`, or sealed by another writer before
  this commit, is not written again: the seal is idempotent.

## Checks at commit

`Exists` for an `add`/`remove` on a sealed subject's own predicates
(the seal rows and the names its `db/preds` row lists); `TypeError` for
a `db/alias` row on a subject holding its own `db/value`, for an alias
whose target (after its own alias chain) holds no `db/value`, for an
object mismatching its predicate's `db/type` (declarations in the same
transaction included), and for a pred holding a list or `Value` under a
`one` predicate with no `db/type`. A `(db/pred/<p>, db/index, true)`
row builds a partial SQL index on `<p>` in the same commit. Then the
seals' bytes go to the art store, the rows are inserted in body order,
then `(db, db/format, …)` on revision 1, then the `db/tx/<rev>` rows.

## Invariants

- One `with` block, one revision; a body exception, a refusal at commit
  or `LockTimeout` writes nothing, unseals every value the body froze
  (`preds` a plain dict again) and unlinks the bytes this transaction
  stored.
- `add`, `remove` and their checks read nothing during the body; only
  the seal, the bracket and `bump` read, through `base`.
- A `db/value` row is written by `v.seal` (or an eval's seal) alone.

- TODO: the module docstring says rows land "in body order, then the
  transaction's own `db/tx/<rev>` rows"; on a ledger's first
  transaction the code writes `(db, db/format, …)` between them.
- TODO: whether a pred is `many` is read at the seal from `base`
  plus the body's earlier rows, so a cardinality declared later in the
  same body is not seen by the seal.

## Left to other modules

Locking, SQL and the art store are [store](store.md)'s; reading back is
[rev](rev.md)'s; the environment items come from [env](env.md); an
eval's seal is assembled by [fn](fn.md) (`seal_entry`) on top of this
module's `_seal`; `bump` is [helpers](helpers.md)'.
