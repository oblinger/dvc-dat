---
description: "The ledger half of dvc_dat: quads read as of a revision, values stored by content, value functions evaluated with a trace. Source: `dvc_dat/ledger/`."
---
:>> [DAT](../../DAT.md) → [ledger](ha://ledger) → [DAT Modules Ledger](ha://p/DAT%20Modules%20Ledger) 
# DAT Ledger
The ledger is a project's history: every fact a quad `(rev, subject, predicate, object)`, every read a frozen view as of one revision, every value stored by its content and found by its preds.

![DAT Ledger](DAT%20Ledger.svg)

*The fold* governs what a `Rev` reads, *Sealing and saving* governs how a `Value` gets its identity, and *Evaluation and the trace* governs when calling an `Fn` runs the body and when it hands back a sealed result.

This page is the package `dvc_dat.ledger` as a caller sees it: the figure above, each public class and its members, then the rules that span them. The per-file pages beside it hold the internals and every refusal in full: [ledger](ledger.md), [rev](rev.md), [txn](txn.md), [value](value.md), [fn](fn.md), [trace](trace.md), [env](env.md), [sandbox](sandbox.md), [worker](worker.md), [store](store.md), [fold](fold.md), [codec](codec.md), [helpers](helpers.md), [errors](errors.md). The dat half, a folder that is its own recipe, is [DAT Dat](../DAT%20Dat.md); how the two halves meet is the [architecture](../../DAT%20Architecture.md).



## Ledger Interface
The handle on one ledger: a folder holding `ledger.db` and the art store `art/`, or a Postgres database named by a DSN with its art store a folder. It finds or opens the ledger, hands out frozen views with `at` and write sets with `transaction`, and holds no reads of its own, so a long run reads one snapshot by construction. Nothing is created on disk without `create=True`. A `Ledger` is a context manager whose exit closes it.

| Ledger | |
| --- | --- |
| [Ledger](#^ledger) | Find, open or create a ledger |
| [path](#^path) | The resolved ledger folder, or the DSN |
| [at](#^at) | A frozen view at a revision or a release |
| [transaction](#^transaction) | A write set that becomes one revision |
| [close](#^close) | Close every database connection the handle opened |

**Ledger**`(path: str | Path | None = None, *, create: bool = False)`
    `Ledger(path)` opens the folder or DSN at `path`; a folder without `ledger.db` is `LedgerError`, and so is a file. `Ledger()` takes `DAT_LEDGER` when set, else the nearest `.datconfig.yaml` at or above the working directory carrying a `ledger:` key (relative to that file), and asserts the config's `mounts:` as `db/mount/<prefix>` rows in one transaction `by="config:<path>"` when they differ from the ledger's; none found is `LedgerError` naming every folder searched. `Ledger(path, create=True)` makes an empty ledger there if absent. `Ledger(create=True)` makes a project in the working directory, writing `ledger: .dat/ledger` into its `.datconfig.yaml`; with `DAT_LEDGER` set it is `ValueError`. ^ledger

**path**`: Path | str`
    The resolved ledger folder; for a Postgres ledger, the DSN with its `art` parameter made absolute. `repr` hides a DSN's password. ^path

**at**`(which: int | str | None = None) -> Rev`
    `None` is the top; an `int` or a digit string is that revision (`KeyError` outside `0..top`); `"M.m.p"` is the latest revision that set `(db, version, M.m.p)` (`KeyError` when none did); a `bool` or anything else is `TypeError`. ^at

**transaction**`(*, by: str, lock: float | None = None, **preds) -> Transaction`
    A write set, used only as `with L.transaction(by=...) as t:`. `by` names the writer and is required; `lock=` holds the write lock for the whole body, at most that many seconds. Each extra keyword is a `str` or a JSON document and lands as a row on the transaction's `db/tx/<rev>` subject beside `db/by` and `db/time`. See [Revisions and transactions](#revisions-and-transactions). ^transaction

**close**`() -> None`
    Close the handle's database connections in every thread; a later read or write reopens one. ^close



## Rev Interface
A frozen view of the ledger as of one revision, made by `Ledger.at`, never by hand. Every read is bounded by `id`, so a `Rev` gives the same answer forever. Row reads fold the rows by each predicate's cardinality ([The fold](#the-fold)); `asserted` and `rows` walk history unfolded; subject reads (`refs`, `values`, `value`, `select`) treat the store as a table whose rows are subjects. A stored reference comes back as an unloaded `Ref`. A `Rev` handed to a value function's body also records every read into the function's trace. Ordered and equal by `id` within one ledger.

| Rev | |
| --- | --- |
| [id](#^id) | The revision number |
| [ledger](#^rev-ledger) | The ledger this view reads |
| [tx](#^tx) | The subject carrying this revision's provenance |
| [__getitem__](#^--getitem--) | A record, an object, or when a triple was added |
| [get](#^get) | The bracket read with a default |
| [all](#^all) | Every match of a pattern |
| [__contains__](#^--contains--) | Whether a triple is held |
| [asserted](#^asserted) | The history of one subject and predicate |
| [rows](#^rows) | Every row, unfolded |
| [refs](#^refs) | The subjects matching a where clause |
| [values](#^values) | The sealed values matching, loaded |
| [value](#^value) | The one sealed value matching, loaded |
| [select](#^select) | Chosen objects of each match, as tuples |
| [load](#^load) | One value by subject or alias |
| [load_fn](#^load-fn) | A value function resolved at this revision |
| [run](#^run) | Evaluate a value function, memoised (`just run`); `eval` is its deprecated alias |

**id**`: int`
    The revision this view reads as of; revision 0 is the empty ledger. ^id

**ledger**`: Ledger`
    The ledger this view reads. ^rev-ledger

**tx**`: str`
    `db/tx/<id>`: the subject holding this revision's `db/by`, `db/time` and transaction keywords. ^tx

**__getitem__**`(key) -> dict | object | Rev`
    `rev[s]` is the subject's record: a dict of predicate to object (a list for a `many` predicate); no rows is `KeyError`. `rev[s, p]` is the one held object; nothing held is `KeyError`, a `many` predicate `TypeError` naming `all`, an object whose tag mismatches the predicate's `db/type` `TypeError`. `rev[s, p, o]` is the revision of the held triple's earliest add not since removed; not held is `KeyError`. ^--getitem--

**get**`(*pattern, default=None, since: Rev | None = None)`
    The bracket read with `default` in place of `KeyError`. `since` keeps only rows in `(since, id]`: what one transaction wrote, or what moved between two releases. ^get

**all**`(*pattern, since: Rev | None = None) -> list`
    Every match of the fold, binding the open positions, in revision order; a prefix glob `"game/*"` binds the subject. Not checked against `db/type`. More than three positions is `TypeError`; a `*` anywhere but the end is `ValueError`. ^all

**__contains__**`(triple) -> bool`
    `(s, p, o) in rev`: whether the triple is held at this revision, by the same fold. ^--contains--

**asserted**`(subject: str, predicate: str, object=...) -> list`
    History at or before this revision, removes included, unfolded. With two arguments, `[(Rev, obj, added)]`; with three, every `Rev` that added that triple. ^asserted

**rows**`(since: Rev | None = None) -> list[Row]`
    Every row at or before this revision, or in `(since, id]`, unfolded, in `(rev, ord)` order: the ledger as stored. ^rows

**refs**`(*, s=None, kind=None, fn=None, where=None, one=False, since=None, **preds) -> list[Ref] | Ref`
    The subjects satisfying every constraint, each a `Ref` at this revision. A bare keyword names a pred (any member of a `many` pred); `kind=` a `Value` class or dotted name, following `db/moved` renames; `fn=` the producing function's dotted name; `where={p: o}` any predicate, `None` meaning any object; `s` an exact subject or a prefix glob. `one=True` returns the single match: none is `KeyError`, several `Multiple`. A dotted predicate neither declared nor on any row is `Unindexed`. ^refs

**values**`(*, s=None, kind=None, fn=None, where=None, since=None, **preds) -> list[Value]`
    The sealed values matching the where clause of `refs`, loaded. ^values

**value**`(*, s=None, kind=None, fn=None, where=None, since=None, **preds) -> Value`
    The one sealed value matching the where clause of `refs`, loaded: none is `KeyError`, several `Multiple`. ^value

**select**`(keys: tuple[str, ...], *, s=None, kind=None, fn=None, where=None, one=False, since=None, **preds) -> list[tuple] | tuple`
    Each match as a tuple of its objects for `keys`: `None` where absent, a list for a `many` predicate. `keys` not a non-empty tuple is `TypeError`; `one=True` as in `refs`. ^select

**load**`(subject: str) -> Value`
    `Ref(self, subject).load()`: the value under a subject or an alias, decoded, its provenance restored. ^load

**load_fn**`(name: str) -> Fn`
    The value function a dotted name resolves to at this revision: under the longest mounted prefix it is sandboxed, otherwise it is imported in this process (base mode). See [Functions and the sandbox](#functions-and-the-sandbox). ^load-fn

**run**`(name: str, /, *, memo=True, clean=False, **keys) -> Value | None`
    The API form of `just run NAME KEY=VALUE`: `load_fn(name)(memo=memo, clean=clean, **keys)`; a name that is not a `str` is `TypeError`. `eval` is a deprecated alias that warns and forwards. See [Evaluation and the trace](#evaluation-and-the-trace). ^run



## Ref Interface
One value at one moment, named without fetching a byte. Making one resolves the `db/alias` chain from `name`; a cycle or more than 8 hops is `AliasLoop`. A `Ref` is frozen, equal and hashed by subject, and does not pickle (it is bound to an open ledger). Its `repr` is the value's name (the alias naming it written latest), else the hash's first 8 hex. Made from a recording `Rev`, it records its reads into the trace like the `Rev` would.

| Ref | |
| --- | --- |
| [Ref](#^ref) | Name a value at a revision |
| [rev](#^rev) | The revision the reference was made at |
| [name](#^name) | The name it was made by |
| [subject](#^subject) | The subject, alias resolved |
| [hash](#^hash) | The sha256 of the value's bytes |
| [type](#^type) | The class that decodes it |
| [preds](#^preds) | The subject's user rows |
| [aliases](#^aliases) | Every alias naming the subject |
| [sealed_at](#^sealed-at) | The revision that sealed it |
| [load](#^ref-load) | Fetch, decode and restore the value |

**Ref**`(rev: Rev, name: str)`
    A reference to whatever `name` (a subject or an alias) names at `rev`. `rev` not a `Rev` or `name` not a non-empty `str` is `TypeError`. ^ref

**rev**`: Rev`
    The revision the reference was made at. ^rev

**name**`: str`
    The name it was made by: an alias or a subject. ^name

**subject**`: str | None`
    The subject after the alias chain. For a stored hint-less reference, the latest entry holding those bytes as of `rev`. ^subject

**hash**`: str | None`
    The 64-hex sha256 of the value's bytes; `None` when the subject holds no value. Byte identity of two refs is `a.hash == b.hash`. ^hash

**type**`: type | None`
    The `Value` subclass that decodes the bytes, following `db/moved` renames; a class that does not import is `ImportError`. ^type

**preds**`: FrozenPreds`
    The subject's non-`db/` rows, annotations included; a typed pred is an unloaded `Ref`. ^preds

**aliases**`: list[str]`
    Every name aliasing the subject as of `rev`. ^aliases

**sealed_at**`: Rev | None`
    The revision of the subject's `db/value` row. ^sealed-at

**load**`() -> Value`
    Fetch the bytes from the art store, decode them by `type`, and restore `subject`, `rev` (the sealing revision), `trace` and `preds`. Cached per `(subject, rev, name)` on the `Ledger`; a cached `Dat` is handed back only while its folder is still there and the same folder. A `decode` that accepts `name=` is passed the alias the `Ref` was made by, so a `Dat` loaded by an alias lands under `art/dats/<alias>/`. No value is `KeyError`; a `decode` returning a non-`Value` is `TypeError`; a `Dat` whose `_spec_` names a `dat.kind` the row's class does not accept is `TypeError`. ^ref-load



## Row Interface
One stored row as `rows()` returns it, a named tuple. `str(row)` is one aligned line: revision, `+` or `-`, subject, predicate, object.

| Row | |
| --- | --- |
| [rev](#^row-rev) | The revision that wrote it |
| [subject](#^row-subject) | The subject |
| [predicate](#^predicate) | The predicate |
| [object](#^object) | The object, decoded |
| [added](#^added) | False on a remove row |

**rev**`: Rev`
    The revision that wrote the row. ^row-rev

**subject**`: str`
    The row's subject. ^row-subject

**predicate**`: str`
    The row's predicate. ^predicate

**object**`: str | dict | list | Ref`
    The row's object, decoded from its tagged text ([Storage](#storage)). ^object

**added**`: bool`
    `True` for an add, `False` for a remove. ^added



## Transaction Interface
The write set of one `with L.transaction(...) as t:` block; it becomes exactly one revision on exit, or nothing. `add` and `remove` append rows and read nothing; `v.seal(t)` seals a value into it; the bracket forms are read-then-write helpers over `add` and `remove` through `base`. Whatever must see the transaction's own rows is checked at commit, inside the write lock. Entered once; a verb used outside the block is `RuntimeError`.

| Transaction | |
| --- | --- |
| [tx](#^transaction-tx) | A placeholder for this revision's tx subject |
| [base](#^base) | The top when the block was entered |
| [rev](#^transaction-rev) | The revision the exit wrote |
| [add](#^add) | Append an add row |
| [remove](#^remove) | Append a remove row |
| [__setitem__](#^--setitem--) | Assign a predicate, or a whole record |
| [__delitem__](#^--delitem--) | Retract a predicate, or every user predicate |

**tx**`: str`
    A placeholder subject, rewritten to `db/tx/<rev>` at commit wherever it appears as a subject or a `str` object, so the body can write rows about its own transaction. ^transaction-tx

**base**`: Rev`
    The top when the block was entered; under `lock=` the top until exit. `RuntimeError` before entry. ^base

**rev**`: Rev`
    The revision written; `RuntimeError` before commit. ^transaction-rev

**add**`(subject: str, predicate: str, object) -> None`
    One add row. `object` is a `str`, a JSON `dict` or `list`, or a `Ref` to a sealed value; a `Value` is `TypeError` naming `seal`; a bare number, bool or `None` is `TypeError` (a number is its string). `predicate == "db/value"` is `TypeError`: only a seal writes it. ^add

**remove**`(subject: str, predicate: str, object) -> None`
    One remove row: the object leaves the set of a `many` predicate, or, when it is the held object of a `one` predicate, leaves nothing held. ^remove

**__setitem__**`(key, value) -> None`
    `t[s, p] = o` is `add` on a `one` predicate; a `many` or `db/` predicate is `TypeError`. `t[s] = {...}` makes the subject's user rows equal to the dict at the next revision; `t[s] = t.base[s]` writes nothing. Brackets take exact subjects; a glob is `TypeError`. ^--setitem--

**__delitem__**`(key) -> None`
    `del t[s, p]` retracts what `p` holds; `del t[s]` retracts every user predicate; `db/` rows survive, and a `db/` predicate is `TypeError`. ^--delitem--



## Value Interface
The object itself with its provenance on it: what `run` returns, what `seal` stores and what `Ref.load` restores. A subclass says how it becomes bytes (`encode`) and back (`decode`); `@ledger_class(preds=...)` names the preds its values may carry. Until sealed, `preds` is a plain dict filled by whoever builds the value; the seal freezes it and fixes the identity. A subclass's `__init__` need not call `super().__init__`.

| Value | |
| --- | --- |
| [preds](#^value-preds) | The strings the value is found by |
| [subject](#^value-subject) | Its ledger subject once saved |
| [rev](#^value-rev) | The revision that saved it |
| [trace](#^trace) | What producing it read |
| [sealed](#^sealed) | Whether its identity is fixed |
| [sealed_at](#^value-sealed-at) | When the seal happened |
| [hash](#^value-hash) | The sha256 of its encoding |
| [encode](#^encode) | The bytes to store |
| [decode](#^decode) | The object from its bytes |
| [seal](#^seal) | Fix its identity, and save it when given a ledger |
| [matches](#^matches) | Whether its trace still holds at a revision |
| [diff](#^diff) | The trace items that differ from another value's |
| [same_as](#^same-as) | Equal bytes |
| [Trace](#^value-trace) | The type of `trace` |

**preds**`: dict | FrozenPreds`
    A `dict` while unsealed, assignable as a whole; a `FrozenPreds` once sealed, whose every mutator is `TypeError`. Each pred is a `str`, number, bool, list, `Value` or `Ref`, and its name must be declared by the class's `@ledger_class` (`Undeclared` at the seal). ^value-preds

**subject**`: str | None`
    The 64-hex subject the value was saved under; `None` until saved, including when sealed by `seal()` alone. ^value-subject

**rev**`: Rev | None`
    The revision that saved the value; set at commit or by `load`. ^value-rev

**trace**`: Mapping[str, str]`
    Item name to version or hash: what producing the value read. Empty until saved or evaluated. See [Evaluation and the trace](#evaluation-and-the-trace). ^trace

**sealed**`: bool`
    The identity is fixed: by `seal()` (saved nowhere yet, `subject` `None`) or by a save. ^sealed

**sealed_at**`: str | None`
    When the seal happened, UTC `YYYY-MM-DDTHH:MM:SSZ`. ^value-sealed-at

**hash**`: str`
    The hex sha256 of `encode()`, cached once sealed; after a save, the stored bytes' hash whatever the live object holds. ^value-hash

**encode**`() -> bytes`
    The bytes to store; `NotImplementedError` unless a subclass defines it. Two calls must return the same bytes: the seal refuses a class whose encoding is not deterministic. ^encode

**decode**`(data: bytes, store: ArtStore) -> Value` (classmethod)
    The object from its bytes; `NotImplementedError` unless a subclass defines it. A `decode` that also accepts `name=` is passed the alias the value is loaded by, `None` when loaded by its subject. ^decode

**seal**`(to=None, *, keep=False, deps=(), alias=None, provenance=None, by=None) -> str`
    `v.seal()` fixes the identity and writes no ledger: preds freeze, and the hash, `deps`, `provenance`, the environment and the time go into a seal record in the kept folder; it returns the hash. `keep=True` also copies the bytes into the kept cache, so the source may change. `v.seal(t)` saves into an open transaction and returns the subject; `v.seal(L)` commits a one-value transaction of its own, written `by` (default the provenance, else `seal`). `alias=` writes `(alias, db/alias, subject)` beside it. A provenance beginning `eval:` is `ValueError`; a second seal is `ValueError`. See [Sealing and saving](#sealing-and-saving). ^seal

**matches**`(rev: Rev) -> bool`
    Whether every trace item holds at `rev`: the memo's hit test. Consults the ledger only; never runs anything. ^matches

**diff**`(other: Value) -> dict[str, tuple]`
    The trace items whose values differ, item to `(mine, theirs)`, `None` where one lacks the item. ^diff

**same_as**`(other: Value | None) -> bool`
    `self.hash == other.hash`; `False` for `None`. ^same-as

**Trace**`: Mapping[str, str]` (class attribute)
    The type of `trace`, for annotations. ^value-trace



## Pickled Interface
A `Value` holding any pickleable object, encoded with pickle protocol 4. Declares no preds.

| Pickled | |
| --- | --- |
| [Pickled](#^pickled) | Wrap an object |
| [obj](#^obj) | The object |

**Pickled**`(obj)`
    A value whose bytes are `obj` pickled. A value function whose return annotation is not a `Value` subclass has its result wrapped in one. ^pickled

**obj**`: Any`
    The wrapped object. ^obj



## Table Interface
A `Value` holding a table, encoded as parquet. A pandas `DataFrame` is converted on encode; a decoded `Table` holds a `pyarrow.Table`.

| Table | |
| --- | --- |
| [Table](#^table) | Wrap a table |
| [table](#^table-table) | The table |

**Table**`(table)`
    A value whose bytes are `table` as parquet; `table` is a `pyarrow.Table` or a pandas `DataFrame`. ^table

**table**`: pyarrow.Table | pandas.DataFrame`
    The wrapped table; a `pyarrow.Table` after a load. ^table-table



## Dat Interface
A `Value` that is a folder: it encodes as its content manifest, `{"files": {relpath: sha256}}`, and its files are its parts, streamed into the art store one at a time, so memory is bounded by the manifest, not the folder. This is the ledger's own folder value, not the dat manager's `dvc_dat.Dat`: it hashes every file in the folder (`__pycache__` skipped) and reads no `_spec_.yaml` except to check its `dat.kind` on load. Each file is hashed in 1 MiB blocks; the per-file hashes are cached on the object, keyed by size, mtime and inode, so only a changed file is hashed again.

| Dat | |
| --- | --- |
| [Dat](#^dat) | Wrap a folder |
| [path](#^dat-path) | The folder |
| [sealed_at_path](#^sealed-at-path) | Reopen a folder sealed in another process |
| [kind_ok](#^kind-ok) | Whether a folder's dat.kind loads as this class |
| [spec_kind](#^spec-kind) | The dat.kind a folder's spec names |
| [decode](#^dat-decode) | Materialise the folder from its manifest |

**Dat**`(path)`
    A value whose bytes are the manifest of the folder at `path`. ^dat

**path**`: Path`
    The folder. After a save it is the stored copy under `art/dats/<16 hex>/`; after a load by an alias, `art/dats/<alias>/`. Those files are hardlinks into the art store where the filesystem allows: write a new folder and seal it, never edit one in place. ^dat-path

**sealed_at_path**`(path, *, name: str | None = None) -> Dat | None` (classmethod)
    The last seal record of the folder `path` not saved since, reopened in this process as the sealing process left it; `None` with no record. `v.seal(t)` on it saves exactly what the sealing process would have saved: the same subject, `SealBroken` on a changed byte unless kept. The record's class must be a subclass of the class called on, else `TypeError`. ^sealed-at-path

**kind_ok**`(kind: str) -> bool` (classmethod)
    Whether a folder whose `_spec_` names `dat.kind` `kind` loads as this class beside the class its `db/value` row names. The default accepts the class's dotted or bare name; a subclass widens it. ^kind-ok

**spec_kind**`(path: Path) -> str | None` (static)
    The `dat.kind` the folder's `_spec_.yaml` (or `_spec_.json`) names, if any. ^spec-kind

**decode**`(data: bytes, store: ArtStore, *, name: str | None = None) -> Dat` (classmethod)
    The folder of a manifest, placed under `<art>/dats/<name>/` when loaded by a name, else `<art>/dats/<first 16 hex of the manifest hash>/`; each file is placed by `ArtStore.get_to`. A named folder holding other content (the alias was re-pointed) is replaced. ^dat-decode



## Fn Interface
A value function resolved at one revision: a frozen dataclass made by `Rev.load_fn`, never by hand. Calling it is `run`. Its mode is `base` (imported in this process) or `sandbox` (loaded from a mount and run in a worker).

| Fn | |
| --- | --- |
| [name](#^fn-name) | The dotted name |
| [module](#^module) | The source file |
| [sha](#^sha) | The sha256 of the source file |
| [mode](#^mode) | base or sandbox |
| [mount](#^mount) | The mounted prefix, in sandbox mode |
| [signature](#^signature) | The keys it takes |
| [env](#^env) | The environment it resolved in |
| [subject](#^fn-subject) | The db/fn subject naming this code |
| [__call__](#^--call--) | Evaluate: a memo hit, or run and seal |

**name**`: str`
    The dotted name it was resolved by. ^fn-name

**module**`: Path`
    The function's source file. ^module

**sha**`: str`
    The sha256 of that file. ^sha

**mode**`: str`
    `"base"` or `"sandbox"`. ^mode

**mount**`: str | None`
    The mounted prefix the name resolved under; `None` in base mode. ^mount

**signature**`: inspect.Signature`
    The keys the function takes, without the leading `Rev` and without `path`. ^signature

**env**`: Env`
    The environment the function resolved in: repos and commits, platform. ^env

**subject**`: str`
    `db/fn/<name>/<16 hex>`, hashing the code that runs ([Evaluation and the trace](#evaluation-and-the-trace)). ^fn-subject

**__call__**`(*, memo=True, clean=False, path=None, kwargs=None, **keys) -> Value | None`
    `memo=True` hands back a memo hit, else runs the body, seals the result and returns it; `memo=False` runs and seals nothing; `memo="get"` returns a hit or `None` and never runs; anything else is `ValueError`. The control options are exactly `memo`, `clean`, `path` and `kwargs`, never keys and never hashed. Keys bind to the signature with defaults applied; `kwargs={...}` passes the whole key set instead, for a key named like a control option, and inline keys beside it are `TypeError`. `path=` names the result (relative to the data folder; a `Dat`'s folder is rebuilt there as a view; a hit under a new name takes it) or, absolute, makes the folder there and names nothing. A base-mode run needs the function's code in a clean git checkout, else `NotEvaluated`; a sandboxed run goes ahead at HEAD, clean or dirty. `clean=True` first requires the checkout clean and at the rev's `code/<repo>` commit, else `NotClean`. A result that is not an instance of a `Value`-subclass return annotation is `TypeError`. ^--call--



## dvc_dat.ledger Interface
The package's other exports: two decorators, two helpers, and the exceptions. Every exception is a `LedgerError` and also the builtin it most resembles, so a caller catches either. `Env`, `Code` and `set_env_provider` are importable as the test suite's seam for the environment and are not part of the interface.

| dvc_dat.ledger | |
| --- | --- |
| [ledger_fn](#^ledger-fn) | Mark a function as a value function |
| [ledger_class](#^ledger-class) | Declare a Value class's pred names |
| [bump](#^bump) | Move a clock subject's version |
| [attr](#^attr) | Walk a dotted path into an object |
| [LedgerError](#^ledgererror) | Base of every ledger exception |
| [Multiple](#^multiple) | Several matched where one was required |
| [NotEvaluated](#^notevaluated) | A miss this environment cannot run |
| [NotClean](#^notclean) | `clean=True`, and the code is not a clean version |
| [UnmountedImport](#^unmountedimport) | A sandboxed import outside every mount |
| [UntracedRead](#^untracedread) | A sandboxed read outside the allowed places |
| [ConfinedWrite](#^confinedwrite) | A sandboxed write outside the path folder |
| [ConfinedNetwork](#^confinednetwork) | A sandboxed network use |
| [LockTimeout](#^locktimeout) | A lock= body past its limit |
| [Unindexed](#^unindexed) | A query on an unknown dotted predicate |
| [Exists](#^exists) | A write to a sealed subject's own rows |
| [Undeclared](#^undeclared) | A pred name the class did not declare |
| [AliasLoop](#^aliasloop) | An alias chain that loops or runs long |
| [SealBroken](#^sealbroken) | A sealed value's bytes changed before saving |

**ledger_fn**`(func: Callable) -> Callable`
    Marks `func` as a value function and returns it unchanged, still a plain callable: a plain call runs the body with whatever `Rev` it is given, records nothing and seals nothing, which is how it is unit-tested. A missing return annotation or a non-callable is `TypeError` at decoration. ^ledger-fn

**ledger_class**`(*, preds: Iterable[str] = ())`
    Class decorator naming the preds a `Value` subclass's values may carry. A name that is empty, not a `str`, or starts `db/` is `TypeError`, as is decorating a class that is not a `Value`. Writes nothing. ^ledger-class

**bump**`(t: Transaction, subject: str, part: str = "patch", *, confirm=None) -> str`
    Reads `version` through `t.base` (`0.0.0` when absent), adds the next by `part`, and returns it. On `code/<repo>` it also adds `commit`, read from that repo's checkout; no checkout or a dirty one is `ValueError`. `minor` and `major` need `confirm(old, new)` to return `True`. A subject holding a `db/alias` is `TypeError`: a value's version is a pred, not a clock. Run it under `lock=` when the update must not be lost. ^bump

**attr**`(obj, path: str)`
    Walks a dotted path over mappings, sequences (integer steps) and attributes; `KeyError` at the first missing step, `TypeError` for an empty path. ^attr

**LedgerError**`(Exception)`
    No ledger found or opened, or the backend refused. ^ledgererror

**Multiple**`(LedgerError, LookupError)`
    `value`, `refs(one=True)` or `select(one=True)` matched several. ^multiple

**NotEvaluated**`(LedgerError, RuntimeError)`
    A run the environment cannot make: a mount whose repo has no checkout here, or (base mode) code outside any git checkout or a dirty checkout. ^notevaluated

**NotClean**`(NotEvaluated)`
    A `clean=True` call whose checkout is dirty, or not at the commit the revision's `code/<repo>` row names, or whose revision names none. ^notclean

**UnmountedImport**`(LedgerError, ImportError)`
    A sandboxed body imported a module of a mounted repo that lies under no mount. ^unmountedimport

**UntracedRead**`(LedgerError, PermissionError)`
    A sandboxed body read outside the mounts, the art store and its `path` folder. ^untracedread

**ConfinedWrite**`(LedgerError, PermissionError)`
    A sandboxed body wrote outside its `path` folder, the dat being produced. ^confinedwrite

**ConfinedNetwork**`(LedgerError, PermissionError)`
    A sandboxed body resolved a host name or opened a network connection other than to a Postgres ledger's own endpoint. ^confinednetwork

**LockTimeout**`(LedgerError, TimeoutError)`
    A `lock=` body ran past its limit, or the lock was not had in time; nothing written. ^locktimeout

**Unindexed**`(LedgerError, LookupError)`
    A where clause or select key named a dotted predicate neither declared nor carried by any row. ^unindexed

**Exists**`(LedgerError, ValueError)`
    An `add`, `remove`, bracket write or `del` on one of a sealed subject's own predicates, raised at commit. ^exists

**Undeclared**`(LedgerError, TypeError)`
    At the seal, a pred name the class's `@ledger_class(preds=...)` did not declare. ^undeclared

**AliasLoop**`(LedgerError, LookupError)`
    A `db/alias` chain loops or runs past 8 hops. ^aliasloop

**SealBroken**`(LedgerError, ValueError)`
    Saving a value sealed by `seal()` whose bytes are no longer the bytes it was sealed with, and which was not kept. ^sealbroken




# Ledger Semantics

## Revisions and transactions
Every fact is a quad `(rev, subject, predicate, object)`; rows are only ever appended, never updated or deleted, and `remove` appends a remove row.

| rev | subject | predicate | object |
| --- | --- | --- | --- |
| 1 | `game/G1` | `home` | `G4` |
| 1 | `game/G1` | `court` | `north` |
| 1 | `db` | `db/format` | `dvc-dat-ledger/1` |
| 1 | `db/tx/1` | `db/by` | `human:dan` |
| 2 | `game/G1` | `court` | `south` |
| 2 | `game/G1` | `officials` | `kim` |
| 2 | `db/tx/2` | `db/by` | `human:dan` |

```python
ledger = Ledger()
with ledger.transaction(by="human:dan") as t:
    t["game/G1", "court"] = "south"
    t.add("game/G1", "officials", "kim")
ledger.at()["game/G1", "court"]      # "south"
ledger.at(1)["game/G1", "court"]     # "north", forever
```

One `with` block is one revision: its rows land together on exit, in body order, followed by the `db/tx/<rev>` rows (`db/by`, `db/time`, and each keyword given `transaction()`), which a body that wrote nothing still writes. A ledger's first transaction also writes `(db, db/format, dvc-dat-ledger/1)`. An exception in the body, a refusal at commit, or `LockTimeout` writes nothing, unseals every value the body sealed and removes the bytes it stored. Revisions are dense and monotonic, so a reader never sees half a transaction.



## The fold
A read turns the rows at or before its revision into what they hold, by each predicate's cardinality. Under `one`, the default, the latest add wins, so `add` is assignment; a remove of the held object leaves nothing held. Under `many`, the held objects are the set added and not since removed, each at its earliest add. Cardinality is itself a row, `(db/pred/officials, db/cardinality, many)`, read as of the same revision; every `db/` predicate and the clocks `version` and `commit` are fixed at `one`. Every read folds except `rows` and `asserted`, which walk history.



## Sealing and saving
A value's subject is a 64-hex hash of its trace, its preds and its `db/value` text (the class and the bytes' hash); no one types it. Sealing fixes that identity; saving writes it into a ledger.

| Form | Bytes copied | In the ledger | Returns |
| --- | --- | --- | --- |
| `v.seal()` | no | no | the hash |
| `v.seal(keep=True)` | into the kept cache | no | the hash |
| `v.seal(t)`, `v.seal(L)` | into the art store | yes, at commit | the subject |

On the seal's line `preds` becomes read-only and `sealed`, `subject` and `trace` are set; `rev` is set at commit, when the bytes go to the art store just before the rows. A save writes the subject's own rows once: `db/value`, `db/kind`, `db/provenance` (default `seal`), `db/preds`, one `db/trace/<item>` per trace item, and one row per pred (per member for a `many` pred). A subject already saved is not written again: the seal is idempotent.

`v.seal()` alone writes a seal record to this machine's kept folder (`$DAT_KEPT`, else `~/.cache/dvc-dat/kept`); a later `v.seal(t)` saves the state it was sealed in, its trace the environment of the seal, not of the save. A value not kept whose bytes changed in between is `SealBroken`. `Dat.sealed_at_path` reopens such a seal in another process. `just sealed` lists the seals never saved; `just sealed purge` drops them.

A sealed value never changes: an `add` or `remove` on one of its own rows is `Exists` at commit. Any other row on its subject is annotation. A new version is a new seal. An alias, `(video/G1, db/alias, <subject>)`, is the re-pointable name: it moves while the values it pointed at stay. An alias names a subject holding a `db/value`, and a subject holding its own `db/value` cannot be an alias.

A hand seal's trace is declared: the `deps` given, plus `code/<repo>` for every repo the environment reports, and `platform`; its provenance is `seal` or the caller's. An eval's trace is recorded and its provenance is `eval:base` or `eval:sandbox`; `seal` refuses a provenance beginning `eval:`, so a consumer that needs proof asks for an `eval:` value.



## Functions and the sandbox
A value function takes the revision first and keywords after, is marked `@ledger_fn`, and returns a `Value`; its return annotation is required.

```python
@ledger_fn
def cut(rev, *, game: str, version: str) -> Cut:
    home = rev[f"game/{game}", "home"]           # traced
    raw = rev.value(kind=Video, game=game)       # traced
    out = Cut(cut_video(raw, home))
    out.preds.update(game=game, version=version)
    return out
```

A function that declares `path: Path` is given a fresh folder under `$DAT_WORK` (default `~/.cache/dvc-dat/work`); it writes a dat there and returns `Dat(path)`, and the seal moves the files into the art store. The result's name is the call's `path=` (relative to the data folder, `<art store>/dats`), else the parameter's default as a path template expanded with the keys, else `anonymous/Dat{unique}`; its folder at the name is a view, hardlinks into the store, rebuilt as a new folder when the name moves. A value has one name, an alias not bound into its hash, settable as `Value(name=...)` or by assigning `v.name`; a name names one value; a value prints as its name, else a hash prefix.

A base-mode function is whatever the running process imports. Its `fn` subject hashes the function module's static import closure within its checkout, and its `code/<repo>` trace item names the checkout's commit. The checkout is found by git discovery over the folders of the imported modules, skipping the standard library, `site-packages` and the dvc-dat checkout; a checkout is named by its `pyproject.toml` `[project].name`.

A sandboxed function lives under a mount: rows naming a dotted prefix, its repo and its root, `(db/mount/demo_game.etl, db/root, demo_game/etl)` with `db/repo` beside it. Each call runs in a fresh process forked from a warm `python -I` server, one per environment, which holds only the ledger's machinery (no mounted module, no CUDA); a finder first on `sys.meta_path` serves the mounted prefixes from their roots, so every run loads, and records, exactly what it uses. The child refuses what it cannot trace: `UnmountedImport`, `UntracedRead`, `ConfinedWrite`, `ConfinedNetwork`. An incomplete mount table is therefore a crash rather than a silently wider trace.



## Evaluation and the trace
`run` is a memo. It looks up every entry at the top whose `db/fn` (the dotted name) and `db/keys` (the bound keys, defaults included, as canonical JSON) match, newest seal first, and hands back the first whose trace holds at the revision asked. A miss runs the body with a recording `Rev`, then seals the result in a transaction `by="eval:<name>"` under a subject hashing the function, keys, trace, preds and `db/value` text. `memo=False` runs without sealing; `memo="get"` looks up and never runs.

| trace item | value | holds when |
| --- | --- | --- |
| `fn` | `db/fn/<name>/<hash>` | the name resolves to the same subject |
| `code/<repo>` | `<version>+<commit8>` | the environment is at that commit |
| `platform` | the environment's | the environment is the same |
| `<subject> <predicate>` | the held object | the same object is held |
| `<name> db/alias` | `ref:<class>:<hash>` | the alias names those bytes |
| `ref:<class>:<hash>` | the same text | always |
| `eval:<name>{keys}` | the result's `ref:` | the lookup yields that hash |
| `salt` | the mount's `db/salt` | the mount has that salt |
| `q:{...}` | the sorted refs it answered | the query answers the same |

A value input is named by its bytes, so identical inputs are the same input. A correction to a row a function read makes its result stale, and the next ask re-derives it. A `code/<repo>` `commit` row pins what a version means. A sandboxed eval runs at HEAD, clean or dirty, and its `fn` item holds the bytes of every module the run loaded, third-party ones included: one changed byte in any of them is a different value, at any revision, whatever commit it names. A base eval runs at any clean commit and its entry holds at the commit it ran at. `clean=True` asks for a clean checkout at the revision's commit in either mode. `matches` and `diff` consult the memo and never run anything.



## The db/ vocabulary
Every predicate the system writes or interprets is `db/...`; everything bare is the user's. The ledger's configuration is ordinary rows written by ordinary transactions, so a declared index, cardinality or mount has a revision and a history like any fact.

| subject | what it holds |
| --- | --- |
| `db` | `version`, the name of a whole state; `db/format` |
| `db/tx/<rev>` | `db/by`, `db/time`, the transaction's keywords |
| `db/pred/<name>` | `db/cardinality`, `db/index`, `db/type`, `db/doc` |
| `db/fn/<name>/<hash>` | `db/name`, `db/module`, `db/sha`, `db/modules`, `db/mounts`, `db/mode`, `db/returns` |
| `db/mount/<prefix>` | `db/repo`, `db/root`, `db/salt` |
| `db/kind/<dotted>` | `db/moved`: a renamed class |

A `(db/pred/<p>, db/index, true)` row builds a partial SQL index on `<p>` in the transaction that commits it. A release is a `bump` of `db`'s own `version`, and `ledger.at("3.2.0")` reads that moment.



## Storage
The quads live in one table, `quads(rev, ord, subject, predicate, object, added)`, keyed by `(rev, ord)` and indexed on `(subject, predicate, rev)` and `(predicate, object, rev)`: in `ledger.db` (SQLite, WAL mode) for a folder ledger, in a Postgres schema for a DSN ledger (`pip install 'dvc_dat[pg]'`). The object is a tagged string, `str:`, `json:` or `ref:<class>:<hash>[:<subject>]`, so a row reads without a schema.

The art store holds bytes by sha256 at `sha256/<2>/<hex>`, write-once, so the same bytes are stored once however many subjects point at them. A value's parts enter by `put_path` (a hardlink on the same filesystem, else a streamed copy checked against the hash) and leave by `get_to`. A stored `Dat`'s files and its materialised folder under `art/dats/` share inodes. The ledger's art store and the dat manager's `art/` are separate folders keyed the same way.



## Concurrency
One writer at a time: a transaction takes the write lock only at commit, and its revision is `MAX(rev) + 1` under that lock. `lock=<seconds>` holds the lock for the whole body when a read must not go stale before the write. Readers take no lock; a `Rev` is a snapshot. Two processes missing on one memo key both run and both seal: identical bytes and trace are one subject, the second dropped at commit; different bytes are two entries, both kept, which is the evidence a nondeterminism check needs. The load harness under `tests/load/` checks these invariants across processes on SQLite and Postgres; its measurements are in [store](store.md).




# BRIEF

- Written from `dvc_dat/ledger/*.py` at v2.18.0. Every name here must exist in the code; re-read the code, not this page, before changing a signature.
- The per-file pages beside this one are the internals and the full refusal lists; this page is the caller's interface. When a public signature changes, change both.
- The figure is hand-written SVG; edit it directly.
