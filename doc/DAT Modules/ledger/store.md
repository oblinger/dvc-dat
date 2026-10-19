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

## Measured

The load harness (`tests/load/`, `uv run python -m tests.load
--processes N --transactions M --ledger <path>`; `pytest -m load` for
a small run) drives N processes on one fresh ledger, each doing M
operations: seals (unique, and a few shared ones raced across
processes), alias re-points and salt changes under `lock=`, base-mode
`eval`s with memo hits and misses, reads. Its invariants (contiguous
revisions, no lost row, no duplicate subject or memo entry, every
memo hit's trace holding at the rev it hit, every alias at its last
re-point, the fold identical from fresh handles and fresh processes,
art bytes present) are checked after the run.

Dexter (macOS 26.6, x86_64, 12 CPUs, Python 3.12.14, SQLite 3.53.1),
2026-10-19, M = 2000 operations per process, 200 eval keys x 3 salts.
Transactions are committed revisions (eval seals included); latency
is per operation (all kinds), and for writes alone.

| Processes | `lock=` | Wall s | Transactions | tx/s | ops/s | p50 ms | p99 ms | write p50 ms | write p99 ms | Memo hits / misses | LockTimeout | Invariant failures |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 10 s | 6.5 | 1294 | 198 | 306 | 2.2 | 23.9 | 2.1 | 28.4 | 201 / 331 | 0 | none |
| 2 | 10 s | 8.4 | 2422 | 288 | 476 | 2.4 | 13.9 | 2.3 | 13.2 | 561 / 483 | 0 | none |
| 4 | 10 s | 15.5 | 4443 | 287 | 517 | 3.6 | 37.1 | 2.7 | 58.4 | 1542 / 580 | 0 | none |
| 8 | 10 s | 29.8 | 8302 | 278 | 536 | 5.8 | 84.6 | 3.6 | 115.8 | 3679 / 601 | 0 | none |
| 16 | 10 s | 78.0 | 16150 | 207 | 410 | 11.4 | 172.7 | 4.6 | 196.3 | 7913 / 607 | 0 | none |
| 8 | 0.02 s | 29.7 | 8196 | 276 | 538 | 5.3 | 65.6 | 3.4 | 89.6 | 3674 / 606 | 108 | none |

- Writes serialize on SQLite's write lock: throughput is flat at
  ~280 tx/s from 2 to 8 processes and falls at 16, while p99 grows
  with the process count.
- Misses exceed memo entries under concurrency (580 / 578, 601 / 600,
  607 / 600): two processes miss the same key, both run, one entry is
  sealed and the other hands it back. Correct, and ~1% wasted runs.
- `lock=0.02` on alias and salt transactions: 108 of 2029 timed out
  (`LockTimeout`), each counted; none left a row or its tag.
- Results: `tests/load/results/*.json`, one line each in
  `summary.txt`.

## Left to other modules

What rows mean (the fold, cardinality, types) is [fold](fold.md)'s and
[rev](rev.md)'s; what to write and when is [txn](txn.md)'s; which
bytes a value is made of is [value](value.md)'s.
