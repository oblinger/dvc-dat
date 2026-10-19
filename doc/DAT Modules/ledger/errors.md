# ledger.errors

Every exception the ledger raises is a `LedgerError` and also the
builtin it most resembles, so a caller can catch either the ledger's
class or the general one (`KeyError`-style lookups, `TypeError`-style
misuse). Plain `KeyError`, `TypeError`, `ValueError` and
`RuntimeError` are raised directly where no ledger-specific class adds
anything. Part of the [architecture](../../DAT%20Architecture.md).

## Public surface

| class | also | raised when |
| --- | --- | --- |
| `LedgerError` | `Exception` | no ledger found or opened; the backend refused |
| `Multiple` | `LookupError` | `value`, `refs(one=True)`, `select(one=True)` matched several |
| `NotEvaluated` | `RuntimeError` | a miss the environment cannot run (see below) |
| `UnmountedImport` | `ImportError` | a sandboxed run imported a mounted repo's module outside every mount |
| `UntracedRead` | `PermissionError` | a sandboxed body read outside the mounts, the dats and its `work` folder |
| `ConfinedWrite` | `PermissionError` | a sandboxed body wrote outside its `work` folder (the dat being produced) |
| `ConfinedNetwork` | `PermissionError` | a sandboxed body resolved a host name or connected to the network |
| `LockTimeout` | `TimeoutError` | a `lock=` body ran past its limit, or the lock was not had in time |
| `Unindexed` | `LookupError` | a where clause or select key named a dotted predicate neither declared nor on any row |
| `Exists` | `ValueError` | an `add`, `remove` or bracket write on a sealed subject's own predicate (at commit) |
| `Undeclared` | `TypeError` | a pred name the kind's `@ledger_class` did not declare (at the seal) |
| `AliasLoop` | `LookupError` | a `db/alias` chain loops or runs past 8 hops |

## Invariants

- Each class subclasses both `LedgerError` and its builtin, so
  `except KeyError` does not catch `Multiple` but `except LookupError`
  does.

- TODO: `NotEvaluated`'s docstring names "a miss at a revision this
  environment cannot run, or a mount whose repo has no checkout here";
  the code also raises it for code outside any git checkout, a dirty
  checkout, and a HEAD other than the rev's `code/<repo>` commit, and
  for `memo=False` runs as well as misses.
- TODO: `UnmountedImport`'s docstring says "a repo module outside every
  mount"; the finder raises it only for modules of a repo that has a
  mount. A module from an unmounted repo is not refused: it fails as
  an ordinary `ModuleNotFoundError`, or, when `site-packages` reaches
  it (an editable install), loads with nothing recorded.

## Left to other modules

Each module raises its own; the rules behind each are in [rev](rev.md),
[txn](txn.md), [fn](fn.md), [sandbox](sandbox.md) and
[store](store.md).
