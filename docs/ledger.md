# The ledger

A dat is space: a folder whose `_spec_.yaml` says what it is. The ledger is
time: one append-only table of events, and what anything was at any moment.

```python
from dvc_dat.ledger import Ledger, Ref, json

# a profile, DAT_LEDGER, or ledger.profile.yaml
L = Ledger.open()
with L.transaction(by="dan") as tx:     # one rev for the block
    tx.assign("game/G7", "court", "hs-wood-2")
    tx.add("gameset", "NORM", Ref("game/G7"))
r = tx.rev

L.get_spec("game/G7", rev=r)     # {"court": "hs-wood-2"}, forever
L.objects("gameset", "NORM")     # [Ref("game/G7")]
L.subjects("court", "hs-wood-2") # ["game/G7"]
shots = L.save({"shots": [1, 2]}, type=json)
L.assign("game/G7", "annot:shots", shots, by="dan")
L.last("game/G7", "annot:shots").load()   # {"shots": [1, 2]}
```

`examples/ledger_walkthrough.ipynb` runs this story and prints every row as stored.

## The datom

Every row is `(added, rev, subject, predicate, object)`: at transaction `rev`
the triple was added or removed. Subjects and predicates are plain strings the
ledger does not interpret. A **rev** is a transaction: revs are dense, in commit
order, and every row of one transaction shares it, so no read ever sees half of
one. Who wrote a transaction and on what (UTC) day are two more rows on the
subject `tx/<rev>`, `by` and `date`, written in the transaction itself; anything
else said about a transaction is another triple there.

Nothing is updated or deleted. `assign` is a removal of every object the
predicate held plus an addition; `remove` is a removal row. So every read is a
function of a rev: the same rev gives the same answer forever, which is what lets
a dat record the rev it was cut at and be derivable from it.

## Values

An object is a `str`, a JSON `dict` or `list`, or a `Ref`, and each is stored
with its kind in front, so a row reads without a schema:

| Value | Row |
| --- | --- |
| `"hs-wood"` | `str:hs-wood` |
| `{"a": 1}` | `json:{"a":1}` (sorted keys; past `BLOB_BYTES`, 2048, `blob:sha256:<hex>` on the shelf) |
| `Ref("game/G7")` | `node:game/G7`: a subject of the ledger |
| `Ref("runs/G7-r1", type=Dat)` | `dat:runs/G7-r1`: a dat, loaded through `Dat.manager` |
| `Ref(…, type=json)` | `art:json:sha256:<hex>`: an artifact on the shelf |

Anything else (an `int`, a `date`) is `ValueError` at the write: say what it
means (`str(n)`, an ISO day). Reads decode, so a caller never sees a prefix.

## Ref

A `Ref` is plain data: `name`, `hash`, `type`, `size`, answered without a fetch.
`load()` fetches and decodes by `type`; `load_path(dest=None)` gives the bytes as
a place on disk. `type` is an artifact class (`json`, `file`, `ckpt`, `video`,
or your own: subclass `Artifact` with a new `token`, a `source` and a `decode`,
and it registers), a `Dat` class, or `Node` (the default). A `Ref` resolves
through `Ledger.default`, the ledger `Ledger.open` last returned.

## The API

| Artifact access | |
| --- | --- |
| `save(obj, *, type, name=None) -> Ref` | Store `obj` content-addressed; `name` is a second key. Writes no triple |
| `load(rid)` | The object a name or hash names, decoded |
| `ref(rid) -> Ref \| None` | The `Ref` a name or hash names, or `None` |

| Update | |
| --- | --- |
| `add(s, p, o, *, by) -> Rev` | Add one object to what `p` holds on `s` |
| `remove(s, p, o, *, by) -> Rev` | Remove one; removing what is not held is not an error |
| `transaction(*, by) -> Batch` | A `with` block of `assign`/`add`/`remove`, one rev, all or nothing; `tx.rev` after |

| Access | |
| --- | --- |
| `rev() -> Rev` | The newest transaction; 0 when empty |
| `query(s=None, p=None, o=None, *, rev=None, tx=None) -> list[Event]` | The event log filtered by any column, as of `rev`; `tx` keeps one transaction (`KeyError` if none has it). Oldest first |

| Derived helpers | every `rev=` is as-of; `None` is `rev()` |
| --- | --- |
| `assign(s, p, o, *, by) -> Rev` | `p` now holds exactly `o` |
| `held(s=None, p=None, o=None, *, rev=None) -> list[Event]` | Every triple held matching the parts given |
| `history(s, p, o=None, *, rev=None)` | `query(s, p, o, rev=rev)` |
| `last(s, p, *, rev=None)` | The object last added and still held, or `None` |
| `objects(s, p, *, rev=None) -> list` | Every object held, in the order last added |
| `subjects(p, o, *, rev=None) -> list[str]` | Every subject holding `o` under `p` |
| `get_spec(s, *, rev=None) -> dict` | `last` for every predicate of `s` |
| `set_spec(s, mapping, *, by) -> Rev` | One `assign` per key, one rev |
| `exists(s, p, o, *, rev=None) -> bool` | Whether the triple is held |
| `date(rev) -> date` | The day a transaction was written |

| Static | |
| --- | --- |
| `Ledger.open(profile=None)` | The ledger, which also becomes `Ledger.default` |
| `Ledger.encode(value) -> str` / `Ledger.decode(text)` | A value to its row string and back |

## Opening a ledger

`Ledger.open()` looks, in order, at the `profile` argument; `DAT_LEDGER`, a
SQLite file or a folder that holds `ledger.db` (and `ledger.art/`, the shelf);
then the nearest `ledger.profile.yaml` in the working directory or above.
A profile is YAML; relative paths are relative to it:

```yaml
# sqlite, or a dotted class name (mypkg.ledger.PgLedger)
backend: sqlite
path: state/ledger.db
# the artifact shelf; default: beside the database
art: state/ledger.art
# this shelf's region, for the whereabouts table
region: local
```

A dotted backend is a `Ledger` subclass whose `from_profile(profile, folder,
shelf)` classmethod builds it; the SQL statements live in
`dvc_dat.ledger.sql.SqlLedger`, so another database supplies `_read`,
`_writing` and `_next_rev`. Keep the profile out of every spec: a dat cut from
a spec would copy the connection.

## Backing

Artifacts live on a **shelf**, write-once and content-addressed:
`sha256/<ab>/<rest>` holds the payload, `<rest>._art_.yaml` its sidecar (type,
size, hash, names), and `_index_.json` maps names to hashes, rebuilt by
`LocalShelf.reindex()`. Beside the events table sits `whereabouts(hash,
region)`: which region holds an artifact's bytes now. That is status, not
history, so it is an ordinary table updated in place and never part of a rev.

## What the ledger does not do

It validates nothing: vocabularies, single-valued keys, curation and
confirmation are a layer above that reads and writes triples, raising its own
errors before the ledger is reached. It knows no domain names: `game/G7` above
is the example's convention, not the library's.

| Exception | Means |
| --- | --- |
| `ValueError` | An empty subject or predicate, an unencodable object, a rev above `rev()`, a row with no known prefix |
| `KeyError` | `query(tx=)` on a rev no transaction has |
| `FileNotFoundError` | `open` found no profile and no `DAT_LEDGER`; `load` on a name no store holds |
| `FileExistsError` | `save` gave a name that already holds different bytes |
| `LedgerError` | The backend refused: a lock, a corrupt file, a failed connection |
