# ledger2.value

A `Value` is the object itself with its provenance on it: what `eval`
returns, what `add_value` stores and what `Ref.load` restores. A
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
  (empty until sealed or evaluated), `sealed: bool`; set only by the
  seal, `load`, or (`trace` alone) an unsealed `memo=False` run.
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

`ledger_class(*, preds=()) -> decorator`: sets the kind's declared pred
names; a name that is empty, not a `str` or starts `db/` is `TypeError`,
as is decorating a non-`Value` class. Writes nothing.

`dotted(cls) -> str`: `module.qualname`, the name `db/kind` and
`ref:` texts carry.

## Invariants

- A sealed value's preds cannot change in place; a different value is a
  new object and a new seal.
- `hash` is a function of `encode()` alone; `add_value` refuses a class
  whose two `encode()` calls differ.
- A subclass's `__init__` need not call `super().__init__`; the
  provenance fields are class-level defaults.
- `Dat` is not `dvc_dat.Dat`: it checks no `_spec_.yaml` and hashes
  every file in the folder.

- TODO: the design (SVP447 Ledger Module § Ref `type`) says a `Dat`'s
  folder `_spec_` names its kind and is checked against the row at
  load; the code does no such check.

## Left to other modules

Sealing is [txn](txn.md)'s and an eval's [fn](fn.md)'s; loading and
restoring provenance is [rev](rev.md)'s `Ref.load`; `matches` delegates
to [trace](trace.md); bytes are stored by [store](store.md).
