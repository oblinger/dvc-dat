# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.19.6
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Demo: the ledger
#
# `dvc_dat.ledger` is one append-only table of events, each saying that at a **rev** (one
# transaction) a subject, a predicate and an object were added or removed. Every read is a
# function of a rev, so a cut that records its rev can be re-derived forever. Beside the events
# sits an **artifact shelf**: bytes stored by hash, referred to from rows by a `Ref`. And a `Ref`
# can also name a **dat**, so the ledger is how a name like `game/G7` reaches the data a run reads.
#
# This notebook runs on a fresh SQLite ledger in a temp dir. Reference: [the ledger](../ledger.md);
# the rows exactly as stored: `demo-ledger-walkthrough`.

# %% [markdown]
# ## Open a ledger

# %%
import os, tempfile
from pathlib import Path

ledger_path = Path(tempfile.mkdtemp(prefix="demo-ledger-"))   # a throwaway folder; the ledger is ledger_path/ledger.db
os.environ["DAT_LEDGER"] = str(ledger_path)

from dvc_dat.ledger import Ledger, Ref, json, file, ckpt

L = Ledger.open()
backend = type(L).__name__
print(f"{backend=}  {L.rev()=}  events={L.query()}  default={Ledger.default is L}")

# %% [markdown]
# `Ledger.open()` found `DAT_LEDGER`; an empty ledger is rev 0 with no events, and it became `Ledger.default`, what every `Ref` resolves through.

# %% [markdown]
# ## Writes: every write is a transaction

# %%
# several writes, one transaction: one rev, atomic
with L.transaction(by="ana") as tx:
    tx.add("game/G7", "court", "hs-wood-2")
    tx.add("game/G7", "season", "2026")
first = tx.rev
for e in L.query(tx=first):
    print(e)

# %% [markdown]
# Two facts, one rev; the transaction's own `tx/<rev> by` and `tx/<rev> time` rows land with them. `Event` is the one record: `(rev, subject, predicate, object, added)`.

# %%
# assign: an atomic retraction and assertion; a read at an old rev sees the old value
r_v1 = L.assign("model/shot-classifier", "version", "1.0.0", by="dan")
r_v2 = L.assign("model/shot-classifier", "version", "1.0.1", by="dan")
print(f"now: {L.last('model/shot-classifier', 'version')}   at r_v1: {L.last('model/shot-classifier', 'version', rev=r_v1)}")
print("history:", [(e.rev, e.object, e.added) for e in L.history("model/shot-classifier", "version")])

# %% [markdown]
# `assign` retracts the old value and asserts the new one under one rev: `last` reads 1.0.1 now and 1.0.0 at the old rev, and `history` keeps every event. `version` is an ordinary predicate, so any subject can carry one.

# %%
# membership: assert and retract members, one write at a time or several in one transaction; the set at any rev; the reverse lookup
L.add("gameset/NORM", "contains", Ref("game/G7"), by="ana")   # one write, one rev
L.add("gameset/NORM", "contains", Ref("game/G3"), by="ana")
before = L.rev()
with L.transaction(by="dan") as tx:                            # a retraction and an assertion, one rev
    tx.remove("gameset/NORM", "contains", Ref("game/G3"))
    tx.add("gameset/NORM", "contains", Ref("game/G5"))
print("at before:", L.objects("gameset/NORM", "contains", rev=before))
print("now:      ", L.objects("gameset/NORM", "contains"))
print("sets holding G7:", L.subjects("contains", Ref("game/G7")))

# %% [markdown]
# Membership is `add`/`remove` on a `contains` predicate, and a transaction mixes them as it likes: `objects` lists the set at any rev, and `subjects` is the reverse lookup (every subject that contains the game). `Ref("game/G7")` names a subject (a `node:` row).

# %% [markdown]
# ## Reads at an old rev

# %%
# a read pinned to an old rev survives later writes
at = L.rev()
L.set_spec("game/G7", {"court": "hs-wood-3", "venue": "Lincoln HS"}, by="dan")
print("at rev:", L.get_spec("game/G7", rev=at))
print("now:   ", L.get_spec("game/G7"))

# %% [markdown]
# `set_spec` is one `assign` per key under one rev; `get_spec` at the earlier rev still reads `hs-wood-2`, because nothing above was rewritten.

# %%
# the fold every read derives from, and a point query on it
print("held court rows:", [(e.rev, e.subject, e.predicate, e.object) for e in L.held(predicate="court")])
print(f"exists now: {L.exists('game/G7', 'court', 'hs-wood-2')}   at rev: {L.exists('game/G7', 'court', 'hs-wood-2', rev=at)}")

# %% [markdown]
# `held` is the fold every helper derives from (newest event per triple, kept if added); `exists` asks it about one triple, now and at a rev.

# %%
# a transaction's own rows: who, and when
print(f"time: {L.time(first)}   tx rows: {[str(e.object) for e in L.query('tx/' + str(first))]}")

# %% [markdown]
# Provenance is triples: `time(rev)` is the `tx/<rev> time` row, a UTC timestamp to the microsecond, and `by` sits beside it.

# %% [markdown]
# ## Artifact access

# %%
# an artifact: a JSON document saved by content hash, with a name as a second key
shots = L.save({"shots": [{"t": 12.4, "made": True}, {"t": 31.0, "made": False}]}, type=json, name="game/G7/annot/shots")
print(f"{shots=}  {shots.size=}  hash={shots.hash[:19]}...")
print(f"ref(name) is the same: {L.ref('game/G7/annot/shots') == shots}   load(name)[0]: {L.load('game/G7/annot/shots')['shots'][0]}")

# %% [markdown]
# `save` puts the bytes on the shelf under their hash and hands back a `Ref`: identity (`type`, `hash`, `size`) with no fetch, and the `name` is a second key to the same bytes, so `ref` and `load` answer to it. It writes no triple.

# %%
# the artifact referenced from a triple, by its ref; the row carries the hash, and the name still reaches the same bytes
L.assign("game/G7", "annot:shots", shots, by="dan")
got = L.last("game/G7", "annot:shots")
print(f"same ref: {got == shots}   stored in the row as: {Ledger.encode(got)[:24]}...   same bytes by name: {got.load() == L.load('game/G7/annot/shots')}")

# %% [markdown]
# A row holding a `Ref` reads back as a `Ref`, never a string, keyed by the hash (the name is a shelf key, not part of the triple); `.load()` is the fetch, decoded by its type.

# %%
# files and folders as artifacts: a note and a checkpoint folder, written with pathlib and saved by path
scratch_path = Path(tempfile.mkdtemp(prefix="demo-files-"))   # a throwaway folder for the files below
(scratch_path / "notes.txt").write_text("rim is low on the east hoop\n")
(scratch_path / "ckpt").mkdir(exist_ok=True)
(scratch_path / "ckpt" / "weights.bin").write_bytes(bytes(range(256)) * 4)
note = L.save(scratch_path / "notes.txt", type=file, name="game/G7/note/east-hoop")
model = L.save(scratch_path / "ckpt", type=ckpt)
print(f"{note.load()=}")
print(f"{model.type.__name__=}  {model.size=}  files={sorted(p.name for p in model.load_path().iterdir())}")

# %% [markdown]
# `file` loads as bytes; `ckpt` is a folder, so it loads as a path; a `name` given at `save` is a second key on the same content.

# %%
# the same artifact by name or by hash; a load to a path of your choosing
by_name, by_hash = L.ref("game/G7/note/east-hoop"), L.ref(note.hash)
copy = note.load_path(scratch_path / "out" / "note.txt")
print(f"same ref: {by_name == by_hash}   unknown name: {L.ref('game/G7/note/nothing')}   {copy.read_text()=}")

# %% [markdown]
# `ref` answers for either key (name or hash) and is `None`, not an error, for a name no store holds; `load_path(dest)` copies the bytes out.

# %%
# a large object is stored as an artifact automatically
doc = [{"t": round(i * 7.3, 1), "made": i % 3 == 0} for i in range(120)]
L.assign("game/G7", "shotlog", doc, by="dan")
row = [e for e in L.query("game/G7", "shotlog")][-1]
print(f"stored as: {Ledger.encode(row.object)[:18]}...   reads back equal: {L.last('game/G7', 'shotlog') == doc}")

# %% [markdown]
# A JSON value over `BLOB_BYTES` spills to the shelf as `blob:` and reads back as the same document: the spill is invisible both ways.

# %% [markdown]
# ## Data access: a dat by reference

# %%
# a dat store, and a dat with one channel, sealed; Shot is that channel's row (a plain dataclass), not a dat
from dataclasses import dataclass
from dvc_dat import Dat, DatManager
from demo_kinds.channels import ChannelDat, kind

dat_store_path = Path(tempfile.mkdtemp(prefix="demo-dats-"))   # a throwaway dat root a dat Ref resolves through
Dat.manager = DatManager(dat_folders=[str(dat_store_path / "dats")], art_folder=str(dat_store_path / "art"))

@dataclass
class Shot:
    frame: int
    made: bool

g7 = Dat.manager.create({"dat": {"name": "game/G7/shots", "kind": kind(ChannelDat)}})
g7.write_channel("shots", [Shot(frame=n, made=n % 3 == 0) for n in range(0, 300, 37)])
g7.save()
print(f"{g7.get_path_name()=}  standing={g7.get_results()['dat']['standing']}")

# %% [markdown]
# A small dat with one channel, sealed: its own `_result_.yaml` carries its hash, so it can be referenced. (`ChannelDat` is the demos' own kind, in `demo_kinds/`: a channel is a list of rows in `<channel>.json`.)

# %%
# a dat referenced from a triple, by name
L.assign("game/G7", "shots", Ref(g7.get_path_name(), type=Dat), by="dan")
ref = L.last("game/G7", "shots")
print(f"{ref=}  stored as: {Ledger.encode(ref)}  path: {ref.load_path().name}")

# %% [markdown]
# The ledger holds the dat as a `dat:` row; a `Ref` read back knows it is a dat and where it lives, without opening it.

# %%
# the dat loaded through its ref: its channel reads as a table
dat = ref.load()
shots_table = dat.table("shots")
print(f"class={type(dat).__name__}  made shots={int(shots_table['made'].sum())}")
print("frame 111:", shots_table[shots_table["frame"] == 111].to_dict("records"))


# %% [markdown]
# `.load()` opens the dat through `Dat.manager`; from there it is the dat's own API: here a pandas view of a channel, and one frame's row.

# %% [markdown]
# ## The refusals

# %%
# what the ledger refuses
def refused(f):
    try:
        f()
        return "not refused"
    except Exception as e:
        return f"{type(e).__name__}: {str(e)[:90]}"

{
    "bare row":      refused(lambda: Ledger.decode("hs-wood-2")),
    "int object":    refused(lambda: L.add("game/G7", "period", 3, by="dan")),
    "future rev":    refused(lambda: L.get_spec("game/G7", rev=L.rev() + 1)),
    "name reused":   refused(lambda: L.save(scratch_path / "ckpt", type=ckpt, name="game/G7/note/east-hoop")),
    "missing art":   refused(lambda: L.load("sha256:" + "0" * 64)),
}

# %% [markdown]
# A bare string has no kind, an `int` must be said as a `str`, a rev past `rev()` is refused, a name holds one content forever, and a missing artifact is `FileNotFoundError`.

# %%
# an exception inside a transaction rolls the whole transaction back
at = L.rev()
try:
    with L.transaction(by="ana") as tx:
        tx.assign("game/G7", "court", "outdoor-1")
        raise RuntimeError("vocabulary check failed")
except RuntimeError:
    pass
print(f"rev unchanged: {L.rev() == at}   court: {L.last('game/G7', 'court')}")

# %% [markdown]
# An exception inside a transaction writes nothing: the rev did not move and the court is unchanged.

# %%
# the event log is the whole ledger
events = L.query()
print(f"events={len(events)}  retractions={sum(not e.added for e in events)}  last rev is current: {events[-1].rev == L.rev()}")

# %% [markdown]
# The whole log, append-only: removals are rows too, and nothing was ever updated or deleted.

# %%
import shutil
L.close(); Ledger.default = None; Dat.manager = None
del os.environ["DAT_LEDGER"]
for d in (ledger_path, scratch_path, dat_store_path):
    shutil.rmtree(d)

# %% [markdown]
# Nothing persists: the ledger, the shelf and the dat store lived in temp dirs.
