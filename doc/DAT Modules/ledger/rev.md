:>> [DAT](../../DAT.md) → [ledger](ledger.md) → [DAT rev](ha://p/DAT%20rev) 
# ledger.rev
Every read of the ledger is made through a `Rev`, a frozen view as of
one revision. Row reads (`[]`, `get`, `all`, `in`) fold the rows at or
before the revision by each predicate's cardinality; `asserted` and
`rows` walk history unfolded; subject reads (`refs`, `values`, `value`,
`select`, `load`, `run`) treat the store as a table whose rows are
subjects. A stored `ref:` object always comes back as a `Ref`,
unloaded; `Ref.load` is the one act that fetches bytes. A `Rev` handed
to a value function's body also records every read into the function's
trace (see [trace](trace.md)). Part of the
[architecture](../../DAT%20Architecture.md).

## Public surface

`Rev` (made by `Ledger.at`, never by hand):

- `id: int`, `tx: str` (`"db/tx/<id>"`), `ledger: Ledger`; ordered and
  equal by `id` within one ledger.
- `rev[s] -> dict`: the subject's record, a `one` predicate's object,
  a `many` predicate's list, keys in the order each predicate's held
  row was asserted; no rows `KeyError`.
- `rev[s, p] -> Obj`: the one held object; nothing held `KeyError`; a
  `many` predicate `TypeError` naming `all`; a stored tag mismatching
  `(db/pred/p, db/type, …)` `TypeError`.
- `rev[s, p, o] -> Rev`: the revision of the held triple's earliest add
  not since removed; not held `KeyError`.
- `get(*pattern, default=None, since=None)`: `[]` with `default`
  instead of `KeyError`; `since` (a `Rev`) keeps rows in `(since, id]`.
- `all(*pattern, since=None) -> list`: every match, binding the open
  positions, ordered by revision; a prefix glob `"game/*"` binds the
  subject; unchecked against `db/type`. More than 3 positions
  `TypeError`; a `*` anywhere but the end `ValueError`.
- `(s, p, o) in rev -> bool`: held at this revision.
- `asserted(s, p) -> [(Rev, obj, added)]`; `asserted(s, p, o) -> [Rev]`:
  history at or before this revision, removes included.
- `rows(since=None) -> [Row]`: every row, unfolded, `(rev, ord)` order.
- `refs(*, s=None, kind=None, fn=None, where=None, one=False,
  since=None, **preds) -> [Ref] | Ref`: subjects satisfying every
  constraint. A bare keyword names a pred (any member of a `many`);
  `kind=` a class or dotted name, following `db/moved` renames; `fn=`
  the `db/fn` row; `where={p: o}` any predicate, `None` meaning any
  object; `s` exact or a prefix glob. `one=True`: none `KeyError`,
  several `Multiple`. A dotted predicate neither declared nor on any
  row `Unindexed`.
- `values(…) -> [Value]` and `value(…) -> Value`: the sealed values
  matching the same where clause, loaded; `value` raises `KeyError` on
  none and `Multiple` on several.
- `select(keys, *, …, one=False) -> [tuple] | tuple`: each match as a
  tuple of its objects for `keys` (`None` absent, a list for `many`);
  `keys` not a non-empty tuple `TypeError`.
- `load(subject) -> Value`: `Ref(self, subject).load()`.
- `load_fn(name) -> Fn`: see [fn](fn.md).
- `run(name, /, *, memo=True, clean=False, path=None, kwargs=None,
  **keys) -> Value | None`: calls the value function `name` with `keys`
  and returns its result, handing back an already-sealed result when one
  from the same code and keys still holds at this revision; `memo` and
  `clean` as on `Fn.__call__` ([fn](fn.md)); a non-`str` name
  `TypeError`.

`Ref(rev, name)`: one value at one moment, frozen, unpicklable.

- Making one resolves the `db/alias` chain from `name`; a cycle or more
  than 8 hops is `AliasLoop`.
- `rev`, `name`, `subject` (alias resolved; for a hint-less stored
  `ref:`, the latest entry holding those bytes as of `rev`), `hash`
  (64 hex or `None`), `type` (the decoding class, `db/moved` followed;
  a class that does not import `ImportError`).
- `preds -> FrozenPreds`: the subject's non-`db/` rows, annotations
  included, unloaded refs for typed preds.
- `aliases -> [str]`: every name aliasing the subject as of `rev`.
- `sealed_at -> Rev | None`: the revision of its `db/value` row.
- `load() -> Value`: decode by `type`, restore `subject`, `rev` (the
  sealing revision), `trace`, `preds`; cached per `(subject, rev,
  name)`, a cached `Dat` handed back only while its folder is still
  there and the same folder (one stat: the directory's device and
  inode), else loaded afresh; no value `KeyError`; a `decode` returning a non-`Value`
  `TypeError`. A `decode` accepting `name=` is passed the alias the
  `Ref` was made by (`None` by subject), so a `Dat` lands under
  `art/dats/<name>/`. A `Dat` whose folder's `_spec_` names a
  `dat.kind` other than the row's class is `TypeError` unless the
  loaded class's `kind_ok(kind)` accepts it ([value](value.md)).
- Equal and hashed by subject; byte identity is `a.hash == b.hash`.
- `repr`: the value's name at the head (the alias naming it written
  latest), else the hash's first 8.

`Row(rev, subject, predicate, object, added)`: a named tuple, `rev` a
`Rev`, `object` decoded, `added` false on a remove; `str()` is one
aligned line.

Module functions used elsewhere: `class_named(ledger, dotted)`,
`kind_names`, `display_name`, `type_ok`, `describe`, `fixed_one`.

## Invariants

- A `Rev` never changes its answer: every read is bounded by `id`.
- `version`, `commit` and every `db/` predicate have cardinality `one`
  whatever `db/pred/<p>` says; a cardinality other than `many` reads as
  `one`. The cardinality cache lives on the `Rev`, so it cannot go
  stale.
- No pattern read decodes a `ref:` object; only `load`, `value`,
  `values` and `Ref.load` fetch bytes, and of the top value only.
- A `Ref` made from a recording `Rev` keeps the recorder: alias
  resolution, `load`, `preds`, `aliases` and `sealed_at` are traced.

- Inside a value function, `rows()` is traced as the number of rows it
  returned, not a token of the rows; equivalent while the store is
  append-only.

## Left to other modules

Folding is [fold](fold.md)'s, SQL is [store](store.md)'s, trace item
names and the hit test are [trace](trace.md)'s, resolution and `run`
are [fn](fn.md)'s, writing is [txn](txn.md)'s.
