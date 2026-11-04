# Ledger load harness: measured
The load harness for the ledger store, and what it measured on SQLite and Postgres.

The load harness (`tests/load/`, `uv run python -m tests.load
--processes N --transactions M --ledger <path>`; `pytest -m load` for
a small run) drives N processes on one fresh ledger, each doing M
operations: seals (unique, and a few shared ones raced across
processes), alias re-points and salt changes under `lock=`, unsandboxed
`run`s with memo hits and misses, reads. Its invariants (contiguous
revisions, no lost row, no duplicate subject or memo entry, every
memo hit's dependencies holding at the rev it hit, every alias at its last
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

Postgres, same machine and parameters: Dexter, PostgreSQL 17.11
(Homebrew, native, default config: `shared_buffers` 128MB,
`synchronous_commit` on, `fsync` on, `max_connections` 100) on
localhost, 2026-10-19, dvc-dat branch `r0017-pg-load` at 2f74f52.
Fresh schema per row (`--ledger
'postgresql://postgres@localhost:5544/postgres?options=-csearch_path%3D<schema>&art=<folder>'`).
`lock=` bounds the `FOR UPDATE` wait (`lock_timeout`) and the body.

| Processes | `lock=` | Wall s | Transactions | tx/s | ops/s | p50 ms | p99 ms | write p50 ms | write p99 ms | Memo hits / misses | LockTimeout | Invariant failures |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 10 s | 28.8 | 1294 | 45 | 69 | 15.2 | 29.8 | 16.1 | 29.0 | 201 / 331 | 0 | none |
| 2 | 10 s | 32.2 | 2437 | 76 | 124 | 16.1 | 35.7 | 17.7 | 38.6 | 546 / 498 | 0 | none |
| 4 | 10 s | 35.0 | 4444 | 127 | 229 | 17.4 | 35.4 | 19.6 | 31.6 | 1542 / 580 | 0 | none |
| 8 | 10 s | 60.3 | 8306 | 138 | 265 | 28.4 | 67.8 | 38.0 | 75.4 | 3674 / 606 | 0 | none |
| 16 | 10 s | 124.2 | 16151 | 130 | 258 | 47.1 | 138.2 | 96.8 | 155.8 | 7909 / 611 | 0 | none |
| 8 | 0.02 s | 54.2 | 7016 | 130 | 295 | 24.7 | 57.9 | 34.1 | 72.0 | 3675 / 605 | 1286 | none |

- Postgres is slower than SQLite on one machine at every process
  count: 45 vs 198 tx/s at 1 process, 127 vs 287 at 4, 138 vs 278 at
  8. Its p50 at 1 process is 15.2 ms (SQLite 2.2 ms). It scales further
  (flat from 8, not from 2) and its p99 is lower at 8 and 16.
- Misses exceed memo entries as in SQLite (580 / 576, 606 / 600,
  611 / 600).
- `lock=0.02`: 1286 of 2029 locked transactions timed out (SQLite: 108);
  a 20 ms bound is below Postgres's p50 here. None left a row or its
  tag.
- The `lock=` alarm interrupting a read leaves the reader usable
  (`test_pg_lock_alarm_mid_read_leaves_the_reader_usable`).
- Run-to-run spread is wide: another run's 4-process row gave 107 tx/s.

Cloud SQL, 2026-10-24 (SVP 1450, R0037): `svp-ledger`, PostgreSQL
17.11 on db-f1-micro (shared vCPU, 0.6 GB), us-central1, reached from
a laptop in California (Merlin, macOS 26.6.2, arm64, 12 CPUs, Python
3.12.0) through `cloud-sql-proxy` 2.26.3 on localhost; round trip 42 ms
(`SELECT 1` p50, 30 samples; ping 40.6 ms). dvc-dat main at d37a71d.
M = 100 operations per process (not 2000: at ~1.3 s an operation, the
2000-operation rows would take ~45 min per process), 200 eval keys x 3
salts, fresh schema per row.

| Processes | `lock=` | Wall s | Transactions | tx/s | ops/s | p50 ms | p99 ms | write p50 ms | write p99 ms | Memo hits / misses | LockTimeout | Invariant failures |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 10 s | 125.4 | 71 | 0.57 | 0.80 | 1329.5 | 1812.5 | 1329.5 | 1368.6 | 0 / 30 | 0 | none |
| 4 | 10 s | 138.5 | 287 | 2.07 | 2.89 | 1323.2 | 2292.7 | 1327.6 | 2234.6 | 9 / 101 | 0 | none |
| 8 | 10 s | 200.8 | 542 | 2.70 | 3.99 | 2077.0 | 3469.9 | 2285.1 | 3220.8 | 48 / 178 | 0 | none |

- Latency-bound from a remote client: an operation is ~30 round trips
  (1.33 s / 42 ms), so 1 process does 0.57 tx/s (Dexter local: 45).
  Throughput scales with processes to 4 (2.07 tx/s, p50 unchanged) and
  flattens at 8, where p50 grows to 2.1 s.
- No invariant failure, LockTimeout or worker error at any row.
- These numbers are the network, not the instance: a client in
  us-central1 (a GPU box) was not measured.

**The floor.** `tests/load/test_threshold.py`, run with `DAT_LOAD=1`
(Postgres also needs `DAT_LOAD_PG`, a server URL; it makes and drops
its own schema): 4 processes x 2000 operations, 200 keys. It fails on
any invariant failure, worker error or timeout, and when tx/s falls
below half the 4-process value recorded on the machine running it:

| Host | Store | Recorded tx/s (4 processes) | Floor tx/s |
| --- | --- | --- | --- |
| dexter | SQLite | 287 | 143 |
| dexter | Postgres | 127 | 63 |

On a host with no recorded floor only the invariants are checked. A
floor, not a target: it catches a regression of 2x, not drift.

**In one process** (SVP 1468, R0001): `tests/load/inproc.py`, `uv run python -m
tests.load.inproc --handles N --threads M --transactions T --ledger <fresh folder or
DSN>`; `tests/load/test_inproc.py` runs a small one (SQLite, and Postgres when
`DVC_DAT_TEST_PG` answers) in the normal suite, and `tests/ledger/test_handles.py`
pins the two-handle cases on both stores. N `Ledger` handles on one ledger, M
threads over them (thread j on handle j % N), each doing T operations: half writes
(one transaction of 4 `(ip/<tag>, part, k)` rows; every other one under `lock=`),
half reads (`h.at()`, the `ip/*` parts folded there, the flipped declarations).
A flipper thread on handle 0 cycles `db/pred/flipc db/cardinality` (one / many),
`db/pred/flipt db/type` (str / json) and a fresh `db/index`, and after each
commit asks every other handle. Invariants: revisions 1..top, one `db/by` each,
none reported twice, each thread's commits increasing and its `at()` never
below its last read or commit; no read sees a subject with other than 4 parts,
every committed tag's 4 rows at its revision, no failed tag in the ledger; every
read's subject digest equal to a fresh handle's at its revision and to the commit
log's; every observed cardinality and type equal to the last flip at or below
the read's revision; after a flip at R every other handle's next `at()` is
`>= R` and answers the new value; a declared index is listed by every handle.

Dexter (same machine as above; Python 3.12.14, SQLite 3.53.1, PostgreSQL 17.11
Homebrew, fresh `initdb`, default config, localhost:5544), 2026-10-29, dvc-dat
branch `row-1468`, T = 200 operations per thread, 60 flips (20 of each kind).

| Store | Handles | Threads | `lock=` | Wall s | Transactions | tx/s | reads/s | write p50 ms | write p99 ms | read p50 ms | read p99 ms | LockTimeout (writes / flips) | Invariant failures |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SQLite | 1 | 8 | 10 s | 59.3 | 851 | 14.4 | 13.6 | 6.8 | 59.7 | 529.0 | 1176.2 | 0 / 0 | none |
| SQLite | 4 | 8 | 10 s | 58.1 | 851 | 14.6 | 13.9 | 6.5 | 60.7 | 538.3 | 1081.7 | 0 / 0 | none |
| SQLite | 8 | 8 | 10 s | 54.9 | 851 | 15.5 | 14.7 | 6.2 | 42.2 | 508.7 | 1034.4 | 0 / 0 | none |
| SQLite | 16 | 16 | 10 s | 253.2 | 1683 | 6.6 | 6.2 | 11.8 | 105.3 | 2485.6 | 4510.5 | 0 / 0 | none |
| SQLite | 4 | 16 | 0.02 s | 237.8 | 1649 | 6.9 | 6.6 | 11.2 | 52.3 | 2277.6 | 4540.9 | 25 / 9 | none |
| Postgres | 1 | 8 | 10 s | 9.8 | 851 | 86.6 | 82.3 | 74.6 | 181.2 | 11.6 | 43.5 | 0 / 0 | none |
| Postgres | 4 | 8 | 10 s | 10.3 | 851 | 83.0 | 78.9 | 78.5 | 163.7 | 11.9 | 40.3 | 0 / 0 | none |
| Postgres | 8 | 8 | 10 s | 10.0 | 851 | 85.5 | 81.2 | 74.3 | 180.5 | 12.0 | 46.3 | 0 / 0 | none |
| Postgres | 16 | 16 | 10 s | 31.3 | 1683 | 53.8 | 50.4 | 237.6 | 626.4 | 23.1 | 107.8 | 0 / 0 | none |
| Postgres | 4 | 16 | 0.02 s | 16.0 | 821 | 51.3 | 98.5 | 66.7 | 428.0 | 21.6 | 88.1 | 802 / 60 | none |

- No invariant failure on either store at any row: no stale cardinality, type
  or index on any handle after a flip, no half-committed transaction seen, no
  as-of read differing from a fresh handle's. There is no head-state cache to go
  stale: a `Rev` folds declarations from the rows at or below its own revision
  (`Rev._cards` lives on the `Rev`), and `h.at()` reads the top from the store
  every call.
- `lock=0.02` in threads takes the `threading.Timer` path (an async
  `LockTimeout` into the body's thread, not `SIGALRM`): 25 (SQLite) and 802
  (Postgres) writes timed out, none left a row or its tag. On Postgres every
  flip timed out, so that row checks no flip; the 10 s rows do.
- Transactions and reads are each about half of the operations, so tx/s and
  reads/s move together; wall time is set by the reads, which fold every `ip/*`
  row (growing with the run).
- SQLite reads are slow under threads: read p50 529 ms at 8 threads, where the
  same read alone on the same ledger takes 28 ms (Postgres p50: 12 ms). Not
  explained here; a correctness run, not a tuning one.
- The leg refuses a ledger that already holds revisions: its tags repeat run to
  run. (Three Postgres rows first run into reused schemas failed `no-half` and
  `as-of` on the earlier run's rows; rerun into fresh schemas they pass; the
  failed JSONs are not kept.)
- Results: `tests/load/results/*-inproc-*.json`, one line each in `summary.txt`.
