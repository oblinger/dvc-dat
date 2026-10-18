"""Leg 5: executable docs. The code blocks of the SVP447 Ledger Module page, copied in, each
test named for its section. Lines are as written on the page except where a comment marked
ADAPTED says what changed and why; the page's `# result` comments become asserts below them."""

import pandas as pd
import pytest

from dvc_dat.ledger2 import Code, Env, Ledger, Ref, Rev, Value


class Shots(Value):
    """The page's `Shots` kind. ADAPTED: defined at module level, not inside the block, because
    `Ref.type` resolves the class by its dotted name; a class local to a function cannot be loaded back."""

    def __init__(self, table: pd.DataFrame): self.table = table

    def encode(self) -> bytes: return self.table.to_parquet()

    @classmethod
    def decode(cls, data, store):
        import io
        return cls(pd.read_parquet(io.BytesIO(data)))   # ADAPTED: read_parquet takes a file, not bytes


def classify(run, model=None):
    return pd.DataFrame({"shot": ["made", "miss"], "run": [run.table.shape[0]] * 2})


classify_by_hand = classify


@pytest.fixture
def world(tmp_path, monkeypatch, envbox):
    """The state the page's examples assume: sv-pipe 0.2.2 at 7d742989, a model, a run, two declared preds."""
    monkeypatch.setenv("DAT_LEDGER", str(tmp_path / "doc.db"))
    envbox.env = Env({"sv-pipe": Code("0.2.2", "7d742989")}, "sha256:lock", "test-platform")
    L = Ledger.open()
    with L.transaction(by="setup") as t:
        t.add("code/sv-pipe", "version", "0.2.2")
        t.add("code/sv-pipe", "commit", "7d742989")
        t.add("ledger/pred/version", "cardinality", "one")
        t.add("ledger/pred/version", "doc", "what bump moves")
        t.add("model/shot", "version", "1.0.0")
        t.add("model/shot", "value", Shots(pd.DataFrame({"w": [0.1, 0.2]})))
        t.add("run/0-2-2/G5", "value", Shots(pd.DataFrame({"frame": [1, 2, 3]})))
    with L.transaction(by="setup") as t:
        t.add("ledger/pred/kwargs.bins", "index", "true")
    return L


def test_module_overview_block(world):
    """The usage block at the top of the page (before § Ledger Summary)."""
    from dvc_dat.ledger2 import Ledger, bump, attr   # ADAPTED: ledger2, the spike's package  # noqa: F401

    L = Ledger.open()                        # DAT_LEDGER
    rev = L.at()                             # one snapshot per session
    assert rev["code/sv-pipe", "version"] == "0.2.2"           # "0.2.2"; exactly one or raise
    assert isinstance(rev.get("model/shot", "value"), Ref)    # a Ref, or None
    rev.refs(s="ledger/pred/*", where={"index": "true"})
    assert ("ledger/pred/kwargs.bins", "index", "true") in rev

    m = rev.eval("svp.identity.train", game="G5")   # a Value, memoised
    m.trace; m.rev; m.sealed                 # the model itself, with its
    assert m.sealed and m.rev == rev and m.trace["code/sv-pipe"] == "0.2.2+7d742989"
    c = rev.eval("svp.identity.train", game="G5", memo=False)   # run, no seal
    g = rev.eval("svp.identity.train", game="G5", memo="get")   # or None
    assert not c.sealed and c.same_as(m) and g.subject == m.subject

    f = rev.load_fn("svp.identity.train")    # Fn: resolved at rev
    f(game="G6")                             # == rev.eval(...)
    f.module, f.sha, f.mode, f.env.platform
    assert f.mode == "base" and f.env.platform == "test-platform"

    # ADAPTED: through L.at(), not `rev`: the memo entry was sealed after `rev`, and an as-of read
    #   at `rev` cannot see it (Found while building)
    refs = L.at().refs(fn="svp.identity.train", game="G5")   # [Ref]
    assert refs[0].load().obj == {"model": "identity-G5-8", "base": "0.0.0"}   # the value, fixed at its rev
    assert sorted(L.at().select(("game", "epochs"), fn="svp.identity.train")) == [("G5", "8"), ("G6", "8")]
    first = rev.id
    rows = L.at().all(since=L.at(first))      # every row in (first, top]  ADAPTED: 398 -> first
    assert any(p == "fn" for _s, p, _o in rows)

    with L.transaction(by="human:dan", time=True, why="T531") as t:
        bump(t, "code/sv-pipe", "patch")     # 0.2.2 -> 0.2.3
        t.add("code/sv-pipe", "commit", "b48dca7c")
        t.add(t.tx, "checked", "G1,G4,G5")
    assert t.rev.id == L.at().id             # 414  ADAPTED: ids differ in a fresh ledger
    assert t.rev[t.rev.tx, "by"] == "human:dan"
    assert t.rev["code/sv-pipe", "version"] == "0.2.3"

    with L.transaction(by="agent:svp", lock=30) as t:
        v = t.base["code/sv-pipe", "version"]        # nothing can move
        m = t.base["model/shot", "version"]
        t.add("rel/pipe", "pair", f"{v}+{m}")
    assert L.at()["rel/pipe", "pair"] == "0.2.3+1.0.0"

    run = rev.load("run/0-2-2/G5")
    hand = Shots(classify(run))              # a hand-made Value
    with L.transaction(by="human:dan") as t:
        subj = t.seal(hand, deps=[run])      # "Shots/<hash>": value, kind,
                                             #   trace rows; immutable
        t.add("shots/G5-byhand", "value", hand)   # a name: a pointer
    assert subj.startswith("Shots/") and hand.sealed
    assert L.at().load("shots/G5-byhand").subject == subj


def test_rev_interface_all_block(world):
    """§ Rev Interface, `all`."""
    L = world
    with L.transaction(by="setup") as t:
        t.add("code/sv-pipe", "commit", "b48dca7c")
    rev = L.at()
    assert rev.all()[:2] == [("ledger/tx/1", "by", "setup"), ("code/sv-pipe", "version", "0.2.2")]
    assert rev.all("code/sv-pipe") == [("version", "0.2.2"), ("commit", "b48dca7c")]
    assert rev.all("ledger/pred/version") == [("cardinality", "one"), ("doc", "what bump moves")]
    shot = rev.all("model/shot", "value")          # [Ref(...)], unloaded
    assert len(shot) == 1 and isinstance(shot[0], Ref)
    assert rev.all("ledger/pred/kwargs.bins", "index", "true") == [L.at(2)]   # [Rev(402)]  ADAPTED: 402 -> 2
    assert rev.all(since=L.at(2)) == [("ledger/tx/3", "by", "setup"), ("code/sv-pipe", "commit", "b48dca7c")]
    assert dict(rev.all("code/sv-pipe")) == {"version": "0.2.2", "commit": "b48dca7c"}


def test_transaction_interface_seal_block(world):
    """§ Transaction Interface, `seal`."""
    L = world
    rev = L.at()
    run = rev.load("run/0-2-2/G5")                # a Value, loaded  ADAPTED: `run: RunDat` annotation dropped
    model = rev.load("model/shot")                # a Value, loaded
    v = Shots(classify_by_hand(run, model))       # an ordinary object

    with L.transaction(by="human:dan") as t:
        subj: str = t.seal(v, deps=[run, model])  # "Shots/3b91e0…"
        t.add(subj, "note", "by hand, G5")        # any further row
        t.add("shots/G5-byhand", "value", v)      # a readable pointer
    assert (v.sealed, v.subject) == (True, subj)  # True, "Shots/3b91e0…"
    assert set(v.trace) == {"dat:run/0-2-2/G5", "dat:model/shot", "code/sv-pipe", "uv.lock", "platform"}
    assert v.trace["code/sv-pipe"] == "0.2.2+7d742989"
    rows = dict(L.at().all(subj))
    assert rows["kind"] == "Shots" and rows["note"] == "by hand, G5" and rows["provenance"] == "seal"
    assert L.at()["shots/G5-byhand", "value"].hash == v.hash

    rev2 = L.at()                                 # ADAPTED: the page uses rev2 without making it
    again: Shots = rev2.load("shots/G5-byhand")   # follows the pointer
    assert again.same_as(v) and again.matches(rev2)   # True, moved?
    with L.transaction(by="t") as t:
        t.add("model/shot", "value", Shots(pd.DataFrame({"w": [9.9]})))
    assert not again.matches(L.at())              # the model it declared moved


def test_semantics_putting_an_artifact_in_block(world):
    """§ Putting an artifact in: the three doors."""
    L = world
    rev = L.at()
    model = {"weights": [1, 2, 3]}
    # 1. a plain assertion: you name the subject and supply the value
    with L.transaction(by="human:dan") as t:
        t.add("model/shot", "value", model)      # a Value, or any
                                                 #   pickleable -> Pickled
    assert L.at().load("model/shot").obj == model and not L.at().load("model/shot").sealed
    # 2. a hand-made Value: sealed with declared dependencies
    run = rev.load("run/0-2-2/G5")
    v = Shots(classify(run))
    with L.transaction(by="human:dan") as t:
        t.seal(v, deps=[run])     # the value row, kind, trace rows, an
                                  #   index row per predicate declared
                                  #   indexed; one immutable subject
    assert v.sealed
    # 3. an eval: the seal of (2) plus fn and kwargs.* rows, so it is
    #   a memo entry findable by eval and refs
    e = rev.eval("svp.identity.train", game="G5")
    assert L.at()[e.subject, "fn"] == "svp.identity.train" and L.at()[e.subject, "kwargs.game"] == "G5"
    assert isinstance(rev, Rev)
