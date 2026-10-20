# ledger.value

A `Value` is the object itself with its provenance on it: what `eval`
returns, what `v.seal` stores and what `Ref.load` restores. A
subclass says how it becomes bytes (`encode`) and back (`decode`), and
`@ledger_class(preds=…)` names the preds its values may carry. Until
the seal, `preds` is a plain dict filled by whoever builds the value;
the seal freezes it and fixes `subject`, `trace` and, at commit, `rev`.
Part of the [architecture](../../DAT%20Architecture.md).

## Public surface

`Value`:

- `encode() -> bytes`, `decode(data, store) -> Value` (classmethod):
  `NotImplementedError` unless a subclass defines them.
- `preds`: a `dict` while unsealed (assignable as a whole); a
  `FrozenPreds` once sealed, whose every mutator is `TypeError`.
- `subject: str | None`, `rev: Rev | None`, `trace: Mapping[str, str]`
  (empty until saved or evaluated), `sealed: bool`,
  `sealed_at: str | None` (UTC `YYYY-MM-DDTHH:MM:SSZ`); set only by the
  seal, `load`, or (`trace` alone) an unsealed `memo=False` run.
  `sealed` with `subject` `None` is a value sealed by `v.seal()` and
  saved nowhere yet.
- `hash -> str`: hex sha256 of `encode()`; cached once sealed.
- `matches(rev) -> bool`: every trace item holds at `rev` (memo only,
  never runs).
- `diff(other) -> {item: (mine, theirs)}`: trace items that differ,
  `None` where one lacks the item.
- `same_as(other) -> bool`: equal `hash`; `False` for `None`.
- `Trace`: the `Mapping[str, str]` type of `trace`.
- `repr`: a sealed value prints as its shortest alias at the head,
  else the hash's first 8; unsealed `<Kind unsealed>`.

Subclasses:

- `Pickled(obj)`: `obj` pickled (protocol 4); declares no preds.
- `Table(table)`: a `pyarrow.Table` or pandas `DataFrame` as parquet;
  decodes to `pyarrow`.
- `Dat(path)`: a folder; encodes as `{"files": {relpath: sha256}}`
  (canonical JSON, `__pycache__` folders skipped); the files go to the
  art store as parts; `decode` materialises the folder under
  `art/dats/<first 16 hex of the manifest hash>/` and returns a `Dat`
  there; after the seal `path` moves to that stored folder.

`seal(to=None, *, keep=False, deps=(), alias=None, provenance=None, by=None) -> str`:
three forms.

| Form | Identity fixed | Bytes copied | In the ledger | Returns |
|---|---|---|---|---|
| `v.seal()` | yes | no | no | the hash |
| `v.seal(keep=True)` | yes | into this machine's kept cache | no | the hash |
| `v.seal(t)`, `v.seal(L)` | yes | into the art store | yes, at commit | the subject |

- `v.seal()` writes nothing: it freezes `preds` (an undeclared name is
  `Undeclared`), and records the bytes' hash, `deps`, `provenance`, the
  environment and `sealed_at`. `alias=`/`by=` are `TypeError`; a second
  seal is `ValueError`.
- `keep=True` also copies the bytes, by hash, into the kept cache
  (`$DAT_KEPT`, else `~/.cache/dvc-dat/kept`; module `ledger.kept`), so
  the folder or object may change afterwards. `just sealed` lists what
  is kept and never saved; `just sealed purge [older=14d]` drops it. A
  save drops its entry at commit.
- `to` a `Transaction` saves into it (the value lands with that
  revision or not at all; `by=` is `TypeError`); `to` a `Ledger` opens
  and commits a one-value transaction of its own, written `by`
  (default the provenance, else `seal`); `keep=` with either is
  `TypeError`; anything else is `TypeError`. The refusals are the
  transaction's ([txn](txn.md)).
- Saving a value sealed by `v.seal()` saves the state it was sealed in:
  its deps, provenance and environment enter the trace, and a
  `db/sealed-at` row records when; `deps=`/`provenance=` at the save
  are `TypeError`. Unless kept, the bytes are hashed again and a change
  is `SealBroken`. An abandoned save leaves the value sealed, saved
  nowhere. A dep sealed but saved nowhere is `ValueError` until it is
  saved first, earlier in the same transaction or before.

`ledger_class(*, preds=()) -> decorator`: sets the kind's declared pred
names; a name that is empty, not a `str` or starts `db/` is `TypeError`,
as is decorating a non-`Value` class. Writes nothing.

`dotted(cls) -> str`: `module.qualname`, the name `db/kind` and
`ref:` texts carry.

## Invariants

- A sealed value's preds cannot change in place; a different value is a
  new object and a new seal.
- `hash` is a function of `encode()` alone; the seal refuses a class
  whose two `encode()` calls differ.
- A subclass's `__init__` need not call `super().__init__`; the
  provenance fields are class-level defaults.
- `Dat` is not `dvc_dat.Dat`: it hashes every file in the folder;
  on load, a `_spec_` naming a `dat.kind` other than the row's class
  is a `TypeError` (leg 8).

## Left to other modules

Sealing is [txn](txn.md)'s and an eval's [fn](fn.md)'s; loading and
restoring provenance is [rev](rev.md)'s `Ref.load`; `matches` delegates
to [trace](trace.md); bytes are stored by [store](store.md).
