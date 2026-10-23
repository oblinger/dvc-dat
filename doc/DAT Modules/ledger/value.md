# ledger.value

A `Value` is the object itself with its provenance on it: what `run`
returns, what `v.seal` stores and what `Ref.load` restores. A
subclass says how it becomes bytes (`encode`) and back (`decode`), and
`@ledger_class(preds=…)` names the preds its values may carry. Until
the seal, `preds` is a plain dict filled by whoever builds the value;
the seal freezes it and fixes `subject`, `dependencies` and, at commit, `rev`.
Part of the [architecture](../../DAT%20Architecture.md).

## Public surface

`Value`:

- `encode() -> bytes`, `decode(data, store) -> Value` (classmethod):
  `NotImplementedError` unless a subclass defines them. A `decode` that
  also accepts `name=` (keyword, or `**kwargs`) is passed the name the
  value is loaded by (an alias), `None` when loaded by its subject.
- `_parts() -> Iterable[(sha256, source)]`: further bytes `decode`
  fetches from the store, default none; `source` is a `Path` or a
  zero-arg opener returning a binary stream. A save streams each part
  into the art store one at a time ([store](store.md) `put_path`); no
  part is ever held in memory whole.
- `preds`: a `dict` while unsealed (assignable as a whole); a
  `FrozenPreds` once sealed, whose every mutator is `TypeError`.
- `subject: str | None`, `rev: Rev | None`, `dependencies: Mapping[str, str]`
  (empty until saved or evaluated), `sealed: str | None` (the seal's
  moment, UTC `YYYY-MM-DDTHH:MM:SSZ`, `None` while unsealed); set only by the
  seal, `load`, or (`dependencies` alone) an unsealed `memo=False` run.
  `sealed` with `subject` `None` is a value sealed by `v.seal()` and
  saved nowhere yet.
- `hash -> str`: hex sha256 of `encode()`; cached once sealed.
- `matches(rev) -> bool`: every dependency item holds at `rev` (memo only,
  never runs).
- `diff(other) -> {item: (mine, theirs)}`: dependency items that differ,
  `None` where one lacks the item.
- `same_as(other) -> bool`: equal `hash`; `False` for `None`.
- `Dependencies`: the `Mapping[str, str]` type of `dependencies`.
- `name: str | None` (Q36): the value's one name, an alias relative
  to the data folder and not part of its identity. Saved: the alias
  naming it at the head, written latest. Unsaved: the name a save
  gives it (`Value(name=...)`, `Value.Blob(obj, name=...)`,
  `Dat(path, name=...)`, or assigned). Assigning it on a saved value
  moves the name in a revision of its own (`by="name"`): the other
  names of the value are retracted and the name leaves any value it
  named; a `Dat`'s folder is rebuilt at the new name. A name is a
  relative path without `.` or `..` (`ValueError`).
- `repr`: a saved value prints as its name, else the hash's first 8;
  unsealed `<Kind unsealed>`.

Subclasses:

- `Value.Blob(obj)`: any Python object, pickled (protocol 4); declares no preds.
- `Value.Table(table)`: a `pyarrow.Table` or pandas `DataFrame` as parquet;
  decodes to `pyarrow`.
- `Dat(path)`: a folder; encodes as `{"files": {relpath: sha256}}`
  (canonical JSON, `__pycache__` folders skipped). Each file is hashed
  in 1 MiB blocks; the per-file hashes are cached on the object, keyed
  by each file's (size, mtime, inode), so `encode`, `_parts` and a
  save walk the folder but hash a changed file only. The files are the
  parts, `(sha256, path)`: a save hardlinks them into the art store
  (same filesystem) or streams a copy. `decode(data, store, *,
  name=None)` materialises the folder under `art/dats/<name>/` when
  loaded by a name, else `art/dats/<first 16 hex of the manifest
  hash>/`, placing each file by `ArtStore.get_to` (a hardlink where
  possible); a named folder holding other content (the alias was
  re-pointed) is replaced. After the seal `path` moves to the hash
  folder. `Dat.kind_ok(kind) -> bool` (classmethod) is the load's kind
  hook, below.

`seal(to=None, *, keep=False, deps=(), name=None, provenance=None, by=None) -> str`:
three forms.

| Form | Identity fixed | Bytes copied | In the ledger | Returns |
|---|---|---|---|---|
| `v.seal()` | yes | no | no | the hash |
| `v.seal(keep=True)` | yes | into this machine's kept cache | no | the hash |
| `v.seal(t)`, `v.seal(L)` | yes | into the art store | yes, at commit | the subject |

- `v.seal()` writes to no ledger: it freezes `preds` (an undeclared name
  is `Undeclared`), fixes the bytes' hash, `deps`, `provenance`, the
  environment and `sealed_at`, and writes them as a **seal record**,
  `sealed/<entry>.json` in the kept folder (`$DAT_KEPT`, else
  `~/.cache/dvc-dat/kept`; module `ledger.kept`): `hash`, `kind`,
  `sealed_at`, `path` (a `Dat`'s folder, resolved; `None` in memory),
  `deps` (each a `ref:` text with its subject, hash and name, or a
  function's subject and rows), `provenance`, `preds` (plain values;
  an edge as its ref), `env`, `kept`, `bytes`. A new unkept seal of a
  folder replaces that folder's unkept records. `alias=`/`by=` are
  `TypeError`; a second seal is `ValueError`; a pred value that is not
  a str, number, bool, list, dict of plain values or value is
  `TypeError` at the seal.
- `keep=True` also copies the bytes, by hash, into the kept cache
  (`$DAT_KEPT`, else `~/.cache/dvc-dat/kept`; module `ledger.kept`), so
  the folder or object may change afterwards. A part is cloned
  copy-on-write where the filesystem can (macOS APFS `clonefile`, Linux
  reflink `FICLONE`), which costs no disk, else streamed in 1 MiB
  blocks; either way it is checked against its hash and never linked,
  so an in-place write to the source cannot reach the kept copy. A save of a kept value hardlinks the kept blobs into the art
  store. `just sealed` lists every seal never saved, kept or not;
  `just sealed purge [older=14d]` drops the records. Each seal is its
  own entry (equal kept bytes share blobs), dropped by its save at
  commit; `purge` also collects blobs no entry names and older than an
  hour. If the kept bytes
  were purged, a save takes the source when it still hashes to the
  seal, else `SealBroken`.
- `to` a `Transaction` saves into it (the value lands with that
  revision or not at all; `by=` is `TypeError`); `to` a `Ledger` opens
  and commits a one-value transaction of its own, written `by`
  (default the provenance, else `seal`); `keep=` with either is
  `TypeError`; anything else is `TypeError`. The refusals are the
  transaction's ([txn](txn.md)).
- Saving a value sealed by `v.seal()` saves the state it was sealed in:
  its deps, provenance and environment enter the dependencies, and a
  `db/sealed-at` row records when; `deps=`/`provenance=` at the save
  are `TypeError`. Unless kept, the bytes are hashed again and a change
  is `SealBroken`. An abandoned save leaves the value sealed, saved
  nowhere. A dep sealed but saved nowhere is `ValueError` until it is
  saved first, earlier in the same transaction or before; one reopened
  with `name=` binds through that name at the save (the name must hold
  its bytes by then, else `ValueError`), with a `<name> db/alias` dependency
  item, as a `Ref` by that name would.
- `Dat.sealed_at_path(path, *, name=None) -> Dat | None` (classmethod):
  the last seal record of the folder `path` not saved since, reopened
  in this process as the sealing one left it (made as `kind(path)`,
  `kind` the record's class, which must be a subclass of the class
  called on, else `TypeError`); `None` with no record. `v.seal(t)` on it saves exactly
  as the sealing process would have: the same subject, `SealBroken` on
  a changed byte unless kept, the kept bytes when kept.
- After a save, `hash` is the stored bytes' hash, whatever the live
  object holds; `db/sealed-at` is one of the subject's frozen rows. An
  `run` whose function returns a value sealed by `v.seal()` is
  `TypeError`: eval seals its own result.

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
  on load, a `_spec_` naming a `dat.kind` that is neither the row's
  class nor accepted by the loaded class's `kind_ok` is a `TypeError`.
  `kind_ok`'s default accepts the class's dotted or bare
  name; a subclass widens it (a hybrid kind loading another library's
  folders).
- Memory is bounded by the manifest, not the folder: a 2 GB, three-file
  `Dat` seals with `keep=True` and saves with under 4 MB of RSS growth
  (`tests/ledger/test_stream.py`, `DAT_SLOW=1`).
- The files of a saved or loaded `Dat` are hardlinks into the art store
  where the filesystem allows, and so are a saved, unkept source
  folder's: an in-place write to either reaches the store. Write a new
  folder and seal it; never edit one in place.

## Left to other modules

Sealing is [txn](txn.md)'s and an eval's [fn](fn.md)'s; loading and
restoring provenance is [rev](rev.md)'s `Ref.load`; `matches` delegates
to [trace](trace.md); bytes are stored by [store](store.md).
