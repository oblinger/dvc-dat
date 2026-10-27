---
description: "The ledger half of dvc_dat: quads read as of a revision, values stored by content, value functions evaluated with their dependencies traced. Source: `dvc_dat/ledger/`."
---
:>> [DAT](../../DAT%20Track/DAT.md) → [DAT doc Modules Ledger](ha://p/DAT%20doc%20Modules%20Ledger) 
# DAT Ledger
The ledger is a project's history: every fact a quad `(rev, subject, predicate, object)`, every read a frozen view as of one revision, every value stored by its content and found by its preds.

![DAT Ledger](DAT%20Ledger.svg) 

**Classes:** [Ledger](#Ledger%20Interface) · [Rev](#Rev%20Interface) · [Ref](#Ref%20Interface) · [Row](#Row%20Interface) · [Transaction](#Transaction%20Interface) · [Value](#Value%20Interface) · [Value.Blob](#Value.Blob%20Interface) · [Value.Table](#Value.Table%20Interface) · [Dat](#Dat%20Interface) · [Fn](#Fn%20Interface) · [module functions](#dvc_dat.ledger%20Interface) 
**Topics:** [Ledger Semantics](#Ledger%20Semantics) · [Execution Semantics](#Execution%20Semantics) · [Value Provenance](#Value%20Provenance) 

| Methods     |                                                                                                                                                                                                                                                                                                            |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ledger      | [path](#^path), [at](#^at), [transaction](#^transaction), [close](#^close)                                                                                                                                                                                                                                 |
| Rev         | [id](#^id), [ledger](#^rev-ledger), [tx](#^tx), [`[]`](#^--getitem--), [get](#^get), [in](#^--contains--), [all](#^all), [rows](#^rows), [refs](#^refs), [values](#^values), [value](#^value), [select](#^select), [load](#^load), [resolve](#^resolve), [run](#^run)                                                      |
| Ref         | [rev](#^rev), [subject](#^subject), [name](#^name), [aliases](#^aliases), [hash](#^hash), [type](#^type), [preds](#^preds), [sealed_at](#^sealed-at), [load](#^ref-load)                                                                                                                                   |
| Row         | [rev](#^row-rev), [subject](#^row-subject), [predicate](#^predicate), [object](#^object), [added](#^added)                                                                                                                                                                                                 |
| Transaction | [tx](#^transaction-tx), [previous_rev](#^previous-rev), [rev](#^transaction-rev), [add](#^add), [`[]=`](#^--setitem--), [remove](#^remove), [`del []`](#^--delitem--)                                                                                                                                       |
| Value       | [preds](#^value-preds), [subject](#^value-subject), [rev](#^value-rev), [sealed](#^sealed), [hash](#^value-hash), [dependencies](#^dependencies), [Dependencies](#^value-dependencies), [encode](#^encode), [decode](#^decode), [seal](#^seal), [same_as](#^same-as), [matches](#^matches), [diff](#^diff) |
| Value.Blob  | [obj](#^obj)                                                                                                                                                                                                                                                                                               |
| Value.Table | [table](#^table-table)                                                                                                                                                                                                                                                                                     |
| Dat         | [path](#^dat-path), [preds](#^dat-preds), [sealed_at_path](#^sealed-at-path), [decode](#^dat-decode), [kind_ok](#^kind-ok), [spec_kind](#^spec-kind)                                                                                                                                                       |
| Fn          | [name](#^fn-name), [module](#^module), [code](#^fn-code), [mount](#^mount), [env](#^env), [signature](#^signature), [()](#^--call--)                                                                                                                                                                       |


This page is the package `dvc_dat.ledger` as a caller sees it: the figure above, each public class and its members, then the rules that span them. The dat half, a folder that is its own recipe, is [DAT Dat](../DAT%20Dat.md); how the two halves meet is the [architecture](../../DAT%20Architecture.md). The four notebooks run it end to end: [ledger-triples](../../DAT%20Demos/ledger-triples.ipynb), [ledger-values](../../DAT%20Demos/ledger-values.ipynb), [ledger-dats](../../DAT%20Demos/ledger-dats.ipynb), [ledger-just](../../DAT%20Demos/ledger-just.ipynb).



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

**transaction**`(*, by: str | dict, lock: float | None = None, **preds) -> Transaction`
    A write set, used only as `with L.transaction(by=...) as t:`. `by` names the writer and is required: a non-empty `str` (`"human:dan"`), or a non-empty JSON `dict` for a structured identity (`{"host": ..., "user": ..., "admins": [...]}`), stored under the `json:` tag and read back as the dict, so no identity is parsed out of a string (DAT 1024); anything else is `TypeError`. The `eval:` prefix convention is a string's alone; `lock=` holds the write lock for the whole body, at most that many seconds. Each extra keyword is a `str` or a JSON document and lands as a row on the transaction's `db/tx/<rev>` subject beside `db/by` and `db/time`. See [Revisions and transactions](#Revisions%20and%20transactions). ^transaction

**close**`() -> None`
    Close the handle's database connections in every thread; a later read or write reopens one. ^close



## Rev Interface
A frozen view of the ledger as of one revision, made by `Ledger.at`, never by hand. Every read is bounded by `id`, so a `Rev` gives the same answer forever. Row reads fold the rows by each predicate's cardinality ([The fold](#The%20fold)); `rows` takes the same pattern and walks history unfolded; subject reads (`refs`, `values`, `value`, `select`) treat the store as a table whose rows are subjects. A stored reference comes back as an unloaded `Ref`. A `Rev` handed to a value function's body also traces every read into its result's dependencies. Ordered and equal by `id` within one ledger.

| Rev                            |                                                            |
| ------------------------------ | ---------------------------------------------------------- |
| [id](#^id)                     | The revision number                                        |
| [ledger](#^rev-ledger)         | The ledger this view reads                                 |
| [tx](#^tx)                     | The subject carrying this revision's provenance            |
| [__getitem__](#^--getitem--)   | A record, an object, or when a triple was added            |
| [get](#^get)                   | __getitem__ with a default                                 |
| [__contains__](#^--contains--) | Tests whether a triple is currently held                   |
| [all](#^all)                   | Returns ordered pattern-matched values with folding        |
| [rows](#^rows)                 | Returns ordered pattern-matched rows without folding       |
| [refs](#^refs)                 | Returns a Ref to every subject matching a query            |
| [values](#^values)             | Returns the values whose subjects match a query            |
| [value](#^value)               | Same as values, but requires exactly one match             |
| [select](#^select)             | Returns chosen preds of matching values, without loading them |
| [load](#^load)                 | One value by subject or alias                              |
| [resolve](#^resolve)           | What a dotted name denotes here: a spec, an `Fn`, an object |
| [run](#^run)                   | Run a value function or a dat, memoised (`just run`)       |

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

**__contains__**`(triple) -> bool`
    `(s, p, o) in rev`: whether the triple is held at this revision, by the same fold. ^--contains--

**all**`(*pattern, since: Rev | None = None) -> list`
    Every currently held match of the pattern (the fold), binding the open positions, in revision order; a prefix glob `"game/*"` binds the subject. Not checked against `db/type`. More than three positions is `TypeError`; a `*` anywhere but the end is `ValueError`. ^all

**rows**`(*pattern, since: Rev | None = None) -> list[Row]`
    Every row matching the pattern at or before this revision, or in `(since, id]`, removes included, unfolded, in `(rev, ord)` order: `all`'s pattern without the fold. No pattern is the ledger as stored; `rows(s, p, o)` with `added` true says when a triple was set. ^rows

**refs**`(*, s=None, kind=None, fn=None, where=None, one=False, since=None, **preds) -> list[Ref] | Ref`
    Returns a `Ref` to every subject matching the query, sealed value or not. `refs`, `values` and `value` take the same query and pick the same subjects: a bare keyword names a pred (any member of a `many` pred); `kind=` a `Value` class or dotted name, following `db/moved` renames; `fn=` the producing function's dotted name; `where={p: o}` any predicate, `None` meaning any object; `s` an exact subject or a prefix glob; `since` keeps rows in `(since, id]`. `one=True` returns the single match: none is `KeyError`, several `Multiple`. A dotted predicate neither declared nor on any row is `Unindexed`. ^refs

**values**`(*, s=None, kind=None, fn=None, where=None, since=None, **preds) -> list[Value]`
    Returns the values whose subjects match the query, loaded: the same query as `refs`, keeping only subjects that hold a sealed value. ^values

**value**`(*, s=None, kind=None, fn=None, where=None, since=None, **preds) -> Value`
    Same as `values`, but requires exactly one match: none is `KeyError`, several `Multiple`. ^value

**select**`(keys: tuple[str, ...], *, s=None, kind=None, fn=None, where=None, one=False, since=None, **preds) -> list[tuple] | tuple`
    Returns the chosen preds of every matching subject without loading the value: the same query as `refs`, and per subject a tuple of its objects for `keys`, `None` where absent, a list for a `many` predicate. `rev.select(("home", "away"), s="game/*")` reads two preds of every game from the ledger alone, where `values` would fetch each value's bytes. `keys` not a non-empty tuple is `TypeError`; `one=True` as in `refs`. ^select

**load**`(subject: str) -> Value`
    `Ref(self, subject).load()`: the value under a subject or an alias, decoded, its provenance restored. ^load

**resolve**`(name: str) -> dict | Fn | Any`
    What the dotted `name` denotes at this revision, through the ledger's namespace (DAT 1046). The `db/mount/<prefix>` rows as of the revision are walked longest prefix first; under a mount the name is a path in the mount's tree, in the checkout discovery reports for its `db/repo` (none is `NotEvaluated`): a `.yaml`/`.yml`/`.json` file is read and comes back a dict (a dotted tail below the file walks into it), a function in a `.py` file comes back its [`Fn`](#Fn%20Interface), read off the file and never imported in this process, and a module-level literal (`TABLE = {...}`) its value. A mounted prefix owns its names: one nothing answers to is `ImportError`, a file and a module answering to one name `KeyError`. A name under no mount is imported (unsandboxed), a `@ledger_fn` coming back its `Fn` and anything else as itself. An `Fn`'s `kind` is read off the function: `"ledger"` for a `@ledger_fn`, `"dat"` for an undecorated one, a dat's run function, which runs only through a spec ([`run`](#^run)). In a project whose `.datconfig.yaml` names a ledger, `Dat.manager.do` is this lookup at the head (a `LedgerDo`: the `Do` interface, `mount` refused); inside a sandboxed dat body it is this lookup at the run's revision (DAT 1047). See [Execution Semantics](#Execution%20Semantics). ^resolve

**run**`(target, /, *, seal=<this rev's ledger>, clean=False, path=None, **kwargs) -> Value | None`
    The result of `target`, handing back an already-sealed result instead of running when one from the same code and memo key still holds at this revision; the API form of `just run TARGET KEY=VALUE` (DAT 1046). `target` is a dotted name, resolved as by [`resolve`](#^resolve), or a spec dict. A ledger function's name runs it with `kwargs` as its keys, which are its memo key. Anything else is a dat: a spec, a spec's name, or a dat's run function's name (the spec `{dat: {do: <name>}}`), `kwargs` updating the spec's `dat.kwargs`. A dat's memo key, `db/keys`, is the spec with its `dat.base` merged, the kwargs merged, `dat.kind` set and every `{}` expanded once (dotted names through the ledger's namespace), `dat.name` removed; `db/fn` is the run function's dotted name and `db/returns` the dat's class. A miss creates the dat in a work folder and runs it there (the machinery of `Dat.manager.run`), then seals the folder the run function saved; a run that leaves its dat open is `ValueError`. Where a miss runs is the function's: under a `db/mount`, in the sandbox worker, imported there from the mounted tree and never in the calling process, confined, its code the modules it loaded, provenance `eval:sandbox`, no `code/<repo>` item (a dat's run function gets the caller's dat folders and art folder, its `Dat.manager.do` a `LedgerDo` at this revision); installed, in this process, its code the static closure and the `code/<repo>` commit, which needs a clean checkout (`NotEvaluated`), provenance `eval:unsandboxed`. `seal` says where the result goes, as on [`Fn.__call__`](#^--call--): by default, the hit, else run and save it as the memo entry; `seal=False` runs and keeps nothing; `seal=True` runs and seals locally; `seal=t` saves into an open transaction; `seal="get"` returns the saved result or `None` and never runs ([Running](#Running)). `clean=True` requires the function's checkout to be clean (no uncommitted changes, and the HEAD at the commit of the latest clean run this revision records, its `db/repo/<repo>` row), else it raises `NotClean`; by default a sandboxed function runs at HEAD, clean or dirty. `path` names the result; a dat's name is `path=`, else its spec's `dat.name` template (`{unique}` counting up in the data folder), else `anonymous/Dat`, and a hit is handed back at its name, its folder a view there. A spec naming a `@ledger_fn` in `dat.do` is `TypeError`; a target that is neither a `str` nor a dict is `TypeError`. The dat's recorded dependencies that are names on the ledger enter its trace as alias reads. See [Execution Semantics](#Execution%20Semantics) and [Value Provenance](#Value%20Provenance). ^run



## Ref Interface
A reference to one value at one moment, named without fetching a byte: the subject and the revision, nothing loaded until `load`. Making one resolves the `db/alias` chain from `name`; a cycle or more than 8 hops is `AliasLoop`. A `Ref` is frozen, equal and hashed by subject, and does not pickle (it is bound to an open ledger). Its `repr` is `<Ref label>` and its `str` the bare label: the value's name (the alias naming it written latest), else `#` + the hash's first 8 hex (DAT 1036). Made from a recording `Rev`, it traces its reads into the dependencies like the `Rev` would.

| Ref                      |                                        |
| ------------------------ | -------------------------------------- |
| [Ref](#^ref)             | Name a value at a revision             |
| [rev](#^rev)             | The revision the reference was made at |
| [subject](#^subject)     | The subject, alias resolved            |
| [name](#^name)           | The print name currently associated with the value |
| [aliases](#^aliases)     | Every alias naming the subject         |
| [hash](#^hash)           | The sha256 of the value's bytes        |
| [type](#^type)           | The class that decodes it              |
| [preds](#^preds)         | The subject's user rows                |
| [sealed_at](#^sealed-at) | The revision it was sealed into the ledger |
| [load](#^ref-load)       | Fetch, decode and restore the value    |

**Ref**`(rev: Rev, name: str)`
    A reference to whatever `name` (a subject or an alias) names at `rev`. `rev` not a `Rev` or `name` not a non-empty `str` is `TypeError`. ^ref

**rev**`: Rev`
    The revision this reference reads through: the snapshot it was made from, so every answer it gives is as of that revision. ^rev

**subject**`: str | None`
    The subject after the alias chain. For a stored hint-less reference, the latest entry holding those bytes as of `rev`. ^subject

**name**`: str`
    The print name currently associated with the value: its alias at the head (the latest written), else `#` + the hash's first 8 hex; `str(ref)`. Unique one way: a name points at one value at a time, and re-pointing it moves it to another value; a value may carry several names (`aliases`). `subject` is what the reference resolved to. ^name

**aliases**`: list[str]`
    Every name aliasing the subject as of `rev`. ^aliases

**hash**`: str | None`
    The 64-hex sha256 of the value's bytes; `None` when the subject holds no value. Byte identity of two refs is `a.hash == b.hash`. ^hash

**type**`: type | None`
    The `Value` subclass that decodes the bytes, following `db/moved` renames; a class that does not import is `ImportError`. ^type

**preds**`: FrozenPreds`
    The subject's non-`db/` rows, annotations included; a typed pred is an unloaded `Ref`. ^preds

**sealed_at**`: Rev | None`
    The revision the value was sealed into the ledger, its `db/value` row's: at or before `rev`, since a reference made later can point at a value sealed earlier. `None` while the subject holds no value. ^sealed-at

**load**`() -> Value`
    Fetch the bytes from the art store, decode them by `type`, and restore `subject`, `rev` (the sealing revision), `dependencies` and `preds`. Cached per `(subject, rev, name)` on the `Ledger`; a cached `Dat` is handed back only while its folder is still there and the same folder. A `decode` that accepts `name=` is passed the alias the `Ref` was made by, so a `Dat` loaded by an alias lands under `art/dats/<alias>/`. No value is `KeyError`; a `decode` returning a non-`Value` is `TypeError`; a `Dat` whose `_spec_` names a `dat.kind` the row's class does not accept is `TypeError`. ^ref-load



## Row Interface
A named tuple encoding a single row in the ledger: revision, subject, predicate, object, and an added/removed bit. `rows()` returns them; `str(row)` is one aligned line: revision, `+` or `-`, subject, predicate, object.

| Row                      |                                    |
| ------------------------ | ---------------------------------- |
| [rev](#^row-rev)         | The revision that wrote it         |
| [subject](#^row-subject) | The subject                        |
| [predicate](#^predicate) | The predicate                      |
| [object](#^object)       | The object, decoded                |
| [added](#^added)         | True/False indicates added/removed |

**rev**`: Rev`
    The revision that wrote the row. ^row-rev

**subject**`: str`
    The row's subject. ^row-subject

**predicate**`: str`
    The row's predicate. ^predicate

**object**`: str | dict | list | Ref`
    The row's object, decoded from its tagged text ([Storage](#Storage)). ^object

**added**`: bool`
    `True` for an add, `False` for a remove. ^added



## Transaction Interface
The write set of one `with L.transaction(...) as t:` block; it becomes exactly one revision on exit, or nothing. `add` and `remove` append rows and read nothing; `v.seal(t)` seals a value into it; the bracket forms are helpers over `add` and `remove`. A transaction has a revision's read operators through `previous_rev`, bound to the previous revision; it exists only under `lock=`, because an unlocked transaction has no well-defined previous revision (another writer may commit between open and exit). The helpers that read and then write (`t[s] = {...}`, `del`, `bump`) read through it, so they need `lock=`; unlocked they raise `Unlocked` and write nothing. Whatever must see the transaction's own rows is checked at commit, inside the write lock. Entered once; a verb used outside the block is `RuntimeError`.

| Transaction | |
| --- | --- |
| [tx](#^transaction-tx) | A placeholder for this revision's tx subject |
| [previous_rev](#^previous-rev) | The previous revision, the top while `lock=` holds |
| [rev](#^transaction-rev) | The revision the exit wrote |
| [add](#^add) | Append an add row |
| [__setitem__](#^--setitem--) | Assign a predicate, or a whole record |
| [remove](#^remove) | Append a remove row |
| [__delitem__](#^--delitem--) | Retract a predicate, or every user predicate |

**tx**`: str`
    A placeholder subject, rewritten to `db/tx/<rev>` at commit wherever it appears as a subject or a `str` object, so the body can write rows about its own transaction. ^transaction-tx

**previous_rev**`: Rev`
    The previous revision, with every read operator a revision has: the top as it stands while `lock=` holds, so a write built on what it reads is built on current data and no other writer commits in between; the revision written is `previous_rev.id + 1`. Without `lock=` it is `Unlocked`: another writer may commit between open and exit, so there is no well-defined previous revision. `RuntimeError` before entry. ^previous-rev

**rev**`: Rev`
    The revision written: the state after this transaction, so it exists only once committed; `RuntimeError` before. Under `lock=` the number it will be is `previous_rev.id + 1`. ^transaction-rev

**add**`(subject: str, predicate: str, object) -> None`
    One add row. `object` is a `str`, a JSON `dict` or `list`, or a `Ref` to a sealed value; a `Value` is `TypeError` naming `seal`; a bare number, bool or `None` is `TypeError` (a number is its string). `predicate == "db/value"` is `TypeError`: only a seal writes it. ^add

**__setitem__**`(key, value) -> None`
    `t[s, p] = o` is `add` on a `one` predicate and needs no lock; a `many` or `db/` predicate is `TypeError`. `t[s] = {...}` makes the subject's user rows equal to the dict at the next revision, reading what the subject holds through `previous_rev`, so it needs `lock=` (`Unlocked` without); `t[s] = t.previous_rev[s]` writes nothing. Brackets take exact subjects; a glob is `TypeError`. ^--setitem--

**remove**`(subject: str, predicate: str, object) -> None`
    One remove row: the object leaves the set of a `many` predicate, or, when it is the held object of a `one` predicate, leaves nothing held. ^remove

**__delitem__**`(key) -> None`
    `del t[s, p]` retracts what `p` holds; `del t[s]` retracts every user predicate; `db/` rows survive, and a `db/` predicate is `TypeError`. Both read through `previous_rev`, so they need `lock=` (`Unlocked` without). ^--delitem--



## Value Interface
The object itself with its provenance on it: what `run` returns, what `seal` stores and what `Ref.load` restores. A subclass says how it becomes bytes (`encode`) and back (`decode`); `@ledger_class(preds=...)` names the preds its values may carry. Until sealed, `preds` is a plain dict filled by whoever builds the value; the seal freezes it and fixes the identity. A subclass's `__init__` need not call `super().__init__`.

**What a value prints as** (DAT 1036). Python's unreadable-object form: `repr` (a bare notebook cell) is `<Type label>`, `str` (`print`, f-strings) the bare label. The label is the value's name at the head, else `#` + the hash's first 8 hex, like a short git sha; a draft has no label. A `Ref` prints the same label as `<Ref …>`; a `Fn` prints its dotted name `@` its code's version (`<Fn plane.measure.length@2.7.1>`, `str` `plane.measure.length@2.7.1`), and its `Code` the unit `@` the same version (`<Code plane@2.7.1>`) (DAT 1037).

```python
v                    # <Video video/G1>     saved, named
v                    # <Video #2db69ce1>    saved, unnamed
str(v)               # 'video/G1'  /  '#2db69ce1'
v                    # <Clip sealed #2db69ce1>   v.seal(), saved nowhere
v                    # <Clip draft>         unsealed; str the same
Ref(rev, "video/G1") # <Ref video/G1>
f                    # <Fn plane.measure.length@2.7.1>
str(f)               # 'plane.measure.length@2.7.1'
f.code               # <Code plane@2.7.1>
```

| Value                      |                                                   |
| -------------------------- | ------------------------------------------------- |
| [preds](#^value-preds)     | The strings the value is found by                 |
| [subject](#^value-subject) | Its ledger subject once saved                     |
| [rev](#^value-rev)         | The revision that saved it                        |
| [sealed](#^sealed)         | The seal's moment, or None while unsealed         |
| [hash](#^value-hash)       | The sha256 of its encoding                        |
| [dependencies](#^dependencies) | What producing it read                       |
| [Dependencies](#^value-dependencies) | The type of `dependencies`             |
| [encode](#^encode)         | Abstract: the bytes to store, every subclass implements it |
| [decode](#^decode)         | Abstract: the object from its bytes, every subclass implements it |
| [seal](#^seal)             | Fix its identity, and save it when given a ledger |
| [same_as](#^same-as)       | Equal bytes                                       |
| [matches](#^matches)       | Whether its dependencies still hold at a revision |
| [diff](#^diff)             | The dependency items that differ from another value's |

**preds**`: dict | FrozenPreds`
    A `dict` while unsealed, assignable as a whole; a `FrozenPreds` once sealed, whose every mutator is `TypeError`. Each pred is a `str`, number, bool, list, `Value` or `Ref`, and its name must be declared by the class's `@ledger_class` (`Undeclared` at the seal). ^value-preds

**subject**`: str | None`
    The 64-hex subject the value was saved under; `None` until saved, including when sealed by `seal()` alone. ^value-subject

**rev**`: Rev | None`
    The revision that saved the value; set at commit or by `load`. ^value-rev

**sealed**`: str | None`
    The moment the identity was fixed, UTC `YYYY-MM-DDTHH:MM:SSZ`, by `seal()` (saved nowhere yet, `subject` `None`) or by a save; `None` while unsealed, so `if v.sealed:` reads as before. A time rather than a revision because a seal can precede any ledger; the revision is `rev`, set at the save. ^sealed

**hash**`: str`
    The hex sha256 of `encode()`, cached once sealed; after a save, the stored bytes' hash whatever the live object holds. ^value-hash

**dependencies**`: Mapping[str, str]`
    Item name to version or hash: what producing the value read. Empty for a hand-built value until saved; a run's result carries its trace here at every `seal=` level. See [Value Provenance](#Value%20Provenance). ^dependencies

**Dependencies**`: Mapping[str, str]` (class attribute)
    The type of `dependencies`, for annotations. ^value-dependencies

**encode**`() -> bytes`
    Abstract: every `Value` subclass must implement it (`NotImplementedError` otherwise). The bytes to store. Two calls must return the same bytes: the seal refuses a class whose encoding is not deterministic. ^encode

**decode**`(data: bytes, store: ArtStore) -> Value` (classmethod)
    Abstract: every `Value` subclass must implement it (`NotImplementedError` otherwise). The object from its bytes. A `decode` that also accepts `name=` is passed the alias the value is loaded by, `None` when loaded by its subject. ^decode

**seal**`(to=True, *, keep=False, deps=(), name=None, provenance=None, by=None) -> str`
    `to` takes what a run's `seal=` takes, so `f(seal=x)` and a later `v.seal(x)` end in one place. `v.seal()`, the same as `v.seal(True)`, fixes the identity and writes no ledger: preds freeze, and the hash, `deps`, `provenance`, the environment and the time go into a seal record in the kept folder; it returns the hash. `keep=True` also copies the bytes into the kept cache, so the source may change. `v.seal(t)` saves into an open transaction and returns the subject; `v.seal(L)` commits a one-value transaction of its own, written `by`, a `str` or a JSON `dict` as on [`transaction`](#^transaction) (default the provenance, else `seal`). `name=` writes `(alias, db/alias, subject)` beside it. A run's result (`seal=False` or `True`) carries its trace: `v.seal(t)` or `v.seal(L)` writes the memo entry the run would have written, so the next identical call hits, after the code check of [Running](#Running) (`NotEvaluated`); `deps=` and `provenance=` on it are `TypeError`. `v.seal(False)` and `v.seal("get")` are `TypeError`: nothing to do to an object. A provenance beginning `eval:` is `ValueError`; a second seal is `ValueError`. See [Versioning](#Versioning). ^seal

**same_as**`(other: Value | None) -> bool`
    `self.hash == other.hash`; `False` for `None`. ^same-as

**matches**`(rev: Rev) -> bool`
    Whether every dependency item holds at `rev`: the memo's hit test. Consults the ledger only; never runs anything. ^matches

**diff**`(other: Value) -> dict[str, tuple]`
    The dependency items whose values differ, item to `(mine, theirs)`, `None` where one lacks the item. ^diff



## Value.Blob Interface
A `Value` holding any Python object, stored with pickle (protocol 4). Declares no preds.

| Value.Blob           |                               |
| -------------------- | ----------------------------- |
| [Value.Blob](#^blob) | Constructor to wrap an object |
| [obj](#^obj)         | The object                    |

**Value.Blob**`(obj, *, name=None)`
    A value whose bytes are `obj` pickled. A value function whose return annotation is not a `Value` subclass has its result wrapped in one. ^blob

**obj**`: Any`
    The wrapped object. ^obj



## Value.Table Interface
A `Value` holding a table, encoded as parquet. A pandas `DataFrame` is converted on encode; a decoded `Value.Table` holds a `pyarrow.Table`. It exists beside `Value.Blob` because the encoding is the identity: pickle bytes change with the Python, pandas and pyarrow versions and nothing outside Python reads them, while parquet encodes the same table the same way, stores it columnar and compact, and any tool that reads parquet can read it from the art store.

| Value.Table            |                             |
| ---------------------- | --------------------------- |
| [Value.Table](#^table) | Constructor to wrap a table |
| [table](#^table-table) | The table                   |

**Value.Table**`(table, *, name=None)`
    A value whose bytes are `table` as parquet; `table` is a `pyarrow.Table` or a pandas `DataFrame`. ^table

**table**`: pyarrow.Table | pandas.DataFrame`
    The wrapped table; a `pyarrow.Table` after a load. ^table-table



## Dat Interface
`dvc_dat.ledger.Dat` is `dvc_dat.Dat`, one class (DAT 1038): a dat, the folder that is its own recipe ([DAT Dat](../DAT%20Dat.md)), is a `Value` whose bytes are the folder. It encodes as its content manifest, `{"files": {relpath: sha256}}`, and its files are its parts, streamed into the art store one at a time, so memory is bounded by the manifest, not the folder. Every file in the folder is hashed (`__pycache__` skipped), `_spec_.yaml`, `_result_.yaml` and `run/` included; each in 1 MiB blocks, the per-file hashes cached on the object, keyed by size, mtime and inode, so only a changed file is hashed again. The `db/value` row's kind and the folder's `dat.kind` are the same dotted name, `dvc_dat.core.Dat` or the subclass. A dat made by `Dat.create` or `Dat.manager.run` seals with no subclass once saved: `dat.seal(t, name="table/12")` stores its files and writes its row, and `rev.load("table/12")` returns a `Dat` whose `get_spec()`, `get_results()` and `get_path()` read the rebuilt folder. A folder whose `_spec_` names a `dat.kind` and was never saved (standing `open`) is `ValueError` naming `dat.save()`; a folder with no spec is a plain folder value.

| Dat | |
| --- | --- |
| [Dat](#^dat) | The dat in a folder |
| [path](#^dat-path) | The folder |
| [preds](#^dat-preds) | The folder's facts, under the hand-written ones |
| [sealed_at_path](#^sealed-at-path) | Reopen a folder sealed in another process |
| [decode](#^dat-decode) | Materialise the folder from its manifest |
| [kind_ok](#^kind-ok) | Whether a folder's dat.kind loads as this class |
| [spec_kind](#^spec-kind) | The dat.kind a folder's spec names |

**Dat**`(path, *, name: str | None = None)`
    The dat already in the folder `path`: its spec and results read from `_spec_.yaml` and `_result_.yaml` (each `{}` when absent); a value whose bytes are the folder's manifest. `name` is the name a save gives it. `Dat.create(spec=...)` and `Dat.load(name)` make one through the dat manager ([DAT Class API](../../DAT%20Design/DAT%20API/DAT%20Class%20API.md)). ^dat

**path**`: Path`
    The folder, `get_path()` as a `Path`. After a save it is the stored copy under `art/dats/<16 hex>/`, or `art/dats/<name>/` when named; after a load by an alias, `art/dats/<alias>/`. Those files are hardlinks into the art store where the filesystem allows: write a new folder and seal it, never edit one in place. ^dat-path

**preds**`: dict`
    Unsealed: the scalar entries of the spec's `dat.kwargs`, then the scalar top-level entries of `_result_.yaml` other than `dat:` (a result entry wins a clash), read from the folder on every access, under every pred written by hand, which wins. Sealed: the read-only mapping the seal fixed. The names are the class's `@ledger_class(preds=...)` plus the folder's own; the `dat:` record of the results (dependencies, standing, sha256) is never a pred. ^dat-preds

**sealed_at_path**`(path, *, name: str | None = None) -> Dat | None` (classmethod)
    The last seal record of the folder `path` not saved since, reopened in this process as the sealing process left it; `None` with no record. `v.seal(t)` on it saves exactly what the sealing process would have saved: the same subject, `SealBroken` on a changed byte unless kept. The record's class must be a subclass of the class called on, else `TypeError`. ^sealed-at-path

**decode**`(data: bytes, store: ArtStore, *, name: str | None = None) -> Dat` (classmethod)
    The folder of a manifest, placed under `<art>/dats/<name>/` when loaded by a name, else `<art>/dats/<first 16 hex of the manifest hash>/`; each file is placed by `ArtStore.get_to`. A named folder holding other content (the alias was re-pointed) is replaced. The dat's spec and results are read from the placed folder. ^dat-decode

**kind_ok**`(kind: str) -> bool` (classmethod)
    Whether a folder whose `_spec_` names `dat.kind` `kind` loads as this class, the class its `db/value` row names. The default accepts this class or a subclass, by dotted name (or a bare name written before 2.3); a subclass widens it. ^kind-ok

**spec_kind**`(path: Path) -> str | None` (static)
    The `dat.kind` the folder's `_spec_.yaml` (or `_spec_.json`) names, if any. ^spec-kind



## Fn Interface
A value function resolved at one revision: a frozen dataclass made by `Rev.resolve`, never by hand. Calling it is `run`. Only the snapshot has identity; a function is a name looked up inside it (DAT 1037): it has `name` and `code` and no `subject` or `sha`, since it is not on the timeline. It prints as `<Fn plane.measure.length@2.7.1>`, `str` `plane.measure.length@2.7.1`: the dotted name `@` its code's version. `code` says where the code comes from: installed in the ledger's own Python environment (imported in this process), or mounted from a checkout (`code.sandboxed`, run in a worker).

| Fn | |
| --- | --- |
| [name](#^fn-name) | The dotted name |
| [module](#^module) | The source file |
| [code](#^fn-code) | The code it is loaded from, at a version: the snapshot, which alone has identity |
| [mount](#^mount) | The mounted prefix, when sandboxed |
| [env](#^env) | The environment it resolved in |
| [signature](#^signature) | The keys it takes |
| [kind](#^fn-kind) | `"ledger"` or `"dat"`, read off the function |
| [__call__](#^--call--) | Evaluate: a memo hit, or run and send the result where `seal=` says |

**name**`: str`
    The dotted name it was resolved by. ^fn-name

**module**`: Path`
    The function's source file. ^module

**code**`: Code`
    The code the function is loaded from, at a version (DAT 1037): a `Code(Value)`, computed at `resolve`; a run writes its identity as the `db/code/<16 hex>` item, and the rest of it is not written to the ledger. Its name is `<unit>@<version>`: the unit is the mount prefix for mounted code (`plane`, `algs.ocr`) and the function's top-level package for installed code (`geometry`). Its identity is the bytes: `encode()` is the canonical `{"modules": relpath -> sha256, "mounts": <hash of the db/mount rows, or null>}`, `hash` its sha256, and `subject` `db/code/<16 hex>`, the first 16 of the hash (the 16 hex the memo key carried as `db/fn/<name>/<16 hex>` before); two functions in one snapshot share it, and any changed byte in a module makes a new one. Read-only properties describe it, fixed at load and not hashed: `sandboxed` (True for mounted code), `version` (the name after `@`), `modules` (the relpaths the loader walked: under the repo root when mounted, under the top-level package's parent when installed), `mounts` (`prefix -> {repo, root}`, empty when installed), `commit` (the checkout's at load, or `None`), `lock` (the git blob id of that checkout's `uv.lock`, or `None`) and `package` (the dotted root whose declared version `version` is, the unit, or `None` when the version came from a commit or the hash: the `<package>` of the `db/repo/<repo>/<package>` clock a clean run moves, DAT 1044). The version is read as a module attribute after import, never parsed from source, and a declared version counts only from a clean checkout (DAT 1043): when the checkout holding the code has modified tracked files, the version is `<commit 8>+dirty` whatever `__version__` says (mounted: the last commit touching the loaded files, else HEAD; installed: HEAD). Clean, mounted: the root package's `__version__` (imported in the worker); else the last commit touching the loaded files, 8 hex, `+dirty` when one differs from HEAD; else `#` + the first 8 hex of `hash`. Clean or outside any checkout (a wheel), installed: `__version__` on the top-level package; else the version of the distribution providing it; else the short commit (8 hex) of the checkout holding it; else `#` + 8 hex of `hash`. The version is a name for people over the hash, and the commit is a result's `code/<repo>` dependency item, so neither moves `subject`, the identity and the memo key. ^fn-code

**mount**`: str | None`
    The mounted prefix the name resolved under; `None` for installed code. ^mount

**env**`: Env`
    The environment the function resolved in: repos and commits, platform. ^env

**signature**`: inspect.Signature`
    The keys the function takes, without the leading `Rev` and without `path`. ^signature

**kind**`: str`
    `"ledger"` for a `@ledger_fn`: its keys are its memo key and it receives them. `"dat"` for an undecorated function, a dat's run function (DAT 1046): its memo key is the expanded spec, and it receives the dat made from that spec in its work folder; it runs only through a spec (`rev.run(spec)`, `rev.run(name, **kwargs)`), and a direct call is `TypeError`. A plain `Dat.manager.run` in a ledger project runs a mounted one in the calling process, nothing memoised. ^fn-kind

**__call__**`(*, seal=<the fn's ledger>, clean=False, path=None, kwargs=None, **keys) -> Value | None`
    `seal` is where the result goes ([Running](#Running)). A `Ledger` (by default the one the function was loaded from) hands back a memo hit, else runs the body and saves the result as the memo entry in a transaction of its own; an open `Transaction` on that ledger does the same into it, the value's subject fixed at once and its revision at commit; `False` runs and keeps nothing, the trace on the result; `True` runs and seals locally (`v.seal()`); `"get"` returns a hit or `None` and never runs. Another ledger, or anything else, is `ValueError`. With `seal=t`, `path=` must be relative: it is the name the entry is saved under. The control options are exactly `seal`, `clean`, `path` and `kwargs`, never keys and never hashed. Keys bind to the signature with defaults applied; `kwargs={...}` passes the whole key set instead, for a key named like a control option, and inline keys beside it are `TypeError`. `path=` names the result (relative to the data folder; a `Dat`'s folder is rebuilt there as a view; a hit under a new name takes it) or, absolute, makes the folder there and names nothing. An unsandboxed run needs the function's code in a clean git checkout, else `NotEvaluated`; a sandboxed run goes ahead at HEAD, clean or dirty. `clean=True` first requires the checkout clean and at the rev's `db/repo/<repo>` commit, else `NotClean`. A result that is not an instance of a `Value`-subclass return annotation is `TypeError`. ^--call--



## dvc_dat.ledger Interface
The package's other exports: two decorators, three helpers, and the exceptions. Every exception is a `LedgerError` and also the builtin it most resembles, so a caller catches either. `Env`, `Checkout` and `set_env_provider` are importable as the test suite's seam for the environment and are not part of the interface.

| dvc_dat.ledger | |
| --- | --- |
| [ledger_fn](#^ledger-fn) | Mark a function as a value function |
| [ledger_class](#^ledger-class) | Declare a Value class's pred names |
| [bump](#^bump) | Move a clock subject's version |
| [bump_source](#^bump-source) | Raise a module's `__version__` in its source |
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
| [Unlocked](#^unlocked) | `previous_rev` or a read-then-write helper without lock= |
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
    Reads `version` through `t.previous_rev` (`0.0.0` when absent), adds the next by `part`, and returns it. `minor` and `major` need `confirm(old, new)` to return `True`. A subject holding a `db/alias` is `TypeError`: a value's version is a pred, not a clock. A `db/repo/` subject is `TypeError` too: a code version lives in its source (`bump_source`), and the first clean run after it moves the `db/repo/<repo>/<package>` clock, which the ledger alone writes (DAT 1043, 1044). It needs `lock=`: unlocked it is `Unlocked` and writes nothing. ^bump

**bump_source**`(module: str, part: str = "patch", *, confirm=None) -> SourceBump`
    Raises a module's `__version__` by `part` in its source and returns `SourceBump(module, old, new, path, repo, package)`. `module` is a dotted name importable in this process; the version is the innermost on its dotted path, the module's own file then each enclosing package's `__init__.py`, the first holding one line `__version__ = "X.Y.Z"` (so `demo_game.etl`, a mount root declaring its own, finds `demo_game/etl/__init__.py`). One line is rewritten; nothing is committed and no ledger is touched. `minor` and `major` need `confirm(old, new)` to return `True`. A module that does not resolve is `ModuleNotFoundError`; no `__version__` line, or one not `MAJOR.MINOR.PATCH`, is `ValueError`, nothing written. `repo` is the checkout's name, `None` outside one; `package` is the dotted root whose file holds the version, the `<package>` of the `db/repo/<repo>/<package>` clock the next clean run moves. A mount name is reached by its dotted module name, not by `db/mount/<prefix>`. `just bump <module> [part]` is this call. ^bump-source

**attr**`(obj, path: str)`
    Walks a dotted path over mappings, sequences (integer steps) and attributes; `KeyError` at the first missing step, `TypeError` for an empty path. ^attr

**LedgerError**`(Exception)`
    No ledger found or opened, or the backend refused. ^ledgererror

**Multiple**`(LedgerError, LookupError)`
    `value`, `refs(one=True)` or `select(one=True)` matched several. ^multiple

**NotEvaluated**`(LedgerError, RuntimeError)`
    A run the environment cannot make: a mount whose repo has no checkout here, or (unsandboxed) code outside any git checkout or a dirty checkout. ^notevaluated

**NotClean**`(NotEvaluated)`
    A `clean=True` call whose checkout is dirty, or not at the commit the revision's `db/repo/<repo>` row names, or whose revision names none. ^notclean

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

**Unlocked**`(LedgerError, RuntimeError)`
    `t.previous_rev`, or a helper reading through it (`bump`, `t[s] = {...}`, `del t[s, p]`, `del t[s]`), in a transaction opened without `lock=`; nothing written. ^unlocked

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
The rows themselves: how triples are written, as revisions by transactions; how they are read, by the fold; which rows are the system's own; and where they live.

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

One `with` block is one revision: its rows land together on exit, in body order, followed by the `db/tx/<rev>` rows (`db/by`, `db/time`, and each keyword given `transaction()`), which a body that wrote nothing still writes. `db/by` is the writer as given: a `str` row, or a dict as one `json:` row in canonical JSON (sorted keys, compact), which `rev[rev.tx, "db/by"]` returns as the dict and `just history` prints as that canonical text. A ledger's first transaction also writes `(db, db/format, dvc-dat-ledger/1)`. An exception in the body, a refusal at commit, or `LockTimeout` writes nothing, unseals every value the body sealed and removes the bytes it stored. Revisions are dense and monotonic, so a reader never sees half a transaction.


## The fold
A read turns the rows at or before its revision into what they hold, by each predicate's cardinality. Under `one`, the default, the latest add wins, so `add` is assignment; a remove of the held object leaves nothing held. Under `many`, the held objects are the set added and not since removed, each at its earliest add. Cardinality is itself a row, `(db/pred/officials, db/cardinality, many)`, read as of the same revision; every `db/` predicate and the clocks `version` and `commit` are fixed at `one`. Every read folds except `rows`, which walks history.


## The db/ vocabulary
Every predicate the system writes or interprets is `db/...`; everything bare is the user's. Every subject the ledger writes itself lives under `db/`, and since DAT 1044 the code clocks do too. The ledger's configuration is ordinary rows written by ordinary transactions, so a declared index, cardinality or mount has a revision and a history like any fact.

| subject | what it holds |
| --- | --- |
| `db` | `version`, the name of a whole state; `db/format` |
| `db/tx/<rev>` | `db/by`, `db/time`, the transaction's keywords |
| `db/pred/<name>` | `db/cardinality`, `db/index`, `db/type`, `db/doc` |
| `db/code/<16 hex>` | `db/modules` (`relpath -> sha256` of every module the run loaded), `db/mounts` (the mounts hash when sandboxed, `none` when installed): a snapshot of code, shared by every function in it and every result it made |
| `db/mount/<prefix>` | `db/repo`, `db/root`, `db/salt` |
| `db/repo/<repo>` | `commit`, the full commit of the latest clean run of any package in the repo: written by that run's seal, never by a person |
| `db/repo/<repo>/<package>` | `version`, the clock of one versioned package (`plane`, `demo_game.etl`, `geometry`): written by the first clean run at a new `__version__`, never by a person (`bump_source` edits the source) |
| `db/kind/<dotted>` | `db/moved`: a renamed class |
| a sealed value's subject | `db/value`, `db/kind`, `db/provenance`, `db/preds`, `db/fn` (the function's dotted name), `db/keys`, `db/returns`, `db/sealed-at`, `db/deps/<item>` ([Value Provenance](#Value%20Provenance)) |

A `(db/pred/<p>, db/index, true)` row builds a partial SQL index on `<p>` in the transaction that commits it. A release is a `bump` of `db`'s own `version`, and `ledger.at("3.2.0")` reads that moment.


## Storage
The quads live in one table, `quads(rev, ord, subject, predicate, object, added)`, keyed by `(rev, ord)` and indexed on `(subject, predicate, rev)` and `(predicate, object, rev)`: in `ledger.db` (SQLite, WAL mode) for a folder ledger, in a Postgres schema for a DSN ledger (`pip install 'dvc_dat[pg]'`). The object is a tagged string, `str:`, `json:` or `ref:<class>:<hash>[:<subject>]`, so a row reads without a schema.

The art store holds bytes by sha256 at `sha256/<2>/<hex>`, write-once, so the same bytes are stored once however many subjects point at them. A value's parts enter by `put_path` (a hardlink on the same filesystem, else a streamed copy checked against the hash) and leave by `get_to`. A stored `Dat`'s files and its materialised folder under `art/dats/` share inodes. The ledger's art store and the dat manager's `art/` are separate folders keyed the same way.


## Concurrency
One writer at a time: a transaction takes the write lock only at commit, and its revision is `MAX(rev) + 1` under that lock. `lock=<seconds>` holds the lock for the whole body when a read must not go stale before the write; `t.previous_rev` and the helpers that read through it require it. Readers take no lock; a `Rev` is a snapshot. Two processes missing on one memo key both run and both seal: identical bytes and dependencies are one subject, the second dropped at commit; different bytes are two entries, both kept, which is the evidence a nondeterminism check needs. The load harness under `tests/load/` checks these invariants across processes on SQLite and Postgres; its measurements are in [`tests/load/README.md`](../../../tests/load/README.md).




# Execution Semantics
Where a value function runs, what the run is allowed to see, and how its result becomes a value in the ledger.

![DAT Ledger Execution](DAT%20Ledger%20Execution.svg) 

## The function
A value function takes the revision first and keywords after, is marked `@ledger_fn`, and returns a `Value`; its return annotation is required. Every read it makes through `rev` becomes a row of its result's dependencies ([Value Provenance](#Value%20Provenance)).

```python
@ledger_fn
def cut(rev, *, game: str, version: str) -> Cut:
    home = rev[f"game/{game}", "home"]           # traced
    raw = rev.value(kind=Video, game=game)       # traced
    out = Cut(cut_video(raw, home))
    out.preds.update(game=game, version=version)
    return out
```

A function that declares `path: Path` is given a fresh folder under `$DAT_WORK` (default `~/.cache/dvc-dat/work`); it writes a folder there and returns `Dat(path)`, and the seal moves the files into the art store. A dat made from a spec needs no function of its own: `rev.run(spec)` ([Running](#Running)). The result's name is the call's `path=` (relative to the data folder, `<art store>/dats`), else the parameter's default as a path template expanded with the keys, else `anonymous/Dat{unique}`; its folder at the name is a view, hardlinks into the store, rebuilt as a new folder when the name moves. A value has one name, an alias not bound into its hash, settable as `Value(name=...)` or by assigning `v.name`; a name names one value; a value prints as its name, else `#` + a hash prefix (`<Video video/G1>`, `<Video #2db69ce1>`).



## The execution environment
`resolve(name)` decides between two environments. A name under a mounted prefix is *sandboxed*; any other name is *unsandboxed*. The difference is what the `fn` dependency item stands for, and so what a changed input the memo can detect.

**Unsandboxed** executes in the Python environment of the ledger's own process: whatever that process has imported, with every package it can see. The function's `code` subject hashes the function module's static import closure within its checkout, and its `code/<repo>` dependency item names the checkout's commit; the commit stands for the bytes, which is why an unsandboxed call needs a clean checkout. The checkout is found by git discovery over the folders of the imported modules, skipping the standard library, `site-packages` and the dvc-dat checkout; a checkout is named by its `pyproject.toml` `[project].name`.

**Sandboxed** functions live under a mount: rows naming a dotted prefix, its repo and its root, `(db/mount/demo_game.etl, db/root, demo_game/etl)` with `db/repo` beside it. Each call runs in a fresh process forked from a warm `python -I` server, one per environment, which holds only the ledger's machinery (no mounted module, no CUDA); a finder first on `sys.meta_path` serves the mounted prefixes from their roots, so every run loads, and records, exactly what it uses, third-party modules included. The `code` item is then the bytes of every module the run loaded: one changed byte anywhere is a different snapshot, so a sandboxed call runs at HEAD, clean or dirty. The child refuses what it cannot trace: `UnmountedImport`, `UntracedRead`, `ConfinedWrite`, `ConfinedNetwork`. An incomplete mount table is therefore a crash rather than a silently wider set of dependencies.

**Versioning.** Every execution environment has a version that ties it to the code: each versioned package's `db/repo/<repo>/<package>` `version` row, written by the first clean run at each new `__version__`, and the repo's `db/repo/<repo>` `commit` row, the latest clean run's; every run's dependencies carry the `code/<repo>` item as `<commit8>`, the commit being what the hit test compares; the version a reader sees stays readable from the `db/repo/` rows at the revision. How versions are asserted and bumped, and what `clean=True` demands of the checkout, is [Versioning](#Versioning).



## Running
**A dat run is a ledger-function call.** `Dat.manager.run` makes a dat outside the ledger: a fresh folder every time, nothing recorded. `rev.run` makes or finds one inside it (DAT 1046): `rev.run(target, **kwargs)` takes a spec, a spec's name or a run function's name, and is a memo lookup over the memo key (the expanded spec, `dat.name` removed) and the run function's code, else a create, a run and a seal of the folder as the memo entry ([`run`](#^run)). The run function is an `Fn` of kind `"dat"`, and the call is the one a `@ledger_fn` gets: the same lookup, the same worker loop, the same seal and place; the kinds differ only in what the body receives, the keys or the dat built from them. A mounted run function runs in the sandbox worker, confined, its code the modules it loaded; so a commit that changes no file it loaded leaves the next call a hit. Inside the body the dat world's `do` is a `LedgerDo` bound to the run's revision, whatever namespace the caller's world has (DAT 1047): a name the body looks up (`Dat.manager.do.load`, a spec's `dat.base` or `dat.do`, a `{}` reference) walks the same `db/mount` rows the run was resolved through, read from the worker's checkout, and `mount` is refused. Names come from the ledger's mounts alone: the spec `mymodule/specs/table12.yaml` under `db/mount/mymodule` is `mymodule.specs.table12`, and `just run mymodule.specs.table12` in a ledger project is `rev.run("mymodule.specs.table12")`; any dat saved by hand seals as `dat.seal(t)`.

**run.** `run(name, **keys)` looks up the function by name (`resolve`), then looks for a result already computed: every entry whose `db/fn` (the dotted name) and `db/keys` (the bound keys, defaults included, as canonical JSON) match, newest seal first, and hands back the first whose dependencies still hold at the revision asked ([Value Provenance](#Value%20Provenance)). That is the memoization. A miss runs the body with a recording `Rev`, in the child for a sandboxed function, and the result comes back with its dependencies. `seal=` says where the result goes; a later `v.seal(x)` takes the same `x`, so a run looked at first can be kept without running again.

| Level | You want | Retained | Call | Later, on the object | Next identical call |
|---|---|---|---|---|---|
| get | a saved result if one exists; never compute | nothing new | `f(**keys, seal="get")` → value or `None` | — | — |
| draft | run it, keep nothing; look first | the object in memory, trace attached | `f(**keys, seal=False)` | `.seal()`, `.seal(L)`, `.seal(t)` | recomputes |
| sealed | run it and freeze it, off the ledger | hash, content in the kept folder, trace, frozen preds | `f(**keys, seal=True)` | `.seal(L)`, `.seal(t)` | recomputes |
| saved | run it and put it on the ledger | the memo entry on the timeline, keyed by fn + keys | `f(**keys, seal=L)` (own transaction; the default is the fn's ledger) or `seal=t` (into that transaction) | — | hits: returns the saved value |

```python
draft = clip_fn(**keys, seal=False)   # run; keep nothing
draft.seal(L)                         # saved; the next call hits
with L.transaction(by="human:dan") as t:
    saved = clip_fn(**keys, seal=t)   # saved with t's other rows
    t[saved.subject, "status"] = "reviewed"
```

Every run attaches its trace (the `code` subject and the `fn` name, the keys, `code/<repo>`, `platform`, every read) to its result, so a draft or a locally sealed result saved later writes the full memo entry, `db/fn`, `db/keys`, `db/returns`, the `db/deps/*` rows and the `db/code/<16 hex>` item when it is new, exactly as the memoised call would. Saving an unsandboxed run's result later checks the code then: the run must not have been on a dirty checkout, and the checkout must now be clean and at the commit the trace names, else `NotEvaluated`; a sandboxed result needs no check, its `code` item being the bytes it loaded. A hand-built value has no trace and seals as before, recording code and platform; it is found by name or pred, never by fn + keys. A result the body sealed itself is refused at every saving level (`TypeError`): the caller's `seal=` is the retention policy. A correction to a row a function read makes its result stale, and the next ask re-derives it; a changed byte in a module a sandboxed run loaded does the same through the `code` row, whatever commit it names.

**Value.** The return of a run is a value: the object the function built, with its preds and, once sealed, its provenance. Sealing is the act of capturing it: the identity is fixed from the dependencies, the preds and the bytes; saving then writes it into the ledger. So a value is in one of three states, and a result of `run` goes as far through them as its `seal=` says before it is returned.

| State | What is fixed | Where it lives | How |
| --- | --- | --- | --- |
| built | nothing: `preds` and the bytes may still change | memory, or its work folder for a `Dat` | the constructor, or the body of a value function |
| sealed | its identity: the subject hashing dependencies, preds and bytes; `preds` read-only | the same place, with a seal record in the kept folder | `v.seal()` (`keep=True` copies the bytes into the kept cache) |
| saved | the rows at a revision, the bytes in the art store | the ledger | `v.seal(t)` or `v.seal(L)`; a run saves its own result by default (`seal=`) |

**Value.seal.** A sealed value that is never saved is still a value with a fixed identity, usable as a dep. `v.seal()` alone writes a seal record to this machine's kept folder (`$DAT_KEPT`, else `~/.cache/dvc-dat/kept`); a later `v.seal(t)` saves the state it was sealed in, its dependencies the environment of the seal, not of the save. A value not kept whose bytes changed in between is `SealBroken`. `Dat.sealed_at_path` reopens such a seal in another process. `just sealed` lists the seals never saved; `just sealed purge` drops them. A saved value never changes; a new version is a new seal ([Versioning](#Versioning)).

A save writes the value's own rows once, under a subject hashing the dependencies, preds and bytes (for a run, the function and keys too): `db/value`, `db/kind`, `db/provenance` (`eval:unsandboxed` or `eval:sandbox` for a run, a dat's included, written in a transaction `by="eval:<name>"`; `seal` or the caller's for a hand seal), `db/preds` (for a dat, its class's names and its folder's own), `db/fn`, `db/keys` and `db/returns` for a run, `db/sealed-at` for a value sealed before the save, one `db/deps/<item>` per dependency item, and one row per pred (per member for a `many` pred). A subject already saved is not written again: the seal is idempotent. A save involving a function whose code is at a declared version from a clean checkout also moves that package's `db/repo/<repo>/<package>` clock and the repo's `db/repo/<repo>` commit ([Versioning](#Versioning)). A hand seal's dependencies are declared, from its `deps` and the environment ([Value Provenance](#Value%20Provenance)); `seal` refuses a provenance beginning `eval:`, so a consumer that needs proof the dependencies were traced rather than declared asks for an `eval:` value.




# Value Provenance
A value's provenance is stored in the ledger as triples whose subject is the value: beside its `db/value` row and its preds, one `db/deps/<item>` row for every input the computation depended on. These rows are the value's *dependencies*. They are written once, at the save, and never change; whether the dependencies still *hold* is computed, by re-asking each item at a revision. Every object is one string, the identity the input had when the value was computed, so two values' dependencies compare row by row and nothing is loaded.

## The dependencies
In the table `<value>` is the value's own subject and the other angle-bracketed names are variables: the predicate names the input, the object is the identity it had.

| subject | predicate | object | meaning |
| --- | --- | --- | --- |
| `<value>` | `db/deps/code` | `db/code/<16 hex>` | the code that ran, the snapshot: the hash of the modules it loaded (sandboxed) or of its static import closure (unsandboxed), with the mounts; holds while the function re-hashes to it at the rev |
| `<value>` | `db/deps/fn` | `<dotted name>` | the function inside that snapshot (`plane.measure.length`) |
| `<value>` | `db/deps/code/<repo>` | `<commit8>` | a checkout the run imported from, at that commit |
| `<value>` | `db/deps/platform` | `<os>-<machine>-py<M.m>` | the platform it ran on |
| `<value>` | `db/deps/<subject> <predicate>` | the held object | a row the body read with `rev[s, p]` or `get`, and what it held |
| `<value>` | `db/deps/<name> db/alias` | `ref:<class>:<hash>` | a name the body loaded through, and the bytes it named |
| `<value>` | `db/deps/ref:<class>:<hash>` | `ref:<class>:<hash>` | a value the body loaded, named by its bytes |
| `<value>` | `db/deps/eval:<name>{keys}` | `ref:<class>:<hash>` | a nested `run`, and the result it got |
| `<value>` | `db/deps/q:{...}` | the sorted `ref:` list, or a token of the result | a query the body made (`refs`, `values`, `value`, `select`; any other read as `__call__`), and what it answered |
| `<value>` | `db/deps/salt` | the mount's `db/salt` | the salt of the mount a sandboxed run was under, when set |

A run records the first eight as it goes: `code`, `fn`, `code/<repo>` and `platform` from the environment, the rest from each read the body makes through its `Rev`. A hand seal's dependencies are declared instead: a `ref:` row for each of its `deps` (an alias row too when the dep was loaded by name, a `code` and an `fn` row for an `Fn` dep), plus `code/<repo>` for every repo the environment reports, and `platform`. Nothing in the dependencies describes the value; it is the evidence the value was computed from.

## same_as, matches and diff
**`same_as(other)`** measures byte identity between the contents of two values: `hash == other.hash`, `False` for `None`. It reads no dependencies. Two values computed from different inputs can be the same bytes, and the store keeps them once; two values with identical dependencies can differ in bytes, which is what a nondeterminism check looks for.

**`matches(rev)`** measures whether anything a value depends on has changed by `rev`: whether any input it was computed from has, at `rev`, an identity other than the one its dependencies recorded. A later `rev` asks whether anything the value was built from has moved since; an earlier one asks whether the value would have been current then. The measure is the dependencies re-asked item by item, each kind its own way: `code` holds when the function its `fn` item names resolves at `rev` to the same `db/code` subject (sandboxed: the recorded modules re-hashed as they are now; unsandboxed: the static closure), and `fn` holds beside it; `code/<repo>` when the environment is at that commit; `platform` when the environment is the same; a `<subject> <predicate>` item when the fold at `rev` holds the same object; an alias item when the name resolves at `rev` to the same bytes; an `eval:` item when the nested lookup at `rev`, never running, yields that hash; a `q:` item when the query asked at `rev` answers the same; a `ref:` item always, since bytes do not change. It consults the ledger and the environment only and never runs anything; it is the hit test `run` applies to each candidate.

**`diff(other)`** measures how two values differ in what they were computed from: the dependency items whose recorded identities differ between them, item to `(mine, theirs)`, `None` where one lacks the item. It compares the two stored dependencies and asks the ledger nothing. Two seals of the same function and keys with different bytes differ in some item here, and that item is the cause.



## Versioning
The ledger has versions for many things: the ledger itself is versioned, the code is versioned, and schemas, APIs, model families and configs are versioned. All of them are asserted within the ledger: the current value of every version is a row, `(<subject>, version, M.m.p)`, so a revision holds every version in force at once. A code version lives in the source tree, as the package's `__version__`: `bump_source` (`just bump <module>`) edits it, the commit records it, and the first clean run after the commit asserts it into the ledger. Every other version is asserted by `bump`.

The ledger version is the main one. It determines the revision we are on, `L.at("1.4.0")` being the latest revision that set `(db, version, 1.4.0)`, and that revision in turn implies a version for everything else: the code's, the schema's, the API's, every `version` row held there. So the version of a value is the ledger version at the revision it was sealed, and one number names the whole state it was computed in; what makes that true is bumping `db` whenever any version it stands for moves. Two pieces have their own machinery:

- **Code**, `db/repo/<repo>/<package>` and `db/repo/<repo>` (DAT 1044): a clock per versioned package, its `version` row the version of that package's code that runs were exposed to, and one `commit` row per repo, the latest clean run of any of its packages. The ledger writes both, under `db/`, and a person never does. A seal involving a function (a run's memo entry, or a hand seal with an `Fn` dep) whose `Code.version` is a plain `MAJOR.MINOR.PATCH`, so from a clean checkout, reads its package's row through the transaction's snapshot: absent or lower, the transaction adds `version`; equal, nothing; higher on the row, a warning and nothing, since the clock never moves back; and it adds the full `commit` to `db/repo/<repo>` whenever that differs from the row. So a package's clock moves at the first clean run after a bump of its `__version__` is committed; a dirty checkout's `<commit 8>+dirty` never moves either row, and `bump` on a `db/repo/` subject is refused. A checkout holding two versioned packages (an installed one and a mounted one) keeps two clocks, neither warning about the other. A run sealed in the sandboxed worker raises its warning in the calling process. Every value's dependencies name the code commit it was computed under as the `code/<repo>` item ([Execution Semantics](#Execution%20Semantics)), because that is the version the memo checks on its own. `clean=True` on `run` asks that the checkout be clean, no uncommitted changes and HEAD at the commit the revision's `db/repo/<repo>` row names, and refuses with `NotClean` otherwise; by default only an unsandboxed call insists on it.
- **Anything else**: a subject with a `version` row, `schema/metrics` or `api/jobs`, bumped when it changes and readable at any revision.

A sealed value never changes: an `add` or `remove` on one of its own rows is `Exists` at commit, and any other row on its subject is annotation. A new version of a value is a new seal and a new subject; the re-pointable name is an alias, `(video/G1, db/alias, <subject>)`, which moves while the values it pointed at stay, so a read at an older revision still finds the older value. An alias names a subject holding a `db/value`, and a subject holding its own `db/value` cannot be an alias.

`bump(t, subject, part)` is the one writer of every version but code's: the current one read through `t.previous_rev` (so under `lock=`), the next by `part`, `minor` and `major` behind a `confirm`. A subject holding a `db/alias` row is refused: a value's version is a pred, and a new version of a value is a new seal and a re-point. A `db/repo/` subject is refused: its writer is the seal, above.




# BRIEF

- Written from `dvc_dat/ledger/*.py` at v2.18.0. Every name here must exist in the code; re-read the code, not this page, before changing a signature.
- The per-file pages beside this one are the internals and the full refusal lists; this page is the caller's interface. When a public signature changes, change both.
- The figure is hand-written SVG; edit it directly.
