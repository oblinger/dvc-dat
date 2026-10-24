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
