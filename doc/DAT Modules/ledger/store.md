# ledger.store

The backend is one SQLite table of quads and a folder of bytes by hash,
both inside the ledger folder (`ledger.db`, `art/`). Rows are only ever
appended: `quads(rev, ord, subject, predicate, object, added)`, `ord`
the row's place within its transaction, `object` a tagged string
([codec](codec.md)), `added` 0 for a remove row. Revisions come from
`MAX(rev) + 1` under SQLite's write lock. Part of the
[architecture](../../DAT%20Architecture.md).

## Public surface

- `Store(folder)`: creates `ledger.db` (WAL mode) and the schema if
  absent; `LedgerError` when SQLite refuses. Reads go through one
  connection per thread; each write opens its own.
- `Store.rows(upto, *, subject, predicate, obj, prefix, after=0) ->
  [Row]`: rows with `after < rev <= upto` matching the columns given,
  `(rev, ord)` order; `prefix` is a range scan on `subject`.
- `Store.subjects(upto, *, predicate, obj, prefix, subject, after=0) ->
  [str]`: distinct subjects with an add row matching, ordered by first
  assertion.
- `Store.top() -> int`, `Store.has_predicate(p, upto) -> bool`,
  `Store.read(sql, params)` (`LedgerError` on a refused read).
- `Store.writer(timeout, *, locked)`: a context manager holding
  `BEGIN IMMEDIATE`; commits on a clean exit, rolls back otherwise;
  failing to get the lock is `LockTimeout` when `locked`, else
  `LedgerError`.
- `Store.reading_through(conn)`: reads in this thread go through an
  open write transaction for the block (how a commit validates its own
  rows).
- `Writer.next_rev() -> int`, `Writer.insert(rev, rows)`: rows get
  `ord` 0, 1, … in the order given.
- `ArtStore(root)`: `put(data) -> hex` writes `sha256/<2>/<hex>` once,
  atomically by rename; `get(hex) -> bytes` (`FileNotFoundError` when
  absent); `path(hex) -> Path`.

## Invariants

- No row is ever updated or deleted; `(rev, ord)` is the primary key.
- Indexes: `(subject, predicate, rev)` and `(predicate, object, rev)`;
  a `(db/pred/<p>, db/index, true)` row adds a partial index on
  `(object, subject, rev) WHERE predicate = '<p>'`, built by
  [txn](txn.md) at commit.
- Art-store bytes are write-once: a hash already present is not
  rewritten.

- TODO: the module docstring names the two SQL indexes as "the index
  table a where clause reads"; it does not mention the partial
  per-predicate indexes the `db/index` rows build.

## Left to other modules

What rows mean (the fold, cardinality, types) is [fold](fold.md)'s and
[rev](rev.md)'s; what to write and when is [txn](txn.md)'s; which
bytes a value is made of is [value](value.md)'s.
