# ledger.ledger

A ledger is a folder holding one SQLite database and an art store, and
`Ledger` is the handle on it. It does three things: find or open (or,
asked, create) that folder; hand out frozen views with `at`; hand out
write sets with `transaction`. It holds no reads of its own, so every
read is made at a `Rev` and a long run reads one snapshot by
construction. Part of the [architecture](../../DAT%20Architecture.md).

## Public surface

- `Ledger(path=None, *, create=False)`: the one constructor.
  - `Ledger(path)` opens the folder at `path`; no `ledger.db` there is
    `LedgerError("no ledger at …")`; a file at `path` is `LedgerError`.
  - `Ledger()` takes `DAT_LEDGER` when set, else the nearest
    `.datconfig.yaml` at or above the working directory that carries a
    `ledger:` key (relative to the file's folder); none is
    `LedgerError` naming every directory searched. Found through a
    config, it asserts the config's `mounts:` as `db/mount/<prefix>`
    rows (`db/root`, and `db/repo` the config's own checkout) in one
    transaction `by="config:<path>"`, only when they differ.
  - `Ledger(path, create=True)` makes an empty ledger at `path` if
    absent, then opens it.
  - `Ledger(create=True)` makes a project in the working directory:
    writes `.datconfig.yaml` with `ledger: .dat/ledger`, or appends that
    line to one lacking a `ledger:` key, or opens the ledger one already
    names; `DAT_LEDGER` set is `ValueError`.
- `Ledger.path: Path`: the resolved ledger folder.
- `Ledger.at(which=None) -> Rev`: `None` the top; an `int` or a digit
  string a revision (`KeyError` outside `0..top`); `"M.m.p"` the latest
  revision that set `(db, version, M.m.p)` (`KeyError` if none); a
  `bool` or anything else `TypeError`.
- `Ledger.transaction(*, by, lock=None, time=False, **preds) ->
  Transaction`: a write set, one revision on exit; used only as
  `with … as t:` (see [txn](txn.md)).
- Module constants `ENV = "DAT_LEDGER"`, `CONFIG = ".datconfig.yaml"`.

## Invariants

- Nothing is created on disk without `create=True`; a missing ledger
  raises instead of appearing empty.
- `Ledger(path)` and `Ledger()` under `DAT_LEDGER` read no config, so
  they assert no mounts.
- `Ledger()` writes a revision only when the config's `mounts:` differ
  from the rows it holds.
- `Ledger._values` caches loaded values per `(subject, rev, name)` for
  the life of the handle (filled by [rev](rev.md) `Ref.load`).

## Left to other modules

The SQLite file and the art store are [store](store.md)'s; reads are
[rev](rev.md)'s; writes and seals are [txn](txn.md)'s. Mount rows are
interpreted by [fn](fn.md) and [sandbox](sandbox.md), not here; the
config's checkout name comes from [env](env.md).
