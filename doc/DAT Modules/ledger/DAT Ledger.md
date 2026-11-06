---
description: "The ledger half of dvc_dat: quads read as of a revision, values stored by content, value functions evaluated with their dependencies traced. Source: `dvc_dat/ledger/`."
---
:>> [DAT](../../DAT%20Track/DAT.md) → [DAT doc Modules Ledger](ha://p/DAT%20doc%20Modules%20Ledger) 
# DAT Ledger
The ledger is a project's history: every fact a quad `(rev, subject, predicate, object)`, every read a frozen view as of one revision, every value stored by its content and found by its preds.

![DAT Ledger](DAT%20Ledger.svg) 

api:: [`dvc_dat.ledger`](../../api/ledger.md) — the classes and functions, rendered from the docstrings

**Classes:** [Ledger](#Ledger%20Interface) · [Rev](#Rev%20Interface) · [Ref](#Ref%20Interface) · [Row](#Row%20Interface) · [Transaction](#Transaction%20Interface) · [Value](#Value%20Interface) · [Value.Blob](#Value.Blob%20Interface) · [Value.Table](#Value.Table%20Interface) · [Dat](#Dat%20Interface) · [Fn](#Fn%20Interface) · [Code](../../api/ledger.md#dvc_dat.ledger.Fn.code) · [module functions](#dvc_dat.ledger%20Interface) 
**Topics:** [Ledger Semantics](#Ledger%20Semantics) · [Many ledgers](#Many%20ledgers) · [Execution Semantics](#Execution%20Semantics) · [Rerunnability](#Rerunnability) · [Value Provenance](#Value%20Provenance) · [dvc_dat.dat](#dvc_dat.dat%20Interface) 

| Methods     |                                                                                                                                                                                                                                                                                                            |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ledger      | [path](../../api/ledger.md#dvc_dat.ledger.Ledger.path), [at](../../api/ledger.md#dvc_dat.ledger.Ledger.at), [revs](../../api/ledger.md#dvc_dat.ledger.Ledger.revs), [transaction](../../api/ledger.md#dvc_dat.ledger.Ledger.transaction), [close](../../api/ledger.md#dvc_dat.ledger.Ledger.close)                                                                                                                                                                                                                                 |
| Rev         | [id](../../api/ledger.md#dvc_dat.ledger.Rev.id), [ledger](../../api/ledger.md#dvc_dat.ledger.Rev.ledger), [tx](../../api/ledger.md#dvc_dat.ledger.Rev.tx), [`[]`](../../api/ledger.md#dvc_dat.ledger.Rev.__getitem__), [get](../../api/ledger.md#dvc_dat.ledger.Rev.get), [in](../../api/ledger.md#dvc_dat.ledger.Rev.__contains__), [all](../../api/ledger.md#dvc_dat.ledger.Rev.all), [history](../../api/ledger.md#dvc_dat.ledger.Rev.history), [last_rev](../../api/ledger.md#dvc_dat.ledger.Rev.last_rev), [refs](../../api/ledger.md#dvc_dat.ledger.Rev.refs), [values](../../api/ledger.md#dvc_dat.ledger.Rev.values), [value](../../api/ledger.md#dvc_dat.ledger.Rev.value), [select](../../api/ledger.md#dvc_dat.ledger.Rev.select), [load](../../api/ledger.md#dvc_dat.ledger.Rev.load), [ns](../../api/ledger.md#dvc_dat.ledger.Rev.ns), [run](../../api/ledger.md#dvc_dat.ledger.Rev.run), [rerun](../../api/ledger.md#dvc_dat.ledger.Rev.rerun), [timezone](../../api/ledger.md#dvc_dat.ledger.Rev.timezone), [show_time](../../api/ledger.md#dvc_dat.ledger.Rev.show_time)                                                |
| Ref         | [rev](../../api/ledger.md#dvc_dat.ledger.Ref.rev), [subject](../../api/ledger.md#dvc_dat.ledger.Ref.subject), [name](../../api/ledger.md#dvc_dat.ledger.Ref.name), [aliases](../../api/ledger.md#dvc_dat.ledger.Ref.aliases), [hash](../../api/ledger.md#dvc_dat.ledger.Ref.hash), [type](../../api/ledger.md#dvc_dat.ledger.Ref.type), [preds](../../api/ledger.md#dvc_dat.ledger.Ref.preds), [sealed_at](../../api/ledger.md#dvc_dat.ledger.Ref.sealed_at), [load](../../api/ledger.md#dvc_dat.ledger.Ref.load)                                                                                                                                   |
| Row         | [rev](../../api/ledger.md#dvc_dat.ledger.Row.rev), [subject](../../api/ledger.md#dvc_dat.ledger.Row.subject), [predicate](../../api/ledger.md#dvc_dat.ledger.Row.predicate), [object](../../api/ledger.md#dvc_dat.ledger.Row.object), [added](../../api/ledger.md#dvc_dat.ledger.Row.added)                                                                                                                                                                                                 |
| Transaction | [tx](../../api/ledger.md#dvc_dat.ledger.Transaction.tx), [previous_rev](../../api/ledger.md#dvc_dat.ledger.Transaction.previous_rev), [ns](../../api/ledger.md#dvc_dat.ledger.Transaction.ns), [rev](../../api/ledger.md#dvc_dat.ledger.Transaction.rev), [add](../../api/ledger.md#dvc_dat.ledger.Transaction.add), [update](../../api/ledger.md#dvc_dat.ledger.Transaction.update), [`[]=`](../../api/ledger.md#dvc_dat.ledger.Transaction.__setitem__), [remove](../../api/ledger.md#dvc_dat.ledger.Transaction.remove), [`del []`](../../api/ledger.md#dvc_dat.ledger.Transaction.__delitem__), [pin](../../api/ledger.md#dvc_dat.ledger.Transaction.pin)                                                                                                       |
| Value       | [preds](../../api/ledger.md#dvc_dat.ledger.Value.preds), [subject](../../api/ledger.md#dvc_dat.ledger.Value.subject), [rev](../../api/ledger.md#dvc_dat.ledger.Value.rev), [at](../../api/ledger.md#dvc_dat.ledger.Value.at), [sealed](../../api/ledger.md#dvc_dat.ledger.Value.sealed), [hash](../../api/ledger.md#dvc_dat.ledger.Value.hash), [dependencies](../../api/ledger.md#dvc_dat.ledger.Value.dependencies), [Dependencies](../../api/ledger.md#dvc_dat.ledger.Value.Dependencies), [encode](../../api/ledger.md#dvc_dat.ledger.Value.encode), [decode](../../api/ledger.md#dvc_dat.ledger.Value.decode), [seal](../../api/ledger.md#dvc_dat.ledger.Value.seal), [same_as](../../api/ledger.md#dvc_dat.ledger.Value.same_as), [matches](../../api/ledger.md#dvc_dat.ledger.Value.matches), [diff](../../api/ledger.md#dvc_dat.ledger.Value.diff) |
| Value.Blob  | [obj](../../api/ledger.md#dvc_dat.ledger.value.Blob.obj)                                                                                                                                                                                                                                                                                               |
| Value.Table | [table](../../api/ledger.md#dvc_dat.ledger.value.Table.table)                                                                                                                                                                                                                                                                                     |
| Dat         | [path](../../api/core.md#dvc_dat.core.Dat.path), [preds](../../api/core.md#dvc_dat.core.Dat.preds), [sealed_at_path](../../api/core.md#dvc_dat.core.Dat.sealed_at_path), [decode](../../api/core.md#dvc_dat.core.Dat.decode), [kind_ok](../../api/core.md#dvc_dat.core.Dat.kind_ok), [spec_kind](../../api/core.md#dvc_dat.core.Dat.spec_kind)                                                                                                                                                       |
| Fn          | [name](../../api/ledger.md#dvc_dat.ledger.Fn.name), [module](../../api/ledger.md#dvc_dat.ledger.Fn.module), [code](../../api/ledger.md#dvc_dat.ledger.Fn.code), [mount](../../api/ledger.md#dvc_dat.ledger.Fn.mount), [env](../../api/ledger.md#dvc_dat.ledger.Fn.env), [signature](../../api/ledger.md#dvc_dat.ledger.Fn.signature), [kind](../../api/ledger.md#dvc_dat.ledger.Fn.kind), [reproducible](../../api/ledger.md#dvc_dat.ledger.Fn.reproducible), [()](../../api/ledger.md#dvc_dat.ledger.Fn.__call__) |


This page is the package `dvc_dat.ledger` as a caller sees it: the figure above, each public class and its members, then the rules that span them. The dat half, a folder that is its own recipe, is [DAT Dat](../DAT%20Dat.md); how the two halves meet is the [architecture](../../DAT%20Architecture.md). The four notebooks run it end to end: [ledger-triples](../../DAT%20Demos/ledger-triples.ipynb), [ledger-values](../../DAT%20Demos/ledger-values.ipynb), [ledger-dats](../../DAT%20Demos/ledger-dats.ipynb), [ledger-just](../../DAT%20Demos/ledger-just.ipynb); [api-walkthrough](../../DAT%20Demos/api-walkthrough.ipynb) is the one API sheet covering all four parts. From a shell, `just values`, `value`, `history`, `why`, `set`, `index`, `bump`, `pin` and `rerun` are one call each of this interface, shipped in `dvc_dat.just` beside `run` ([Command Line](../../cli.md) § The ledger verbs).



## Ledger Interface
The handle on one ledger: a folder holding `ledger.db` and the art store `art/`, or a Postgres database named by a DSN with its art store a folder. It finds or opens the ledger, hands out frozen views with `at` and write sets with `transaction`, and holds no reads of its own, so a long run reads one snapshot by construction. Nothing is created on disk without `create=True`. A `Ledger` is a context manager whose exit closes it.

<!-- methods: dvc_dat.ledger.Ledger -->

## Rev Interface
A frozen view of the ledger as of one revision, made by `Ledger.at`, never by hand. Every read is bounded by `id`, so a `Rev` gives the same answer forever. Row reads fold the rows by each predicate's cardinality ([The fold](#The%20fold)); `history` takes the same pattern unfolded; subject reads (`refs`, `values`, `value`, `select`) treat the store as a table whose rows are subjects. A stored reference comes back as an unloaded `Ref`. A `Rev` handed to a value function's body also traces every read into its result's dependencies. Ordered and equal by `id` within one ledger.

<!-- methods: dvc_dat.ledger.Rev -->

## Ref Interface
A reference to one value at one moment, named without fetching a byte: the subject and the revision, nothing loaded until `load`. Making one resolves the `db/alias` chain from `name`; a cycle or more than 8 hops is `AliasLoop`. A `Ref` is frozen, equal and hashed by subject, and does not pickle (it is bound to an open ledger). Its `repr` is `<Ref label>` and its `str` the bare label: the value's name (the alias naming it written latest), else `#` + the hash's first 8 hex (DAT 1036). Made from a recording `Rev`, it traces its reads into the dependencies like the `Rev` would.

<!-- methods: dvc_dat.ledger.Ref -->

## Row Interface
A named tuple encoding a single row in the ledger: revision, subject, predicate, object, and an added/removed bit. `history()` returns them; `str(row)` is one aligned line: revision, `+` or `-`, subject, predicate, object.

<!-- methods: dvc_dat.ledger.Row -->

## Transaction Interface
The write set of one `with L.transaction(...) as t:` block; it becomes exactly one revision on exit, or nothing. `add`, `update` and `remove` append rows and read nothing; `v.seal(t)` seals a value into it; the bracket forms are helpers over `add` and `remove`. **A transaction reads the previous revision and writes the next; its own pending writes are not seen until it closes.** Its read verbs are `previous_rev`'s: `get`, `all`, `history`, `refs`, `values`, `value`, `select`, `load`, `in`, and `t[s, p]` / `t[s]` as a read (`t[s, p] = o` / `t[s] = {...}` write). `previous_rev` is bound to the previous revision and exists only under `lock=`, because an unlocked transaction has no well-defined previous revision (another writer may commit between open and exit). The helpers that read and then write (`t[s] = {...}`, `del`, `bump`) read through it, so they need `lock=`; unlocked they raise `Unlocked` and write nothing. Whatever must see the transaction's own rows is checked at commit, inside the write lock. Entered once; a verb used outside the block is `RuntimeError`.

<!-- methods: dvc_dat.ledger.Transaction -->

## Value Interface
The object itself with its provenance on it: what `run` returns, what `seal` stores and what `Ref.load` restores. A subclass says how it becomes bytes (`encode`) and back (`decode`); `@ledger_class(preds=...)` names the preds its values may carry. Every subclass's encoding is deterministic and lossless: see [`encode`](../../api/ledger.md#dvc_dat.ledger.Value.encode). Until sealed, `preds` is a plain dict filled by whoever builds the value; the seal freezes it and fixes the identity. A subclass's `__init__` need not call `super().__init__`.

**What a value prints as** (DAT 1036). Python's unreadable-object form: `repr` (a bare notebook cell) is `<Type label>`, `str` (`print`, f-strings) the bare label. The label is the value's name at the head, else `#` + the hash's first 8 hex, like a short git sha; a draft has no label. A `Ref` prints the same label as `<Ref …>`; a `Fn` prints its dotted name `@` its code's version (`<Fn mnt.plane.measure.length@2.7.1>`, `str` `mnt.plane.measure.length@2.7.1`), and its `Code` the unit `@` the same version (`<Code plane@2.7.1>`) (DAT 1037).

```python
v                    # <Video video/G1>     saved, named
v                    # <Video #2db69ce1>    saved, unnamed
str(v)               # 'video/G1'  /  '#2db69ce1'
v                    # <Clip sealed #2db69ce1>   v.seal(), saved nowhere
v                    # <Clip draft>         unsealed; str the same
Ref(rev, "video/G1") # <Ref video/G1>
f                    # <Fn mnt.plane.measure.length@2.7.1>
str(f)               # 'mnt.plane.measure.length@2.7.1'
f.code               # <Code plane@2.7.1>
```

<!-- methods: dvc_dat.ledger.Value -->

## Value.Blob Interface
A `Value` holding any Python object, stored with pickle (protocol 4). Declares no preds.

<!-- methods: dvc_dat.ledger.value.Blob -->

## Value.Table Interface
A `Value` holding a table, encoded as parquet. A pandas `DataFrame` is converted on encode; a decoded `Value.Table` holds a `pyarrow.Table`. It exists beside `Value.Blob` because the encoding is the identity: pickle bytes change with the Python, pandas and pyarrow versions and nothing outside Python reads them, while parquet stores it columnar and compact, and any tool that reads parquet can read it from the art store. Its bytes still follow the table's chunks and schema metadata and name the pyarrow version ([`encode`](../../api/ledger.md#dvc_dat.ledger.Value.encode)).

<!-- methods: dvc_dat.ledger.value.Table -->

## Dat Interface
`dvc_dat.ledger.Dat` is `dvc_dat.Dat`, one class (DAT 1038): a dat, the folder that is its own recipe ([DAT Dat](../DAT%20Dat.md)), is a `Value` whose bytes are the folder. It encodes as its content manifest, `{"files": {relpath: sha256}}`, written to the sink, and its files are its parts, streamed into the art store one at a time, so memory is bounded by the manifest, not the folder. Every file in the folder is hashed (`__pycache__` and the [subdats](#Subdats) skipped), `_spec_.yaml` and `_result_.yaml` included; each in 1 MiB blocks, the per-file hashes cached on the object, keyed by size, mtime and inode, so only a changed file is hashed again. The `db/value` row's kind and the folder's `dat.kind` are the same dotted name, `dvc_dat.core.Dat` or the subclass. A dat made by `Dat.create` or `Dat.manager.run` seals with no subclass once saved: `dat.seal(t, name="table/12")` stores its files and writes its row, and `rev.load("table/12")` returns a `Dat` whose `get_spec()`, `get_results()` and `get_path()` read the rebuilt folder. A folder whose `_spec_` names a `dat.kind` and was never saved (standing `open`) is `ValueError` naming `dat.save()`; a folder with no spec is a plain folder value.

The members a value uses: [path](../../api/core.md#dvc_dat.core.Dat.path) · [at](../../api/core.md#dvc_dat.core.Dat.at) · [preds](../../api/core.md#dvc_dat.core.Dat.preds) · [sealed_at_path](../../api/core.md#dvc_dat.core.Dat.sealed_at_path) · [decode](../../api/core.md#dvc_dat.core.Dat.decode) · [kind_ok](../../api/core.md#dvc_dat.core.Dat.kind_ok) · [spec_kind](../../api/core.md#dvc_dat.core.Dat.spec_kind); the rest are on [DAT Dat](../DAT%20Dat.md#dat-interface).

## Fn Interface
A value function resolved at one revision: a frozen dataclass made by `rev.ns.load`, never by hand. Calling it is `run`. Only the snapshot has identity; a function is a name looked up inside it (DAT 1037): it has `name` and `code` and no `subject` or `sha`, since it is not on the timeline. It prints as `<Fn mnt.plane.measure.length@2.7.1>`, `str` `mnt.plane.measure.length@2.7.1`: the dotted name `@` its code's version; a mounted function's name starts `mnt.`. `code` says where the code comes from: installed in the ledger's own Python environment (imported in this process), or mounted from a checkout (`code.sandboxed`, run in a worker).

<!-- methods: dvc_dat.ledger.Fn -->

## dvc_dat.ledger Interface
The package's other exports: the two ledger handles (also exported from `dvc_dat`), one decorator (the function decorators are `dvc_dat.dat`'s, [below](#dvc_dat.dat%20Interface)), four helpers, and the exceptions. Every exception is a `LedgerError` and also the builtin it most resembles, so a caller catches either. `Env`, `Checkout` and `set_env_provider` are importable as the test suite's seam for the environment and are not part of the interface.

| dvc_dat.ledger | |
| --- | --- |
| [L](../../api/ledger.md#dvc_dat.ledger.named) | The active ledger, resolved at each use |
| [ledgers](../../api/ledger.md#dvc_dat.ledger.named.Ledgers) | The project's ledgers by name |
| [ledger_class](../../api/ledger.md#dvc_dat.ledger.ledger_class) | Declare a Value class's pred names |
| [bump](../../api/ledger.md#dvc_dat.ledger.bump) | Move a clock subject's version |
| [bump_source](../../api/ledger.md#dvc_dat.ledger.bump_source) | Raise a module's `__version__` in its source |
| [attr](../../api/ledger.md#dvc_dat.ledger.attr) | Walk a dotted path into an object |
| [register_policy](../../api/ledger.md#dvc_dat.ledger.register_policy) | Name a memo policy a ledger's `db/memo-policy` row can select |
| [register_store](../../api/ledger.md#dvc_dat.ledger.register_store) | Name a value store a ledger's `db/store` row can select |
| [Remote](../../api/ledger.md#dvc_dat.ledger.Remote) | What a value store is: bytes by hash on a remote place |
| [LedgerError](../../api/ledger.md#dvc_dat.ledger.errors.LedgerError) | Base of every ledger exception |
| [Multiple](../../api/ledger.md#dvc_dat.ledger.errors.Multiple) | Several matched where one was required |
| [NotEvaluated](../../api/ledger.md#dvc_dat.ledger.errors.NotEvaluated) | A miss this environment cannot run |
| [NotClean](../../api/ledger.md#dvc_dat.ledger.errors.NotClean) | `clean=True`, and the code is not a clean version |
| [NotPinned](../../api/ledger.md#dvc_dat.ledger.errors.NotPinned) | A pin or rerun refused |
| [NotCopied](../../api/ledger.md#dvc_dat.ledger.errors.NotCopied) | A copy refused |
| [SpecOnly](../../api/ledger.md#dvc_dat.ledger.errors.SpecOnly) | A value this ledger holds as its spec alone |
| [Differed](../../api/ledger.md#dvc_dat.ledger.errors.Differed) | A rerun of a claim of `exact` gave another hash |
| [UnmountedImport](../../api/ledger.md#dvc_dat.ledger.errors.UnmountedImport) | A sandboxed import outside every mount |
| [UntracedRead](../../api/ledger.md#dvc_dat.ledger.errors.UntracedRead) | A sandboxed read outside the allowed places, or an unsandboxed read of its repo outside the dats |
| [ConfinedWrite](../../api/ledger.md#dvc_dat.ledger.errors.ConfinedWrite) | A sandboxed write outside the path folder |
| [ConfinedNetwork](../../api/ledger.md#dvc_dat.ledger.errors.ConfinedNetwork) | A sandboxed network use |
| [LockTimeout](../../api/ledger.md#dvc_dat.ledger.errors.LockTimeout) | A lock= body past its limit |
| [Unlocked](../../api/ledger.md#dvc_dat.ledger.errors.Unlocked) | `previous_rev` or a read-then-write helper without lock= |
| [Unindexed](../../api/ledger.md#dvc_dat.ledger.errors.Unindexed) | A query on an unknown dotted predicate |
| [Exists](../../api/ledger.md#dvc_dat.ledger.errors.Exists) | A write to a sealed subject's own rows |
| [Undeclared](../../api/ledger.md#dvc_dat.ledger.errors.Undeclared) | A pred name the class did not declare |
| [AliasLoop](../../api/ledger.md#dvc_dat.ledger.errors.AliasLoop) | An alias chain that loops or runs long |
| [SealBroken](../../api/ledger.md#dvc_dat.ledger.errors.SealBroken) | A sealed value's bytes changed before saving |

# Ledger Semantics
The rows themselves: how triples are written, as revisions by transactions; how they are read, by the fold; which rows are the system's own; and where they live.

## Revisions and transactions
Every fact is a quad `(rev, subject, predicate, object)`; rows are only ever appended, never updated or deleted, and `remove` appends a remove row.

So on a ledger project `Dat.delete()`, and `Dat.create` with `target_exists: overwrite` onto an existing dat, are `TypeError`: nothing is reclaimed. To stop a dat being in the current view, retract its rows in a transaction (`del t[s]`); every earlier revision keeps them, and its folder stays as a local copy.

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

One `with` block is one revision: its rows land together on exit, in body order, followed by the `db/tx/<rev>` rows (`db/by`, `db/time`, and each keyword given `transaction()`), which a body that wrote nothing still writes. `db/by` is the writer as given: a `str` row, or a dict as one `json:` row in canonical JSON (sorted keys, compact), which `rev[rev.tx, "db/by"]` returns as the dict and `just history` prints as that canonical text. A ledger's first transaction also writes `(db, db/format, dvc-dat-ledger/1)`. `db/time` is UTC, `YYYY-MM-DDTHH:MM:SSZ`; it prints in the [display zone](../../api/ledger.md#dvc_dat.ledger.Rev.timezone). An exception in the body, a refusal at commit, or `LockTimeout` writes nothing, unseals every value the body sealed and removes the bytes it stored. Revisions are dense and monotonic, so a reader never sees half a transaction.


## The fold
A read turns the rows at or before its revision into what they hold, by each predicate's cardinality. Under `one`, the default, the latest add wins, so `add` is assignment; a remove of the held object leaves nothing held. Under `many`, the held objects are the set added and not since removed, each at its earliest add. Cardinality is itself a row, `(db/pred/officials, db/cardinality, many)`, read as of the same revision; every `db/` predicate (the clocks `db/version` and `db/commit` among them) is fixed at `one`, but `db/tag`, fixed at `many`; a bare `version` or `commit` is the user's, `one` by default and declarable `many` like any other. Every read folds except `history`.


## The db/ vocabulary
`db/<p>` is a predicate the ledger interprets, on any subject; everything bare is the user's and the ledger reads nothing into it (DAT 1052 Q2, Q3). Every subject the ledger writes itself lives under `db/`, and since DAT 1044 the code clocks do too. `db/version` is the version identifier, on any subject: the release on `db`, a code clock, and the version of anything of yours you version (`bump(t, "schema/metrics")`); its object is a `MAJOR.MINOR.PATCH` string, checked at `add`. A bare `version` is yours, free text the ledger never reads. The ledger's configuration is ordinary rows written by ordinary transactions, so a declared index, cardinality or mount has a revision and a history like any fact.

| subject | what it holds |
| --- | --- |
| `db` | `db/version`, the release, the name of a whole state (`bump(t, "db")`, `L.at("M.m.p")`); `db/tag`, a name for the revision its transaction commits (`t.add("db", "db/tag", "2026-Q4-official")`, `L.at("2026-Q4-official")`): cardinality `many`, never reused (a name added before is `Exists`, nothing written), neither digits, `M.m.p` nor an ISO 8601 timestamp (a tag `2026-11-02` is `ValueError`); `db/format`; `db/timezone`, the IANA zone times print in, any revision may change it, validated when added, on the subject `db` only ([`timezone`](../../api/ledger.md#dvc_dat.ledger.Rev.timezone)); `db/memo-policy`, the memo policy's name ([Memoization and the platform](#Memoization%20and%20the%20platform)); `db/store`, the value store its values' bytes go to, `local` when absent ([Value stores](#Value%20stores)) |
| `db/tx/<rev>` | `db/by`, `db/time`, the transaction's keywords |
| `db/pred/<name>` | `db/cardinality`, `db/index`, `db/type` |
| `db/code/<16 hex>` | `db/modules` (`relpath -> sha256` of every module the run loaded, a module its caller loaded first included, and every mounted file it read, through the namespace or by opening it), `db/mounts` (the mounts hash when sandboxed, `none` when installed): a snapshot of code, shared by every function in it and every result it made |
| `db/mount/<prefix>` | `db/repo`, `db/root`, `db/salt` |
| `db/repo/<repo>` | `db/commit`, the full commit of the latest clean run of any package in the repo: written by that run's seal, never by a person |
| `db/repo/<repo>/<commit12>` | `db/pinned`, the tag `dat/<commit12>` a [`pin`](../../api/ledger.md#dvc_dat.ledger.Transaction.pin) pushed: the commit is permanent, and every value this ledger holds from it is rerunnable with it ([Rerunnability](#Rerunnability)) |
| `db/repo/<repo>/<package>` | `db/version`, the clock of one versioned package (`plane`, `demo_game.etl`, `geometry`): written by the first clean run at a new `__version__`, never by a person (`bump_source` edits the source) |
| `db/kind/<dotted>` | `db/moved`: a renamed class |
| `ledger/<name>`, on the root ledger | `ledger/location`, where the ledger `<name>` is, and `ledger/dropped` once it is gone ([Many ledgers](#Many%20ledgers)); `ledger/lifetime`, what root declares of it: `permanent`, `archival` or `transient`, written once ([Copying](#Copying)) |
| a sealed value's subject | `db/value`, `db/kind`, `db/provenance`, `db/preds`, `db/fn` (the function's dotted name), `db/keys`, `db/returns`, `db/reproducible`, `db/at` (the revision the run read, as a str, [Running over past revisions](#Running%20over%20past%20revisions)), `db/copied-from`, `db/commit` and `db/spec-only` on a copy, `db/sealed-at`, `db/deps/<item>` ([Value Provenance](#Value%20Provenance)); `db/store`, the store its bytes were put on (none: the writer's folder alone) ([Value stores](#Value%20stores)); `db/rerunnable` (`true` or `recursive`), the claim a [`pin`](../../api/ledger.md#dvc_dat.ledger.Transaction.pin) asserted, and `db/rerun`, the outcome `pin(rerun=True)` recorded ([Rerunnability](#Rerunnability)); `db/subdat/<relpath>`, a `ref:` to a subdat or `str:declined` ([Subdats](#Subdats)) |

A `(db/pred/<p>, db/index, true)` row builds a partial SQL index on `<p>` in the transaction that commits it. A release is a `bump` of `db`, which moves its `db/version`, and `ledger.at("3.2.0")` reads that moment.


## Subdats
A **subdat** is a dat (a folder whose `_spec_` names `dat.kind`, `is_subdat_dir`) inside another dat's folder tree, like a git repo inside a git repo (SVP 241). Creating it there is the whole declaration. The nearest enclosing dat leaves it out of its manifest and its `dat.sha256`, so two folders equal but for a gallery are one hash, and a parent's load fetches its manifest and its own files and not a byte of a child. `run/` is one. A folder with no spec, such as a video's segments, stays in the parent's bytes. A dat inside the running dat's folder is its output and enters no `dat.dependencies`.

A save seals the subdats with the parent, in one transaction, recursively, and a subdat that may not seal (never saved) refuses the whole save. Each child is a value of its own, named `<parent name>/<relpath>`, with the parent as its one declared dep and the parent's provenance; one sealed by `v.seal()`, or carrying a run's trace, keeps what it carries. Its folder lands under the parent's, which prunes it again.

| subject | predicate | object |
| --- | --- | --- |
| parent | `db/subdat/<relpath>` | `ref:<class>:<hash>:<child subject>`, the child sealed |
| parent | `db/subdat/<relpath>` | `str:declined`, the child was there and not sealed |

The row is outside the subject hash and re-points: a later seal of one subject, with another gallery, moves it, each revision reading its own and `rev.history` all. `db/subdat/` is the one `db/` predicate of a sealed subject a body may add, so a gallery drawn later attaches with `child.seal(t, name=f"{name}/viz", deps=[parent_ref])` and `t.add(parent.subject, "db/subdat/viz", child)`.

**Declining.** `skip` entries and a class's `skip_subdats` are relative-path suffixes: `viz` declines `viz/` and `run/viz/`, and a plain folder named declines every subdat under it. A declined subdat stays on disk, outside every hash, and stores no byte. `dvc_dat.Dat` declines nothing, so `run/` seals by default.

**Reaching a child.** By its alias and no other way: `L.at().load("run/G1/viz")`, a namespace read the sandbox watches like any other. A loaded parent exposes no attribute for a child and its load places none, because a reader of the result must go back to the ledger to reach what the result says it does not depend on; `dat.run` on a loaded dat is `None` unless a seal or load of `<name>/run` placed it in the folder. `dat.at` still answers, from the `db/at` row. A result that must always see one gallery stores its hash in its own rows. The rows serve `t.copy(deep=True)`, which brings the children, and provenance listing. Setting `name` moves every alias with prefix `<old>/` in the same transaction; a first name names the subdats by their rows, and `None` unnames the tree.

## Storage
The quads live in one table, `quads(rev, ord, subject, predicate, object, added)`, keyed by `(rev, ord)` and indexed on `(subject, predicate, rev)` and `(predicate, object, rev)`: in `ledger.db` (SQLite, WAL mode) for a folder ledger, in a Postgres schema for a DSN ledger (`pip install 'dvc_dat[pg]'`). The object is a tagged string, `str:`, `json:` or `ref:<class>:<hash>[:<subject>]`, so a row reads without a schema.

The art store holds bytes by sha256 at `sha256/<2>/<hex>`, write-once, so the same bytes are stored once however many subjects point at them. A value's encoding enters through a sink (`ArtStore.sink()`: a temp file hashed as written, renamed to its hash at close) and leaves through `ArtStore.open(h)`, a read stream; its parts enter by `put_path` (a hardlink on the same filesystem, else a streamed copy checked against the hash) and leave by `get_to`. No value's bytes are held in memory whole on either path (DAT 240). A value store (`Remote`) sees one blob per file plus one for the encoding, by the sha256 of the bytes as dvc-dat handed them; it may compress or wrap each blob, provided `get_to(h, dest)` yields bytes hashing to `h`. A stored `Dat`'s files and its materialised folder under `art/dats/` share inodes. The ledger's art store and the dat manager's `art/` are separate folders keyed the same way.

### Value stores
The art store is a folder on the machine that opened the ledger. A **value store** is where the bytes also go, so a value sealed on one machine loads on another (SVP 1511). The ledger names it in one row, `(db, db/store, <name>)`, read at the sealing transaction's snapshot; absent, it is `local`. A name other than `local` and `folder` is a store some code in the process registered (`register_store`): dvc-dat carries no cloud code.

- **Sealing.** A transaction that seals values on a store uploads each new value's parts and encoding (skipping any the remote holds) *before* it takes the write lock, so a large push never holds the ledger's other writers; under `lock=` the lock is already held. A blob a commit leaves behind when it then fails is harmless: write-once, by hash. A failed upload fails the commit, nothing written. The seal adds `(<value subject>, db/store, <name>)`, naming where its bytes went, and the local folder keeps its copy. A sandboxed body never uploads: its seal runs in the parent.
- **Reading.** A read takes the bytes from the local folder; on a miss it reads the value's own `db/store` row and fetches from that store into the folder, which is so a cache, checked against the hash (`LedgerError` on a failed fetch or a wrong hash). A value with no row is read from the folder alone, as before 1511. A value stored on `azure` loads in a process whose `local` is `gcp`: the row, not the reader, names the store.
- **`local`** is resolved once per process, first to last: `DAT_STORE_LOCAL` (a registered name, or `folder`); the cloud this machine is a VM of, by a 0.3 s probe of the link-local metadata endpoint (`169.254.169.254`: `gcp` on Compute Engine, `azure` on Azure), when this process registered that name; `stores: {local: <name>}` in the nearest `.datconfig.yaml`; else `folder`. With no store registered, `local` is `folder` and nothing is probed.
- **`folder`** is the built-in store: the ledger's own art folder alone, nothing uploaded, no per-value row.

```python
from dvc_dat.ledger import register_store
# GcsRemote: your Remote
register_store("gcp",
               lambda ledger: GcsRemote("gs://data", ledger))
with L.transaction(by="dan") as t:
    t.add("db", "db/store", "gcp")
```


## Many ledgers
A project may keep several ledgers, split by how long their data lives, so cleanup is dropping a whole ledger rather than thinning one row by row (SVP 239). The list of them lives in one place, on the **root ledger**: `.datconfig.yaml`, the one config file, committed, says only how to reach root, and root's *registry* names every other ledger. Every name but `root` resolves through it.

```yaml
# .datconfig.yaml: a folder relative to the file, or a DSN
root: postgresql://dat@db/root?art=/data/art/root
# optional: the active ledger of a solo project
default: do26
```

```text
# on root: the registry, one subject per ledger ever created
(ledger/games, ledger/location, postgresql://dat@db/games?…)
(ledger/do26,  ledger/location, postgresql://dat@db/do26?…)
# a folder, relative to the config
(ledger/tmp1,  ledger/location, .dat/tmp1)
# gone: the name resolves no more, and is never reused
(ledger/tmp1,  ledger/dropped,  2026-11-05)
```

**No `root:`** means a SQLite root at `.ledgers/root` under the first dat folder (`DAT_FOLDERS`, else `dat_folders:`, else `data`), made on first use; a named root is never made except by `Ledger(create=True)`. Nothing reads root until a name is asked, so a project that never asks one never meets a ledger. A registry row is written by whatever creates the ledger (SVP's `just create ledger`); dvc-dat reads the shape above: `ledger/location` on `ledger/<name>` (the last one added wins), and a name holding `ledger/dropped` is gone. `ledger/lifetime` is read by `t.copy(..., safe=True)` ([Copying](#Copying)). Other `ledger/` predicates (`created`, `by`, `owner`, `store`) are the creator's and are not read here.

**`ledgers` is a mutable mapping** over the project's names, filled lazily from the registry, one read of root per project and process: `ledgers.games`, `ledgers["games"]` (opened on first use and kept), `"games" in ledgers`, `list(ledgers)` (`root` first, then the registry in revision order), `len(ledgers)`. A name root does not hold is `KeyError` (`AttributeError` as an attribute) naming the registry. `del ledgers["prod_kit"]` drops a name from this process, so nothing here reaches it by name; a handle already in hand keeps working, so this is a weak permission and not a guard. `ledgers["tmp"] = Ledger(location)` puts a ledger in by hand, for this process; setting `ledgers["root"]` before the first name replaces the root itself, which is how a test runs on a temp SQLite root. Neither writes the registry.

**Names** are Python identifiers, `[a-z][a-z0-9_]*` and not a keyword; a hyphen is refused, and `root` is the root's. So every ledger is an attribute, `ledgers.<name>`, and its name is a dotted-name segment as it stands (a mount at `mnt.<name>` loads as `mnt.<name>...`). A Postgres ledger's database is named the ledger name, unchanged: `do26` lives in the database `do26`. A rolling ledger is a *generation* named `<owner><yy>` or `<kind><yy>`, the two-digit year with no separator: `do26`, `ar26`, `ci26`, `prod_run26`, `dev_run26`; a second generation in the same year appends a letter, `do26b`. A ledger that does not roll by year has a plain name (`games`, `results`, `official`, `exp`); a throwaway one is `tmp<n>`, the prefix saying it may be gone, and a branch's is `branch_<name>`. A ledger name is never reused, not even after the ledger is dropped: the registry is what makes it unique.

**The active ledger** is where work lands when a script names none: `L`, and `Ledger()`. It is, first to last:

1. `DAT_LEDGER`: a name (`DAT_LEDGER=do26`, resolved through `ledgers`, so a dropped or deleted name is refused), else a location (a folder or a DSN).
2. `default:` in `.datconfig.yaml`: a name or a location, likewise. A solo project commits it (`default: root`); a team's file leaves it out, since whose ledger is active is a per-checkout fact, set by `DAT_LEDGER`.

Neither is `LedgerError`, one line: `no active ledger: DAT_LEDGER unset and <config> names no 'default:'; set DAT_LEDGER=<name> (root, or a ledger registered on root) or a location`. Nothing falls back to a shared ledger. CI and long-running agents set `DAT_LEDGER` in their environment; a runner that cannot reach root uses a location there, which needs no name. A script written for a specialty ledger names it: `ledgers.games`, `ledgers.do26`.

**One config file.** There is no override or local file: a `.datconfig.override.yaml` beside the config is `ValueError` (`LedgerError` from the ledger side) saying what replaced it. The keys `ledger:` and `ledgers:` were removed in 2.63 and are refused naming their replacement: `ledger: X` is `root: X` and `default: root` (and `namespace: ledger`, which it implied); `ledgers:` is the registry on root.

**Every ledger is a universe.** Provenance never crosses ledgers: a function may read another ledger (or anything else), but what it writes is a value on its own ledger, so a ledger can be iced whole. Promoting a value to another ledger copies it with its provenance chain.

**The global reference** to a value on any ledger is `<ledger>@<revision>:<name-or-sha>`, e.g. `do26@512:run/0-3-0/G1` or `do26@512:sha256:…`. It is unique because a ledger name is never reused, and it stays meaningful after the ledger is iced: it says which ledger held the value at which revision, even when the value can no longer be fetched. `dat.load("<ledger>@<revision>:<name-or-sha>")` resolves it to the value, and `dat.at("<ledger>@<revision>")` to a `Rev`, on any registered ledger; `ledger.at(rev)` stays that ledger's alone. Both take an optional default ledger (a `Ledger` or a name; else the active one) for a bare reference; a `sha256:<hex>` finds the value by the hash of its bytes; in a project with no active ledger, `dat.load` is `Dat.manager.load` (SVP 248).

**Whose names the project uses** is a separate choice from which ledgers it names. A *ledger-namespace project* names things through its active ledger's `db/mount` rows: its `ns` is a `LedgerNamespace`, `Dat.ns.mount` is refused (`t.ns.mount` writes a mount), and `x TARGET` runs through the ledger. `namespace: ledger` is the one switch; without it the project keeps the plain `Namespace` (its own mounts, `Dat.ns.mount`, a `manager:` subclass that mounts; `x TARGET` the bare run), and `L`, `Ledger()` and `ledgers.<name>` still open its ledgers. `namespace:` takes only `ledger`; any other value is `ValueError` at the config load. `Ledger(create=True)` makes a project in the working directory: it writes `default: root` and `namespace: ledger` when the file names no default, and makes the ledger the default names.

## Concurrency
One writer at a time: a transaction takes the write lock only at commit, and its revision is `MAX(rev) + 1` under that lock. `lock=<seconds>` holds the lock for the whole body when a read must not go stale before the write; `t.previous_rev` and the helpers that read through it require it. Readers take no lock; a `Rev` is a snapshot. Two processes missing on one memo key both run and both seal: identical bytes and dependencies are one subject, the second dropped at commit; different bytes are two entries, both kept, which is the evidence a nondeterminism check needs. The load harness under `tests/load/` checks these invariants across processes on SQLite and Postgres; its measurements are in [`tests/load/README.md`](https://github.com/oblinger/dvc-dat/blob/main/tests/load/README.md).




# Execution Semantics
Where a value function runs, what the run is allowed to see, and how its result becomes a value in the ledger.

![DAT Ledger Execution](DAT%20Ledger%20Execution.svg) 

## The function
A value function takes the revision first and keywords after, is marked `@dat.fn`, and returns a `Value`; its return annotation is required. Every read it makes through `rev` becomes a row of its result's dependencies ([Value Provenance](#Value%20Provenance)).

```python
@dat.fn
def cut(rev, *, game: str, version: str) -> Cut:
    home = rev[f"game/{game}", "home"]           # traced
    raw = rev.value(kind=Video, game=game)       # traced
    out = Cut(cut_video(raw, home))
    out.preds.update(game=game, version=version)
    return out
```

A function that declares `path: Path` is given a fresh folder under `$DAT_WORK` (default `~/.cache/dvc-dat/work`); it writes a folder there and returns `Dat(path)`, and the seal moves the files into the art store. A dat made from a spec needs no function of its own: `rev.run(spec)` ([Running](#Running)). The result's name is the call's `path=` (relative to the data folder, `<art store>/dats`), else the parameter's default as a path template expanded with the keys, else `anonymous/Dat{unique}`; its folder at the name is a view, hardlinks into the store, rebuilt as a new folder when the name moves. A value has one name, an alias not bound into its hash, settable as `Value(name=...)` or by assigning `v.name`; a name names one value (a name added retracts the value's other names as of open and again at commit inside the write lock); a value prints as its name, else `#` + a hash prefix (`<Video video/G1>`, `<Video #2db69ce1>`).



## The execution environment
`rev.ns.load(name)` decides between two environments. A name under a mounted prefix is *sandboxed*; any other name is *unsandboxed*. The difference is what the `fn` dependency item stands for, and so what a changed input the memo can detect.

**Unsandboxed** executes in the Python environment of the ledger's own process: whatever that process has imported, with every package it can see. The function's `code` subject hashes the function module's static import closure within its checkout, and its `code/<repo>` dependency item names the checkout's commit; the commit stands for the bytes, which is why an unsandboxed call needs a clean checkout. The commit vouches for the code the body imports, not for a file it opens: while an unsandboxed body runs, a file of its repo checkout opened to read outside the dats (the dat folders, the art stores, the ledger's folder, its `path` folder) is `UntracedRead`; the import system and the ledger's own machinery read freely, and a write is not checked. Mount the function to have such a read traced by its bytes. The checkout is found by git discovery over the folders of the imported modules, skipping the standard library, `site-packages` and the dvc-dat checkout; a checkout is named by its `pyproject.toml` `[project].name`.

**Sandboxed** functions live under a mount: rows naming a dotted prefix, its repo and its root, `(db/mount/demo_game.etl, db/root, demo_game/etl)` with `db/repo` beside it. Each call runs in a fresh process forked from a warm `python -I` server, one per environment, which holds only the ledger's machinery (no mounted module, no CUDA) and is retired after ten idle minutes, the next call starting a fresh one; a finder first on `sys.meta_path` serves the mounted prefixes from their roots, so every run loads, and records, exactly what it uses, third-party modules included. The `code` item is then the bytes of every module the run loaded, and of every mounted file it read, through `ns.load` (a spec, a literal) or by opening it (a config, a yaml); a nested run's are its own, a module its caller loaded first included: one changed byte anywhere is a different snapshot, so a sandboxed call runs at HEAD, clean or dirty. A nested run under the body's own mount runs in the same child; one under another mount runs in a fresh child of the server, as fresh as the first; an unsandboxed function called inside a sandboxed body is `NotEvaluated`, naming the mount and the function. The child refuses what it cannot trace: `UnmountedImport`, `UntracedRead`, `ConfinedWrite`, `ConfinedNetwork`, and `ConfinedProcess` for any process the body creates (`subprocess`, `os.system`, `os.exec*`, `os.posix_spawn`, `os.fork`), whose reads and writes no hook in the child sees. A body that needs a tool runs unsandboxed (base mode). An incomplete mount table is therefore a crash rather than a silently wider set of dependencies.

**Another ledger from a sandboxed body (SVP 1521).** A body reads any ledger of the caller's `ledgers`, the names of the `.datconfig.yaml` above the working directory of the call, which cross to the worker with the call (as the caller has them, `del` and hand-set included; a caller that never read root ships root's location, and the body reads the registry there on its first name): `ledgers.games.at(137).load("G1")`, `dat.at("games@137")`, `dat.load("games@137:G1")`, SQLite or Postgres. The handle is read-only. Each value or run read is a `foreign:` item, as outside the sandbox, at the revision read: a bare `.at()` reads the top and records the number it read, and a stated revision reads that revision. A raw row is untracked. A `Ref` or a sealed `Value` key on another ledger crosses with its location and revision and works the same way; that ledger need not be in the section, since the caller holds it. An unsaved `Value` is no key.

Opening a ledger lets the body read that ledger's art store, and its Postgres endpoint through the network hook; a registered ledger the body has not opened stays `UntracedRead`, and so does a SQLite ledger's database file opened as a file. A name the caller's view does not hold is `KeyError` naming the registry; a caller with no config, or a registered ledger that is not there, is `LedgerError`.

Nothing lands on that ledger. `Transaction` refuses the handle (`ConfinedWrite`) and its database connections are read-only (SQLite `mode=ro`; Postgres `default_transaction_read_only`). `rev.run` on it is a lookup: a hit reads the entry, `seal="get"` on a miss gives `None`, any other miss is `ConfinedWrite`, and `seal=True`, `seal=False` and `path=` are refused, so a body starts no run there. What a read has to place (a `Dat`'s folder, bytes fetched from the value's store) goes to a folder of the child's, gone with it. A run read through `rev.run` resolves the function on that ledger's mounts, so its repo needs a checkout in the caller's environment; a value of a class under a mount of that ledger alone does not import in the body. `Ledger(<location>)` in a body opens a store that may write, and stays `ConfinedWrite` for SQLite. One write is not closed: a body holding psycopg can connect to a Postgres endpoint the network hook passes, with whatever rights the login has.

**Versioning.** Every execution environment has a version that ties it to the code: each versioned package's `db/repo/<repo>/<package>` `db/version` row, written by the first clean run at each new `__version__`, and the repo's `db/repo/<repo>` `db/commit` row, the latest clean run's; every run's dependencies carry the `code/<repo>` item as `<commit8>`, the commit being what the hit test compares; the version a reader sees stays readable from the `db/repo/` rows at the revision. How versions are asserted and bumped, and what `clean=True` demands of the checkout, is [Versioning](#Versioning).



## Running
**A dat run is a ledger-function call.** `Dat.manager.run` makes a dat outside the ledger: a fresh folder every time, nothing recorded. `rev.run` makes or finds one inside it (DAT 1046): `rev.run(target, **kwargs)` takes a spec, a spec's name or a run function's name, and is a memo lookup over the memo key (the expanded spec, `dat.name` removed) and the run function's code, else a create, a run and a seal of the folder as the memo entry ([`run`](../../api/ledger.md#dvc_dat.ledger.Rev.run)). The run function is an `Fn` of kind `"dat"`, and the call is the one a `@dat.fn` gets: the same lookup, the same worker loop, the same seal and place; the kinds differ only in what the body receives, the keys or the dat built from them. A mounted run function runs in the sandbox worker, confined, its code the modules it loaded; so a commit that changes no file it loaded leaves the next call a hit. Inside the body the dat world's `ns` is a `LedgerNamespace` bound to the run's revision, whatever namespace the caller's world has (DAT 1047): a name the body looks up (`Dat.manager.ns.load`, a spec's `dat.base` or `dat.do`, a `{}` reference) walks the same `db/mount` rows the run was resolved through, read from the worker's checkout, and `mount` is refused. Names come from the ledger's mounts alone: the spec `mymodule/specs/table12.yaml` under `db/mount/mymodule` is `mnt.mymodule.specs.table12`, and `just run mnt.mymodule.specs.table12` in a ledger project is `rev.run("mnt.mymodule.specs.table12")`; any dat saved by hand seals as `dat.seal(t)`.

**run.** `run(name, **keys)` looks up the function by name (`rev.ns.load`), then looks for a result already computed: every entry whose `db/fn` (the dotted name) and `db/keys` (the bound keys, defaults included, as canonical JSON) match, newest seal first, and hands back the first whose dependencies still hold at the revision asked ([Value Provenance](#Value%20Provenance)). That is the memoization. A miss runs the body with a recording `Rev`, in the child for a sandboxed function, and the result comes back with its dependencies. `seal=` says where the result goes; a later `v.seal(x)` takes the same `x`, so a run looked at first can be kept without running again.

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

### Running over past revisions
**`L.at(rev).run(target, **keys)` is present code over a past revision; `L.revs` names a set of them ([Rerunning](../../DAT%20Demos/demo-rerunning.ipynb)).** The body's `Rev` reads every row, alias, value and query as of `rev`, and the code is the checkout's: a ledger holds rows and sealed bytes, never a checkout. The result is saved at the top, and its row `(<value>, db/at, "<rev.id>")` says what it read, `v.at` beside `v.rev` (SVP 245). `db/at` is provenance: outside the subject's hash and outside the hit test, so an ask at 413 may hand back the entry computed at 412, whose `db/at` still says 412, the trace proving its bytes hold at 413. A sweep over N revisions costs one run per distinct set of reads. An edit of the code misses at every revision, leaving the old entries for the old checkout. `clean=True` demands the commit the revision names, the opposite of present code, so a sweep never passes it; a [`rerun`](../../api/ledger.md#dvc_dat.ledger.Rev.rerun) reads at `db/at`.

```python
months = L.revs("month", since="2025-11", until="2026-11")
rate_by_month = {month: rev.run("metrics.rate", game="G1").obj
                 for month, rev in months.items()}
```

**Value.** The return of a run is a value: the object the function built, with its preds and, once sealed, its provenance. Sealing is the act of capturing it: the identity is fixed from the dependencies, the preds and the bytes; saving then writes it into the ledger. So a value is in one of three states, and a result of `run` goes as far through them as its `seal=` says before it is returned.

| State | What is fixed | Where it lives | How |
| --- | --- | --- | --- |
| built | nothing: `preds` and the bytes may still change | memory, or its work folder for a `Dat` | the constructor, or the body of a value function |
| sealed | its identity: the subject hashing dependencies, preds and bytes; `preds` read-only | the same place, with a seal record in the kept folder | `v.seal()` (`keep=True` copies the bytes into the kept cache) |
| saved | the rows at a revision, the bytes in the art store | the ledger | `v.seal(t)` or `v.seal(L)`; a run saves its own result by default (`seal=`) |

**Value.seal.** A sealed value that is never saved is still a value with a fixed identity, usable as a dep. `v.seal()` alone writes a seal record to this machine's kept folder (`$DAT_KEPT`, else `~/.cache/dvc-dat/kept`); a later `v.seal(t)` saves the state it was sealed in, its dependencies the environment of the seal, not of the save. A value not kept whose bytes changed in between is `SealBroken`. `Dat.sealed_at_path` reopens such a seal in another process. `just sealed` lists the seals never saved; `just sealed purge` drops them. A saved value never changes; a new version is a new seal ([Versioning](#Versioning)).

A save writes the value's own rows once, under a subject hashing the dependencies, preds and bytes (for a run, the function and keys too): `db/value`, `db/kind`, `db/provenance` (`eval:unsandboxed` or `eval:sandbox` for a run, a dat's included, written in a transaction `by="eval:<name>"`; `seal` or the caller's for a hand seal), `db/preds` (for a dat, its class's names and its folder's own), `db/fn`, `db/keys` and `db/returns` for a run, `db/sealed-at` for a value sealed before the save, one `db/deps/<item>` per dependency item, and one row per pred (per member for a `many` pred). A subject already saved is not written again: the seal is idempotent. A save involving a function whose code is at a declared version from a clean checkout also moves that package's `db/repo/<repo>/<package>` clock and the repo's `db/repo/<repo>` `db/commit` ([Versioning](#Versioning)). A hand seal's dependencies are declared, from its `deps` and the environment ([Value Provenance](#Value%20Provenance)); `seal` refuses a provenance beginning `eval:`, so a consumer that needs proof the dependencies were traced rather than declared asks for an `eval:` value.



## Memoization and the platform
A memo entry records the whole platform it ran on; the ledger decides, at each lookup, how much of it must agree (SVP 1474). **Record at write, policy at lookup.**

**The record.** Every run's entry stores two platform items. `platform` is the short tag `<os>-<machine>-py<X.Y>` (`linux-x86_64-py3.11`), as every entry before 1474 did. `platform/record` is the full record as canonical JSON, captured where the function ran: in the sandbox worker for a mounted function, in the calling process for an installed one, and for a draft saved later the machine it ran on, not the one that saved it.

| field | holds |
| --- | --- |
| `platform` | the short tag, `<os>-<machine>-py<X.Y>` |
| `os` | `sys.platform` (`linux`, `darwin`) |
| `machine` | `platform.machine()` (`x86_64`, `arm64`) |
| `python` | the full Python version, `3.11.9` |
| `cpu` | the CPU model (`sysctl` on macOS, `/proc/cpuinfo` on Linux) |
| `card` | the NVIDIA card model the process sees (`nvidia-smi`, honouring `CUDA_VISIBLE_DEVICES`; distinct models joined by ` + `), else `null` |
| `driver` | the NVIDIA driver version, else `null` |
| `cuda` | the CUDA version torch was built against, else `null` |
| `torch` | the installed torch version, else `null` |

The record is probed once per process; torch is never imported to read it. A hand seal (`v.seal(t)` of a value no run made) records `platform` alone, as before.

**The policy.** A policy is a function from a record to a string; a lookup hits an entry only when `policy(stored record) == policy(current record)`, every other dependency item holding as before. A field the policy reads that a record lacks is a miss, never a hit: an entry written before 1474 holds only `platform`, read as the record `{"platform": <tag>}`, so a policy reading `card` never matches it, while the default still does. Built-ins:

| name | compares |
| --- | --- |
| `platform` | the default: the `platform` field, byte for byte the tag every entry has always been matched on, so every existing entry keeps hitting |
| `card` | `platform`, `card` and `driver`: a result computed on an H100 no longer answers on an RTX PRO 6000; a CPU-only entry (`card` `null`) still answers a CPU-only host |

**Which policy is in force.** One row: `(db, db/memo-policy, <name>)`. A new ledger's first transaction writes it as `platform` (unless that transaction writes its own); a ledger made before 1474 has no row and reads `platform`. Changing the policy is a new row at a later revision, a plain `add`; every `db/` predicate is cardinality one, so the latest wins:

```python
with L.transaction(by="human:dan") as t:
    t.add("db", "db/memo-policy", "card")
```

Every handle reads the policy at the ledger's top, whatever revision it looks up at, so all handles judge by one policy, and every entry, old or new, is judged by the policy in force at the lookup: after the change above, an entry sealed on an H100 under `platform` misses on an RTX PRO 6000 and still hits on an H100. Changing back restores the old answers; nothing is rewritten.

**A policy of your own.** `register_policy(name, fn)` adds one in code, `fn` taking the record (a mapping of the fields above) to a `str`; the row then names it. The row stores only the name, so every process that looks up under it registers it first; an unregistered name is `LedgerError` naming it, at the lookup.

```python
from dvc_dat.ledger import register_policy

def by_cuda(r):
    return f"{r['platform']}|{r['card']}|{r['cuda']}"

register_policy("cuda", by_cuda)
```

**Functions claiming `exact`.** A function whose claim reaches `exact` in any clause ([Reproducibility](#Reproducibility)): every memo lookup of it adds `card` and `driver` to whatever the policy compares, since a bit-identical rerun is per card; the entry a miss writes is the one any function writes. `True`, `None` and `False` leave the lookup alone.

**The index.** Each store handle keeps, in memory, the policy's reduction of every memo entry's record (subject to string), stamped with the policy it was built under. A lookup reads the policy row, rebuilds the index once when the stamp differs (a new row, or a name registered again), otherwise adds only the entries sealed since, and skips a candidate whose reduction cannot match without reading its rows. It is a pre-filter: every candidate it passes is judged in full by the hit test, so correctness never depends on it. It is not persisted; a new process builds it on its first lookup.



## Rerunnability
A sealed value names the code that made it (`db/fn`, its `db/code/<16 hex>` item, the `db/repo/<repo> db/commit` clock at its revision), but nothing keeps that commit alive: a squash-merge with the branch deleted leaves it unreachable, and `git gc` or the host's collector removes it. A **pin** (SVP 250) is a git tag `dat/<commit12>` on the commit, pushed to the repo's remote before [`pin`](../../api/ledger.md#dvc_dat.ledger.Transaction.pin) returns (it is not rerunnable until the push has landed), plus two rows: `(db/repo/<repo>/<commit12>, db/pinned, dat/<commit12>)`, one per commit per ledger, so every value sealed from that commit is pinned by it, and `(<value>, db/rerunnable, true|recursive)`, the value's claim that its run can be rerun. The tag is made once and reused by every ledger; a second ledger pinning the same commit writes only its own row; a pinned commit pays no push (the local tag stands for the pushed one; a failed push removes it). Nothing about the value's bytes changes.

**What the claim says.** The commit is pinned; the function is importable by its dotted name from that commit, a top-level `@dat.fn` of the module the name says (no closure, no lambda, no function made at import); the commit holds the bytes the run loaded (a sandboxed run from a dirty checkout is refused, as a revision naming no commit is: code with no `__version__` never moves the clock); and every input, a value key or a traced read that is a value, resolves on this ledger. `recursive=True` asks the same of every input that is itself a run's result, down to values with no run (a hand seal, a game). The claim costs a lookup per input; a pin whose inputs cannot be found fails rather than half-succeeds. Pinning is on request, never by default; a `just copy ... rerunnable=true` onto a results ledger is where a result earns it (feature 251).

**Rerunning.** [`rev.rerun(value)`](../../api/ledger.md#dvc_dat.ledger.Rev.rerun) reads the pin, checks the commit out under `<ledger>/rerun/<commit12>/<repo>` (a worktree of the checkout here when it holds the commit, else `git clone --depth 1 --branch dat/<commit12>` from its remote: one commit's tree, no history; reused across reruns of the commit), syncs its `uv.lock` when it has one (`uv sync --frozen`, the cost that dominates, once per commit), and runs the function in a fresh interpreter over that tree (`python -m dvc_dat.ledger.pin`) at the revision its run read, `db/at`, with its recorded keys, writing nothing. An unsandboxed function runs in that interpreter, its checkout the worktree; a sandboxed one in that interpreter's worker. The hash of what comes back against the value's gives the outcome: `reproduced`; else, by the level the value's claim gives ([Reproducibility](#Reproducibility)), `differed-as-allowed` at `True`, `differed-nondeterministic` at `False` or unknown, and `differed-deterministic` at `exact`, the one error, which `pin(rerun=True)` raises as `Differed` after writing nothing (a plain `rerun` reports it). Nothing is called verified: a match proves bit-identity for this run, not a guarantee, and even a deterministic function is deterministic per card.

**What a rerun can restore, and what it cannot.** The code (the tag's tree), the packages (the lockfile), the inputs (every read is a trace item; a key is a value, a `Ref` or plain data), the platform record (recorded and compared by the memo policy). Not: heap state reached through a closure or a mutated module global, environment variables, the clock, an unseeded random source, files outside the checkout, the network. A function that reads outside the trace reruns to a different hash, which `pin(rerun=True)` reports at pin time rather than later. A `@dat.warm` memo ([dvc_dat.dat](#dvc_dat.dat%20Interface)) is invisible here: the trace records the same reads, and a fresh-process rerun is what catches a broken promise.

**From a shell.** `just pin VALUE [recursive=true] [rerun=true]` and `just rerun VALUE` ([Command Line](../../cli.md) § The ledger verbs).


## Reproducibility
How far a rerun of a function can be trusted (SVP 251 Q2), on one ordered scale: `"exact"` (bit-identical), `True` (good enough, no need to save it), `None` (unknown, the default), `False` (flaky, save it). A claim is a level, a tuple of a level and the predicates that must match for it, or a list of those read in order, first match wins:

```python
@dat.fn(reproducible=[("exact", "platform/card"),
                      (True, "assets/rev"), False])
def detect(rev, *, game: str) -> Table: ...
```

A predicate is a row the value carries, which the consumer writes; nothing like a card is a special case, and a clause naming a predicate the value does not carry does not match. Falling off the list means unknown.

**Where the claim lives.** On the ledger, never read from code, since `safe` cannot import a past commit: one row at seal, `(<value>, db/reproducible, [[level, [predicate, ...]], ...])`, beside `db/fn`, `db/keys` and `db/returns`. It is not in the subject's hash: a value's hash is its content, and one content can come from two functions. `None` writes no row.

**What reads it.** [`rev.rerun`](../../api/ledger.md#dvc_dat.ledger.Rev.rerun) compares the listed predicates between the old value's rows and the new value's preds and takes the first clause that matches: at `exact` a differing hash is `differed-deterministic`, the one error (`Differed`, from `pin(rerun=True)`); at `True` it is `differed-as-allowed`, since judging "good enough" needs a comparator that does not exist yet; at `None` or `False` it is `differed-nondeterministic`. A matching hash is `reproduced` at any level. `safe` runs before any rerun and reads only the first unconditional clause ([Copying](#Copying)).

**From `deterministic=` (2.54).** `True` is `"exact"`, its memo widening kept; `False` is `False`; `None` is `None`. A value sealed before 2.56.0 has no row, so it is unknown whatever its function said.


## Copying
`t.copy(*values, deep=False, safe=True, rerunnable=False)` moves a value or a reference to one onto another ledger, the one the transaction writes (SVP 251); `L.at().copy(v)` is the head form. The bytes go to the destination's store if absent, by hash and never decoded, with the subject rows and the provenance around them: the `db/code/<16 hex>` item, the preds' `db/cardinality` and `db/type`, a sandboxed function's mount when the prefix is free here, the run's commit as `(<value>, db/commit, <sha>)` (one revision's clock cannot hold the commits of a chain), and the value's one name, moved here as a seal moves it. The subject is the source's. `(<value>, db/copied-from, <ledger>@<rev>)` records the origin; a `Value` is read at its ledger's head, a `Ref` at its own revision. `db/store`, `db/at`, `db/rerunnable`, `db/rerun` and an earlier `db/copied-from` stay behind: they are about the ledger. A `db/subdat/` row comes with the rest; its child comes only under `deep`.

**Lifetime.** Root's registry declares one for each ledger, in the row `(ledger/<name>, ledger/lifetime, <word>)` on the root ledger (`ledgers.root`), `<name>` the ledger's folder or database (SVP 251 Q3 (B)). It is read there, at root's head, never on the ledger itself, so a ledger that is gone or offline is still judged. Ordered: `permanent` (always reachable) > `archival` (kept in principle; nothing may depend on it) > `transient` (known to be trashed). A timeless assertion, never its state today, written once by whatever creates the ledger. `safe` compares them and guesses nothing: `NotCopied` when root does not open, or declares none for a ledger it must read, more than one, or another word.

**The inputs** of a value are its value keys, every value its trace read, and its `foreign:` items, found on the ledgers they name ([The dependencies](#The%20dependencies)). `deep` copies them recursively until values with no inputs; `safe` copies those on a ledger ranked below the destination, by the same rule, and references the rest; a plain copy leaves them, and promises nothing at the destination. `deep` and `safe` refuse an input that cannot be found.

**Only the spec.** `safe` keeps a value's rows and not its bytes when it can be rerun instead: its first unconditional clause reaches `True` or better, its commit is pinned where it stands, and every input is safe in turn, on a permanent ledger or by this same rule. A claim only conditional on a predicate has no fallback, since that environment may not exist later, so it keeps the bytes, as unknown and `False` do. Such a value carries `(<value>, db/spec-only, true)` and its commit's `db/pinned` row; a load is `SpecOnly`, a memo lookup passes it over, and a run or a byte copy fills it. `deep` asks for every byte, and `safe=False` for the value's: neither keeps a spec alone.

**The claim.** `safe` asserts a source's `db/rerunnable` again here; `rerunnable=True` asserts it new, as [`pin`](../../api/ledger.md#dvc_dat.ledger.Transaction.pin) does, tag and push included. [`rev.rerun`](../../api/ledger.md#dvc_dat.ledger.Rev.rerun) of a copied value runs at its origin while that ledger can be found, and on this ledger's copy after: rows the function reads with `rev[s, p]` are then this ledger's.


## dvc_dat.dat Interface
The decorators, under one name so code says what each belongs to (SVP 250 Q4): `from dvc_dat import dat`.

| dvc_dat.dat | |
| --- | --- |
| [fn](../../api/ledger.md#dvc_dat.ledger.fn.fn) | Mark a function as a value function; `reproducible=` its claim |
| [warm](../../api/ledger.md#dvc_dat.ledger.warm.Warm) | A process-level memo by the canonical hash of the arguments |
| [command](../../api/just.md#dvc_dat.just.command) | Mark a function a command: also `just <name>` |

# Value Provenance
A value's provenance is stored in the ledger as triples whose subject is the value: beside its `db/value` row and its preds, one `db/deps/<item>` row for every input the computation depended on. These rows are the value's *dependencies*. They are written once, at the save, and never change; whether the dependencies still *hold* is computed, by re-asking each item at a revision. Every object is one string, the identity the input had when the value was computed, so two values' dependencies compare row by row and nothing is loaded.

## The dependencies
In the table `<value>` is the value's own subject and the other angle-bracketed names are variables: the predicate names the input, the object is the identity it had.

| subject | predicate | object | meaning |
| --- | --- | --- | --- |
| `<value>` | `db/deps/code` | `db/code/<16 hex>` | the code that ran, the snapshot: the hash of the modules it loaded (sandboxed) or of its static import closure (unsandboxed), with the mounts; holds while the function re-hashes to it at the rev |
| `<value>` | `db/deps/fn` | `<dotted name>` | the function inside that snapshot (`mnt.plane.measure.length`) |
| `<value>` | `db/deps/code/<repo>` | `<commit8>` | a checkout the run imported from, at that commit |
| `<value>` | `db/deps/platform` | `<os>-<machine>-py<M.m>` | the platform it ran on, its short tag; judged by the ledger's memo policy |
| `<value>` | `db/deps/platform/record` | the platform record, canonical JSON | the full platform it ran on, captured where the function ran (a run's entry only; [Memoization and the platform](#Memoization%20and%20the%20platform)) |
| `<value>` | `db/deps/<subject> <predicate>` | the held object | a row the body read with `rev[s, p]` or `get`, and what it held |
| `<value>` | `db/deps/<name> db/alias` | `ref:<class>:<hash>` | a name the body loaded through, and the bytes it named |
| `<value>` | `db/deps/ref:<class>:<hash>` | `ref:<class>:<hash>` | a value the body loaded, named by its bytes |
| `<value>` | `db/deps/eval:<name>{keys}` | `ref:<class>:<hash>` | a nested `run`, and the result it got |
| `<value>` | `db/deps/foreign:{"at":"<ledger>@<rev>","name":<name>}` | `ref:<class>:<hash>` | a value or a run the body reached through any `Rev` but its recording one, on any ledger; provenance only |
| `<value>` | `db/deps/q:{...}` | the sorted `ref:` list, or a token of the result | a query the body made (`refs`, `values`, `value`, `select`; any other read as `__call__`), and what it answered |
| `<value>` | `db/deps/salt` | the mount's `db/salt` | the salt of the mount a sandboxed run was under, when set |

**Reads on other ledgers (SVP 1521).** While a run is open a process-wide hook sees every `load`, `value`, `values` and `run` through a `Rev` that records nothing, on any ledger, its own included, and adds a `foreign:` item: the revision by `<ledger>@<rev>`, the name asked for (for a run `eval:<name>{keys}`) and the `ref:` it gave. The run's own recording `Rev` is unchanged. A `foreign:` item always holds, so it is no part of the hit test: a name that moves on another ledger is no miss, and a hit may return a result built from the older value. Raw rows on other ledgers (`rev[s, p]`, `all`, `get`) are not tracked. Nested runs each see their own reads. **A read during a run is recorded on that run, never on another and never dropped, because the run travels with the work, not the thread (SVP 1551).** A thread a body starts, and work a body submits to a `ThreadPoolExecutor` (however long before the run the pool and its threads were made), read for that run; work started or submitted outside every run reads for none, even while another thread's run is open, so two threads racing for one memo entry write the same subject (SVP 1549). Work handed over by any other road (a queue to a thread already running, `multiprocessing.pool.ThreadPool`) reads for no run unless the body wraps it in `contextvars.copy_context().run`; a child process or a subinterpreter is not seen, as for the sandbox's audit hook. Reads through the run's recording `Rev` are its own on any thread. A value key on the run's own ledger, loaded through its `Ref`, adds nothing: it is in `db/keys`. A sandboxed body reads other ledgers the same way, by name and read-only; see [The execution environment](#The%20execution%20environment).

A run records the first nine as it goes: `code`, `fn`, `code/<repo>`, `platform` and `platform/record` from the environment, the rest from each read the body makes through its `Rev`. A hand seal's dependencies are declared instead: a `ref:` row for each of its `deps` (an alias row too when the dep was loaded by name, a `code` and an `fn` row for an `Fn` dep), plus `code/<repo>` for every repo the environment reports, and `platform`. Nothing in the dependencies describes the value; it is the evidence the value was computed from.

## same_as, matches and diff
**`same_as(other)`** measures byte identity between the contents of two values: `hash == other.hash`, `False` for `None`. It reads no dependencies. Two values computed from different inputs can be the same bytes, and the store keeps them once; two values with identical dependencies can differ in bytes, which is what a nondeterminism check looks for.

**`matches(rev)`** measures whether anything a value depends on has changed by `rev`: whether any input it was computed from has, at `rev`, an identity other than the one its dependencies recorded. A later `rev` asks whether anything the value was built from has moved since; an earlier one asks whether the value would have been current then. The measure is the dependencies re-asked item by item, each kind its own way: `code` holds when the function its `fn` item names resolves at `rev` to the same `db/code` subject (sandboxed: the recorded modules re-hashed as they are now; unsandboxed: the static closure), and `fn` holds beside it; `code/<repo>` when the environment is at that commit; `platform` when the ledger's memo policy reduces the stored platform record and the environment's to the same string (`platform/record` is judged through it); a `<subject> <predicate>` item when the fold at `rev` holds the same object; an alias item when the name resolves at `rev` to the same bytes; an `eval:` item when the nested lookup at `rev`, never running, yields that hash; a `q:` item when the query asked at `rev` answers the same; a `ref:` item always, since bytes do not change. It consults the ledger and the environment only and never runs anything; it is the hit test `run` applies to each candidate.

**`diff(other)`** measures how two values differ in what they were computed from: the dependency items whose recorded identities differ between them, item to `(mine, theirs)`, `None` where one lacks the item. It compares the two stored dependencies and asks the ledger nothing. Two seals of the same function and keys with different bytes differ in some item here, and that item is the cause.



## Versioning
The ledger has versions for many things: the ledger itself is versioned, the code is versioned, and schemas, APIs, model families and configs are versioned. All of them are asserted within the ledger: the current value of every version is a row, `(<subject>, db/version, M.m.p)`, so a revision holds every version in force at once. A code version lives in the source tree, as the package's `__version__`: `bump_source` (`just bump <module>`) edits it, the commit records it, and the first clean run after the commit asserts it into the ledger. Every other version is asserted by `bump`.

The ledger version is the main one. It determines the revision we are on, `L.at("1.4.0")` being the latest revision that set `(db, db/version, 1.4.0)`, and that revision in turn implies a version for everything else: the code's, the schema's, the API's, every `db/version` row held there. So the version of a value is the ledger version at the revision it was sealed, and one number names the whole state it was computed in; what makes that true is bumping `db` whenever any version it stands for moves. Two pieces have their own machinery:

- **Code**, `db/repo/<repo>/<package>` and `db/repo/<repo>` (DAT 1044): a clock per versioned package, its `db/version` row the version of that package's code that runs were exposed to, and one `db/commit` row per repo, the latest clean run of any of its packages. The ledger writes both, under `db/` (DAT 1052 Q2 B), so `preds()` hides them and `t[s] = {...}` keeps them, and a person never does. A seal involving a function (a run's memo entry, or a hand seal with an `Fn` dep) whose `Code.version` is `MAJOR.MINOR.PATCH[.devN]` (`.devN` sorting below its patch, SVP 1482), so from a clean checkout, reads its package's row through the transaction's snapshot at open, and again at commit inside the write lock (an unlocked transaction's add at or below a version committed meanwhile is dropped): absent or lower, the transaction adds `db/version`; equal, nothing; higher on the row, a warning and nothing, since the clock never moves back; and it adds the full `db/commit` to `db/repo/<repo>` whenever that differs from the row. So a package's clock moves at the first clean run after a bump of its `__version__` is committed; a dirty checkout's `<commit 8>+dirty` never moves either row, and `bump` on a `db/repo/` subject is refused. A checkout holding two versioned packages (an installed one and a mounted one) keeps two clocks, neither warning about the other. A run sealed in the sandboxed worker raises its warning in the calling process. Every value's dependencies name the code commit it was computed under as the `code/<repo>` item ([Execution Semantics](#Execution%20Semantics)), because that is the version the memo checks on its own. `clean=True` on `run` asks that the checkout be clean, no uncommitted changes and HEAD at the commit the revision's `db/repo/<repo>` `db/commit` row names, and refuses with `NotClean` otherwise; by default only an unsandboxed call insists on it.
- **Anything else**: a subject with a `db/version` row, `schema/metrics` or `api/jobs`, bumped when it changes and readable at any revision.

A sealed value never changes: an `add` or `remove` on one of its own rows is `Exists` at commit, and any other row on its subject is annotation. A new version of a value is a new seal and a new subject; the re-pointable name is an alias, `(video/G1, db/alias, <subject>)`, which moves while the values it pointed at stay, so a read at an older revision still finds the older value. An alias names a subject holding a `db/value`, and a subject holding its own `db/value` cannot be an alias.

`bump(t, subject, part)` is the one writer of every version but code's: the current one read through `t.previous_rev` (so under `lock=`), the next by `part`, `minor` and `major` behind a `confirm`. A subject holding a `db/alias` row is refused: a value's version is a pred, and a new version of a value is a new seal and a re-point. A `db/repo/` subject is refused: its writer is the seal, above.




# BRIEF

- Written from `dvc_dat/ledger/*.py` at v2.18.0. Every name here must exist in the code; re-read the code, not this page, before changing a signature.
- Each member's contract and refusals are its docstring; this page is the overview, tables generated from those docstrings, and the topics that span classes (246).
- The figure is hand-written SVG; edit it directly.
